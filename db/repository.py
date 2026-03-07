"""Async repository with a reusable connection context manager.

Usage::

    repo = Repository(db_path)
    await repo.init()

    # Every public method manages its own connection lifecycle via ``_conn``.
    sites = await repo.get_active_sites()
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Optional

import aiosqlite

from db.models import (
    Site, Opportunity, FormSubmission,
    Zone, SiteType, OpportunityStatus, FormStatus, FormType,
)
from exceptions import RepositoryError

logger = logging.getLogger(__name__)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT    UNIQUE NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    zone          TEXT    NOT NULL DEFAULT 'todas',
    site_type     TEXT    NOT NULL DEFAULT 'portal',
    discovered_at TEXT    NOT NULL,
    last_visited  TEXT,
    active        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    title           TEXT    NOT NULL,
    description     TEXT    NOT NULL DEFAULT '',
    estimated_price TEXT,
    zone            TEXT    NOT NULL DEFAULT 'todas',
    status          TEXT    NOT NULL DEFAULT 'nueva',
    detected_at     TEXT    NOT NULL,
    ai_score        REAL,
    url             TEXT    NOT NULL DEFAULT '',
    notified        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS form_submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id         INTEGER NOT NULL REFERENCES sites(id),
    form_url        TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'pendiente',
    data_sent       TEXT,
    submitted_at    TEXT,
    screenshot_path TEXT,
    error_message   TEXT,
    form_type       TEXT    NOT NULL DEFAULT 'contacto'
);

CREATE TABLE IF NOT EXISTS preferences (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sites_active          ON sites(active);
CREATE INDEX IF NOT EXISTS idx_opportunities_site     ON opportunities(site_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_status   ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_forms_status           ON form_submissions(status);
"""

_OPP_MIGRATIONS = [
    "ALTER TABLE opportunities ADD COLUMN house_type TEXT",
    "ALTER TABLE opportunities ADD COLUMN bedrooms INTEGER",
    "ALTER TABLE opportunities ADD COLUMN sqm REAL",
    "ALTER TABLE opportunities ADD COLUMN amenities TEXT",
    "ALTER TABLE opportunities ADD COLUMN protection_type TEXT",
    "ALTER TABLE opportunities ADD COLUMN availability TEXT",
    "ALTER TABLE opportunities ADD COLUMN project_date TEXT",
]


