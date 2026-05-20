from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

import pandas as pd
from langchain_core.tools import StructuredTool


@dataclass
class DynamicToolEntry:
    tool: StructuredTool
    description: str
    columns: dict[str, str]
    caller: Callable[[list[str], dict], pd.DataFrame]
    extra_args_keys: list[str]
    column_name: str
    add_area: bool
    extra_args_config: dict


class Area(TypedDict):
    name: str
    code: str
    tracts: list[str]
