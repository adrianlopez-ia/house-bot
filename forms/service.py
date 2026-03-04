"""Unified form-filling and registry service.

Merges the former ``filler`` and ``registry`` modules behind a single
injectable service.  All state is in the DB -- no module-level mutables.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.protocols import AIAnalyzer
from db.models import FormFillSummary, FormStatus, FormSubmission, Site
from db.repository import Repository
from exceptions import FormFillingError
from forms.detector import detect_fields, find_submit_button
from scraper.browser import BrowserManager, dismiss_cookies

logger = logging.getLogger(__name__)

_FIELD_ALIASES: dict[str, list[str]] = {
    "name":        ["name", "nombre", "full_name", "fullname", "nombre_completo"],
    "email":       ["email", "correo", "e-mail", "mail", "correo_electronico"],
    "phone":       ["phone", "telefono", "tel", "telephone", "movil", "mobile"],
    "city":        ["city", "ciudad", "localidad", "poblacion"],
    "postal_code": ["postal_code", "cp", "codigo_postal", "zip"],
    "address":     ["address", "direccion", "domicilio"],
    "dni":         ["dni", "nif", "documento"],
}

_DEFAULT_MESSAGE = (
    "Buenos dias, estoy interesado/a en recibir informacion "
    "sobre esta promocion/cooperativa. Gracias."
)


class FormService:
    def __init__(
        self,
        repo: Repository,
        ai: AIAnalyzer,
        browser: BrowserManager,
        user_data: dict[str, str],
        screenshots_dir: Path,
    ) -> None:
        self._repo = repo
        self._ai = ai
        self._browser = browser
        self._user_data = user_data
        self._screenshots = screenshots_dir

    # ── filling ────────────────────────────────────────────────────────

    async def fill_pending(self) -> FormFillSummary:
        pending = await self._repo.get_forms(status=FormStatus.PENDIENTE)
        sites = {s.id: s for s in await self._repo.get_active_sites()}
        filled = errors = skipped = 0

        for form in pending:
            site = sites.get(form.site_id)
            if site is None:
                skipped += 1
                continue
            try:
                ok = await self._fill_one(form, site.name)
                if ok:
                    filled += 1
                else:
                    errors += 1
            except Exception as exc:
                logger.error("Form error %s: %s", form.form_url, exc)
                await self._repo.update_form_status(
                    form.id, FormStatus.ERROR, error_message=str(exc)[:500],
                )
                errors += 1

        logger.info("Forms: %d filled, %d errors, %d skipped", filled, errors, skipped)
        return FormFillSummary(filled=filled, errors=errors, skipped=skipped)

    async def _fill_one(self, form: FormSubmission, site_name: str) -> bool:
        ctx = await self._browser.new_context()
        try:
            page = await ctx.new_page()
            await page.goto(form.form_url, wait_until="domcontentloaded",
                            timeout=self._browser._timeout_ms)
            await page.wait_for_timeout(2000)
            await dismiss_cookies(page)

            fields = await detect_fields(page)
            if not fields:
                await self._repo.update_form_status(
                    form.id, FormStatus.OMITIDO, error_message="No fields found",
                )
                return False

            field_names = [
                f.get("label") or f.get("name") or f.get("placeholder") or f.get("id")
                for f in fields
            ]
            strategy = await self._ai.generate_form_fill_strategy(
                field_names, self._user_data, f"Pagina de {site_name}",
            )
            if not strategy:
                strategy = self._fallback_mapping(fields)

            filled_data = await self._apply_strategy(page, fields, strategy)
            if not filled_data:
                await self._repo.update_form_status(
                    form.id, FormStatus.ERROR, error_message="No fields filled",
                )
                return False

            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            pre_path = str(self._screenshots / f"form_{form.id}_{ts}.png")
            await page.screenshot(path=pre_path, full_page=True)

            submit_sel = await find_submit_button(page)
            if submit_sel:
                try:
                    await page.click(submit_sel, timeout=5000)
                    await page.wait_for_timeout(3000)
                    post_path = str(self._screenshots / f"form_{form.id}_submitted.png")
                    await page.screenshot(path=post_path, full_page=True)
                except Exception as exc:
                    logger.warning("Submit click failed: %s", exc)

            await self._repo.update_form_status(
                form.id, FormStatus.ENVIADO,
                screenshot_path=pre_path,
                data_sent=json.dumps(filled_data, ensure_ascii=False),
            )
            logger.info("Filled form: %s", form.form_url)
            return True
        except Exception as exc:
            await self._repo.update_form_status(
                form.id, FormStatus.ERROR, error_message=str(exc)[:500],
            )
            return False
        finally:
            await ctx.close()

    @staticmethod
    async def _apply_strategy(
        page: Any, fields: list[dict], strategy: dict[str, str],
    ) -> dict[str, str]:
        filled: dict[str, str] = {}
        for info in fields:
            selector = info.get("selector")
            if not selector:
                continue
            value = _match_value(info, strategy)
            if not value:
                continue
            try:
                await page.fill(selector, value, timeout=3000)
                key = info.get("name") or info.get("id") or selector
                filled[key] = value
            except Exception as exc:
                logger.debug("Could not fill %s: %s", selector, exc)
        return filled

    def _fallback_mapping(self, fields: list[dict]) -> dict[str, str]:
        user = self._user_data
        value_map = {
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "phone": user.get("phone", ""),
            "city": user.get("city", ""),
            "postal_code": user.get("postal_code", ""),
            "message": _DEFAULT_MESSAGE,
        }
        result: dict[str, str] = {}
        for field in fields:
            idents = " ".join(
                field.get(k, "") for k in ("label", "name", "placeholder")
            ).lower()
            for user_key, aliases in _FIELD_ALIASES.items():
                if any(a in idents for a in aliases):
                    val = value_map.get(user_key, "")
                    if val:
                        result[field.get("name") or field.get("label", "")] = val
                    break
            else:
                if any(w in idents for w in ("mensaje", "message", "comentario", "comment")):
                    result[field.get("name") or "mensaje"] = _DEFAULT_MESSAGE
        return result

    # ── registry / reporting ───────────────────────────────────────────

    async def get_report(self) -> str:
        forms = await self._repo.get_forms()
        sites = {s.id: s for s in await self._repo.get_all_sites()}
        if not forms:
            return "No hay formularios registrados todavia."

        by_status: dict[FormStatus, list[FormSubmission]] = {}
        for f in forms:
            by_status.setdefault(f.status, []).append(f)

        lines = [
            "*Registro de Formularios*",
            "",
            f"Total: {len(forms)} formularios",
            f"  Enviados: {len(by_status.get(FormStatus.ENVIADO, []))}",
            f"  Pendientes: {len(by_status.get(FormStatus.PENDIENTE, []))}",
            f"  Con error: {len(by_status.get(FormStatus.ERROR, []))}",
            f"  Omitidos: {len(by_status.get(FormStatus.OMITIDO, []))}",
            "",
        ]

        for status, label in (
            (FormStatus.ENVIADO, "Enviados"),
            (FormStatus.PENDIENTE, "Pendientes"),
            (FormStatus.ERROR, "Con errores"),
        ):
            group = by_status.get(status, [])
            if not group:
                continue
            lines.append(f"*{label}:*")
            for f in group:
                name = (sites.get(f.site_id) or Site(url="?")).name or "Desconocido"
                extra = ""
                if status is FormStatus.ENVIADO and f.submitted_at:
                    extra = f" - {f.submitted_at[:10]}"
                elif status is FormStatus.ERROR and f.error_message:
                    extra = f": {f.error_message[:60]}"
                lines.append(f"  {f.status_emoji} {name} ({f.form_type.value}){extra}")
            lines.append("")

        return "\n".join(lines)

    async def get_stats(self) -> dict[str, int]:
        forms = await self._repo.get_forms()
        counts: dict[str, int] = {"total": len(forms)}
        for status in FormStatus:
            counts[status.value] = sum(1 for f in forms if f.status is status)
        return counts


def _match_value(info: dict, strategy: dict[str, str]) -> str | None:
    identifiers = [
        info.get(k, "").lower() for k in ("label", "name", "placeholder", "id")
    ]
    for key, value in strategy.items():
        kl = key.lower()
        for ident in identifiers:
            if ident and (kl in ident or ident in kl):
                return value
    return None
