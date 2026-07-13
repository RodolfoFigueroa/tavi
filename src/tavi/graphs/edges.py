import logging
from typing import Literal

from langchain_core.messages import ToolMessage
from langgraph.graph import END

from tavi.state import AgentState

logger = logging.getLogger(__name__)

MAX_SQL_RETRIES = 3


def route_after_geo(
    state: AgentState,
) -> Literal["get_tracts", END]:  # ty:ignore[invalid-type-form]
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


def route_after_tools(state: AgentState) -> Literal["agent", END]:  # ty:ignore[invalid-type-form]
    """Conditional edge: route back to agent or end after tool execution.

    Implements the SQL autocorrection loop with a hard limit of
    ``MAX_SQL_RETRIES`` attempts:

    - If the last tool result is a SQL execution error (``"SQL error: ..."``),
      route back to ``"agent"`` so the LLM can regenerate the query, unless
      the retry limit has been reached, in which case route to ``END``.
    - If the last tool result is a security rejection (``"Error: ..."``), route
      to ``END`` immediately, security violations are never retried.
    - Otherwise (successful result), route to ``"agent"`` for synthesis.

    Args:
        state: Current agent state.

    Returns:
        ``"agent"`` to continue, or ``END`` to terminate the turn.
    """
    messages = state.get("messages", [])
    retry_count = state.get("retry_count", 0)

    last_tool_msg = next(
        (m for m in reversed(messages) if isinstance(m, ToolMessage)),
        None,
    )

    if last_tool_msg is None:
        return "agent"

    content: str = last_tool_msg.content if isinstance(last_tool_msg.content, str) else ""

    # Security rejections are never retried.
    if content.startswith("Error:"):
        logger.warning("Security rejection — terminating turn: %s", content)
        return END

    # SQL execution errors trigger autocorrection up to MAX_SQL_RETRIES.
    if content.startswith("SQL error:"):
        if retry_count >= MAX_SQL_RETRIES:
            logger.warning(
                "SQL autocorrection limit reached (%d/%d) — terminating turn.",
                retry_count,
                MAX_SQL_RETRIES,
            )
            return END
        logger.info(
            "SQL error on attempt %d/%d — routing back to agent for autocorrection: %s",
            retry_count + 1,
            MAX_SQL_RETRIES,
            content,
        )
        return "agent"

    # Successful result — route to agent for narrative synthesis.
    return "agent"