class Repository:
    """Thin async repository over SQLite.  Thread-safe via aiosqlite."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    # ── lifecycle ──────────────────────────────────────────────────────

    async def init(self) -> None:
        async with self._conn() as db:
            await db.executescript(_SCHEMA)
            for ddl in _OPP_MIGRATIONS:
                try:
                    await db.execute(ddl)
                except Exception:
                    pass
            await db.commit()
        logger.info("Database initialised at %s", self._db_path)

    @asynccontextmanager
    async def _conn(self) -> AsyncIterator[aiosqlite.Connection]:
        db = await aiosqlite.connect(str(self._db_path))
        try:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        except Exception as exc:
            raise RepositoryError(str(exc)) from exc
        finally:
            await db.close()

    # ── sites ──────────────────────────────────────────────────────────

    async def upsert_site(self, site: Site) -> int:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id FROM sites WHERE url = ?", (site.url,),
            )
            if rows:
                site_id: int = rows[0][0]
                await db.execute(
                    "UPDATE sites SET name=?, zone=?, site_type=?, active=? WHERE id=?",
                    (site.name, site.zone.value, site.site_type.value,
                     int(site.active), site_id),
                )
            else:
                cur = await db.execute(
                    "INSERT INTO sites (url,name,zone,site_type,discovered_at,active) "
                    "VALUES (?,?,?,?,?,?)",
                    (site.url, site.name, site.zone.value, site.site_type.value,
                     site.discovered_at, int(site.active)),
                )
                site_id = cur.lastrowid
            await db.commit()
            return site_id

    async def get_active_sites(self) -> list[Site]:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT * FROM sites WHERE active=1 ORDER BY last_visited ASC",
            )
            return [self._to_site(r) for r in rows]

    async def get_all_sites(self) -> list[Site]:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT * FROM sites ORDER BY discovered_at DESC",
            )
            return [self._to_site(r) for r in rows]

    async def mark_site_visited(self, site_id: int) -> None:
        async with self._conn() as db:
            await db.execute(
                "UPDATE sites SET last_visited=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), site_id),
            )
            await db.commit()

    # ── opportunities ──────────────────────────────────────────────────

    async def upsert_opportunity(self, opp: Opportunity) -> int:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id FROM opportunities WHERE url=? AND site_id=?",
                (opp.url, opp.site_id),
            )
            if rows:
                opp_id: int = rows[0][0]
                await db.execute(
                    "UPDATE opportunities SET title=?,description=?,estimated_price=?,"
                    "zone=?,status=?,ai_score=?,house_type=?,bedrooms=?,sqm=?,"
                    "amenities=?,protection_type=?,availability=?,project_date=? "
                    "WHERE id=?",
                    (opp.title, opp.description, opp.estimated_price,
                     opp.zone.value, opp.status.value, opp.ai_score,
                     opp.house_type, opp.bedrooms, opp.sqm, opp.amenities,
                     opp.protection_type, opp.availability, opp.project_date,
                     opp_id),
                )
            else:
                cur = await db.execute(
                    "INSERT INTO opportunities "
                    "(site_id,title,description,estimated_price,zone,status,"
                    "detected_at,ai_score,url,notified,house_type,bedrooms,"
                    "sqm,amenities,protection_type,availability,project_date) "
                    "VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?)",
                    (opp.site_id, opp.title, opp.description, opp.estimated_price,
                     opp.zone.value, opp.status.value, opp.detected_at,
                     opp.ai_score, opp.url, opp.house_type, opp.bedrooms,
                     opp.sqm, opp.amenities, opp.protection_type,
                     opp.availability, opp.project_date),
                )
                opp_id = cur.lastrowid
            await db.commit()
            return opp_id

    async def get_opportunities(
        self,
        *,
        status: Optional[OpportunityStatus] = None,
        notified: Optional[bool] = None,
    ) -> list[Opportunity]:
        async with self._conn() as db:
            clauses = ["1=1"]
            params: list = []
            if status is not None:
                clauses.append("status=?")
                params.append(status.value)
            if notified is not None:
                clauses.append("notified=?")
                params.append(int(notified))
            where = " AND ".join(clauses)
            rows = await db.execute_fetchall(
                f"SELECT * FROM opportunities WHERE {where} "
                "ORDER BY ai_score DESC, detected_at DESC",
                params,
            )
            return [self._to_opportunity(r) for r in rows]

    async def mark_opportunity_notified(self, opp_id: int) -> None:
        async with self._conn() as db:
            await db.execute(
                "UPDATE opportunities SET notified=1 WHERE id=?", (opp_id,),
            )
            await db.commit()

    # ── form submissions ───────────────────────────────────────────────

    async def upsert_form(self, form: FormSubmission) -> int:
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT id FROM form_submissions WHERE form_url=? AND site_id=?",
                (form.form_url, form.site_id),
            )
            if rows:
                return rows[0][0]
            cur = await db.execute(
                "INSERT INTO form_submissions "
                "(site_id,form_url,status,data_sent,submitted_at,"
                "screenshot_path,error_message,form_type) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (form.site_id, form.form_url, form.status.value, form.data_sent,
                 form.submitted_at, form.screenshot_path, form.error_message,
                 form.form_type.value),
            )
            await db.commit()
            return cur.lastrowid

    async def update_form_status(
        self,
        form_id: int,
        status: FormStatus,
        *,
        screenshot_path: Optional[str] = None,
        error_message: Optional[str] = None,
        data_sent: Optional[str] = None,
    ) -> None:
        async with self._conn() as db:
            fields = ["status=?"]
            params: list = [status.value]
            if status is FormStatus.ENVIADO:
                fields.append("submitted_at=?")
                params.append(datetime.now(timezone.utc).isoformat())
            if screenshot_path is not None:
                fields.append("screenshot_path=?")
                params.append(screenshot_path)
            if error_message is not None:
                fields.append("error_message=?")
                params.append(error_message)
            if data_sent is not None:
                fields.append("data_sent=?")
                params.append(data_sent)
            params.append(form_id)
            await db.execute(
                f"UPDATE form_submissions SET {','.join(fields)} WHERE id=?",
                params,
            )
            await db.commit()

    async def get_forms(
        self, *, status: Optional[FormStatus] = None,
    ) -> list[FormSubmission]:
        async with self._conn() as db:
            if status is not None:
                rows = await db.execute_fetchall(
                    "SELECT * FROM form_submissions WHERE status=? "
                    "ORDER BY submitted_at DESC NULLS LAST",
                    (status.value,),
                )
            else:
                rows = await db.execute_fetchall(
                    "SELECT * FROM form_submissions "
                    "ORDER BY submitted_at DESC NULLS LAST",
                )
            return [self._to_form(r) for r in rows]

    # ── row mappers (private) ──────────────────────────────────────────

    @staticmethod
    def _to_site(row: aiosqlite.Row) -> Site:
        return Site(
            id=row[0], url=row[1], name=row[2],
            zone=Zone(row[3]),
            site_type=SiteType(row[4]),
            discovered_at=row[5], last_visited=row[6],
            active=bool(row[7]),
        )

    @staticmethod
    def _to_opportunity(row: aiosqlite.Row) -> Opportunity:
        n = len(row)
        return Opportunity(
            id=row[0], site_id=row[1], title=row[2], description=row[3],
            estimated_price=row[4],
            zone=Zone(row[5]),
            status=OpportunityStatus(row[6]),
            detected_at=row[7], ai_score=row[8], url=row[9],
            notified=bool(row[10]),
            house_type=row[11] if n > 11 else None,
            bedrooms=row[12] if n > 12 else None,
            sqm=row[13] if n > 13 else None,
            amenities=row[14] if n > 14 else None,
            protection_type=row[15] if n > 15 else None,
            availability=row[16] if n > 16 else None,
            project_date=row[17] if n > 17 else None,
        )

    @staticmethod
    def _to_form(row: aiosqlite.Row) -> FormSubmission:
        return FormSubmission(
            id=row[0], site_id=row[1], form_url=row[2],
            status=FormStatus(row[3]),
            data_sent=row[4], submitted_at=row[5],
            screenshot_path=row[6], error_message=row[7],
            form_type=FormType(row[8]),
        )

    # ── preferences ────────────────────────────────────────────────────

    async def get_preferences(self) -> dict:
        import json as _json
        async with self._conn() as db:
            rows = await db.execute_fetchall(
                "SELECT data FROM preferences WHERE id=1",
            )
            if rows:
                return _json.loads(rows[0][0])
            return {}

    async def save_preferences(self, prefs: dict) -> None:
        import json as _json
        data = _json.dumps(prefs, ensure_ascii=False)
        async with self._conn() as db:
            await db.execute(
                "INSERT OR REPLACE INTO preferences (id, data) VALUES (1, ?)",
                (data,),
            )
            await db.commit()

    # ── danger zone ────────────────────────────────────────────────────

    async def reset_all(self) -> None:
        """Delete ALL data from every table. Use with extreme caution."""
        async with self._conn() as db:
            await db.execute("DELETE FROM form_submissions")
            await db.execute("DELETE FROM opportunities")
            await db.execute("DELETE FROM sites")
            await db.execute("DELETE FROM preferences")
            await db.commit()
        logger.warning("All data deleted (panic reset)")
