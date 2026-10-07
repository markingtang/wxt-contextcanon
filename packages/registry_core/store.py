"""SQLite storage for Registry Core.

The registry is a *file-state ledger*: append-only events per device, a local
outbox for offline work, and a shared index that is a pure projection of the
event log. If the index is wrong or lost, rebuild it. That is the whole point.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id   TEXT PRIMARY KEY,
    role        TEXT NOT NULL DEFAULT 'primary',
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL UNIQUE,
    device_id  TEXT NOT NULL,
    stream     TEXT NOT NULL DEFAULT 'default',
    kind       TEXT NOT NULL,
    ts         TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_device ON events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream);

CREATE TABLE IF NOT EXISTS outbox (
    outbox_id   TEXT PRIMARY KEY,
    device_id   TEXT NOT NULL,
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_status ON outbox(status);

CREATE TABLE IF NOT EXISTS applied (
    event_id   TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS shared_index (
    object_key TEXT NOT NULL,
    device_id  TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT '{}',
    version    INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (object_key, device_id)
);

CREATE TABLE IF NOT EXISTS manifests (
    manifest_id TEXT PRIMARY KEY,
    device_id   TEXT NOT NULL,
    scope       TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    payload     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS checkpoints (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class RegistryStore:
    def __init__(self, database_path: str):
        self.database_path = database_path
        parent = os.path.dirname(os.path.abspath(database_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.conn = sqlite3.connect(database_path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # --------------------------------------------------------------- devices

    def upsert_device(self, device_id: str, role: str, label: str, created_at: str) -> None:
        self.conn.execute(
            "INSERT INTO devices (device_id, role, label, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET role = excluded.role, label = excluded.label",
            (device_id, role, label, created_at),
        )
        self.conn.commit()

    def list_devices(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM devices ORDER BY device_id")]

    # ---------------------------------------------------------------- events

    def append_event(
        self,
        event_id: str,
        device_id: str,
        kind: str,
        ts: str,
        payload: Optional[Dict[str, Any]] = None,
        stream: str = "default",
    ) -> int:
        """Append-only, idempotent by event_id. Returns the sequence number."""
        cur = self.conn.execute("SELECT seq FROM events WHERE event_id = ?", (event_id,))
        row = cur.fetchone()
        if row:
            return int(row["seq"])
        cur = self.conn.execute(
            "INSERT INTO events (event_id, device_id, stream, kind, ts, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, device_id, stream, kind, ts, json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def events_since(self, seq: int, limit: int = 1000) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM events WHERE seq > ? ORDER BY seq ASC LIMIT ?", (seq, limit)
        )
        return [self._decode_event(r) for r in cur]

    def has_event(self, event_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM events WHERE event_id = ?", (event_id,)).fetchone()
        return row is not None

    def all_events(self) -> List[Dict[str, Any]]:
        return [
            self._decode_event(r)
            for r in self.conn.execute("SELECT * FROM events ORDER BY seq ASC")
        ]

    def max_seq(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) AS m FROM events").fetchone()
        return int(row["m"])

    # ---------------------------------------------------------------- outbox

    def enqueue(self, outbox_id: str, device_id: str, kind: str, payload: Dict[str, Any], created_at: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO outbox (outbox_id, device_id, kind, payload, status, "
            "attempts, last_error, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', 0, '', ?, ?)",
            (outbox_id, device_id, kind, json.dumps(payload, ensure_ascii=False, sort_keys=True), created_at, created_at),
        )
        self.conn.commit()

    def pending_outbox(self, limit: int = 500) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' ORDER BY created_at ASC, outbox_id ASC LIMIT ?",
            (limit,),
        )
        out = []
        for row in cur:
            item = dict(row)
            try:
                item["payload"] = json.loads(item["payload"])
            except (TypeError, ValueError):
                pass
            out.append(item)
        return out

    def mark_outbox(self, outbox_id: str, status: str, error: str = "", updated_at: str = "") -> None:
        self.conn.execute(
            "UPDATE outbox SET status = ?, attempts = attempts + 1, last_error = ?, updated_at = ? "
            "WHERE outbox_id = ?",
            (status, error, updated_at, outbox_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------- idempotency

    def already_applied(self, event_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM applied WHERE event_id = ?", (event_id,)).fetchone()
        return row is not None

    def mark_applied(self, event_id: str, applied_at: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO applied (event_id, applied_at) VALUES (?, ?)", (event_id, applied_at)
        )

    # ----------------------------------------------------------- shared index

    def put_index(self, object_key: str, device_id: str, state: Dict[str, Any], version: int, updated_at: str) -> None:
        self.conn.execute(
            "INSERT INTO shared_index (object_key, device_id, state, version, updated_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(object_key, device_id) DO UPDATE SET "
            "state = excluded.state, version = excluded.version, updated_at = excluded.updated_at",
            (object_key, device_id, json.dumps(state, ensure_ascii=False, sort_keys=True), version, updated_at),
        )

    def get_index(self, object_key: str, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if device_id:
            cur = self.conn.execute(
                "SELECT * FROM shared_index WHERE object_key = ? AND device_id = ?", (object_key, device_id)
            )
        else:
            cur = self.conn.execute("SELECT * FROM shared_index WHERE object_key = ?", (object_key,))
        return [self._decode_index(r) for r in cur]

    def all_index(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if device_id:
            cur = self.conn.execute(
                "SELECT * FROM shared_index WHERE device_id = ? ORDER BY object_key", (device_id,)
            )
        else:
            cur = self.conn.execute("SELECT * FROM shared_index ORDER BY object_key, device_id")
        return [self._decode_index(r) for r in cur]

    def replace_index(self, rows: List[Dict[str, Any]]) -> None:
        self.conn.execute("DELETE FROM shared_index")
        for row in rows:
            self.conn.execute(
                "INSERT INTO shared_index (object_key, device_id, state, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                (
                    row["object_key"],
                    row["device_id"],
                    json.dumps(row["state"], ensure_ascii=False, sort_keys=True),
                    row["version"],
                    row["updated_at"],
                ),
            )

    def snapshot_index(self) -> List[Dict[str, Any]]:
        return [self._decode_index(r) for r in self.conn.execute("SELECT * FROM shared_index")]

    # -------------------------------------------------------------- manifests

    def put_manifest(self, manifest_id: str, device_id: str, scope: str, checksum: str, created_at: str, payload: Dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO manifests (manifest_id, device_id, scope, checksum, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (manifest_id, device_id, scope, checksum, created_at, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()

    def list_manifests(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if device_id:
            cur = self.conn.execute(
                "SELECT * FROM manifests WHERE device_id = ? ORDER BY created_at DESC", (device_id,)
            )
        else:
            cur = self.conn.execute("SELECT * FROM manifests ORDER BY created_at DESC")
        out = []
        for row in cur:
            item = dict(row)
            try:
                item["payload"] = json.loads(item["payload"])
            except (TypeError, ValueError):
                pass
            out.append(item)
        return out

    # ------------------------------------------------------------ checkpoints

    def set_checkpoint(self, name: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO checkpoints (name, value) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
            (name, value),
        )
        self.conn.commit()

    def get_checkpoint(self, name: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM checkpoints WHERE name = ?", (name,)).fetchone()
        return row["value"] if row else None

    # ------------------------------------------------------------------ misc

    def commit(self) -> None:
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "RegistryStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _decode_event(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["payload"] = json.loads(data["payload"])
        except (TypeError, ValueError):
            data["payload"] = {}
        return data

    @staticmethod
    def _decode_index(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        try:
            data["state"] = json.loads(data["state"])
        except (TypeError, ValueError):
            data["state"] = {}
        return data
