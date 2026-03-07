"""REST API endpoints for the dashboard."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from typing import TYPE_CHECKING, Any

from aiohttp import web

from ai.providers import (
    PROVIDERS, available_providers, build_analyzer, get_api_key, get_provider,
)
from web.event_bus import emit, subscribe, unsubscribe, format_sse

logger = logging.getLogger(__name__)


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

    # ── Config & AI providers ──────────────────────────────────────────

    @routes.get("/api/config")
    async def config(_req: web.Request) -> web.Response:
        provider = settings.ai_provider.lower()
        profile = get_provider(provider)
        model = getattr(container.ai, "_model", profile["default_model"])
        scrape_h = settings.scrape_interval_hours or profile["auto_interval_hours"]
        return _json({
            "zones": settings.zone_list,
            "ai_provider": provider,
            "ai_provider_name": profile["name"],
            "ai_model": model,
            "rpd": profile["rpd"],
            "scrape_interval_hours": scrape_h,
            "discovery_interval_hours": settings.discovery_interval_hours,
            "form_fill_interval_hours": settings.form_fill_interval_hours,
            "playwright_timeout_ms": settings.playwright_timeout_ms,
            "max_sites_per_cycle": container.scraper.max_sites_per_cycle,
            "delay_between_sites": container.scraper.delay_between_sites,
        })

    @routes.get("/api/providers")
    async def providers(_req: web.Request) -> web.Response:
        current_provider = settings.ai_provider.lower()
        current_model = getattr(container.ai, "_model", "")
        all_providers = available_providers(settings)
        return _json({
            "current_provider": current_provider,
            "current_model": current_model,
            "providers": all_providers,
        })

    @routes.put("/api/ai-config")
    async def change_ai_config(req: web.Request) -> web.Response:
        body = await req.json()
        new_provider = body.get("provider", "").strip().lower()
        new_model = body.get("model", "").strip()

        if new_provider and new_provider not in PROVIDERS:
            return _json({"error": f"Unknown provider: {new_provider}"}, 400)

        provider = new_provider or settings.ai_provider.lower()
        profile = get_provider(provider)
        api_key = get_api_key(provider, settings)

        if not api_key:
            return _json({"error": f"No API key configured for {profile['name']}"}, 400)

        model = new_model or profile["default_model"]

        try:
            new_ai = build_analyzer(provider, model, settings)
        except Exception as exc:
            return _json({"error": f"Failed to create analyzer: {exc}"}, 500)

        container.ai = new_ai
        settings.ai_provider = provider

        container.scraper.reconfigure(
            new_ai,
            max_sites_per_cycle=settings.max_sites_per_cycle or profile["auto_sites_per_cycle"],
            delay_between_sites=profile["delay_between_sites"],
            skip_visited_hours=profile["auto_skip_hours"],
        )
        container.forms._ai = new_ai

        prefs = await repo.get_preferences()
        prefs["ai_provider"] = provider
        prefs["ai_model"] = model
        await repo.save_preferences(prefs)

        logger.info("AI switched to %s / %s", profile["name"], model)
        return _json({
            "status": "ok",
            "provider": provider,
            "model": model,
            "max_sites_per_cycle": container.scraper.max_sites_per_cycle,
        })

    # Keep legacy endpoint for backward compat
    @routes.get("/api/ai-models")
    async def ai_models(_req: web.Request) -> web.Response:
        provider = settings.ai_provider.lower()
        current = getattr(container.ai, "_model", "")
        profile = get_provider(provider)
        return _json({
            "provider": provider,
            "current": current,
            "models": profile["models"],
        })

    @routes.put("/api/ai-model")
    async def change_model(req: web.Request) -> web.Response:
        body = await req.json()
        return await change_ai_config(req)

    # ── Preferences ────────────────────────────────────────────────────

    @routes.get("/api/preferences")
    async def get_prefs(_req: web.Request) -> web.Response:
        return _json(await repo.get_preferences())

    @routes.put("/api/preferences")
    async def save_prefs(req: web.Request) -> web.Response:
        body = await req.json()
        existing = await repo.get_preferences()
        existing.update(body)
        await repo.save_preferences(existing)
        return _json({"status": "ok"})

    # ── SSE (Server-Sent Events) ─────────────────────────────────────

    @routes.get("/api/events")
    async def sse_events(req: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        resp.enable_chunked_encoding()
        await resp.prepare(req)

        padding = b": " + b" " * 2048 + b"\n\n"
        connected = format_sse({
            "type": "connected",
            "running": {k: v for k, v in _running_actions.items() if v},
        }).encode()
        await resp.write(padding + connected)
        logger.info("SSE client connected")

        q = subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    await resp.write(format_sse(event).encode())
                except asyncio.TimeoutError:
                    try:
                        await resp.write(b": ping\n\n")
                    except (ConnectionResetError, ConnectionError):
                        break
                except (ConnectionResetError, ConnectionError,
                        asyncio.CancelledError):
                    break
                except Exception:
                    logger.exception("SSE write error")
                    break
        finally:
            unsubscribe(q)
            logger.info("SSE client disconnected")
        return resp

    # ── Actions (background with SSE events) ──────────────────────────

    async def _run_bg(name: str, coro_fn: Any) -> dict:
        if _running_actions.get(name):
            return {"status": "already_running", "action": name}
        _running_actions[name] = True
        emit({"type": "action_start", "action": name})

        async def _wrapper() -> None:
            try:
                result = await coro_fn()
                emit({"type": "action_complete", "action": name, "result": result})
            except Exception as exc:
                logger.exception("Action %s failed", name)
                emit({"type": "action_error", "action": name, "error": str(exc)[:300]})
            finally:
                _running_actions[name] = False

        asyncio.create_task(_wrapper())
        return {"status": "started", "action": name}

    @routes.post("/api/actions/discover")
    async def action_discover(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            await container.discovery.load_seeds()
            new = await container.discovery.discover()
            return {"new_sites": len(new)}
        return _json(await _run_bg("discover", _do))

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
        return _json(await _run_bg("scrape", _do))

    @routes.post("/api/actions/fill-forms")
    async def action_fill(_req: web.Request) -> web.Response:
        async def _do() -> dict:
            r = await container.forms.fill_pending()
            return {"filled": r.filled, "errors": r.errors, "skipped": r.skipped}
        return _json(await _run_bg("fill-forms", _do))

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
        return _json(await _run_bg("full-search", _do))

    @routes.post("/api/actions/reset-db")
    async def action_reset(_req: web.Request) -> web.Response:
        await repo.reset_all()
        emit({"type": "action_complete", "action": "reset-db", "result": {}})
        return _json({"status": "ok", "message": "All data deleted"})

    return routes
