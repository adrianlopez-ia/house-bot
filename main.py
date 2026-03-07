#!/usr/bin/env python3
"""Madrid Housing Bot -- composition root.

This module is the single place where all services are instantiated and
wired together (Dependency Injection via constructors).  No service knows
how the others are created; they only depend on protocols and interfaces.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from aiohttp import web

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ai.pool import AnalyzerPool
from ai.providers import build_analyzer, get_provider
from config import Settings, load_settings
from exceptions import ConfigError

logger = logging.getLogger("house_bot")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("house_bot.log", encoding="utf-8"),
        ],
    )


# ── Web server (dashboard + API + health check) ───────────────────────

async def _health(_request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def _start_web_server(container: "_Container") -> web.AppRunner:
    from pathlib import Path
    from web.api import build_api_routes

    app = web.Application()
    app.router.add_get("/health", _health)

    api_routes = build_api_routes(container)
    app.router.add_routes(api_routes)

    static_dir = Path(__file__).parent / "web" / "static"
    if static_dir.is_dir():
        app.router.add_static("/static", static_dir)
        index_html = static_dir / "index.html"

        async def _serve_index(_req: web.Request) -> web.FileResponse:
            return web.FileResponse(index_html)

        app.router.add_get("/", _serve_index)
    else:
        app.router.add_get("/", _health)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Web server listening on port %d", port)
    return runner


# ── Service container ──────────────────────────────────────────────────

class _Container:
    """Holds all service instances -- created once, used everywhere."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        from db.repository import Repository
        from discovery.service import DiscoveryService
        from forms.service import FormService
        from notifier.service import NotifierService
        from scraper.browser import BrowserManager
        from scraper.service import ScraperService

        provider = settings.ai_provider.lower()
        profile = get_provider(provider)

        self.repo = Repository(settings.db_path)
        self.ai = build_analyzer(provider, settings.ai_model, settings)
        self.browser = BrowserManager(timeout_ms=settings.playwright_timeout_ms)

        max_sites = settings.max_sites_per_cycle or profile["auto_sites_per_cycle"]
        delay = profile["delay_between_sites"]
        skip_h = profile["auto_skip_hours"]

        self.pool = AnalyzerPool(settings)

        self.discovery = DiscoveryService(self.repo, ai=self.ai)
        self.scraper = ScraperService(
            self.repo, self.ai, self.browser,
            max_sites_per_cycle=max_sites,
            delay_between_sites=delay,
            skip_visited_hours=skip_h,
            pool=self.pool,
        )
        self.forms = FormService(
            self.repo, self.ai, self.browser,
            settings.user_data.as_dict(),
            settings.screenshots_dir,
        )
        self.notifier = NotifierService(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
            self.repo,
        )
        self.notifier.set_services(self.discovery, self.scraper, self.forms)

        logger.info(
            "AI: %s / %s (max %d sites/cycle, %ds delay, skip <%dh)",
            profile["name"], getattr(self.ai, "_model", "?"),
            max_sites, delay, skip_h,
        )

    async def startup(self) -> None:
        await self.repo.init()
        await self.notifier.start()

    async def shutdown(self) -> None:
        await self.notifier.stop()
        await self.browser.close()


# ── Scheduled jobs ─────────────────────────────────────────────────────

async def _job_scrape(c: _Container) -> None:
    logger.info("JOB scrape start")
    try:
        summary = await c.scraper.analyze_all()
        sent = await c.notifier.send_new_alerts()
        logger.info("JOB scrape done: %d opps, %d alerts", summary.opportunities_found, sent)
    except Exception as exc:
        logger.error("JOB scrape failed: %s", exc)


async def _job_discover(c: _Container) -> None:
    logger.info("JOB discover start")
    try:
        new_sites = await c.discovery.discover()
        if new_sites:
            names = "\n".join(f"  - {s.name}" for s in new_sites[:10])
            await c.notifier.send(f"*Nuevos sitios descubiertos:* {len(new_sites)}\n{names}")
        logger.info("JOB discover done: %d new", len(new_sites))
    except Exception as exc:
        logger.error("JOB discover failed: %s", exc)


async def _job_fill_forms(c: _Container) -> None:
    logger.info("JOB fill_forms start")
    try:
        result = await c.forms.fill_pending()
        if result.filled > 0:
            await c.notifier.send(
                f"*Formularios rellenados:* {result.filled}\n"
                f"Errores: {result.errors}\nOmitidos: {result.skipped}",
            )
        logger.info("JOB fill_forms done: %s", result)
    except Exception as exc:
        logger.error("JOB fill_forms failed: %s", exc)


async def _job_weekly(c: _Container) -> None:
    logger.info("JOB weekly_report")
    try:
        await c.notifier.send_weekly_report()
    except Exception as exc:
        logger.error("JOB weekly_report failed: %s", exc)


async def _initial_run(c: _Container) -> None:
    logger.info("Initial run start")
    await c.discovery.load_seeds()
    await c.discovery.discover()
    await c.notifier.send_new_alerts()
    logger.info("Initial run complete (scrape deferred to scheduled job)")


# ── Entry point ────────────────────────────────────────────────────────

async def main() -> None:
    _setup_logging()
    settings = load_settings()

    missing = settings.validate_required()
    if missing:
        for key in missing:
            logger.error("Missing required config: %s", key)
        raise ConfigError(
            "Fix .env and restart. See .env.example for reference. "
            f"Missing: {', '.join(missing)}"
        )

    container = _Container(settings)
    await container.startup()
    logger.info("All services started")

    web_runner = await _start_web_server(container)

    profile = get_provider(settings.ai_provider)
    scrape_h = settings.scrape_interval_hours or profile["auto_interval_hours"]
    form_h = settings.form_fill_interval_hours

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _job_scrape, IntervalTrigger(hours=scrape_h),
        args=[container], id="scrape", max_instances=1,
    )
    scheduler.add_job(
        _job_discover, IntervalTrigger(hours=settings.discovery_interval_hours),
        args=[container], id="discover", max_instances=1,
    )
    scheduler.add_job(
        _job_fill_forms, IntervalTrigger(hours=form_h),
        args=[container], id="fill_forms", max_instances=1,
    )
    scheduler.add_job(
        _job_weekly, CronTrigger(day_of_week="mon", hour=9, minute=0),
        args=[container], id="weekly_report", max_instances=1,
    )
    scheduler.start()
    logger.info(
        "Scheduler: scrape=%dh, discover=%dh, forms=%dh, weekly=Mon 09:00",
        scrape_h, settings.discovery_interval_hours, form_h,
    )

    asyncio.create_task(_initial_run(container))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("Bot running. Press Ctrl+C to stop.")
    await stop.wait()

    logger.info("Shutting down...")
    scheduler.shutdown(wait=False)
    await container.shutdown()
    await web_runner.cleanup()
    logger.info("Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
