"""Playwright browser lifecycle manager.

Owns a single Chromium instance; hands out ephemeral contexts.
Includes a startup lock to prevent concurrent launches and automatic
recycling after N scrapes to keep memory bounded.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
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

_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--disable-translate",
    "--disable-sync",
    "--disable-software-rasterizer",
    "--no-first-run",
    "--js-flags=--max-old-space-size=128",
]

_RECYCLE_AFTER = 10


class BrowserManager:
    """Owns a single Chromium instance; hands out ephemeral contexts."""

    def __init__(self, *, timeout_ms: int = 30_000) -> None:
        self._timeout_ms = timeout_ms
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._lock = asyncio.Lock()
        self._scrape_count = 0

    async def start(self) -> None:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                args=_CHROMIUM_ARGS,
            )
            self._scrape_count = 0
            logger.info("Browser started (low-memory mode)")

    async def close(self) -> None:
        async with self._lock:
            await self._close_internal()

    async def _close_internal(self) -> None:
        if self._browser and self._browser.is_connected():
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None
        self._scrape_count = 0
        logger.info("Browser closed")

    async def _recycle_if_needed(self) -> None:
        if self._scrape_count >= _RECYCLE_AFTER:
            logger.info("Recycling browser after %d scrapes", self._scrape_count)
            await self._close_internal()

    async def _new_context(self) -> BrowserContext:
        await self.start()
        return await self._browser.new_context(
            user_agent=_DEFAULT_UA,
            locale="es-ES",
            viewport={"width": 1024, "height": 768},
        )

    # ── high-level helpers ─────────────────────────────────────────────

    async def scrape(self, url: str, *, max_text: int = 20_000, max_html: int = 12_000) -> ScrapeResult:
        for attempt in range(2):
            try:
                return await self._scrape_once(url, max_text=max_text, max_html=max_html)
            except Exception as exc:
                if attempt == 0 and "closed" in str(exc).lower():
                    logger.warning("Browser died, restarting for retry: %s", url)
                    async with self._lock:
                        await self._close_internal()
                    continue
                logger.warning("Scrape failed for %s: %s", url, exc)
                return ScrapeResult(
                    text="", html="", title="", final_url=url,
                    success=False, error=str(exc)[:300],
                )
        return ScrapeResult(text="", html="", title="", final_url=url,
                            success=False, error="max retries")

    async def _scrape_once(self, url: str, *, max_text: int, max_html: int) -> ScrapeResult:
        async with self._lock:
            await self._recycle_if_needed()

        ctx = await self._new_context()
        try:
            page = await ctx.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=self._timeout_ms)
            await page.wait_for_timeout(1500)
            await dismiss_cookies(page)
            await page.evaluate(_SCROLL_JS)
            await page.wait_for_timeout(800)

            title = await page.title()
            text = await page.evaluate(_STRIP_JS)
            html = await page.content()

            self._scrape_count += 1
            logger.info("Scraped: %s (%d chars)", url, len(text))
            return ScrapeResult(
                text=text[:max_text],
                html=html[:max_html],
                title=title,
                final_url=page.url,
                success=True,
            )
        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    async def screenshot(self, url: str, path: str) -> bool:
        ctx = await self._new_context()
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
            try:
                await ctx.close()
            except Exception:
                pass


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
