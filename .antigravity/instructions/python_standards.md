# Python Coding Standards

Specific standards for the `house-bot` Python codebase.

## 1. Core Technologies
- **Runtime**: Python 3.9+
- **Async**: Use `asyncio` for I/O operations (Scraping, AI, Telegram).
- **Type Checking**: Use `mypy` compatible type hints.
- **Data Models**: Use `db/models.py` with `dataclass(frozen=True)` for immutable domain models.
- **Validation**: Use `pydantic` (BaseSettings) in `config.py`.

## 2. Scraping & Automation
- **Playwright**: Use the `BrowserManager` in `scraper/browser.py` for browser lifecycle.
- **Resilience**: Implement retries for flaky websites.
- **Stealth**: Ensure scraping behavior is respectful and avoids detection.

## 3. AI Integration
- **Provider Agnostic**: Follow the `AIAnalyzer` protocol in `ai/protocols.py`.
- **Structured Output**: Always try to extract JSON from LLM responses using `ai/_json_parser.py`.
- **Costs**: Favor `gemini-2.0-flash-lite` or similar for discovery; use more powerful models only when necessary.

## 4. Testing
- **Framework**: Use `pytest`.
- **Async Tests**: Use `pytest-asyncio`.
- **Mocks**: Mock external services (AI, Telegram, DuckDuckGo) in unit tests.

## 5. Persistence
- **SQLite**: Use the Repository pattern in `db/repository.py`.
- **Migrations**: Since it's a simple bot, manual schema updates are okay for now, but keep `db/repository.py` as the source of truth for queries.
