from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path


def _extract_text(content: str | list) -> str:
    """Return plain text from a message content field.

    Handles both plain strings and lists of content blocks (e.g. Anthropic's
    ``[{"type": "text", "text": "..."}]`` format).
    """
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block["text"]))
    return "\n".join(parts)


def format_history_as_markdown(
    messages: list[AnyMessage],
    started_at: datetime,
    *,
    include_tools: bool = False,
) -> str:
    """Render Human and AI messages as a markdown document.

    Skips ``SystemMessage`` instances. ``ToolMessage`` instances are included
    only when ``include_tools`` is ``True``. AI messages that carry only tool
    calls (no text content) are rendered as ``*[called tools]*``.

    Args:
        messages: Full message list from the agent state.
        started_at: Datetime when the conversation was started; used in the
            document header.
        include_tools: When ``True``, tool result messages are rendered as
            ``## Tool Result`` sections.

    Returns:
        A markdown string representing the conversation history.
    """
    lines: list[str] = [
        "# Conversation History",
        f"Started: {started_at:%Y-%m-%d %H:%M:%S}",
        "",
    ]

    for msg in messages:
        if isinstance(msg, HumanMessage):
            text = _extract_text(msg.content)
            lines += ["---", "", "## Human", "", text, ""]
        elif isinstance(msg, AIMessage):
            text = _extract_text(msg.content)
            if not text:
                text = "*[called tools]*"
            lines += ["---", "", "## Assistant", "", text, ""]
        elif include_tools and isinstance(msg, ToolMessage):
            text = _extract_text(msg.content)
            lines += ["---", "", "## Tool Result", "", text, ""]

    lines.append("---")
    return "\n".join(lines)


def save_history(
    messages: list[AnyMessage],
    file_path: Path,
    started_at: datetime,
    *,
    include_tools: bool = False,
) -> None:
    """Format and overwrite the history file with the current message list.

    Args:
        messages: Full message list from the agent state.
        file_path: Destination path; the file is created or overwritten.
        started_at: Datetime passed through to ``format_history_as_markdown``.
        include_tools: When ``True``, tool result messages are included.
    """
    file_path.write_text(
        format_history_as_markdown(messages, started_at, include_tools=include_tools),
        encoding="utf-8",
    )
