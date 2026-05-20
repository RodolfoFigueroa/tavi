import os
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

TAVI_API_KEY = os.environ.get("TAVI_API_KEY", "")

_thread_registry: set[str] = set()


def verify_api_key(
    key: Annotated[
        str | None, Security(APIKeyHeader(name="X-API-Key", auto_error=False))
    ],
) -> None:
    """Verify the ``X-API-Key`` request header against the configured secret.

    Intended as a FastAPI ``Security`` dependency. Raises ``RuntimeError``
    when ``TAVI_API_KEY`` is not set in the environment, and HTTP 401 when
    the provided key is absent or does not match.

    Args:
        key: Value of the ``X-API-Key`` header, or ``None`` if absent.

    Raises:
        RuntimeError: If ``TAVI_API_KEY`` is not set in the environment.
        HTTPException: With status 401 if the key is missing or incorrect.
    """
    if not TAVI_API_KEY:
        msg = "TAVI_API_KEY environment variable is not set"
        raise RuntimeError(msg)
    if key != TAVI_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


APIKeyDep = Annotated[None, Depends(verify_api_key)]


def register_thread(thread_id: str) -> None:
    """Register a thread ID as an active conversation.

    Args:
        thread_id: Unique identifier for the conversation thread.
    """
    _thread_registry.add(thread_id)


def verify_thread_exists(thread_id: str) -> None:
    """Raise HTTP 404 if the thread ID is not registered.

    Args:
        thread_id: Unique identifier for the conversation thread.

    Raises:
        HTTPException: With status 404 if ``thread_id`` is not in the
            registry.
    """
    if thread_id not in _thread_registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{thread_id}' not found",
        )


def remove_thread(thread_id: str) -> None:
    """Remove a thread ID from the active registry.

    Safe to call even if ``thread_id`` is not currently registered.

    Args:
        thread_id: Unique identifier for the conversation thread.
    """
    _thread_registry.discard(thread_id)


def all_threads() -> frozenset[str]:
    """Return a snapshot of all currently registered thread IDs.

    Returns:
        A frozen set of thread ID strings.
    """
    return frozenset(_thread_registry)
