"""Multi-provider AI analyzer pool for turbo mode.

Manages multiple AI providers simultaneously, distributing work
across them and disabling providers that hit rate limits or errors.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ai.providers import PROVIDERS, build_analyzer, get_api_key

logger = logging.getLogger(__name__)

_COOLDOWN_SECS = 120
_MAX_CONSECUTIVE_ERRORS = 3


@dataclass
class PoolEntry:
    provider_id: str
    name: str
    analyzer: Any
    rpm: int
    delay: float
    semaphore: asyncio.Semaphore = field(repr=False)
    consecutive_errors: int = 0
    disabled_until: float = 0.0
    total_calls: int = 0
    total_errors: int = 0

    def is_available(self) -> bool:
        if self.consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
            if time.monotonic() < self.disabled_until:
                return False
            self.consecutive_errors = 0
        return True

    def record_success(self) -> None:
        self.consecutive_errors = 0
        self.total_calls += 1

    def record_error(self, *, rate_limited: bool = False) -> None:
        self.consecutive_errors += 1
        self.total_errors += 1
        self.total_calls += 1
        if self.consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
            cd = _COOLDOWN_SECS * (3 if rate_limited else 1)
            self.disabled_until = time.monotonic() + cd
            logger.warning(
                "Pool: %s disabled for %ds (%d consecutive errors, rate_limited=%s)",
                self.name, cd, self.consecutive_errors, rate_limited,
            )

    def status_dict(self) -> dict:
        return {
            "provider": self.provider_id,
            "name": self.name,
            "available": self.is_available(),
            "rpm": self.rpm,
            "calls": self.total_calls,
            "errors": self.total_errors,
        }


class AnalyzerPool:
    """Round-robins AI analysis across all configured providers."""

    def __init__(self, settings: Any) -> None:
        self._entries: list[PoolEntry] = []
        self._idx = 0

        for pid, profile in PROVIDERS.items():
            key = get_api_key(pid, settings)
            if not key:
                continue
            try:
                analyzer = build_analyzer(pid, profile["default_model"], settings)
                rpm = max(1, profile.get("rpm", 10))
                entry = PoolEntry(
                    provider_id=pid,
                    name=profile["name"],
                    analyzer=analyzer,
                    rpm=rpm,
                    delay=profile.get("delay_between_sites", 3),
                    semaphore=asyncio.Semaphore(max(1, min(rpm, 10))),
                )
                self._entries.append(entry)
                logger.info("Pool: added %s (%d RPM, delay %ds)",
                            profile["name"], rpm, entry.delay)
            except Exception as exc:
                logger.warning("Pool: failed to add %s: %s", pid, exc)

        logger.info("Pool ready: %d providers", len(self._entries))

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def active_count(self) -> int:
        return sum(1 for e in self._entries if e.is_available())

    def get_available(self) -> list[PoolEntry]:
        return [e for e in self._entries if e.is_available()]

    def reset_health(self) -> None:
        for e in self._entries:
            e.consecutive_errors = 0
            e.disabled_until = 0

    def status(self) -> list[dict]:
        return [e.status_dict() for e in self._entries]

    def total_capacity(self) -> int:
        """Sum of auto_sites_per_cycle across available providers."""
        total = 0
        for e in self._entries:
            if e.is_available():
                profile = PROVIDERS.get(e.provider_id, {})
                total += profile.get("auto_sites_per_cycle", 30)
        return total
