from typing import Literal

from langgraph.graph import END

from tavi.state import AgentState


def route_after_geo(state: AgentState) -> Literal["get_tracts", END]:  # ty:ignore[invalid-type-form]
    """Conditional edge: route to tract resolution or end after geo extraction.

    Args:
        state: Current agent state.

    Returns:
        ``"get_tracts"`` if at least one area was resolved, otherwise ``END``.
    """
    return "get_tracts" if state.get("areas") else END


def route_after_tracts(state: AgentState) -> Literal["agent", END]:  # ty:ignore[invalid-type-form]
    """Conditional edge: route to agent or end after tract resolution.

    Args:
        state: Current agent state.

    Returns:
        ``"agent"`` if at least one area has a non-empty ``tracts`` list,
        otherwise ``END``.
    """
    return "agent" if any(a["tracts"] for a in state.get("areas", [])) else END


def route_after_agent(state: AgentState) -> Literal["tools", END]:  # ty:ignore[invalid-type-form]
    """Conditional edge: route to tool execution or end after agent response.

    Args:
        state: Current agent state.

    Returns:
        ``"tools"`` if the last message contains tool calls, otherwise ``END``.
    """
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END
