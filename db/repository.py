"""Async repository – works with both Turso (libsql) and local SQLite.

When ``turso_url`` is provided the repository talks to Turso over the
``libsql://`` protocol.  Otherwise it falls back to local SQLite via
``aiosqlite``.  Every public method manages its own connection/query
lifecycle so callers don't need to worry about backends.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Sequence

from db.models import (
    Site, Opportunity, FormSubmission,
    Zone, SiteType, OpportunityStatus, FormStatus, FormType,
)
from exceptions import RepositoryError

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────

_SCHEMA_TABLES = [
    """\
CREATE TABLE IF NOT EXISTS sites (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT    UNIQUE NOT NULL,
    name          TEXT    NOT NULL DEFAULT '',
    zone          TEXT    NOT NULL DEFAULT 'todas',
    site_type     TEXT    NOT NULL DEFAULT 'portal',
    discovered_at TEXT    NOT NULL,
    last_visited  TEXT,
    active        INTEGER NOT NULL DEFAULT 1
)""",
    """\
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
)""",
    """\
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
)""",
    """\
CREATE TABLE IF NOT EXISTS preferences (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL DEFAULT '{}'
)""",
]

_SCHEMA_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sites_active          ON sites(active)",
    "CREATE INDEX IF NOT EXISTS idx_opportunities_site     ON opportunities(site_id)",
    "CREATE INDEX IF NOT EXISTS idx_opportunities_status   ON opportunities(status)",
    "CREATE INDEX IF NOT EXISTS idx_forms_status           ON form_submissions(status)",
]

_OPP_MIGRATIONS = [
    "ALTER TABLE opportunities ADD COLUMN house_type TEXT",
    "ALTER TABLE opportunities ADD COLUMN bedrooms INTEGER",
    "ALTER TABLE opportunities ADD COLUMN sqm REAL",
    "ALTER TABLE opportunities ADD COLUMN amenities TEXT",
    "ALTER TABLE opportunities ADD COLUMN protection_type TEXT",
    "ALTER TABLE opportunities ADD COLUMN availability TEXT",
    "ALTER TABLE opportunities ADD COLUMN project_date TEXT",
]

# ── Thin async wrapper for libsql_experimental ────────────────────────

class _TursoConn:
    """Async wrapper around the ``libsql_client`` connection."""

    def __init__(self, url: str, auth_token: str) -> None:
        self._url = url
        self._token = auth_token
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _get(self) -> Any:
        if self._client is None:
            import libsql_client
            self._client = libsql_client.create_client(
                url=self._url, auth_token=self._token
            )
        return self._client

    async def execute(self, sql: str, params: Sequence = ()) -> Any:
        client = await self._get()
        result = await client.execute(sql, list(params))
        class MockCursor:
            lastrowid = result.last_insert_rowid
        return MockCursor()

    async def execute_fetchall(self, sql: str, params: Sequence = ()) -> list[tuple]:
        client = await self._get()
        result = await client.execute(sql, list(params))
        return [tuple(row) for row in result.rows]

    async def executescript(self, script: str) -> None:
        client = await self._get()
        statements = [s.strip() for s in script.split(';') if s.strip()]
        if statements:
            await client.batch(statements)

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None


class _SqliteConn:
    """Async wrapper using ``aiosqlite`` for local SQLite files."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @asynccontextmanager
    async def _open(self) -> AsyncIterator:
        import aiosqlite
        db = await aiosqlite.connect(str(self._path))
        try:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("PRAGMA foreign_keys=ON")
            yield db
        finally:
            await db.close()

    async def execute(self, sql: str, params: Sequence = ()) -> Any:
        async with self._open() as db:
            cur = await db.execute(sql, tuple(params))
            await db.commit()
            return cur

    async def execute_fetchall(self, sql: str, params: Sequence = ()) -> list[tuple]:
        async with self._open() as db:
            return await db.execute_fetchall(sql, tuple(params))

    async def executescript(self, script: str) -> None:
        async with self._open() as db:
            await db.executescript(script)

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


