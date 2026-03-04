"""Domain-specific exception hierarchy.

Every layer raises its own subclass so callers can decide granularity of
their ``except`` clauses while the top-level scheduler can always catch
``HouseBotError`` as a safety net.
"""
from __future__ import annotations


class HouseBotError(Exception):
    """Root exception for the entire application."""


class ConfigError(HouseBotError):
    """Missing or invalid configuration."""


class ScraperError(HouseBotError):
    """Failure during page scraping or browser automation."""


class AIAnalysisError(HouseBotError):
    """Failure during AI content analysis."""


class FormFillingError(HouseBotError):
    """Failure while detecting or filling a web form."""


class DiscoveryError(HouseBotError):
    """Failure during site discovery."""


class NotifierError(HouseBotError):
    """Failure sending a Telegram notification."""


class RepositoryError(HouseBotError):
    """Failure accessing the database."""
