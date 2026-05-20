import asyncio
import contextlib
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response, StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from tavi import auth
from tavi.db import close_session
from tavi.history import format_history_as_markdown
from tavi.workflow import app as graph

# ---------------------------------------------------------------------------
# Rate limiter (keyed by client IP; single global API key means per-IP is
# the meaningful per-caller boundary)
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Per-thread bookkeeping
# ---------------------------------------------------------------------------

_last_activity: dict[str, datetime] = {}
_created_at: dict[str, datetime] = {}
# Threads whose first message has been sent (state fully initialised in graph)
_initialized: set[str] = set()


# ---------------------------------------------------------------------------
# Background cleanup task
# ---------------------------------------------------------------------------


async def _cleanup_idle_sessions() -> None:
    """Periodically close DuckDB sessions that have been idle too long."""
    timeout_minutes = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "30"))
    while True:
        await asyncio.sleep(300)  # check every 5 minutes
        timeout = timedelta(minutes=timeout_minutes)
        now = datetime.now().astimezone()
        expired = [
            tid for tid, last in list(_last_activity.items()) if now - last > timeout
        ]
        for tid in expired:
            close_session(tid)
            auth.remove_thread(tid)
            _last_activity.pop(tid, None)
            _created_at.pop(tid, None)
            _initialized.discard(tid)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI):  # noqa: ANN201
    """Manage application startup and shutdown lifecycle.

    Starts the background idle-session cleanup task on startup. On shutdown,
    cancels that task and closes all open DuckDB sessions.

    Yields:
        Control to the FastAPI application while it is running.
    """
    cleanup_task = asyncio.create_task(_cleanup_idle_sessions())
    yield
    cleanup_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cleanup_task
    for tid in auth.all_threads():
        close_session(tid)


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:  # noqa: ARG001
    """Return a 429 JSON response when a rate limit is exceeded.

    Args:
        request: The incoming HTTP request (unused, required by FastAPI).
        exc: The rate-limit exception raised by SlowAPI.

    Returns:
        A ``JSONResponse`` with status 429 and a human-readable detail message.
    """
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"detail": "Rate limit exceeded. Please slow down."},
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MessageRequest(BaseModel):
    content: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(_: auth.APIKeyDep) -> dict:
    """Create a new conversation and return its thread ID.

    Returns:
        A dict with a single key ``thread_id`` containing the UUID string
        of the newly created conversation.
    """
    thread_id = str(uuid.uuid4())
    now = datetime.now().astimezone()
    auth.register_thread(thread_id)
    _last_activity[thread_id] = now
    _created_at[thread_id] = now
    return {"thread_id": thread_id}


@app.post("/conversations/{thread_id}/messages")
@limiter.limit("20/minute")
async def send_message(
    request: Request,  # noqa: ARG001
    thread_id: str,
    body: MessageRequest,
    _: auth.APIKeyDep,
) -> StreamingResponse:
    """Send a message and stream the assistant's response as SSE.

    Each SSE event is a JSON object with a ``type`` field:
    - ``{"type": "token", "content": "..."}`` — one per streamed token
    - ``{"type": "done"}`` — emitted once after the graph finishes
    - ``{"type": "error", "detail": "..."}`` — emitted if an exception occurs

    Args:
        thread_id: ID of an existing conversation, as returned by
            ``POST /conversations``.
        body: Request body containing the user's message ``content``.

    Returns:
        A ``StreamingResponse`` with media type ``text/event-stream``.
    """
    auth.verify_thread_exists(thread_id)
    _last_activity[thread_id] = datetime.now().astimezone()

    config = {"configurable": {"thread_id": thread_id}}

    # First message must initialise all state fields; subsequent messages
    # need only provide the new human message (checkpoint handles the rest).
    if thread_id not in _initialized:
        _initialized.add(thread_id)
        inputs: dict = {
            "messages": [HumanMessage(content=body.content)],
            "areas": [],
            "available_tables": [],
            "available_table_meta": {},
        }
    else:
        inputs = {"messages": [HumanMessage(content=body.content)]}

    async def event_stream():
        try:
            async for chunk, metadata in graph.astream(
                inputs,  # ty: ignore[invalid-argument-type]
                config=config,  # ty: ignore[invalid-argument-type]
                stream_mode="messages",
            ):
                # Only surface tokens from the agent node, not from the
                # internal geo-extraction LLM.
                if metadata.get("langgraph_node") != "agent":
                    continue
                if not isinstance(chunk, AIMessageChunk):
                    continue

                # Anthropic returns content as a list of typed blocks;
                # other providers return a plain string.
                raw = chunk.content
                if isinstance(raw, list):
                    text = "".join(
                        block.get("text", "")
                        for block in raw
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                else:
                    text = raw

                if text:
                    yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/conversations/{thread_id}/history")
async def get_history(thread_id: str, _: auth.APIKeyDep) -> Response:
    """Return the conversation history as a Markdown document.

    Args:
        thread_id: ID of the conversation whose history to fetch.

    Returns:
        A ``Response`` with media type ``text/markdown`` containing the
        formatted conversation history.
    """
    auth.verify_thread_exists(thread_id)
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph.aget_state(config)  # ty: ignore[invalid-argument-type]
    messages = state.values.get("messages", [])
    started_at = _created_at.get(thread_id, datetime.now().astimezone())
    return Response(
        content=format_history_as_markdown(messages, started_at),
        media_type="text/markdown",
    )


@app.delete("/conversations/{thread_id}")
async def delete_conversation(thread_id: str, _: auth.APIKeyDep) -> dict:
    """Close a conversation and free its resources."""
    auth.verify_thread_exists(thread_id)
    close_session(thread_id)
    auth.remove_thread(thread_id)
    _last_activity.pop(thread_id, None)
    _created_at.pop(thread_id, None)
    _initialized.discard(thread_id)
    return {"status": "closed"}
