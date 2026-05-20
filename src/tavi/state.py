from typing import Annotated

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from tavi.models import Area


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    areas: list[Area]
    available_tables: list[str]
    available_table_meta: dict[str, dict]