# ── Repository ─────────────────────────────────────────────────────────

class Repository:
    """Thin async repository over SQLite / Turso."""

    def __init__(
        self,
        db_path: Path,
        *,
        turso_url: str = "",
        turso_auth_token: str = "",
    ) -> None:
        if turso_url and turso_auth_token:
            self._db = _TursoConn(turso_url, turso_auth_token)
            self._backend = "turso"
        else:
            self._db = _SqliteConn(db_path)
            self._backend = "sqlite"

    # ── lifecycle ──────────────────────────────────────────────────────

    async def init(self) -> None:
        for ddl in _SCHEMA_TABLES:
            await self._db.execute(ddl)
        for ddl in _SCHEMA_INDEXES:
            await self._db.execute(ddl)
        await self._db.commit()

        for ddl in _OPP_MIGRATIONS:
            try:
                await self._db.execute(ddl)
                await self._db.commit()
            except Exception:
                pass
        logger.info("Database initialised (%s)", self._backend)

    async def close(self) -> None:
        await self._db.close()

    # ── sites ──────────────────────────────────────────────────────────

    async def upsert_site(self, site: Site) -> int:
        rows = await self._db.execute_fetchall(
            "SELECT id FROM sites WHERE url = ?", (site.url,),
        )
        if rows:
            site_id: int = rows[0][0]
            await self._db.execute(
                "UPDATE sites SET name=?, zone=?, site_type=?, active=? WHERE id=?",
                (site.name, site.zone.value, site.site_type.value,
                 int(site.active), site_id),
            )
        else:
            cur = await self._db.execute(
                "INSERT INTO sites (url,name,zone,site_type,discovered_at,active) "
                "VALUES (?,?,?,?,?,?)",
                (site.url, site.name, site.zone.value, site.site_type.value,
                 site.discovered_at, int(site.active)),
            )
            site_id = cur.lastrowid
        await self._db.commit()
        return site_id

    async def get_active_sites(self) -> list[Site]:
        rows = await self._db.execute_fetchall(
            "SELECT * FROM sites WHERE active=1 ORDER BY last_visited ASC",
        )
        return [self._to_site(r) for r in rows]

    async def get_all_sites(self) -> list[Site]:
        rows = await self._db.execute_fetchall(
            "SELECT * FROM sites ORDER BY discovered_at DESC",
        )
        return [self._to_site(r) for r in rows]

    async def mark_site_visited(self, site_id: int) -> None:
        await self._db.execute(
            "UPDATE sites SET last_visited=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), site_id),
        )
        await self._db.commit()

    # ── opportunities ──────────────────────────────────────────────────

    async def upsert_opportunity(self, opp: Opportunity) -> int:
        rows = await self._db.execute_fetchall(
            "SELECT id FROM opportunities WHERE url=? AND site_id=?",
            (opp.url, opp.site_id),
        )
        if rows:
            opp_id: int = rows[0][0]
            await self._db.execute(
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
            cur = await self._db.execute(
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
        await self._db.commit()
        return opp_id

    async def get_opportunities(
        self,
        *,
        status: Optional[OpportunityStatus] = None,
        notified: Optional[bool] = None,
    ) -> list[Opportunity]:
        clauses = ["1=1"]
        params: list = []
        if status is not None:
            clauses.append("status=?")
            params.append(status.value)
        if notified is not None:
            clauses.append("notified=?")
            params.append(int(notified))
        where = " AND ".join(clauses)
        rows = await self._db.execute_fetchall(
            f"SELECT * FROM opportunities WHERE {where} "
            "ORDER BY ai_score DESC, detected_at DESC",
            params,
        )
        return [self._to_opportunity(r) for r in rows]

    async def mark_opportunity_notified(self, opp_id: int) -> None:
        await self._db.execute(
            "UPDATE opportunities SET notified=1 WHERE id=?", (opp_id,),
        )
        await self._db.commit()

    # ── form submissions ───────────────────────────────────────────────

    async def upsert_form(self, form: FormSubmission) -> int:
        rows = await self._db.execute_fetchall(
            "SELECT id FROM form_submissions WHERE form_url=? AND site_id=?",
            (form.form_url, form.site_id),
        )
        if rows:
            return rows[0][0]
        cur = await self._db.execute(
            "INSERT INTO form_submissions "
            "(site_id,form_url,status,data_sent,submitted_at,"
            "screenshot_path,error_message,form_type) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (form.site_id, form.form_url, form.status.value, form.data_sent,
             form.submitted_at, form.screenshot_path, form.error_message,
             form.form_type.value),
        )
        await self._db.commit()
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
        await self._db.execute(
            f"UPDATE form_submissions SET {','.join(fields)} WHERE id=?",
            params,
        )
        await self._db.commit()

    async def get_forms(
        self, *, status: Optional[FormStatus] = None,
    ) -> list[FormSubmission]:
        if status is not None:
            rows = await self._db.execute_fetchall(
                "SELECT * FROM form_submissions WHERE status=? "
                "ORDER BY submitted_at DESC NULLS LAST",
                (status.value,),
            )
        else:
            rows = await self._db.execute_fetchall(
                "SELECT * FROM form_submissions "
                "ORDER BY submitted_at DESC NULLS LAST",
            )
        return [self._to_form(r) for r in rows]

    # ── row mappers ───────────────────────────────────────────────────

    @staticmethod
    def _to_site(row) -> Site:
        return Site(
            id=row[0], url=row[1], name=row[2],
            zone=Zone(row[3]),
            site_type=SiteType(row[4]),
            discovered_at=row[5], last_visited=row[6],
            active=bool(row[7]),
        )

    @staticmethod
    def _to_opportunity(row) -> Opportunity:
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
    def _to_form(row) -> FormSubmission:
        return FormSubmission(
            id=row[0], site_id=row[1], form_url=row[2],
            status=FormStatus(row[3]),
            data_sent=row[4], submitted_at=row[5],
            screenshot_path=row[6], error_message=row[7],
            form_type=FormType(row[8]),
        )

    # ── preferences ────────────────────────────────────────────────────

    _DEFAULT_PREFS: dict = {
        "house_types": ["piso"],
        "price_max": 400000,
        "bedrooms_min": 2,
        "sqm_min": 60,
        "zones": ["norte", "oeste"],
        "protection_types": ["VPO", "VPP", "VPPL"],
        "turbo_mode": True,
    }

    async def get_preferences(self) -> dict:
        rows = await self._db.execute_fetchall(
            "SELECT data FROM preferences WHERE id=1",
        )
        if rows:
            stored = _json.loads(rows[0][0])
            if stored:
                return stored
        prefs = dict(self._DEFAULT_PREFS)
        await self.save_preferences(prefs)
        return prefs

    async def save_preferences(self, prefs: dict) -> None:
        data = _json.dumps(prefs, ensure_ascii=False)
        await self._db.execute(
            "INSERT OR REPLACE INTO preferences (id, data) VALUES (1, ?)",
            (data,),
        )
        await self._db.commit()

    # ── stats ──────────────────────────────────────────────────────────

    async def get_stats(self) -> dict:
        rows = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM sites WHERE active=1",
        )
        sites = rows[0][0] if rows else 0
        rows = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM opportunities",
        )
        opps = rows[0][0] if rows else 0
        rows = await self._db.execute_fetchall(
            "SELECT COUNT(*) FROM form_submissions",
        )
        forms = rows[0][0] if rows else 0
        return {"sites": sites, "opportunities": opps, "forms": forms}

    # ── danger zone ────────────────────────────────────────────────────

    async def reset_all(self) -> None:
        """Delete ALL data from every table. Use with extreme caution."""
        await self._db.execute("DELETE FROM form_submissions")
        await self._db.execute("DELETE FROM opportunities")
        await self._db.execute("DELETE FROM sites")
        await self._db.execute("DELETE FROM preferences")
        await self._db.commit()
        logger.warning("All data deleted (panic reset)")
