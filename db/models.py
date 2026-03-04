from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Zone(str, enum.Enum):
    NORTE = "norte"
    ESTE = "este"
    OESTE = "oeste"
    TODAS = "todas"


class SiteType(str, enum.Enum):
    COOPERATIVA = "cooperativa"
    CONSTRUCTORA = "constructora"
    PORTAL = "portal"


class OpportunityStatus(str, enum.Enum):
    NUEVA = "nueva"
    EN_CURSO = "en_curso"
    PROXIMA = "proxima"
    CERRADA = "cerrada"


class FormStatus(str, enum.Enum):
    PENDIENTE = "pendiente"
    ENVIADO = "enviado"
    ERROR = "error"
    OMITIDO = "omitido"


class FormType(str, enum.Enum):
    CONTACTO = "contacto"
    INSCRIPCION = "inscripcion"
    INFORMACION = "informacion"


_FORM_STATUS_EMOJI: dict[FormStatus, str] = {
    FormStatus.PENDIENTE: "\u23f3",
    FormStatus.ENVIADO: "\u2705",
    FormStatus.ERROR: "\u274c",
    FormStatus.OMITIDO: "\u23ed\ufe0f",
}


@dataclass(frozen=True)
class Site:
    url: str
    name: str = ""
    zone: Zone = Zone.TODAS
    site_type: SiteType = SiteType.PORTAL
    discovered_at: str = field(default_factory=_utcnow_iso)
    last_visited: Optional[str] = None
    active: bool = True
    id: Optional[int] = None

    def short(self) -> str:
        return f"{self.name or self.url} ({self.zone.value})"


@dataclass(frozen=True)
class Opportunity:
    site_id: int
    title: str
    url: str
    description: str = ""
    estimated_price: Optional[str] = None
    zone: Zone = Zone.TODAS
    status: OpportunityStatus = OpportunityStatus.NUEVA
    detected_at: str = field(default_factory=_utcnow_iso)
    ai_score: Optional[float] = None
    notified: bool = False
    id: Optional[int] = None

    def summary(self) -> str:
        parts = [f"Zona: {self.zone.value} | Estado: {self.status.value}"]
        if self.estimated_price:
            parts.append(f"Precio: {self.estimated_price}")
        if self.ai_score is not None:
            parts.append(f"Puntuacion: {self.ai_score}/10")
        meta = " | ".join(parts)
        desc = self.description[:200]
        return f"*{self.title}*\n{meta}\n{desc}\n[Ver mas]({self.url})"


@dataclass(frozen=True)
class FormSubmission:
    site_id: int
    form_url: str
    status: FormStatus = FormStatus.PENDIENTE
    form_type: FormType = FormType.CONTACTO
    data_sent: Optional[str] = None
    submitted_at: Optional[str] = None
    screenshot_path: Optional[str] = None
    error_message: Optional[str] = None
    id: Optional[int] = None

    @property
    def status_emoji(self) -> str:
        return _FORM_STATUS_EMOJI.get(self.status, "\u2753")


@dataclass(frozen=True)
class ScrapeResult:
    """Typed return value from the scraper, replacing loose dicts."""

    text: str
    html: str
    title: str
    final_url: str
    success: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class AnalysisResult:
    """Aggregate result of analyzing one site."""

    opportunities: int = 0
    forms: int = 0
    error: Optional[str] = None


@dataclass(frozen=True)
class AnalysisSummary:
    """Aggregate result of analyzing all sites."""

    sites_analyzed: int = 0
    opportunities_found: int = 0
    forms_found: int = 0
    errors: int = 0


@dataclass(frozen=True)
class FormFillSummary:
    filled: int = 0
    errors: int = 0
    skipped: int = 0
