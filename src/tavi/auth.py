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
    _thread_registry.add(thread_id)


def verify_thread_exists(thread_id: str) -> None:
    if thread_id not in _thread_registry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation '{thread_id}' not found",
        )


def remove_thread(thread_id: str) -> None:
    _thread_registry.discard(thread_id)


def all_threads() -> frozenset[str]:
    return frozenset(_thread_registry)
