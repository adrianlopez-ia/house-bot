"""Telegram bot service -- commands, alerts, and reporting.

All domain logic lives in the injected collaborators; this module only
formats messages and wires Telegram handlers.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from telegram import BotCommand, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from db.models import FormStatus, Opportunity, OpportunityStatus
from db.repository import Repository
from exceptions import NotifierError

if TYPE_CHECKING:
    from discovery.service import DiscoveryService
    from forms.service import FormService
    from scraper.service import ScraperService

logger = logging.getLogger(__name__)

_MAX_MSG = 4000

_COMMANDS = (
    BotCommand("start", "Bienvenida"),
    BotCommand("oportunidades", "Ver oportunidades activas"),
    BotCommand("futuras", "Ver proximos lanzamientos"),
    BotCommand("formularios", "Estado de formularios"),
    BotCommand("buscar", "Forzar busqueda ahora"),
    BotCommand("reporte", "Resumen completo"),
    BotCommand("sites", "Webs monitorizadas"),
    BotCommand("chatid", "Mostrar tu chat ID"),
    BotCommand("help", "Ayuda"),
)

_HELP_TEXT = (
    "*Comandos:*\n\n"
    "/oportunidades - Oportunidades activas de vivienda\n"
    "/futuras - Proximos lanzamientos detectados\n"
    "/formularios - Estado de formularios (rellenados y pendientes)\n"
    "/buscar - Busqueda inmediata de nuevos sitios\n"
    "/reporte - Resumen completo con estadisticas\n"
    "/sites - Webs monitorizadas\n"
    "/chatid - Mostrar tu chat ID (para configurar)\n"
    "/help - Esta ayuda"
)


class NotifierService:
    """Owns the Telegram ``Application`` and registers all command handlers."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        repo: Repository,
    ) -> None:
        self._chat_id = chat_id
        self._repo = repo
        self._app: Application = Application.builder().token(token).build()

        self._discovery: DiscoveryService | None = None
        self._scraper: ScraperService | None = None
        self._forms: FormService | None = None

        self._register_handlers()

    def set_services(
        self,
        discovery: DiscoveryService,
        scraper: ScraperService,
        forms: FormService,
    ) -> None:
        """Late-bind domain services to avoid circular init order."""
        self._discovery = discovery
        self._scraper = scraper
        self._forms = forms

    @property
    def app(self) -> Application:
        return self._app

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.bot.set_my_commands(_COMMANDS)
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot polling started")

    async def stop(self) -> None:
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        logger.info("Telegram bot stopped")

    # ── public send helpers ────────────────────────────────────────────

    async def send(self, text: str) -> None:
        for chunk in _split(text):
            try:
                await self._app.bot.send_message(
                    chat_id=self._chat_id, text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                )
            except Exception as exc:
                logger.error(
                    "Failed to send message to chat %s: %s. "
                    "Use /chatid to get your correct ID.",
                    self._chat_id, exc,
                )

    async def send_new_alerts(self) -> int:
        opps = await self._repo.get_opportunities(notified=False)
        if not opps:
            return 0
        for chunk in _opportunity_chunks(opps, "Nuevas Oportunidades Detectadas"):
            await self.send(chunk)
        for opp in opps:
            await self._repo.mark_opportunity_notified(opp.id)
        return len(opps)

    async def send_weekly_report(self) -> None:
        opps = await self._repo.get_opportunities()
        sites = await self._repo.get_active_sites()
        form_stats = await self._forms.get_stats() if self._forms else {}

        active = [o for o in opps if o.status in (OpportunityStatus.NUEVA, OpportunityStatus.EN_CURSO)]
        future = [o for o in opps if o.status is OpportunityStatus.PROXIMA]

        header = (
            "*Reporte Semanal - Bot Vivienda Madrid*\n\n"
            f"Webs monitorizadas: {len(sites)}\n"
            f"Oportunidades activas: {len(active)}\n"
            f"Proximos lanzamientos: {len(future)}\n"
            f"Formularios enviados: {form_stats.get('enviado', 0)}\n"
            f"Formularios pendientes: {form_stats.get('pendiente', 0)}\n"
        )
        await self.send(header)

        if active:
            for chunk in _opportunity_chunks(active, "Oportunidades Activas"):
                await self.send(chunk)

        if self._forms:
            report = await self._forms.get_report()
            await self.send(report)

    # ── handlers ───────────────────────────────────────────────────────

    def _register_handlers(self) -> None:
        h = self._app.add_handler
        h(CommandHandler("start", self._h_start))
        h(CommandHandler("oportunidades", self._h_opportunities))
        h(CommandHandler("futuras", self._h_future))
        h(CommandHandler("formularios", self._h_forms))
        h(CommandHandler("buscar", self._h_search))
        h(CommandHandler("reporte", self._h_report))
        h(CommandHandler("sites", self._h_sites))
        h(CommandHandler("chatid", self._h_chatid))
        h(CommandHandler("help", self._h_help))

    async def _reply(self, update: Update, text: str) -> None:
        for chunk in _split(text):
            await update.message.reply_text(
                chunk, parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )

    async def _h_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply(
            update,
            "*Bot de Vivienda Madrid*\n\n"
            "Busco cooperativas y constructoras de vivienda en Madrid "
            "(norte, este, oeste) para ti.\n\n" + _HELP_TEXT,
        )

    async def _h_chatid(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id
        user_name = update.effective_user.first_name if update.effective_user else "?"
        await self._reply(
            update,
            f"*Tu Chat ID:* `{chat_id}`\n"
            f"Usuario: {user_name}\n\n"
            f"Pon este valor en la variable TELEGRAM\\_CHAT\\_ID "
            f"de tu entorno (Railway, .env, etc.)",
        )
        logger.info("Chat ID requested by %s: %d", user_name, chat_id)

    async def _h_help(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply(update, _HELP_TEXT)

    async def _h_opportunities(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        opps = await self._repo.get_opportunities()
        active = [o for o in opps if o.status in (OpportunityStatus.NUEVA, OpportunityStatus.EN_CURSO)]
        if not active:
            await self._reply(update, "No hay oportunidades activas todavia.")
            return
        for chunk in _opportunity_chunks(active, "Oportunidades Activas"):
            await self._reply(update, chunk)

    async def _h_future(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        opps = await self._repo.get_opportunities(status=OpportunityStatus.PROXIMA)
        if not opps:
            await self._reply(update, "No hay oportunidades futuras registradas.")
            return
        for chunk in _opportunity_chunks(opps, "Proximos Lanzamientos"):
            await self._reply(update, chunk)

    async def _h_forms(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if self._forms:
            await self._reply(update, await self._forms.get_report())
        else:
            await self._reply(update, "Servicio de formularios no disponible.")

    async def _h_search(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await self._reply(update, "Iniciando busqueda... puede tardar unos minutos.")
        if self._discovery:
            await self._discovery.load_seeds()
            new = await self._discovery.discover()
            site_count = len(new)
        else:
            site_count = 0
        if self._scraper:
            summary = await self._scraper.analyze_all()
        else:
            from db.models import AnalysisSummary
            summary = AnalysisSummary()
        await self._reply(
            update,
            f"*Busqueda completada*\n\n"
            f"Nuevos sitios: {site_count}\n"
            f"Sitios analizados: {summary.sites_analyzed}\n"
            f"Oportunidades: {summary.opportunities_found}\n"
            f"Formularios: {summary.forms_found}\n"
            f"Errores: {summary.errors}",
        )

    async def _h_report(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        opps = await self._repo.get_opportunities()
        sites = await self._repo.get_active_sites()
        form_stats = await self._forms.get_stats() if self._forms else {}

        active = [o for o in opps if o.status in (OpportunityStatus.NUEVA, OpportunityStatus.EN_CURSO)]
        future = [o for o in opps if o.status is OpportunityStatus.PROXIMA]

        lines = [
            "*Reporte Completo*", "",
            f"Webs monitorizadas: {len(sites)}",
            f"Oportunidades activas: {len(active)}",
            f"Proximos lanzamientos: {len(future)}", "",
            "*Formularios:*",
            f"  Enviados: {form_stats.get('enviado', 0)}",
            f"  Pendientes: {form_stats.get('pendiente', 0)}",
            f"  Errores: {form_stats.get('error', 0)}", "",
        ]
        if active:
            lines.append("*Top Oportunidades:*")
            for opp in sorted(active, key=lambda o: o.ai_score or 0, reverse=True)[:5]:
                score = f" ({opp.ai_score}/10)" if opp.ai_score else ""
                lines.append(f"  - {opp.title}{score} [{opp.zone.value}]")
            lines.append("")
        if future:
            lines.append("*Proximos:*")
            for opp in future[:5]:
                lines.append(f"  - {opp.title} [{opp.zone.value}]")

        await self._reply(update, "\n".join(lines))

    async def _h_sites(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        sites = await self._repo.get_active_sites()
        if not sites:
            await self._reply(update, "No hay sitios monitorizados.")
            return
        lines = ["*Sitios Monitorizados:*", ""]
        for s in sites:
            visited = f" (visitado: {s.last_visited[:10]})" if s.last_visited else ""
            lines.append(f"  - {s.name} [{s.zone.value}]{visited}")
        await self._reply(update, "\n".join(lines))


# ── pure formatting helpers ────────────────────────────────────────────

def _opportunity_chunks(opps: list[Opportunity], title: str) -> list[str]:
    chunks: list[str] = []
    current = f"*{title}* ({len(opps)})\n\n"
    for opp in opps:
        entry = opp.summary() + "\n\n"
        if len(current) + len(entry) > _MAX_MSG:
            chunks.append(current)
            current = ""
        current += entry
    if current.strip():
        chunks.append(current)
    return chunks


def _split(text: str) -> list[str]:
    if len(text) <= _MAX_MSG:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= _MAX_MSG:
            chunks.append(text)
            break
        at = text.rfind("\n", 0, _MAX_MSG)
        if at == -1:
            at = _MAX_MSG
        chunks.append(text[:at])
        text = text[at:].lstrip("\n")
    return chunks
