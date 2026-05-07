import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import sqlalchemy
from langchain_core.tools import BaseTool, StructuredTool, tool
from lyra_api import LyraAPIClient
from pydantic import BaseModel, Field, create_model

logger = logging.getLogger(__name__)

LYRA_HOST = os.environ.get("LYRA_HOST", "localhost:5219")
lyra_client = LyraAPIClient(
    host=LYRA_HOST,
    timeout=60,
    headers={
        "P-Access-Token-Id": os.environ["PANGOLIN_ACCESS_TOKEN_ID"],
        "P-Access-Token": os.environ["PANGOLIN_ACCESS_TOKEN"],
    },
    log_level=logging.INFO,
    secure=not LYRA_HOST.startswith("localhost"),
)

engine = sqlalchemy.create_engine(os.environ["DATABASE_URL"])


@tool
def get_geographic_area_code(area_name: str) -> str:
    """To be implemented. Given an area name, return its geographic code."""
    area_map = {
        "Mexico City": "09.1.01",
        "Monterrey": "19.1.01",
    }
    return area_map.get(area_name, "Unknown area")


@tool
def get_census_tracts_from_area_code(area_code: str) -> list[str]:
    """To be implemented. Given an area code, return a list of census tract codes."""
    with engine.connect() as conn:
        results = pd.read_sql(
            """
            SELECT census_2020_ageb.cvegeo FROM census_2020_ageb
            INNER JOIN census_2020_mun
                ON census_2020_ageb.cve_mun = census_2020_mun.cvegeo
            WHERE census_2020_mun.cve_met = %(area_code)s
            """,
            conn,
            params={"area_code": area_code},
        )
    return results["cvegeo"].tolist()


class NoArgs(BaseModel):
    pass


_TYPE_MAP: dict[str, type] = {"int": int, "str": str, "float": float}
_SAFE_VALUE_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _build_extra_args_schema(
    tool_name: str, extra_args_config: dict
) -> type[BaseModel]:
    """Build a Pydantic model from the extra_args config block."""
    if not extra_args_config:
        return NoArgs
    fields: dict = {}
    for arg_name, arg_spec in extra_args_config.items():
        py_type = _TYPE_MAP.get(arg_spec["type"], str)
        desc = arg_spec.get("description", "")
        values = arg_spec.get("values")
        if values:
            desc = f"{desc} Valid values: {values}."
        fields[arg_name] = (py_type, Field(..., description=desc))
    return create_model(f"{tool_name}_args", **fields)


def _sanitize(value: object) -> str:
    s = str(value).lower().replace(" ", "_")
    return s if _SAFE_VALUE_RE.match(s) else re.sub(r"[^a-z0-9_]", "", s)


def make_table_name(
    tool_name: str,
    extra_args: dict,
    arg_keys: list[str],
    area_name: str | None = None,
) -> str:
    """Build a unique table name from a tool name, runtime arg values, and area name."""
    base = tool_name.replace("fetch_", "local_")
    parts = [_sanitize(extra_args[k]) for k in arg_keys if k in extra_args]
    if area_name:
        parts.append(_sanitize(area_name))
    suffix = "_".join(parts)
    return f"{base}_{suffix}" if suffix else base


def get_area_col(cvegeos: list[str]) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(
            """
            SELECT
                cvegeo,
                ST_Area(geometry) AS area_ageb
            FROM census_2020_ageb
            WHERE cvegeo IN %(cvegeos)s
            """,
            conn,
            params={"cvegeos": tuple(cvegeos)},
        )


def create_dynamic_tool(
    tool_name: str, config: dict
) -> tuple[StructuredTool, Callable[[list[str], dict], pd.DataFrame]]:
    extra_args_config: dict = config.get("extra_args", {})
    args_schema = _build_extra_args_schema(tool_name, extra_args_config)

    def _caller(cvegeo_list: list[str], extra_args: dict) -> pd.DataFrame:
        response = lyra_client.process(
            metric=config["endpoint"],
            payload={
                "data": {
                    "data_type": "cvegeo_list",
                    "value": cvegeo_list,
                },
                **extra_args,
                **config.get("fixed_args", {}),
            },
        )
        out = (
            pd.Series(response["result"], name=config["column_name"])
            .to_frame()
            .reset_index()
            .rename(columns={"index": "cvegeo"})
        )

        if config.get("add_area", False):
            df_area = get_area_col(cvegeo_list)
            out = (
                out.merge(df_area, on="cvegeo", how="left")
                .assign(
                    area_frac=lambda df: df[config["column_name"]] / df["area_ageb"]
                )
                .drop(columns=["area_ageb"])
            )

        return out

    def _no_op(**_kwargs: object) -> str:
        return "This tool is executed automatically by the system."

    structured = StructuredTool.from_function(
        func=_no_op,
        name=tool_name,
        description=config["details"],
        args_schema=args_schema,
    )
    return structured, _caller


@tool
def execute_spatial_query(sql: str) -> str:
    """Execute a DuckDB SELECT query and return results as a table."""
    raise NotImplementedError


tool_list_path = Path(__file__).parent.parent.parent / "config" / "tool_list.json"
with Path(tool_list_path).open(encoding="utf-8") as file:
    tool_list = json.load(file)

dynamic_tools: list[StructuredTool] = []
DYNAMIC_TOOL_BASE_TABLE_MAP: dict[str, str] = {}
DYNAMIC_TOOL_DESC_MAP: dict[str, str] = {}
DYNAMIC_TOOL_COLUMNS_MAP: dict[str, dict[str, str]] = {}
DYNAMIC_TOOL_CALLERS: dict[str, Callable[[list[str], dict], pd.DataFrame]] = {}
DYNAMIC_TOOL_EXTRA_ARGS_KEYS: dict[str, list[str]] = {}

for name, conf in tool_list.items():
    generated_tool, caller = create_dynamic_tool(name, conf)
    dynamic_tools.append(generated_tool)
    base_table = name.replace("fetch_", "local_")
    DYNAMIC_TOOL_BASE_TABLE_MAP[name] = base_table
    DYNAMIC_TOOL_DESC_MAP[name] = conf["table_description"]
    DYNAMIC_TOOL_COLUMNS_MAP[name] = conf.get("columns", {})
    DYNAMIC_TOOL_CALLERS[name] = caller
    DYNAMIC_TOOL_EXTRA_ARGS_KEYS[name] = list(conf.get("extra_args", {}).keys())

dynamic_tool_names: set[str] = set(DYNAMIC_TOOL_BASE_TABLE_MAP.keys())
agent_tools: list[BaseTool] = [*dynamic_tools, execute_spatial_query]
