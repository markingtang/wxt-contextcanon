"""SQLite storage for Profile Core.

Why SQLite: a new user should be able to run the whole thing on a laptop with
zero infrastructure. The same service layer can be pointed at PostgreSQL later;
nothing above this file depends on SQLite semantics beyond standard SQL.
"""

from __future__ import annotations

import json
import os
import sqlite3
from .model import normalize_timestamp
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    fact_id        TEXT PRIMARY KEY,
    subject        TEXT NOT NULL,
    key            TEXT NOT NULL,
    value          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    sensitivity    TEXT NOT NULL DEFAULT 'personal',
    durability     TEXT NOT NULL DEFAULT 'durable',
    certainty      REAL NOT NULL DEFAULT 1.0,
    valid_from     TEXT,
    valid_until    TEXT,
    provenance     TEXT NOT NULL DEFAULT '{}',
    revision       INTEGER NOT NULL DEFAULT 1,
    supersedes     TEXT,
    superseded_by  TEXT,
    conflicts_with TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_subject_key   ON facts(subject, key);
CREATE INDEX IF NOT EXISTS idx_facts_subject_status ON facts(subject, status);
CREATE INDEX IF NOT EXISTS idx_facts_validity      ON facts(valid_from, valid_until);

CREATE TABLE IF NOT EXISTS fact_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id    TEXT NOT NULL,
    subject    TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor      TEXT NOT NULL DEFAULT 'system',
    at         TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_subject ON fact_events(subject);
