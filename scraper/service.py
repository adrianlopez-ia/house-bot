"""Scraper orchestration service.

Coordinates browser scraping, AI analysis, and persistence for each site.
Supports two modes:
  - Normal: sequential analysis with a single AI provider
  - Turbo: parallel workers, one per configured AI provider
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

from ai.protocols import AIAnalyzer
from db.models import (
    AnalysisResult, AnalysisSummary, FormSubmission, FormStatus,
    FormType, Opportunity, OpportunityStatus, Site, Zone,
)
from db.repository import Repository
from exceptions import ScraperError
from scraper.browser import BrowserManager
from web.event_bus import emit as _emit

if TYPE_CHECKING:
    from ai.pool import AnalyzerPool, PoolEntry

logger = logging.getLogger(__name__)

_MIN_CONTENT_CHARS = 20


class ScraperService:
    def __init__(
        self,
        repo: Repository,
        ai: AIAnalyzer,
        browser: BrowserManager,
        *,
        max_sites_per_cycle: int = 100,
        delay_between_sites: int = 3,
        skip_visited_hours: int = 2,
        pool: "AnalyzerPool | None" = None,
    ) -> None:
        self._repo = repo
        self._ai = ai
        self._browser = browser
        self._lock = asyncio.Lock()
        self.max_sites_per_cycle = max_sites_per_cycle
        self.delay_between_sites = delay_between_sites
        self.skip_visited_hours = skip_visited_hours
        self._pool = pool

    def set_pool(self, pool: "AnalyzerPool") -> None:
        self._pool = pool

    def reconfigure(
        self,
        ai: AIAnalyzer,
        *,
        max_sites_per_cycle: int,
        delay_between_sites: int,
        skip_visited_hours: int,
    ) -> None:
        """Hot-swap AI provider and capacity settings."""
        self._ai = ai
        self.max_sites_per_cycle = max_sites_per_cycle
        self.delay_between_sites = delay_between_sites
        self.skip_visited_hours = skip_visited_hours

    # ── Single-site analysis (accepts optional AI override) ───────────

    async def analyze_site(
        self,
        site: Site,
        preference_hint: str = "",
        *,
        ai: AIAnalyzer | None = None,
    ) -> AnalysisResult:
        analyzer = ai or self._ai
        result = await self._browser.scrape(site.url)
        if not result.success:
            logger.warning("Skipping %s: %s", site.url, result.error)
            return AnalysisResult(error=result.error)

        if len(result.text.strip()) < _MIN_CONTENT_CHARS:
            logger.info(
                "Skipping %s: too little content (%d chars)",
                site.url, len(result.text.strip()),
            )
            await self._repo.mark_site_visited(site.id)
            return AnalysisResult()

        zone_str = site.zone.value if site.zone is not Zone.TODAS else ""

        combined = await analyzer.analyze_page_and_forms(
            result.text, result.html, site.url, zone_str, preference_hint,
        )

        opp_count = 0
        for data in combined.get("opportunities", []):
            opp = Opportunity(
                site_id=site.id,
                title=data.get("title", "Sin titulo"),
                url=data.get("url", site.url),
                description=data.get("description", ""),
                estimated_price=data.get("estimated_price"),
                zone=_parse_zone(data.get("zone", zone_str) or site.zone.value),
                status=_parse_opp_status(data.get("status", "nueva")),
                ai_score=data.get("ai_score"),
                house_type=data.get("house_type"),
                bedrooms=data.get("bedrooms"),
                sqm=data.get("sqm"),
                amenities=data.get("amenities"),
                protection_type=data.get("protection_type"),
                availability=data.get("availability"),
                project_date=data.get("project_date"),
            )
            await self._repo.upsert_opportunity(opp)
            opp_count += 1
            logger.info("Opportunity: %s (score=%s)", opp.title, opp.ai_score)
            _emit({
                "type": "opportunity_found",
                "title": opp.title,
                "score": opp.ai_score,
                "zone": opp.zone.value,
                "price": opp.estimated_price,
            })

        form_count = 0
        for fdata in combined.get("forms", []):
            form = FormSubmission(
                site_id=site.id,
                form_url=site.url,
                status=FormStatus.PENDIENTE,
                form_type=_parse_form_type(fdata.get("form_type", "contacto")),
            )
            await self._repo.upsert_form(form)
            form_count += 1

        await self._repo.mark_site_visited(site.id)
        logger.info("Analyzed %s: %d opps, %d forms", site.name, opp_count, form_count)
        return AnalysisResult(opportunities=opp_count, forms=form_count)

    # ── Analyze all ───────────────────────────────────────────────────

    async def analyze_all(self) -> AnalysisSummary:
        if self._lock.locked():
            logger.warning("Scrape already running, skipping")
            return AnalysisSummary()

        async with self._lock:
            prefs = await self._repo.get_preferences()
            turbo = prefs.get("turbo_mode", True)
            use_turbo = (
                turbo
                and self._pool is not None
                and self._pool.active_count > 1
            )
            if use_turbo:
                return await self._analyze_turbo(prefs)
            return await self._analyze_sequential(prefs)

    # ── Sequential mode (original) ────────────────────────────────────

    async def _analyze_sequential(self, prefs: dict) -> AnalysisSummary:
        sites = await self._get_pending_sites(self.max_sites_per_cycle)
        if not sites:
            logger.info("All sites recently visited, nothing to analyze")
            return AnalysisSummary()

        pref_hint = build_preference_hint(prefs)
        logger.info(
            "Sequential: analyzing %d sites (max %d/cycle, delay %ds)",
            len(sites), self.max_sites_per_cycle, self.delay_between_sites,
        )

        total_opps = total_forms = errors = 0
        for idx, site in enumerate(sites):
            _emit({
                "type": "site_analyzing",
                "site": site.name, "url": site.url,
                "index": idx + 1, "total": len(sites),
            })
            try:
                result = await self.analyze_site(site, pref_hint)
                total_opps += result.opportunities
                total_forms += result.forms
                if result.error:
                    errors += 1
                    _emit({"type": "site_error", "site": site.name, "error": result.error})
                else:
                    _emit({"type": "site_analyzed", "site": site.name,
                           "opps": result.opportunities, "forms": result.forms})
            except Exception as exc:
                logger.error("Error analyzing %s: %s", site.url, exc)
                errors += 1
                _emit({"type": "site_error", "site": site.name, "error": str(exc)[:200]})

            if idx < len(sites) - 1:
                await asyncio.sleep(self.delay_between_sites)

        return _summary(len(sites), total_opps, total_forms, errors)

    # ── Turbo mode (parallel multi-provider) ──────────────────────────

    async def _analyze_turbo(self, prefs: dict) -> AnalysisSummary:
        pool = self._pool
        assert pool is not None

        max_sites = pool.total_capacity()
        sites = await self._get_pending_sites(max_sites)
        if not sites:
            logger.info("All sites recently visited, nothing to analyze")
            return AnalysisSummary()

        pref_hint = build_preference_hint(prefs)
        entries = pool.get_available()

        _emit({"type": "turbo_start", "providers": [e.name for e in entries],
               "sites": len(sites)})
        logger.info(
            "TURBO: %d sites across %d providers (%s)",
            len(sites), len(entries),
            ", ".join(f"{e.name}({e.rpm}rpm)" for e in entries),
        )

        queue: asyncio.Queue[Site] = asyncio.Queue()
        for s in sites:
            queue.put_nowait(s)

        counter = _Counter()

        async def worker(entry: "PoolEntry") -> None:
            while True:
                if not entry.is_available():
                    logger.info("Turbo worker %s: disabled, stopping", entry.name)
                    break
                try:
                    site = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                async with entry.semaphore:
                    idx = counter.analyzed + counter.errors + 1
                    _emit({
                        "type": "site_analyzing",
                        "site": site.name, "url": site.url,
                        "index": idx, "total": len(sites),
                        "provider": entry.name,
                    })
                    try:
                        result = await self.analyze_site(
                            site, pref_hint, ai=entry.analyzer,
                        )
                        entry.record_success()
                        counter.analyzed += 1
                        counter.opps += result.opportunities
                        counter.forms += result.forms
                        if result.error:
                            counter.errors += 1
                            _emit({"type": "site_error", "site": site.name,
                                   "error": result.error})
                        else:
                            _emit({"type": "site_analyzed", "site": site.name,
                                   "opps": result.opportunities,
                                   "forms": result.forms,
                                   "provider": entry.name})
                    except Exception as exc:
                        err_str = str(exc)
                        is_rl = "429" in err_str or "rate" in err_str.lower()
                        entry.record_error(rate_limited=is_rl)
                        counter.errors += 1
                        logger.error("Turbo %s error on %s: %s",
                                     entry.name, site.url, exc)
                        _emit({"type": "site_error", "site": site.name,
                               "error": f"[{entry.name}] {err_str[:150]}"})
                        if is_rl:
                            queue.put_nowait(site)
                            break

                await asyncio.sleep(entry.delay)

        await asyncio.gather(*(worker(e) for e in entries))

        _emit({"type": "turbo_end",
               "analyzed": counter.analyzed, "opps": counter.opps,
               "errors": counter.errors, "pool_status": pool.status()})
        logger.info(
            "TURBO complete: %d analyzed, %d opps, %d forms, %d errors",
            counter.analyzed, counter.opps, counter.forms, counter.errors,
        )
        return _summary(counter.analyzed, counter.opps, counter.forms,
                        counter.errors)

    # ── Helpers ────────────────────────────────────────────────────────

    async def _get_pending_sites(self, max_count: int) -> list[Site]:
        all_sites = await self._repo.get_active_sites()
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=self.skip_visited_hours)
        ).isoformat()
        sites: list[Site] = []
        for s in all_sites:
            if s.last_visited and s.last_visited > cutoff:
                continue
            sites.append(s)
            if len(sites) >= max_count:
                break
        return sites


class _Counter:
    __slots__ = ("analyzed", "opps", "forms", "errors")

    def __init__(self) -> None:
        self.analyzed = self.opps = self.forms = self.errors = 0


def _summary(analyzed: int, opps: int, forms: int, errors: int) -> AnalysisSummary:
    s = AnalysisSummary(
        sites_analyzed=analyzed,
        opportunities_found=opps,
        forms_found=forms,
        errors=errors,
    )
    logger.info("Analysis complete: %d sites, %d opps, %d forms, %d errors",
                s.sites_analyzed, s.opportunities_found, s.forms_found, s.errors)
    return s


def _parse_zone(raw: str) -> Zone:
    try:
        return Zone(raw.lower())
    except ValueError:
        return Zone.TODAS


def _parse_opp_status(raw: str) -> OpportunityStatus:
    try:
        return OpportunityStatus(raw.lower())
    except ValueError:
        return OpportunityStatus.NUEVA


def _parse_form_type(raw: str) -> FormType:
    try:
        return FormType(raw.lower())
    except ValueError:
        return FormType.CONTACTO


def build_preference_hint(prefs: dict) -> str:
    """Build a human-readable preference summary for AI prompts."""
    if not prefs:
        return ""
    parts: list[str] = []
    if prefs.get("zones"):
        parts.append(f"Zonas preferidas: {', '.join(prefs['zones'])}")
    if prefs.get("house_types"):
        parts.append(f"Tipos preferidos: {', '.join(prefs['house_types'])}")
    pmin, pmax = prefs.get("price_min"), prefs.get("price_max")
    if pmin or pmax:
        parts.append(f"Precio: {pmin or '?'} - {pmax or '?'} EUR")
    if prefs.get("bedrooms_min"):
        parts.append(f"Minimo {prefs['bedrooms_min']} habitaciones")
    if prefs.get("sqm_min"):
        parts.append(f"Minimo {prefs['sqm_min']} m2")
    if prefs.get("amenities"):
        parts.append(f"Extras deseados: {', '.join(prefs['amenities'])}")
    if prefs.get("protection_types"):
        parts.append(f"Proteccion: {', '.join(prefs['protection_types'])}")
    if not parts:
        return ""
    return "PREFERENCIAS DEL USUARIO:\n" + "\n".join(f"- {p}" for p in parts)
