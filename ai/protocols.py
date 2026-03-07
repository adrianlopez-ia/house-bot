"""Protocols (interfaces) for AI analysis, enabling provider-agnostic code."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AIAnalyzer(Protocol):
    """Abstract contract for an AI-powered page analyzer.

    Implementing a new provider (OpenAI, local model, etc.) only requires
    satisfying this protocol -- no base class inheritance needed.
    """

    async def analyze_page(
        self, text: str, url: str, zone: str,
    ) -> list[dict[str, Any]]: ...

    async def detect_forms(
        self, html: str, url: str,
    ) -> list[dict[str, str]]: ...

    async def analyze_page_and_forms(
        self, text: str, html: str, url: str, zone: str,
        preference_hint: str = "",
    ) -> dict[str, Any]: ...

    async def generate_search_queries(
        self, known_sites: list[str],
    ) -> list[dict[str, str]]: ...

    async def generate_form_fill_strategy(
        self,
        form_fields: list[str],
        user_data: dict[str, str],
        page_context: str,
    ) -> dict[str, str]: ...
