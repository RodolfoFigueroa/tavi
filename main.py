from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from tavi.workflow import app

load_dotenv()


def run_turn(
    stream_inputs: dict,
    config: dict,
    seen_ids: set[str],
) -> None:
    """Stream a single conversation turn and print new messages.

    Streams events from the LangGraph app, deduplicates messages by ID,
    pretty-prints each new message, and logs the current ``areas`` and
    ``available_tables`` state summary.

    Args:
        stream_inputs: Input dict passed directly to ``app.stream()``.
        config: LangGraph run configuration (e.g. containing ``thread_id``).
        seen_ids: Mutable set of already-printed message IDs used to
            avoid reprinting messages emitted in earlier events.
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


if __name__ == "__main__":
    initial_inputs = {
        "messages": [
            HumanMessage(
                content=(
                    "Between Mexico City and Monterrey, which had more elderly "
                    "population exposed to high temperatures (above 30C) in the "
                    "summer of 2025?"
                )
            )
        ],
        "areas": [],
        "available_tables": [],
        "available_table_meta": {},
    }

    config = {"configurable": {"thread_id": "session-001"}}
    seen_ids: set[str] = set()

    run_turn(initial_inputs, config, seen_ids)

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
        )
