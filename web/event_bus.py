"""Lightweight async event bus for real-time SSE streaming.

Services emit events; each SSE subscriber gets its own asyncio.Queue.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_subscribers: list[asyncio.Queue[dict[str, Any]]] = []


def emit(event: dict[str, Any]) -> None:
    event.setdefault("ts", time.time())
    for q in _subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers.append(q)
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass


def format_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
