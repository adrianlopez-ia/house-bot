# Bot de Vivienda Madrid

Bot que busca automaticamente cooperativas y constructoras de vivienda en Madrid (norte, este, oeste), analiza oportunidades con IA (Gemini), rellena formularios de contacto y envia reportes por Telegram.

## Que hace

- **Descubre** webs de cooperativas y constructoras buscando en DuckDuckGo + lista semilla de sitios conocidos
- **Analiza** cada web con Gemini AI para extraer oportunidades (proyectos, precios, plazos, puntuacion de interes)
- **Rellena formularios** de contacto/inscripcion automaticamente con tus datos
- **Notifica por Telegram** con alertas de nuevas oportunidades y reportes semanales
- **Lleva un registro** de todos los formularios enviados/pendientes

## Requisitos

- Python 3.9+
- API key de Gemini (gratis): https://aistudio.google.com
- Bot de Telegram (gratis): habla con [@BotFather](https://t.me/BotFather) en Telegram

## Instalacion

```bash
git clone <repo-url>
cd house-bot

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Editar .env con tus datos (ver seccion siguiente)
```

## Configuracion (.env)

```
GEMINI_API_KEY=tu_api_key
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=tu_chat_id

USER_FULL_NAME=Tu Nombre
USER_EMAIL=tu@email.com
USER_PHONE=+34600000000
```

### Como obtener el TELEGRAM_CHAT_ID

1. Crea un bot con [@BotFather](https://t.me/BotFather) (`/newbot`)
2. Copia el token que te da
3. Envia cualquier mensaje a tu nuevo bot en Telegram
4. Abre en el navegador: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
5. Busca el campo `"chat":{"id": XXXXXXX}` -- ese numero es tu `TELEGRAM_CHAT_ID`

## Uso

```bash
source .venv/bin/activate
python main.py
```

## Comandos de Telegram

| Comando | Descripcion |
|---------|-------------|
| `/start` | Mensaje de bienvenida |
| `/oportunidades` | Lista de oportunidades activas |
| `/futuras` | Proximos lanzamientos detectados |
| `/formularios` | Estado de formularios (enviados/pendientes) |
| `/buscar` | Forzar busqueda inmediata |
| `/reporte` | Resumen completo con estadisticas |
| `/sites` | Webs que se estan monitorizando |
| `/help` | Ayuda |

## Frecuencia de ejecucion

| Tarea | Frecuencia |
|-------|------------|
| Scraping de sitios conocidos | Cada 6 horas |
| Descubrimiento de nuevos sitios | Cada 24 horas |
| Rellenado de formularios | Cada 12 horas |
| Reporte semanal | Lunes a las 9:00 |

Configurable en `.env` con `SCRAPE_INTERVAL_HOURS`, `DISCOVERY_INTERVAL_HOURS`, `FORM_FILL_INTERVAL_HOURS`.

## Arquitectura

```
house-bot/
├── main.py              # Composition root + scheduler
├── config.py            # Pydantic Settings (validated .env)
├── exceptions.py        # Custom exception hierarchy
├── db/
│   ├── models.py        # Enums + frozen dataclasses
│   └── repository.py    # Repository pattern (async context manager)
├── ai/
│   ├── protocols.py     # AIAnalyzer Protocol (provider-agnostic)
│   ├── gemini.py        # Gemini implementation
│   └── _json_parser.py  # Robust LLM JSON extraction
├── scraper/
│   ├── browser.py       # BrowserManager (Playwright lifecycle)
│   └── service.py       # ScraperService (DI)
├── discovery/
│   ├── seed_sites.py    # Pure data: known sites + queries
│   └── service.py       # DiscoveryService (DI)
├── forms/
│   ├── detector.py      # Pure functions: form field detection
│   └── service.py       # FormService (fill + registry, DI)
├── notifier/
│   └── service.py       # NotifierService (Telegram, DI)
└── screenshots/         # Form submission evidence
```

### Principios de diseno

- **Dependency Injection**: todas las dependencias se inyectan via constructor, sin estado global
- **Protocol-based abstractions**: el proveedor de IA se puede cambiar sin tocar el resto del codigo
- **Repository pattern**: acceso a datos centralizado con async context manager
- **Frozen dataclasses + Enums**: modelos inmutables, sin magic strings
- **Composition root**: `main.py` es el unico lugar donde se cablea todo
- **Custom exceptions**: jerarquia de errores especifica del dominio
- **Validated config**: Pydantic Settings con validacion al arrancar

## Coste

Todo gratuito:
- **Gemini AI**: capa gratuita (1,000 peticiones/dia con Flash-Lite)
- **Telegram Bot**: completamente gratis
- **DuckDuckGo Search**: sin API key, gratis
- **SQLite**: base de datos local, sin servidor
