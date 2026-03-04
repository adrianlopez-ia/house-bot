"""Scraper orchestration service.

Coordinates browser scraping, AI analysis, and persistence for each site.
All external dependencies are injected via the constructor.
"""
from __future__ import annotations

import logging

from ai.protocols import AIAnalyzer
from db.models import (
    AnalysisResult, AnalysisSummary, FormSubmission, FormStatus,
    FormType, Opportunity, OpportunityStatus, Site, Zone,
)
from db.repository import Repository
from exceptions import ScraperError
from scraper.browser import BrowserManager

logger = logging.getLogger(__name__)


class ScraperService:
    def __init__(
        self,
        repo: Repository,
        ai: AIAnalyzer,
        browser: BrowserManager,
    ) -> None:
        self._repo = repo
        self._ai = ai
        self._browser = browser

    async def analyze_site(self, site: Site) -> AnalysisResult:
        result = await self._browser.scrape(site.url)
        if not result.success:
            logger.warning("Skipping %s: %s", site.url, result.error)
            return AnalysisResult(error=result.error)

        zone_str = site.zone.value if site.zone is not Zone.TODAS else ""

        raw_opps = await self._ai.analyze_page(result.text, site.url, zone_str)
        opp_count = 0
        for data in raw_opps:
            opp = Opportunity(
                site_id=site.id,
                title=data.get("title", "Sin titulo"),
                url=data.get("url", site.url),
                description=data.get("description", ""),
                estimated_price=data.get("estimated_price"),
                zone=_parse_zone(data.get("zone", zone_str) or site.zone.value),
                status=_parse_opp_status(data.get("status", "nueva")),
                ai_score=data.get("ai_score"),
            )
            await self._repo.upsert_opportunity(opp)
            opp_count += 1
            logger.info("Opportunity: %s (score=%s)", opp.title, opp.ai_score)

        raw_forms = await self._ai.detect_forms(result.html, site.url)
        form_count = 0
        for fdata in raw_forms:
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
        sites = await self._repo.get_active_sites()
        total_opps = total_forms = errors = 0

        for site in sites:
            try:
                result = await self.analyze_site(site)
                total_opps += result.opportunities
                total_forms += result.forms
                if result.error:
                    errors += 1
            except Exception as exc:
                logger.error("Error analyzing %s: %s", site.url, exc)
                errors += 1

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
