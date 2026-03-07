"""Scraper orchestration service.

Coordinates browser scraping, AI analysis, and persistence for each site.
Uses a single AI call per site to conserve API quota.
Includes a global lock to prevent concurrent scrape runs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from ai.protocols import AIAnalyzer
from db.models import (
    AnalysisResult, AnalysisSummary, FormSubmission, FormStatus,
    FormType, Opportunity, OpportunityStatus, Site, Zone,
)
from db.repository import Repository
from exceptions import ScraperError
from scraper.browser import BrowserManager
from web.event_bus import emit as _emit

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
    ) -> None:
        self._repo = repo
        self._ai = ai
        self._browser = browser
        self._lock = asyncio.Lock()
        self.max_sites_per_cycle = max_sites_per_cycle
        self.delay_between_sites = delay_between_sites
        self.skip_visited_hours = skip_visited_hours

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

    async def analyze_site(
        self, site: Site, preference_hint: str = "",
    ) -> AnalysisResult:
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

        combined = await self._ai.analyze_page_and_forms(
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

    async def analyze_all(self) -> AnalysisSummary:
        if self._lock.locked():
            logger.warning("Scrape already running, skipping")
            return AnalysisSummary()

        async with self._lock:
            return await self._analyze_all_locked()

    async def _analyze_all_locked(self) -> AnalysisSummary:
        all_sites = await self._repo.get_active_sites()
        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=self.skip_visited_hours)
        ).isoformat()

        sites = []
        for s in all_sites:
            if s.last_visited and s.last_visited > cutoff:
                continue
            sites.append(s)
            if len(sites) >= self.max_sites_per_cycle:
                break

        if not sites:
            logger.info("All sites recently visited, nothing to analyze")
            return AnalysisSummary()

        pref_hint = build_preference_hint(await self._repo.get_preferences())
        logger.info(
            "Analyzing %d/%d sites (max %d/cycle, skip <%dh, delay %ds)",
            len(sites), len(all_sites), self.max_sites_per_cycle,
            self.skip_visited_hours, self.delay_between_sites,
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
                    _emit({
                        "type": "site_error",
                        "site": site.name, "error": result.error,
                    })
                else:
                    _emit({
                        "type": "site_analyzed",
                        "site": site.name,
                        "opps": result.opportunities,
                        "forms": result.forms,
                    })
            except Exception as exc:
                logger.error("Error analyzing %s: %s", site.url, exc)
                errors += 1
                _emit({
                    "type": "site_error",
                    "site": site.name, "error": str(exc)[:200],
                })

            if idx < len(sites) - 1:
                await asyncio.sleep(self.delay_between_sites)

        summary = AnalysisSummary(
            sites_analyzed=len(sites),
            opportunities_found=total_opps,
            forms_found=total_forms,
            errors=errors,
        )
        logger.info(
            "Analysis complete: %d sites, %d opps, %d forms, %d errors",
            summary.sites_analyzed, summary.opportunities_found,
            summary.forms_found, summary.errors,
        )
        return summary


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