CREATE INDEX IF NOT EXISTS idx_events_fact    ON fact_events(fact_id);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    kind      TEXT NOT NULL,
    trust     REAL NOT NULL DEFAULT 0.5,
    note      TEXT NOT NULL DEFAULT ''
);
"""


class ProfileStore:
    """Thin persistence layer. No business rules live here."""

    def __init__(self, database_path: str):
        self.database_path = database_path
        parent = os.path.dirname(os.path.abspath(database_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(database_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ facts

    def insert_fact(self, row: Dict[str, Any]) -> None:
        payload = dict(row)
        payload["value"] = json.dumps(row["value"], ensure_ascii=False, sort_keys=True)
        payload["provenance"] = json.dumps(row.get("provenance") or {}, ensure_ascii=False)
        self.conn.execute(
            """
            INSERT INTO facts (fact_id, subject, key, value, status, sensitivity,
                               durability, certainty, valid_from, valid_until,
                               provenance, revision, supersedes, superseded_by,
                               conflicts_with, created_at, updated_at)
            VALUES (:fact_id, :subject, :key, :value, :status, :sensitivity,
                    :durability, :certainty, :valid_from, :valid_until,
                    :provenance, :revision, :supersedes, :superseded_by,
                    :conflicts_with, :created_at, :updated_at)
            """,
            payload,
        )

    def get_fact(self, fact_id: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM facts WHERE fact_id = ?", (fact_id,))
        row = cur.fetchone()
        return self._decode(row) if row else None

    def facts_effective_at(
        self, subject: str, timestamp: str, include_rejected: bool = False, key: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """The single temporal rule shared by "current" reads and `as_of`.

        A fact is a candidate at time T when T sits inside its validity window
        (``valid_from <= T < valid_until``; a null bound is open-ended). The
        highest revision wins per key - exactly one fact per key is returned.
        ``rejected`` claims are excluded unless asked for. Superseded revisions
        *stay* candidates on purpose: a revision scheduled for the future must
        not hide the value that is true today.
        """
        timestamp = normalize_timestamp(timestamp)
        sql = (
            "SELECT * FROM facts WHERE subject = ? "
            "AND (valid_from IS NULL OR julianday(valid_from) <= julianday(?)) "
            "AND (valid_until IS NULL OR julianday(valid_until) > julianday(?)) "
        )
        args: List[Any] = [subject, timestamp, timestamp]
        if key is not None:
            sql += "AND key = ? "
            args.append(key)
        if not include_rejected:
            sql += "AND status <> 'rejected' "
        # ORDER BY ranks the newest revision of each key first, so the first row
        # seen per key is the winner.
        sql += "ORDER BY key ASC, revision DESC"
        best: Dict[str, Dict[str, Any]] = {}
        for row in self.conn.execute(sql, args):
            if row["key"] not in best:
                best[row["key"]] = self._decode(row)
        return [best[key] for key in sorted(best)]

    def current_fact(
        self, subject: str, key: str, timestamp: str, include_rejected: bool = False
    ) -> Optional[Dict[str, Any]]:
        """The fact that is true for ``key`` at ``timestamp`` - same rule as above."""
        for fact in self.facts_effective_at(subject, timestamp, include_rejected, key=key):
            if fact["key"] == key:
                return fact
        return None

    def get_active(
        self, subject: str, key: str, timestamp: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Backwards-compatible wrapper. Delegates to the shared temporal rule.

        ``timestamp`` defaults to the caller's "now"; a fact whose ``valid_from``
        is in the future is therefore never returned as current.
        """
        if timestamp is None:
            timestamp = _utc_now_iso()
        return self.current_fact(subject, key, timestamp)

    def list_subject(
        self,
        subject: str,
        status: Optional[str] = None,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM facts WHERE subject = ?"
        args: List[Any] = [subject]
        if status:
            sql += " AND status = ?"
            args.append(status)
        elif not include_inactive:
            sql += " AND status = 'active'"
        sql += " ORDER BY key ASC, revision DESC"
        return [self._decode(r) for r in self.conn.execute(sql, args)]

    def all_facts(self) -> List[Dict[str, Any]]:
        """Every fact, any status - used by lifecycle sweeps and rebuilds."""
        return [self._decode(r) for r in self.conn.execute("SELECT * FROM facts")]

    def list_all(self, limit: int = 1000) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM facts ORDER BY subject, key, revision DESC LIMIT ?", (limit,)
        )
        return [self._decode(r) for r in cur]

    def search(self, subject: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        like = "%" + query.replace("%", "") + "%"
        cur = self.conn.execute(
            "SELECT * FROM facts WHERE subject = ? AND status = 'active' "
            "AND (key LIKE ? OR value LIKE ?) ORDER BY key ASC LIMIT ?",
            (subject, like, like, limit),
        )
        return [self._decode(r) for r in cur]

    def update_fact_fields(self, fact_id: str, **fields: Any) -> None:
        if not fields:
            return
        assignments = ", ".join("%s = ?" % name for name in fields)
        args = [json.dumps(v, ensure_ascii=False, sort_keys=True)
                if isinstance(v, (dict, list)) else v for v in fields.values()]
        args.append(fact_id)
        self.conn.execute("UPDATE facts SET %s WHERE fact_id = ?" % assignments, args)

    def set_status(self, fact_id: str, status: str) -> None:
        self.conn.execute("UPDATE facts SET status = ? WHERE fact_id = ?", (status, fact_id))

    def count(self, status: Optional[str] = None) -> int:
        if status:
            cur = self.conn.execute("SELECT COUNT(*) FROM facts WHERE status = ?", (status,))
        else:
            cur = self.conn.execute("SELECT COUNT(*) FROM facts")
        return int(cur.fetchone()[0])

    # ----------------------------------------------------------------- events

    def append_event(
        self,
        fact_id: str,
        subject: str,
        event_type: str,
        actor: str = "system",
        at: str = "",
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conn.execute(
            "INSERT INTO fact_events (fact_id, subject, event_type, actor, at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                fact_id,
                subject,
                event_type,
                actor,
                at,
                json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            ),
        )

    def events_for_subject(self, subject: str, limit: int = 100) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM fact_events WHERE subject = ? ORDER BY event_id DESC LIMIT ?",
            (subject, limit),
        )
        return [self._decode_event(r) for r in cur]

    def events_for_fact(self, fact_id: str) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM fact_events WHERE fact_id = ? ORDER BY event_id ASC", (fact_id,)
        )
        return [self._decode_event(r) for r in cur]

    # ---------------------------------------------------------------- sources

    def upsert_source(self, source_id: str, kind: str, trust: float, note: str = "") -> None:
        self.conn.execute(
            "INSERT INTO sources (source_id, kind, trust, note) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET kind = excluded.kind, "
            "trust = excluded.trust, note = excluded.note",
            (source_id, kind, trust, note),
        )

    def list_sources(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM sources ORDER BY source_id")]

    # ------------------------------------------------------------------ misc

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ProfileStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["value"] = json.loads(data["value"])
        except (TypeError, ValueError):
            pass
        try:
            data["provenance"] = json.loads(data["provenance"])
        except (TypeError, ValueError):
            data["provenance"] = {}
        return data

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["payload"] = json.loads(data["payload"])
        except (TypeError, ValueError):
            data["payload"] = {}
        return data
