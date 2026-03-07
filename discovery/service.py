"""Site discovery service.

Loads seed sites, runs DuckDuckGo searches, and persists new finds.
Uses AI + user preferences to generate targeted search queries.
All external dependencies are injected.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlparse

from duckduckgo_search import DDGS

from db.models import Site, SiteType, Zone
from db.repository import Repository
from discovery.seed_sites import SEARCH_QUERIES, SEED_SITES
from exceptions import DiscoveryError
from web.event_bus import emit as _emit

logger = logging.getLogger(__name__)

_EXCLUDED_DOMAINS = frozenset({
    "youtube.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "linkedin.com", "tiktok.com", "reddit.com",
    "wikipedia.org", "amazon.es", "amazon.com", "google.com",
    "bing.com", "yahoo.com", "whatsapp.com", "web.whatsapp.com",
    "mediamarkt.es", "elcorteingles.es", "groupon.es", "lidl.es",
    "tiendeo.com", "poki.com", "gry.pl", "bab.la", "rae.es",
    "wordreference.com", "thefreedictionary.com", "wiktionary.org",
    "scribd.com", "zhihu.com", "se-escribe.com",
})

_REQUIRED_KEYWORDS = frozenset({
    "vivienda", "cooperativa", "constructora", "obra nueva", "promocion",
    "piso", "casa", "inmobiliaria", "residencial", "urbanizacion", "nuevo norte",
    "madrid", "alcobendas", "torrejon", "solana", "fuencarral",
    "barrio del pilar", "arroyofresno", "valdebebas", "valdezarza",
    "tetuan", "hortaleza", "las tablas", "la moraleja",
    "pozuelo", "majadahonda", "boadilla", "san sebastian",
    "tres cantos", "colmenar", "las rozas", "villanueva",
    "alcala de henares", "arganda", "villaviciosa", "coslada", "rivas",
    "promotora", "pisos nuevos", "vpo", "vppl", "vivienda protegida",
    "entrega", "dormitorio", "habitacion", "desde", "precio",
    "comprar piso", "obra nueva madrid",
})

_ES_TLDS = (".es", ".com", ".org", ".net", ".eu")

_ZONE_TERMS = {
    "norte": "Alcobendas Tres Cantos Colmenar Viejo San Sebastian Reyes",
    "este": "Torrejon Coslada Rivas Alcala Henares Arganda",
    "oeste": "Pozuelo Majadahonda Boadilla Las Rozas Villanueva",
}


class DiscoveryService:
    """Discovers housing sites via seeds, DuckDuckGo, and AI-generated queries."""

    def __init__(self, repo: Repository, ai: Optional[Any] = None) -> None:
        self._repo = repo
        self._ai = ai

    def set_ai(self, ai: Any) -> None:
        """Hot-swap the AI analyzer (called when user switches provider)."""
        self._ai = ai

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
        prefs = await self._repo.get_preferences()
        turbo = prefs.get("turbo_mode", True)

        queries = list(SEARCH_QUERIES) + (extra_queries or [])
        pref_queries = _build_preference_queries(prefs)
        if pref_queries:
            queries += pref_queries
            logger.info("Added %d preference-based queries", len(pref_queries))

        known_domains = {
            urlparse(s.url).netloc.replace("www.", "")
            for s in await self._repo.get_all_sites()
        }
        new_sites: list[Site] = []

        if turbo:
            raw = await self._run_queries_parallel(queries, known_domains)
        else:
            raw = await self._run_queries(queries, known_domains)
        found = await self._persist_and_emit(raw)
        new_sites += found
        logger.info("Phase 1 (%s): %d new sites from %d queries",
                     "parallel" if turbo else "sequential", len(found), len(queries))

        if self._ai and hasattr(self._ai, "generate_search_queries"):
            try:
                known_urls = [s.url for s in await self._repo.get_all_sites()]
                _emit({"type": "discovery_searching",
                       "query": "IA generando queries con tus preferencias...",
                       "zone": "todas", "index": 0, "total": 0})
                ai_queries = await self._ai.generate_search_queries(
                    known_urls, prefs,
                )
                if ai_queries:
                    logger.info("AI generated %d extra queries", len(ai_queries))
                    if turbo:
                        raw_ai = await self._run_queries_parallel(ai_queries, known_domains)
                    else:
                        raw_ai = await self._run_queries(ai_queries, known_domains)
                    found_ai = await self._persist_and_emit(raw_ai)
                    new_sites += found_ai
                    logger.info("Phase 2 (AI queries): %d new sites from %d queries",
                                len(found_ai), len(ai_queries))
            except Exception as exc:
                logger.warning("AI query generation failed (non-fatal): %s", exc)

        logger.info("Discovery complete: %d total new sites", len(new_sites))
        return new_sites

    # ── Sequential query runner ───────────────────────────────────────

    async def _run_queries(
        self,
        queries: list[dict[str, str]],
        known_domains: set[str],
    ) -> list[Site]:
        new_sites: list[Site] = []
        total = len(queries)
        for qi, q in enumerate(queries):
            query_text = q.get("query", "")
            if not query_text:
                continue
            _emit({
                "type": "discovery_searching",
                "query": query_text, "zone": q.get("zone", "todas"),
                "index": qi + 1, "total": total,
            })
            hits = await _search_ddg(query_text)
            new_sites += self._process_hits(hits, q, known_domains)
        return new_sites

    # ── Parallel query runner (turbo) ─────────────────────────────────

    async def _run_queries_parallel(
        self,
        queries: list[dict[str, str]],
        known_domains: set[str],
        max_concurrent: int = 6,
    ) -> list[Site]:
        sem = asyncio.Semaphore(max_concurrent)
        total = len(queries)
        completed = 0

        async def _search_one(qi: int, q: dict[str, str]) -> list[dict]:
            nonlocal completed
            query_text = q.get("query", "")
            if not query_text:
                return []
            async with sem:
                _emit({
                    "type": "discovery_searching",
                    "query": query_text, "zone": q.get("zone", "todas"),
                    "index": qi + 1, "total": total,
                })
                result = await _search_ddg(query_text)
                completed += 1
                return result

        tasks = [_search_one(i, q) for i, q in enumerate(queries)]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)

        new_sites: list[Site] = []
        for i, result in enumerate(batch_results):
            if isinstance(result, Exception):
                logger.warning("Parallel DDG error for query %d: %s", i, result)
                continue
            new_sites += self._process_hits(result, queries[i], known_domains)

        logger.info("Parallel discovery: %d queries -> %d new sites",
                     total, len(new_sites))
        return new_sites

    # ── Shared hit processing ─────────────────────────────────────────

    def _process_hits(
        self,
        hits: list[dict],
        q: dict[str, str],
        known_domains: set[str],
    ) -> list[Site]:
        """Synchronous part: filter hits, build Site objects. DB writes are deferred."""
        new: list[Site] = []
        for hit in hits:
            url: str = hit.get("href", "")
            if not url:
                continue
            domain = urlparse(url).netloc.replace("www.", "")
            if domain in _EXCLUDED_DOMAINS or domain in known_domains:
                continue
            title = hit.get("title", "")
            body = hit.get("body", "")
            if not _is_relevant(url, title, body):
                continue
            site = Site(
                url=url,
                name=title[:120] or domain,
                zone=_parse_zone(q.get("zone", "")),
                site_type=_guess_type(title, body),
            )
            new.append(site)
            known_domains.add(domain)
        return new

    async def _persist_and_emit(self, sites: list[Site]) -> list[Site]:
        """Save discovered sites to DB and emit events."""
        result: list[Site] = []
        for site in sites:
            site_id = await self._repo.upsert_site(site)
            result.append(Site(
                url=site.url, name=site.name, zone=site.zone,
                site_type=site.site_type, id=site_id,
            ))
            logger.info("Discovered: %s -> %s", site.name, site.url)
            _emit({"type": "discovery_found", "site": site.name,
                   "url": site.url, "zone": site.zone.value})
        return result


def _build_preference_queries(prefs: dict) -> list[dict[str, str]]:
    """Generate extra DuckDuckGo queries based on user preferences."""
    if not prefs:
        return []
    queries: list[dict[str, str]] = []

    zones = prefs.get("zones") or ["norte", "este", "oeste"]
    house_types = prefs.get("house_types") or []
    protection = prefs.get("protection_types") or []

    pmin = prefs.get("price_min")
    pmax = prefs.get("price_max")
    price_hint = ""
    if pmax:
        price_hint = f" desde {pmin or 0} hasta {pmax} euros"
    elif pmin:
        price_hint = f" desde {pmin} euros"

    beds = prefs.get("bedrooms_min")
    beds_hint = f" {beds} habitaciones" if beds else ""

    for zone in zones:
        zone_towns = _ZONE_TERMS.get(zone, "")

        for ht in (house_types or [""]):
            type_word = ht if ht else "vivienda"
            queries.append({
                "query": f"{type_word} obra nueva Madrid {zone} {zone_towns}{price_hint}{beds_hint} 2025 2026",
                "zone": zone,
            })

        for pt in protection:
            queries.append({
                "query": f"{pt} vivienda protegida Madrid {zone} {zone_towns} 2025 2026",
                "zone": zone,
            })

        queries.append({
            "query": f"cooperativa vivienda Madrid {zone} {zone_towns}{price_hint} nueva inscripcion",
            "zone": zone,
        })

    return queries


def _is_relevant(url: str, title: str, body: str) -> bool:
    """Filter out results that are clearly not Spanish housing-related."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    tld = "." + domain.rsplit(".", 1)[-1] if "." in domain else ""

    if tld not in _ES_TLDS:
        return False

    text = f"{title} {body}".lower()
    return any(kw in text for kw in _REQUIRED_KEYWORDS)


async def _search_ddg(query: str, max_results: int = 25) -> list[dict]:
    def _run() -> list[dict]:
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(
                    query, region="es-es", max_results=max_results,
                ))
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
