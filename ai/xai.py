"""xAI (Grok) implementation of :class:`AIAnalyzer`."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openai import AsyncOpenAI, RateLimitError

from ai._json_parser import parse_json_array, parse_json_object
from exceptions import AIAnalysisError

logger = logging.getLogger(__name__)

_MAX_PAGE_CHARS = 12_000
_MAX_HTML_CHARS = 8_000
_MAX_CONTEXT_CHARS = 2_000

_MAX_RETRIES = 4
_BASE_BACKOFF_SECS = 5.0


class XAIAnalyzer:
    """Concrete :class:`AIAnalyzer` backed by xAI Grok models."""

    _BASE_URL = "https://api.x.ai/v1"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=self._BASE_URL)
        self._model = model

    async def _generate(self, prompt: str) -> str:
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                )
                return response.choices[0].message.content or ""
            except RateLimitError as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    wait = _BASE_BACKOFF_SECS * (2 ** attempt)
                    logger.warning(
                        "Rate-limited (attempt %d/%d), waiting %.0fs",
                        attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                break
            except Exception as exc:
                last_exc = exc
                err = str(exc)
                if "429" in err and attempt < _MAX_RETRIES:
                    wait = _BASE_BACKOFF_SECS * (2 ** attempt)
                    logger.warning(
                        "Rate-limited (attempt %d/%d), waiting %.0fs",
                        attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                break

        raise AIAnalysisError(f"xAI generation failed: {last_exc}") from last_exc

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

    async def analyze_page_and_forms(
        self, text: str, html: str, url: str, zone: str,
        preference_hint: str = "",
    ) -> dict[str, Any]:
        """Single API call that extracts both opportunities and forms."""
        pref_block = f"\n\n{preference_hint}\n" if preference_hint else ""
        prompt = (
            "Eres un experto en mercado inmobiliario de Madrid.\n"
            "Analiza el contenido de esta pagina web y haz DOS cosas:\n\n"
            "1) Extrae TODAS las oportunidades de vivienda "
            "(cooperativas, obra nueva, promociones)\n"
            "2) Detecta formularios de contacto, inscripcion o "
            "solicitud de informacion\n\n"
            f"URL: {url}\nZona objetivo: {zone}\n"
            f"{pref_block}\n"
            "Responde con UN SOLO JSON objeto con dos claves:\n\n"
            '"opportunities": array donde cada elemento tiene:\n'
            '  - "title": nombre del proyecto\n'
            '  - "description": descripcion breve (max 300 chars)\n'
            '  - "estimated_price": precio o rango (string o null)\n'
            '  - "status": "nueva"|"en_curso"|"proxima"|"cerrada"\n'
            '  - "ai_score": interes 1-10 (si hay preferencias, puntua mas alto las que encajen)\n'
            '  - "url": URL directa\n'
            '  - "house_type": "piso"|"chalet"|"adosado"|"duplex"|"atico"|"estudio"|"otro" o null\n'
            '  - "bedrooms": numero de habitaciones (int o null)\n'
            '  - "sqm": metros cuadrados (float o null)\n'
            '  - "amenities": extras separados por coma (garaje,piscina,trastero,zonas_verdes,gimnasio,portero) o null\n'
            '  - "protection_type": "vpo"|"vpp"|"vppl"|"libre"|"otro" o null\n'
            '  - "availability": "disponible"|"reservado"|"vendido"|"lista_espera" o null\n'
            '  - "project_date": fecha estimada de entrega (string o null)\n\n'
            '"forms": array donde cada elemento tiene:\n'
            '  - "form_type": "contacto"|"inscripcion"|"informacion"\n'
            '  - "description": que pide el formulario\n'
            '  - "fields": lista de campos\n\n'
            "Sin oportunidades o formularios -> arrays vacios.\n"
            "Responde SOLO con el JSON objeto.\n\n"
            f"Contenido texto:\n{text[:_MAX_PAGE_CHARS]}\n\n"
            f"HTML (extracto):\n{html[:_MAX_HTML_CHARS]}"
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
