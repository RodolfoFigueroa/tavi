import json
from pathlib import Path

from tavi.models import DynamicToolEntry
from tavi.tools.dynamic import create_dynamic_tool
from tavi.tools.static import execute_spatial_query

tool_list_path = (
    Path(__file__).parent.parent.parent.parent / "config" / "tool_list.json"
)
with tool_list_path.open(encoding="utf-8") as file:
    tool_list = json.load(file)


dynamic_tool_registry: dict[str, DynamicToolEntry] = {}

for name, conf in tool_list.items():
    generated_tool, caller = create_dynamic_tool(name, conf)
    dynamic_tool_registry[name] = DynamicToolEntry(
        tool=generated_tool,
        description=conf["table_description"],
        columns=conf.get("columns", {}),
        caller=caller,
        extra_args_keys=list(conf.get("extra_args", {}).keys()),
        column_name=conf["column_name"],
        add_area=conf.get("add_area", False),
        extra_args_config=conf.get("extra_args", {}),
    )

dynamic_tools = [e.tool for e in dynamic_tool_registry.values()]
agent_tools = [*dynamic_tools, execute_spatial_query]

__all__ = ["agent_tools", "dynamic_tool_registry"]
