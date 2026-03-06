"""REST API endpoints for the dashboard."""
from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    pass


def _json(data: object, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _serialize(obj: object) -> dict:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        d = dataclasses.asdict(obj)
        for k, v in d.items():
            if hasattr(v, "value"):
                d[k] = v.value
        return d
    return {}


_running_actions: dict[str, bool] = {}


def build_api_routes(container: Any) -> web.RouteTableDef:
    repo = container.repo
    settings = container.settings
    routes = web.RouteTableDef()

    @routes.get("/api/stats")
    async def stats(_req: web.Request) -> web.Response:
        sites = await repo.get_all_sites()
        opps = await repo.get_opportunities()
        forms = await repo.get_forms()

        active_sites = [s for s in sites if s.active]
        by_zone: dict[str, int] = {}
        by_status: dict[str, int] = {}
        scores: list[float] = []
        for o in opps:
            z = o.zone.value
            by_zone[z] = by_zone.get(z, 0) + 1
            st = o.status.value
            by_status[st] = by_status.get(st, 0) + 1
            if o.ai_score is not None:
                scores.append(o.ai_score)

        form_by_status: dict[str, int] = {}
        for f in forms:
            st = f.status.value
            form_by_status[st] = form_by_status.get(st, 0) + 1

        return _json({
            "total_sites": len(sites),
            "active_sites": len(active_sites),
            "total_opportunities": len(opps),
            "total_forms": len(forms),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "top_score": max(scores) if scores else 0,
            "opportunities_by_zone": by_zone,
            "opportunities_by_status": by_status,
            "forms_by_status": form_by_status,
            "running_actions": {k: v for k, v in _running_actions.items() if v},
        })

    @routes.get("/api/opportunities")
    async def opportunities(req: web.Request) -> web.Response:
        opps = await repo.get_opportunities()
        site_map = {s.id: s.name for s in await repo.get_all_sites()}
        data = []
        for o in opps:
            d = _serialize(o)
            d["site_name"] = site_map.get(d.get("site_id"), "")
            data.append(d)

        zone = req.query.get("zone")
        if zone:
            data = [d for d in data if d.get("zone") == zone]
        status = req.query.get("status")
        if status:
            data = [d for d in data if d.get("status") == status]

        return _json(data)

    @routes.get("/api/sites")
    async def sites(_req: web.Request) -> web.Response:
        return _json([_serialize(s) for s in await repo.get_all_sites()])

    @routes.get("/api/forms")
    async def forms(_req: web.Request) -> web.Response:
        site_map = {s.id: s.name for s in await repo.get_all_sites()}
        data = []
        for f in await repo.get_forms():
            d = _serialize(f)
            d["site_name"] = site_map.get(d.get("site_id"), "")
            data.append(d)
        return _json(data)

    @routes.get("/api/config")
    async def config(_req: web.Request) -> web.Response:
        return _json({
            "zones": settings.zone_list,
            "gemini_model": settings.gemini_model,
            "scrape_interval_hours": settings.scrape_interval_hours,
            "discovery_interval_hours": settings.discovery_interval_hours,
            "form_fill_interval_hours": settings.form_fill_interval_hours,
            "playwright_timeout_ms": settings.playwright_timeout_ms,
        })

    # ── Action endpoints (mirror Telegram commands) ────────────────────

    async def _run_action(name: str, coro: Any) -> dict:
        if _running_actions.get(name):
            return {"status": "already_running", "action": name}
        _running_actions[name] = True
        try:
            result = await coro
            return {"status": "ok", "action": name, "result": result}
        except Exception as exc:
            return {"status": "error", "action": name, "error": str(exc)}
        finally:
            _running_actions[name] = False

    @routes.post("/api/actions/discover")
    async def action_discover(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            await container.discovery.load_seeds()
            new = await container.discovery.discover()
            return {"new_sites": len(new)}
        r = await _run_action("discover", _do())
        return _json(r)

    @routes.post("/api/actions/scrape")
    async def action_scrape(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            s = await container.scraper.analyze_all()
            await container.notifier.send_new_alerts()
            return {
                "sites_analyzed": s.sites_analyzed,
                "opportunities": s.opportunities_found,
                "forms": s.forms_found,
                "errors": s.errors,
            }
        r = await _run_action("scrape", _do())
        return _json(r)

    @routes.post("/api/actions/fill-forms")
    async def action_fill(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            r = await container.forms.fill_pending()
            return {"filled": r.filled, "errors": r.errors, "skipped": r.skipped}
        r = await _run_action("fill-forms", _do())
        return _json(r)

    @routes.post("/api/actions/full-search")
    async def action_full(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            await container.discovery.load_seeds()
            new = await container.discovery.discover()
            s = await container.scraper.analyze_all()
            await container.notifier.send_new_alerts()
            return {
                "new_sites": len(new),
                "sites_analyzed": s.sites_analyzed,
                "opportunities": s.opportunities_found,
            }
        r = await _run_action("full-search", _do())
        return _json(r)

    return routes
