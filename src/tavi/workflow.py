import os
from pathlib import Path
from typing import Literal

import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tavi.state import AgentState
from tavi.tools import all_tools

llm = ChatAnthropic(model_name="claude-sonnet-4-6")
llm_with_tools = llm.bind_tools(all_tools)


def generate_dynamic_schema_string(local_tables: dict[str, pd.DataFrame]) -> str:
    if not local_tables:
        return (
            "*No local tables are currently in memory. You must call a tool "
            "to fetch data first.*"
        )

    schema_lines = []
    for table_name, df in local_tables.items():
        schema_lines.append(f"**Table: `{table_name}`**")

        for col_name, dtype in df.dtypes.items():
            clean_type = (
                str(dtype)
                .upper()
                .replace("64", "")
                .replace("32", "")
                .replace("OBJECT", "VARCHAR")
            )
            schema_lines.append(f"* `{col_name}` ({clean_type})")

        schema_lines.append("")

    return "\n".join(schema_lines)


def call_model(state: AgentState) -> dict[str, list]:
    prompt_env_path = os.getenv("PROMPT_FILE__PATH")
    if prompt_env_path is None:
        prompt_template = "You are a helpful spatial data assistant."
    else:
        with Path(prompt_env_path).open(encoding="utf-8") as file:
            prompt_template = file.read()

    tables_in_memory = state.get("local_tables", {})

    dynamic_schemas = generate_dynamic_schema_string(tables_in_memory)

    final_prompt_text = prompt_template.replace(
        "{DYNAMIC_LOCAL_TABLES}", dynamic_schemas
    )

    sys_msg = SystemMessage(content=final_prompt_text)

    messages = [sys_msg] + state["messages"]
    response = llm_with_tools.invoke(messages)

    return {"messages": [response]}


def should_continue(state: AgentState) -> Literal["tools", END]:  # ty:ignore[invalid-type-form]
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END


# Initialize the graph
workflow = StateGraph(AgentState)  # ty:ignore[invalid-argument-type]

workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(all_tools))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue)
workflow.add_edge("tools", "agent")

app = workflow.compile()
