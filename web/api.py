"""REST API endpoints for the dashboard."""
from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from aiohttp import web

if TYPE_CHECKING:
    from db.repository import Repository
    from config import Settings


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


def build_api_routes(repo: "Repository", settings: "Settings") -> web.RouteTableDef:
    routes = web.RouteTableDef()

    @routes.get("/api/stats")
    async def stats(_req: web.Request) -> web.Response:
        sites = await repo.get_all_sites()
        opps = await repo.get_opportunities()
        forms = await repo.get_forms()

        active_sites = [s for s in sites if s.active]
        by_zone = {}
        by_status = {}
        scores = []
        for o in opps:
            z = o.zone.value
            by_zone[z] = by_zone.get(z, 0) + 1
            st = o.status.value
            by_status[st] = by_status.get(st, 0) + 1
            if o.ai_score is not None:
                scores.append(o.ai_score)

        form_by_status = {}
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
        })

    @routes.get("/api/opportunities")
    async def opportunities(req: web.Request) -> web.Response:
        opps = await repo.get_opportunities()
        data = []
        for o in opps:
            d = _serialize(o)
            d["site_name"] = ""
            data.append(d)

        sites = {s.id: s.name for s in await repo.get_all_sites()}
        for d in data:
            d["site_name"] = sites.get(d.get("site_id"), "")

        zone = req.query.get("zone")
        if zone:
            data = [d for d in data if d.get("zone") == zone]

        status = req.query.get("status")
        if status:
            data = [d for d in data if d.get("status") == status]

        return _json(data)

    @routes.get("/api/sites")
    async def sites(_req: web.Request) -> web.Response:
        all_sites = await repo.get_all_sites()
        return _json([_serialize(s) for s in all_sites])

    @routes.get("/api/forms")
    async def forms(_req: web.Request) -> web.Response:
        all_forms = await repo.get_forms()
        data = []
        sites = {s.id: s.name for s in await repo.get_all_sites()}
        for f in all_forms:
            d = _serialize(f)
            d["site_name"] = sites.get(d.get("site_id"), "")
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

    return routes
