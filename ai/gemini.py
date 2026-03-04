"""Gemini implementation of :class:`AIAnalyzer`."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from google import genai

from ai._json_parser import parse_json_array, parse_json_object
from exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

_MAX_PAGE_CHARS = 15_000
_MAX_HTML_CHARS = 12_000
_MAX_CONTEXT_CHARS = 2_000


class GeminiAnalyzer:
    """Concrete :class:`AIAnalyzer` backed by Google Gemini."""

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def _generate(self, prompt: str) -> str:
        def _call() -> str:
            response = self._client.models.generate_content(
                model=self._model, contents=prompt,
            )
            return response.text

        try:
            return await asyncio.to_thread(_call)
        except Exception as exc:
            raise AIAnalysisError(f"Gemini generation failed: {exc}") from exc

    # ── protocol methods ───────────────────────────────────────────────

    async def analyze_page(
        self, text: str, url: str, zone: str,
    ) -> list[dict[str, Any]]:
        prompt = (
            "Eres un experto en mercado inmobiliario de Madrid.\n"
            "Analiza el siguiente contenido de una pagina web y extrae TODAS las "
            "oportunidades de vivienda (cooperativas, obra nueva, promociones).\n\n"
            f"URL: {url}\nZona objetivo: {zone}\n\n"
            "Para CADA oportunidad devuelve un JSON con:\n"
            '- "title": nombre del proyecto\n'
            '- "description": descripcion breve (max 300 chars)\n'
            '- "estimated_price": precio estimado o rango (string o null)\n'
            '- "status": "nueva"|"en_curso"|"proxima"|"cerrada"\n'
            '- "ai_score": interes 1-10 (10 = muy interesante)\n'
            '- "url": URL directa a la oportunidad o la de la pagina\n\n'
            "Responde SOLO con un array JSON. Sin oportunidades -> [].\n\n"
            f"Contenido:\n{text[:_MAX_PAGE_CHARS]}"
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

    async def generate_search_queries(
        self, known_sites: list[str],
    ) -> list[dict[str, str]]:
        sites_summary = "\n".join(known_sites[:30])
        prompt = (
            "Eres un experto en buscar cooperativas y constructoras de vivienda "
            "en Madrid.\n\nYa conozco estos sitios:\n"
            f"{sites_summary}\n\n"
            "Genera 5 queries nuevas para DuckDuckGo (en espanol) para encontrar "
            "MAS cooperativas y constructoras en Madrid norte, este, oeste.\n\n"
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
