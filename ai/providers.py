"""Provider registry: metadata, capacity profiles, and analyzer factory.

All OpenAI-compatible providers (Cerebras, Groq, DeepSeek, Mistral, xAI)
share the same analyzer implementation via ``openai_compat``.  Gemini uses
its own SDK and is handled separately.
"""
from __future__ import annotations

from typing import Any

PROVIDERS: dict[str, dict[str, Any]] = {
    "cerebras": {
        "name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "default_model": "gpt-oss-120b",
        "rpd": 14_400,
        "rpm": 30,
        "auto_sites_per_cycle": 100,
        "auto_interval_hours": 2,
        "auto_skip_hours": 2,
        "delay_between_sites": 3,
        "key_field": "cerebras_api_key",
        "models": [
            {"id": "gpt-oss-120b", "name": "GPT OSS 120B", "cost": "Gratis", "capacity": "14,400 RPD · 30 RPM · ~3000 tok/s", "description": "120B params, el mas rapido. Ideal para analisis profundo."},
            {"id": "llama3.1-8b", "name": "Llama 3.1 8B", "cost": "Gratis", "capacity": "14,400 RPD · 30 RPM · ~2200 tok/s", "description": "Ultrarapido y ligero. Maximo volumen."},
            {"id": "qwen-3-235b-a22b-instruct-2507", "name": "Qwen 3 235B", "cost": "Gratis (limites reducidos)", "capacity": "RPD reducido temporalmente · ~1400 tok/s", "description": "235B params. Maxima calidad, limites temporales por demanda."},
            {"id": "zai-glm-4.7", "name": "Z.ai GLM 4.7", "cost": "Gratis (limites reducidos)", "capacity": "RPD reducido temporalmente · ~1000 tok/s", "description": "355B params. Modelo mas grande disponible."},
        ],
    },
    "groq": {
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "rpd": 1_000,
        "rpm": 30,
        "auto_sites_per_cycle": 40,
        "auto_interval_hours": 4,
        "auto_skip_hours": 4,
        "delay_between_sites": 3,
        "key_field": "groq_api_key",
        "models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "cost": "Gratis", "capacity": "1,000 RPD · 30 RPM", "description": "El mas capaz en Groq gratis."},
            {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant", "cost": "Gratis", "capacity": "14,400 RPD · 30 RPM", "description": "Ultrarapido. Maximo volumen."},
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "rpd": 5_000,
        "rpm": 60,
        "auto_sites_per_cycle": 60,
        "auto_interval_hours": 3,
        "auto_skip_hours": 3,
        "delay_between_sites": 2,
        "key_field": "deepseek_api_key",
        "models": [
            {"id": "deepseek-chat", "name": "DeepSeek V3.2 Chat", "cost": "5M tokens gratis + $0.28/M", "capacity": "Alta (tokens) · 60 RPM", "description": "Muy capaz y barato. Cache automatico reduce costes 90%."},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner", "cost": "5M tokens gratis + $0.55/M", "capacity": "Alta (tokens) · 60 RPM", "description": "Razonamiento profundo. Para analisis complejos."},
        ],
    },
    "mistral": {
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "rpd": 10_000,
        "rpm": 2,
        "auto_sites_per_cycle": 20,
        "auto_interval_hours": 4,
        "auto_skip_hours": 4,
        "delay_between_sites": 35,
        "key_field": "mistral_api_key",
        "models": [
            {"id": "mistral-small-latest", "name": "Mistral Small", "cost": "Gratis (1B tokens/mes)", "capacity": "Alta (tokens) · 2 RPM", "description": "Ligero y eficiente. Limite 2 req/min."},
            {"id": "mistral-large-latest", "name": "Mistral Large", "cost": "Gratis (1B tokens/mes)", "capacity": "Alta (tokens) · 2 RPM", "description": "Maximo rendimiento Mistral."},
        ],
    },
    "xai": {
        "name": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-mini-fast",
        "rpd": 5_000,
        "rpm": 60,
        "auto_sites_per_cycle": 50,
        "auto_interval_hours": 3,
        "auto_skip_hours": 3,
        "delay_between_sites": 3,
        "key_field": "xai_api_key",
        "models": [
            {"id": "grok-3-mini-fast", "name": "Grok 3 Mini Fast", "cost": "$0.10/M in · $0.30/M out", "capacity": "Alta ($25 creditos)", "description": "Rapido y barato. Los $25 dan para miles de calls."},
            {"id": "grok-3-mini", "name": "Grok 3 Mini", "cost": "$0.30/M in · $0.50/M out", "capacity": "Alta ($25 creditos)", "description": "Mejor razonamiento que Fast."},
            {"id": "grok-4.1-fast", "name": "Grok 4.1 Fast", "cost": "$0.20/M in · $0.50/M out", "capacity": "Alta ($25 creditos)", "description": "Modelo reciente de alta calidad."},
        ],
    },
    "gemini": {
        "name": "Google Gemini",
        "base_url": "",
        "default_model": "gemini-2.5-flash-lite",
        "rpd": 20,
        "rpm": 5,
        "auto_sites_per_cycle": 5,
        "auto_interval_hours": 8,
        "auto_skip_hours": 8,
        "delay_between_sites": 10,
        "key_field": "gemini_api_key",
        "models": [
            {"id": "gemini-2.5-flash-lite", "name": "Gemini 2.5 Flash Lite", "cost": "Gratis (20 RPD real)", "capacity": "Muy limitada · 5 RPM", "description": "Cuota gratuita muy baja."},
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "cost": "Gratis (250 RPD oficial)", "capacity": "Limitada · 15 RPM", "description": "Mejor equilibrio."},
            {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "cost": "Gratis (100 RPD oficial)", "capacity": "Limitada · 2 RPM", "description": "Mejor razonamiento."},
        ],
    },
}


def get_provider(name: str) -> dict[str, Any]:
    return PROVIDERS.get(name.lower(), PROVIDERS["cerebras"])


def get_api_key(provider: str, settings: Any) -> str:
    profile = get_provider(provider)
    return getattr(settings, profile["key_field"], "")


def build_analyzer(provider: str, model: str, settings: Any) -> Any:
    """Factory: create the right AI analyzer for *provider* + *model*."""
    profile = get_provider(provider)
    resolved_model = model or profile["default_model"]
    api_key = get_api_key(provider, settings)

    if provider.lower() == "gemini":
        from ai.gemini import GeminiAnalyzer
        return GeminiAnalyzer(api_key, resolved_model)

    from ai.openai_compat import OpenAICompatAnalyzer
    return OpenAICompatAnalyzer(api_key, resolved_model, profile["base_url"])


def available_providers(settings: Any) -> list[dict[str, Any]]:
    """Return providers that have an API key configured."""
    result = []
    for pid, profile in PROVIDERS.items():
        key = get_api_key(pid, settings)
        result.append({
            "id": pid,
            "name": profile["name"],
            "configured": bool(key),
            "rpd": profile["rpd"],
            "models": profile["models"],
            "auto_sites_per_cycle": profile["auto_sites_per_cycle"],
            "auto_interval_hours": profile["auto_interval_hours"],
        })
    return result
