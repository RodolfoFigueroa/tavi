import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, StateGraph

from tavi.graphs.agent import agent_node, tools_node
from tavi.graphs.edges import route_after_agent, route_after_geo, route_after_tracts
from tavi.graphs.geo import extract_area_node, get_tracts_node
from tavi.state import AgentState

logger = logging.getLogger(__name__)

builder = StateGraph(AgentState)  # ty:ignore[invalid-argument-type]

builder.add_node("extract_area", extract_area_node)
builder.add_node("get_tracts", get_tracts_node)
builder.add_node("agent", agent_node)
builder.add_node("tools", tools_node)

builder.add_edge(START, "extract_area")
builder.add_conditional_edges("extract_area", route_after_geo)
builder.add_conditional_edges("get_tracts", route_after_tracts)
builder.add_conditional_edges("agent", route_after_agent)
builder.add_edge("tools", "agent")

app = builder.compile(checkpointer=MemorySaver())
