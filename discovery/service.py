"""Site discovery service.

Loads seed sites, runs DuckDuckGo searches, and persists new finds.
All external dependencies are injected.
"""
from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from db.models import Site, SiteType, Zone
from db.repository import Repository
from discovery.seed_sites import SEARCH_QUERIES, SEED_SITES
from exceptions import DiscoveryError

logger = logging.getLogger(__name__)

_EXCLUDED_DOMAINS = frozenset({
    "youtube.com", "facebook.com", "twitter.com", "instagram.com",
    "linkedin.com", "tiktok.com", "reddit.com", "wikipedia.org",
    "amazon.es", "amazon.com",
})


class DiscoveryService:
    def __init__(self, repo: Repository) -> None:
        self._repo = repo

    async def load_seeds(self) -> list[int]:
        ids: list[int] = []
        for site in SEED_SITES:
            site_id = await self._repo.upsert_site(site)
            ids.append(site_id)
            logger.info("Seed loaded: %s (id=%d)", site.name, site_id)
        return ids

    async def discover(
        self, extra_queries: list[dict[str, str]] | None = None,
    ) -> list[Site]:
        queries = list(SEARCH_QUERIES) + (extra_queries or [])
        known_domains = {
            urlparse(s.url).netloc.replace("www.", "")
            for s in await self._repo.get_all_sites()
        }
        new_sites: list[Site] = []

        for q in queries:
            results = await _search_ddg(q["query"])
            for hit in results:
                url: str = hit["href"]
                domain = urlparse(url).netloc.replace("www.", "")
                if domain in _EXCLUDED_DOMAINS or domain in known_domains:
                    continue

                site = Site(
                    url=url,
                    name=hit.get("title", domain)[:120],
                    zone=_parse_zone(q.get("zone", "")),
                    site_type=_guess_type(
                        hit.get("title", ""), hit.get("body", ""),
                    ),
                )
                site_id = await self._repo.upsert_site(site)
                new_sites.append(Site(
                    url=site.url, name=site.name, zone=site.zone,
                    site_type=site.site_type, id=site_id,
                ))
                known_domains.add(domain)
                logger.info("Discovered: %s -> %s", site.name, url)

        logger.info("Discovery complete: %d new sites", len(new_sites))
        return new_sites


async def _search_ddg(query: str, max_results: int = 10) -> list[dict]:
    def _run() -> list[dict]:
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, region="es-es", max_results=max_results))
        except Exception as exc:
            logger.warning("DDG search failed for '%s': %s", query, exc)
            return []

    return await asyncio.to_thread(_run)


def _guess_type(title: str, body: str) -> SiteType:
    text = f"{title} {body}".lower()
    if any(kw in text for kw in ("cooperativa", "cooperativas", "cooptima")):
        return SiteType.COOPERATIVA
    if any(kw in text for kw in ("constructora", "promotora", "promocion", "obra nueva")):
        return SiteType.CONSTRUCTORA
    return SiteType.PORTAL


def _parse_zone(raw: str) -> Zone:
    try:
        return Zone(raw.lower())
    except ValueError:
        return Zone.TODAS
