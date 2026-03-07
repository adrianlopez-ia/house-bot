"""Playwright browser lifecycle manager.

Encapsulates all browser creation, context setup, cookie dismissal, and
teardown behind a clean async interface -- no global state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
)

from db.models import ScrapeResult
from exceptions import ScraperError

logger = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

_COOKIE_SELECTORS = (
    "button:has-text('Aceptar')",
    "button:has-text('Aceptar todo')",
    "button:has-text('Aceptar todas')",
    "button:has-text('Accept')",
    "button:has-text('Accept all')",
    "[id*='cookie'] button",
    "[class*='cookie'] button",
    "[id*='consent'] button",
)

_STRIP_JS = """\
(() => {
    document.querySelectorAll(
        'script, style, noscript, iframe, svg'
    ).forEach(el => el.remove());
    return document.body ? document.body.innerText : '';
})()
"""

_SCROLL_JS = """\
(async () => {
    const delay = ms => new Promise(r => setTimeout(r, ms));
    for (let i = 0; i < 3; i++) {
        window.scrollBy(0, window.innerHeight);
        await delay(400);
    }
    window.scrollTo(0, 0);
})()
"""


class BrowserManager:
    """Owns a single Chromium instance; hands out ephemeral contexts."""

    def __init__(self, *, timeout_ms: int = 30_000) -> None:
        self._timeout_ms = timeout_ms
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def start(self) -> None:
        if self._browser is None or not self._browser.is_connected():
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            logger.info("Browser started")

    async def close(self) -> None:
        if self._browser and self._browser.is_connected():
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = None
        self._pw = None
        logger.info("Browser closed")

    async def new_context(self) -> BrowserContext:
        await self.start()
        return await self._browser.new_context(
            user_agent=_DEFAULT_UA,
            locale="es-ES",
            viewport={"width": 1280, "height": 900},
        )

    # ── high-level helpers ─────────────────────────────────────────────

    async def scrape(self, url: str, *, max_text: int = 50_000, max_html: int = 80_000) -> ScrapeResult:
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            await page.wait_for_timeout(2500)
            await dismiss_cookies(page)
            await page.evaluate(_SCROLL_JS)
            await page.wait_for_timeout(1500)

            title = await page.title()
            text = await page.evaluate(_STRIP_JS)
            html = await page.content()

            logger.info("Scraped: %s (%d chars)", url, len(text))
            return ScrapeResult(
                text=text[:max_text],
                html=html[:max_html],
                title=title,
                final_url=page.url,
                success=True,
            )
        except Exception as exc:
            logger.warning("Scrape failed for %s: %s", url, exc)
            return ScrapeResult(
                text="", html="", title="", final_url=url,
                success=False, error=str(exc),
            )
        finally:
            await ctx.close()

    async def screenshot(self, url: str, path: str) -> bool:
        ctx = await self.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            await page.wait_for_timeout(2000)
            await page.screenshot(path=path, full_page=True)
            return True
        except Exception as exc:
            logger.warning("Screenshot failed for %s: %s", url, exc)
            return False
        finally:
            await ctx.close()


async def dismiss_cookies(page: Page) -> None:
    """Best-effort dismissal of common cookie-consent banners."""
    for sel in _COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=2000)
                await page.wait_for_timeout(500)
                return
        except Exception:
            continue
