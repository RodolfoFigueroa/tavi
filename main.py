import logging
import os
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage

from tavi.history import save_history
from tavi.workflow import app

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "WARNING").upper(),
    format="%(levelname)s %(name)s: %(message)s",
)


def run_turn(
    stream_inputs: dict,
    config: dict,
    seen_ids: set[str],
    *,
    history_file: Path | None = None,
    started_at: datetime | None = None,
    include_tools: bool = False,
) -> None:
    """Stream a single conversation turn and print new messages.

    Streams events from the LangGraph app, deduplicates messages by ID,
    pretty-prints each new message, and logs the current ``areas`` and
    ``available_tables`` state summary. If ``history_file`` is provided, the
    markdown history file is overwritten after every new message.

    Args:
        stream_inputs: Input dict passed directly to ``app.stream()``.
        config: LangGraph run configuration (e.g. containing ``thread_id``).
        seen_ids: Mutable set of already-printed message IDs used to
            avoid reprinting messages emitted in earlier events.
        history_file: Optional path to the markdown history file to update.
        started_at: Conversation start time written into the history header.
        include_tools: When ``True``, tool result messages are included.
    """
    for event in app.stream(stream_inputs, config=config, stream_mode="values"):  # ty:ignore[invalid-argument-type]
        last_message = event["messages"][-1]
        msg_id = getattr(last_message, "id", None)
        if msg_id in seen_ids:
            continue
        if msg_id is not None:
            seen_ids.add(msg_id)
        last_message.pretty_print()
        area_names = [a["name"] for a in (event.get("areas") or [])]
        print(  # noqa: T201
            f"  [state] areas={area_names} | "
            f"available_tables={event.get('available_tables')}"
        )
        if history_file is not None and started_at is not None:
            save_history(
                event["messages"],
                history_file,
                started_at,
                include_tools=include_tools,
            )


if __name__ == "__main__":
    initial_inputs = {
        "messages": [
            HumanMessage(
                content=(
                    "Is there a correlation between tree coverage and surface temperature in Mexico City?"
                )
            )
        ],
        "areas": [],
        "available_tables": [],
        "available_table_meta": {},
    }

    started_at = datetime.now()
    history_file: Path | None = None
    save_history_dir = os.environ.get("SAVE_HISTORY")
    if save_history_dir:
        history_dir = Path(save_history_dir)
        history_dir.mkdir(parents=True, exist_ok=True)
        history_file = history_dir / f"conversation_{started_at:%Y-%m-%d_%H-%M-%S}.md"
    include_tools = bool(os.environ.get("SAVE_TOOL_HISTORY"))

    config = {"configurable": {"thread_id": "session-001"}}
    seen_ids: set[str] = set()

    run_turn(
        initial_inputs,
        config,
        seen_ids,
        history_file=history_file,
        started_at=started_at,
        include_tools=include_tools,
    )

    while True:
        try:
            follow_up = input("\nAnything else? (press Enter to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not follow_up:
            break
        run_turn(
            {"messages": [HumanMessage(content=follow_up)]},
            config,
            seen_ids,
            history_file=history_file,
            started_at=started_at,
            include_tools=include_tools,
        )
