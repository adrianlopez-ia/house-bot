"""REST API endpoints for the dashboard."""
from __future__ import annotations

import asyncio
import dataclasses
from typing import TYPE_CHECKING, Any

from aiohttp import web

if TYPE_CHECKING:
    pass

_AI_MODELS = {
    "xai": [
        {
            "id": "grok-3-mini-fast",
            "name": "Grok 3 Mini Fast",
            "cost": "$0.10/M in · $0.30/M out",
            "capacity": "Alta ($25 creditos gratis)",
            "description": "Rapido y barato. Ideal para analisis masivo.",
        },
        {
            "id": "grok-3-mini",
            "name": "Grok 3 Mini",
            "cost": "$0.30/M in · $0.50/M out",
            "capacity": "Alta ($25 creditos)",
            "description": "Mejor razonamiento. Algo mas lento.",
        },
        {
            "id": "grok-4.1-fast",
            "name": "Grok 4.1 Fast",
            "cost": "$0.20/M in · $0.50/M out",
            "capacity": "Alta ($25 creditos)",
            "description": "Modelo reciente de alta calidad.",
        },
    ],
    "gemini": [
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "cost": "Gratis (20 RPD real)",
            "capacity": "Muy limitada",
            "description": "Ligero y rapido. Cuota gratuita muy baja.",
        },
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "cost": "Gratis (250 RPD oficial)",
            "capacity": "Limitada",
            "description": "Equilibrio velocidad/capacidad.",
        },
        {
            "id": "gemini-2.5-pro",
            "name": "Gemini 2.5 Pro",
            "cost": "Gratis (100 RPD oficial)",
            "capacity": "Limitada",
            "description": "Mejor razonamiento, menos cuota.",
        },
    ],
}


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

    # ── Stats ──────────────────────────────────────────────────────────

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

    # ── Data ───────────────────────────────────────────────────────────

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

    # ── Config & models ────────────────────────────────────────────────

    @routes.get("/api/config")
    async def config(_req: web.Request) -> web.Response:
        provider = settings.ai_provider.lower()
        model = getattr(container.ai, "_model", settings.xai_model if provider == "xai" else settings.gemini_model)
        return _json({
            "zones": settings.zone_list,
            "ai_provider": provider,
            "ai_model": model,
            "scrape_interval_hours": settings.scrape_interval_hours,
            "discovery_interval_hours": settings.discovery_interval_hours,
            "form_fill_interval_hours": settings.form_fill_interval_hours,
            "playwright_timeout_ms": settings.playwright_timeout_ms,
        })

    @routes.get("/api/ai-models")
    async def ai_models(_req: web.Request) -> web.Response:
        provider = settings.ai_provider.lower()
        current = getattr(container.ai, "_model", "")
        return _json({
            "provider": provider,
            "current": current,
            "models": _AI_MODELS.get(provider, []),
        })

    @routes.put("/api/ai-model")
    async def change_model(req: web.Request) -> web.Response:
        body = await req.json()
        model = body.get("model", "").strip()
        if not model:
            return _json({"error": "model required"}, 400)
        container.ai._model = model
        prefs = await repo.get_preferences()
        prefs["ai_model"] = model
        await repo.save_preferences(prefs)
        return _json({"status": "ok", "model": model})

    # ── Preferences ────────────────────────────────────────────────────

    @routes.get("/api/preferences")
    async def get_prefs(_req: web.Request) -> web.Response:
        return _json(await repo.get_preferences())

    @routes.put("/api/preferences")
    async def save_prefs(req: web.Request) -> web.Response:
        body = await req.json()
        await repo.save_preferences(body)
        return _json({"status": "ok"})

    # ── Actions ────────────────────────────────────────────────────────

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

    @routes.post("/api/actions/reset-db")
    async def action_reset(_req: web.Request) -> web.Response:
        await repo.reset_all()
        return _json({"status": "ok", "message": "All data deleted"})

    return routes
