"""Gemini implementation of :class:`AIAnalyzer`."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from google import genai

from ai._json_parser import parse_json_array, parse_json_object
from exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

_MAX_PAGE_CHARS = 20_000
_MAX_HTML_CHARS = 10_000
_MAX_CONTEXT_CHARS = 3_000

_MAX_RETRIES = 4
_BASE_BACKOFF_SECS = 15.0
_RETRY_DELAY_RE = re.compile(r"retryDelay.*?(\d+)")


def _parse_retry_delay(error_text: str) -> float:
    """Extract the retry delay from a Gemini 429 error, or use a default."""
    match = _RETRY_DELAY_RE.search(error_text)
    if match:
        return max(float(match.group(1)), _BASE_BACKOFF_SECS)
    return _BASE_BACKOFF_SECS


class GeminiAnalyzer:
    """Concrete :class:`AIAnalyzer` backed by Google Gemini."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def _generate(self, prompt: str) -> str:
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            def _call() -> str:
                response = self._client.models.generate_content(
                    model=self._model, contents=prompt,
                )
                return response.text

            try:
                return await asyncio.to_thread(_call)
            except Exception as exc:
                last_exc = exc
                err = str(exc)
                if "429" in err and attempt < _MAX_RETRIES:
                    wait = _parse_retry_delay(err) + attempt * 10
                    logger.warning(
                        "Rate-limited (attempt %d/%d), waiting %.0fs",
                        attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

        raise AIAnalysisError(f"Gemini generation failed: {last_exc}") from last_exc

    # ── protocol methods ───────────────────────────────────────────────

    async def analyze_page(
        self, text: str, url: str, zone: str,
    ) -> list[dict[str, Any]]:
        prompt = (
            "Eres un analista experto del mercado inmobiliario de Madrid.\n"
            "Extrae TODAS las oportunidades de vivienda del siguiente contenido.\n"
            "Busca pisos, viviendas, promociones, cooperativas, obra nueva, residenciales.\n"
            "Extrae CADA proyecto como oportunidad separada, incluso con info parcial.\n\n"
            f"URL: {url}\nZona: {zone or 'todas'}\n\n"
            "Para CADA oportunidad devuelve JSON con:\n"
            '- "title", "description" (max 300 chars), "estimated_price" (string o null),\n'
            '  "status" ("nueva"|"en_curso"|"proxima"|"cerrada"), "ai_score" (1-10),\n'
            '  "url", "house_type", "bedrooms", "sqm", "amenities", "protection_type",\n'
            '  "availability", "project_date"\n\n'
            "Responde SOLO con un array JSON.\n\n"
            f"=== CONTENIDO ===\n{text[:_MAX_PAGE_CHARS]}"
        )
        try:
            raw = await self._generate(prompt)
            return parse_json_array(raw)
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.error("analyze_page failed for %s: %s", url, exc)
            return []

    async def detect_forms(self, html: str, url: str) -> list[dict[str, str]]:
        prompt = (
            "Analiza el HTML y detecta formularios de contacto, inscripcion o "
            "solicitud de informacion sobre vivienda.\n\n"
            f"URL: {url}\n\n"
            "Para cada formulario devuelve JSON con:\n"
            '- "form_type": "contacto"|"inscripcion"|"informacion"\n'
            '- "description": que pide el formulario\n'
            '- "fields": lista de campos detectados\n\n'
            "Responde SOLO con un array JSON. Sin formularios -> [].\n\n"
            f"HTML:\n{html[:_MAX_HTML_CHARS]}"
        )
        try:
            raw = await self._generate(prompt)
            return parse_json_array(raw)
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.error("detect_forms failed for %s: %s", url, exc)
            return []

    async def analyze_page_and_forms(
        self, text: str, html: str, url: str, zone: str,
        preference_hint: str = "",
    ) -> dict[str, Any]:
        """Single API call that extracts both opportunities and forms."""
        pref_block = f"\n\nPREFERENCIAS DEL USUARIO (puntua mas alto lo que encaje):\n{preference_hint}\n" if preference_hint else ""
        prompt = (
            "Eres un analista experto del mercado inmobiliario de Madrid.\n"
            "Tu trabajo es extraer TODAS las oportunidades de vivienda de esta pagina web.\n\n"
            "IMPORTANTE:\n"
            "- Busca CUALQUIER mencion a pisos, viviendas, promociones, proyectos residenciales, cooperativas, obra nueva\n"
            "- Si la pagina lista varias promociones o proyectos, extrae CADA UNO como oportunidad separada\n"
            "- Si solo hay informacion general de UNA promocion, extrae esa como oportunidad\n"
            "- Incluso si la informacion es parcial (sin precio, sin m2), extraela igual\n"
            "- Busca tambien formularios de contacto, inscripcion o solicitud de informacion\n"
            "- NO devuelvas arrays vacios si hay CUALQUIER mencion a vivienda en el contenido\n\n"
            f"URL: {url}\n"
            f"Zona objetivo: {zone or 'todas'}\n"
            f"{pref_block}\n"
            "Responde con UN SOLO JSON objeto con estas dos claves:\n\n"
            '{\n'
            '  "opportunities": [\n'
            '    {\n'
            '      "title": "Nombre del proyecto/promocion",\n'
            '      "description": "Descripcion breve, max 300 chars",\n'
            '      "estimated_price": "Desde 185.000 EUR" o null,\n'
            '      "status": "nueva"|"en_curso"|"proxima"|"cerrada",\n'
            '      "ai_score": 7,\n'
            '      "url": "URL directa al proyecto o la de la pagina",\n'
            '      "house_type": "piso"|"chalet"|"adosado"|"duplex"|"atico"|"estudio"|"otro" o null,\n'
            '      "bedrooms": 2,\n'
            '      "sqm": 75.0,\n'
            '      "amenities": "garaje,trastero,piscina" o null,\n'
            '      "protection_type": "vpo"|"vpp"|"vppl"|"libre"|"otro" o null,\n'
            '      "availability": "disponible"|"reservado"|"vendido"|"lista_espera" o null,\n'
            '      "project_date": "2026-Q3" o null\n'
            '    }\n'
            '  ],\n'
            '  "forms": [\n'
            '    {"form_type": "contacto"|"inscripcion"|"informacion", "description": "...", "fields": ["nombre","email","telefono"]}\n'
            '  ]\n'
            '}\n\n'
            "ai_score: 1-10 donde 10 es muy interesante (cooperativa nueva, buen precio, buena zona).\n"
            "status: nueva = recien anunciada, en_curso = ya en venta, proxima = futura, cerrada = agotada.\n\n"
            "Responde SOLO con el JSON.\n\n"
            f"=== CONTENIDO DE LA PAGINA ===\n{text[:_MAX_PAGE_CHARS]}\n\n"
            f"=== HTML ===\n{html[:_MAX_HTML_CHARS]}"
        )
        try:
            raw = await self._generate(prompt)
            result = parse_json_object(raw)
            if "opportunities" not in result:
                result["opportunities"] = []
            if "forms" not in result:
                result["forms"] = []
            return result
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.error("analyze_page_and_forms failed for %s: %s", url, exc)
            return {"opportunities": [], "forms": []}

    async def generate_search_queries(
        self, known_sites: list[str], prefs: dict | None = None,
    ) -> list[dict[str, str]]:
        sites_summary = "\n".join(known_sites[:40])
        pref_block = ""
        if prefs:
            from scraper.service import build_preference_hint
            hint = build_preference_hint(prefs)
            if hint:
                pref_block = (
                    f"\n\nEl usuario busca especificamente:\n{hint}\n"
                    "Genera queries que encajen con estas preferencias.\n"
                )
        prompt = (
            "Eres un experto en buscar cooperativas de vivienda, constructoras, "
            "promotoras y oportunidades de obra nueva en Madrid.\n\n"
            "Ya conozco estos sitios:\n"
            f"{sites_summary}\n\n"
            f"{pref_block}"
            "Genera 10 queries NUEVAS y DIVERSAS para DuckDuckGo (en espanol) "
            "para encontrar MAS cooperativas, constructoras, promotoras, "
            "viviendas VPO, obra nueva y promociones residenciales en "
            "Madrid norte, este y oeste.\n\n"
            'Array JSON con: "query" y "zone" ("norte"|"este"|"oeste"|"todas").\n'
            "Responde SOLO con el array JSON."
        )
        try:
            raw = await self._generate(prompt)
            return parse_json_array(raw)
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.error("generate_search_queries failed: %s", exc)
            return []

    async def generate_form_fill_strategy(
        self,
        form_fields: list[str],
        user_data: dict[str, str],
        page_context: str,
    ) -> dict[str, str]:
        prompt = (
            f"Campos del formulario: {json.dumps(form_fields)}\n\n"
            f"Datos del usuario:\n{json.dumps(user_data, ensure_ascii=False)}\n\n"
            f"Contexto: {page_context[:_MAX_CONTEXT_CHARS]}\n\n"
            "Decide que valor rellenar en cada campo. Si hay campo de 'mensaje', "
            "escribe un texto breve y profesional mostrando interes.\n\n"
            "Responde SOLO con un JSON objeto campo->valor."
        )
        try:
            raw = await self._generate(prompt)
            return parse_json_object(raw)
        except AIAnalysisError:
            raise
        except Exception as exc:
            logger.error("generate_form_fill_strategy failed: %s", exc)
            return {}
