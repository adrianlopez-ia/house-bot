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
    n = len(_subscribers)
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass
    if n:
        logger.debug("Event %s -> %d subscribers", event.get("type"), n)


def subscribe() -> asyncio.Queue[dict[str, Any]]:
    q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers.append(q)
    logger.info("SSE subscriber added (total: %d)", len(_subscribers))
    return q


def unsubscribe(q: asyncio.Queue[dict[str, Any]]) -> None:
    try:
        _subscribers.remove(q)
    except ValueError:
        pass
    logger.info("SSE subscriber removed (total: %d)", len(_subscribers))


def format_sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
