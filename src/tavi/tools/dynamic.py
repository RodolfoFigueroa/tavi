from collections.abc import Callable

import pandas as pd
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from tavi.connections import engine, lyra_client

_TYPE_MAP: dict[str, type] = {"int": int, "str": str, "float": float}


class NoArgs(BaseModel):
    pass


def _build_extra_args_schema(
    tool_name: str, extra_args_config: dict
) -> type[BaseModel]:
    """Build a Pydantic model class from an ``extra_args`` config block.

    Iterates over ``extra_args_config``, maps type strings to Python types
    via ``_TYPE_MAP``, and constructs ``Field`` objects with descriptions
    (including valid-values hints when provided).

    Args:
        tool_name: Name of the parent tool; used to name the generated model
            as ``{tool_name}_args``.
        extra_args_config: Mapping of argument name to spec dict with keys
            ``type``, ``description``, and optionally ``values``.

    Returns:
        A dynamically created ``BaseModel`` subclass whose fields correspond
        to ``extra_args_config``. Returns ``NoArgs`` when the config is empty.
    """
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


def get_area_col(cvegeos: list[str]) -> pd.DataFrame:
    """Fetch the geographic area (in CRS units²) for a list of AGEB codes.

    Queries ``census_2020_ageb`` for the ``cvegeo`` identifier and
    ``ST_Area(geometry)`` of each requested census tract.

    Args:
        cvegeos: List of AGEB ``cvegeo`` codes to look up.

    Returns:
        A DataFrame with columns ``cvegeo`` (str) and ``area_ageb`` (float).
    """
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
    """Build a StructuredTool and its associated caller for a dynamic data tool.

    The returned ``StructuredTool`` uses a no-op stub as its ``func`` so that
    LangChain/LangGraph can introspect the schema without executing real I/O.
    Actual data fetching is performed by the returned ``caller``.

    Args:
        tool_name: The tool's registered name (e.g. ``"fetch_temperature"``).
        config: Tool configuration dict with required keys ``endpoint``,
            ``column_name``, and ``details``, plus optional ``extra_args``,
            ``fixed_args``, and ``add_area``.

    Returns:
        A tuple of:

        - ``StructuredTool``: LangChain tool with schema but no-op execution.
        - ``Callable[[list[str], dict], pd.DataFrame]``: Caller that fetches
          data from the Lyra API for a given list of AGEB codes and extra args.
    """
    extra_args_config: dict = config.get("extra_args", {})
    args_schema = _build_extra_args_schema(tool_name, extra_args_config)

    def _caller(cvegeo_list: list[str], extra_args: dict) -> pd.DataFrame:
        """Fetch data from the Lyra API for a list of census tracts.

        Calls the configured ``endpoint`` via ``lyra_client.process()``,
        converts the result dict into a cvegeo-indexed DataFrame. If
        ``add_area`` is set in the parent config, merges in AGEB area
        geometry and computes an ``area_frac`` column.

        Args:
            cvegeo_list: Census tract codes to fetch data for.
            extra_args: Runtime arguments forwarded to the API alongside
                any ``fixed_args`` from the tool config.

        Returns:
            A DataFrame with at least a ``cvegeo`` column and the tool's
            configured ``column_name`` column. Includes ``area_frac`` if
            ``add_area`` is enabled.
        """
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
        """Placeholder stub; real execution is handled by ``tools_node``.

        Returns:
            A fixed string indicating the tool is executed automatically.
        """
        return "This tool is executed automatically by the system."

    structured = StructuredTool.from_function(
        func=_no_op,
        name=tool_name,
        description=config["details"],
        args_schema=args_schema,
    )
    return structured, _caller
