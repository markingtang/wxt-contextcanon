"""Business rules for Registry Core.

Contract consumed by WXT ContextCanon (frozen behaviours, no production writes):
  * device identity        - every writer announces who it is
  * manifests              - a device publishes what it holds, with a checksum
  * append-only events     - the ledger is truth; nothing is edited in place
  * local outbox           - work continues offline, then replays
  * shared index rebuild   - the index is a projection; rebuild anytime
  * idempotency            - replaying an event twice changes nothing
  * last-good behaviour    - a failed rebuild restores the previous good index
  * offline recovery       - drain outbox + rebuild = converged
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .store import RegistryStore

# Kinds whose whole purpose is to describe a file's state; such an event is
# meaningless - and must be rejected, not silently applied - without a key.
FILE_KINDS = ("file.upsert", "file.write", "file.update",
              "file.delete", "file.remove", "file.move")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(repr(p) for p in parts)
    return "%s_%s" % (prefix, hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16])


def checksum_of(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


class RegistryService:
    def __init__(self, store: RegistryStore, device_id: str = "demo-device", device_role: str = "primary"):
        self.store = store
        self.device_id = device_id
        self.device_role = device_role

    # ------------------------------------------------------------- identity

    def ensure_device(self, label: str = "") -> Dict[str, Any]:
        self.store.upsert_device(self.device_id, self.device_role, label or self.device_id, now_iso())
        return {"device_id": self.device_id, "role": self.device_role, "label": label or self.device_id}

    def list_devices(self) -> List[Dict[str, Any]]:
        return self.store.list_devices()

    # ------------------------------------------------------------ manifests

    def record_manifest(self, scope: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        payload = {"scope": scope, "entries": entries}
        checksum = checksum_of(payload)
        manifest_id = make_id("mf", self.device_id, scope, checksum)
        self.store.put_manifest(manifest_id, self.device_id, scope, checksum, now_iso(), payload)
        self.append_event("manifest.published", {"manifest_id": manifest_id, "scope": scope, "checksum": checksum})
        return {"manifest_id": manifest_id, "checksum": checksum, "entry_count": len(entries)}

    def list_manifests(self, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.store.list_manifests(device_id)

    # --------------------------------------------------------------- events

    def append_event(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        device_id: Optional[str] = None,
        stream: str = "default",
        event_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        device_id = device_id or self.device_id
        payload = payload or {}
        # A fresh uuid is part of every generated id: two identical events in the
        # same second must not collapse into one, and an id must not be derivable
        # from kind + payload + a second-granular timestamp.
        event_id = event_id or make_id(
            "ev", device_id, kind, json.dumps(payload, sort_keys=True), uuid.uuid4().hex
        )
        seq = self.store.append_event(event_id, device_id, kind, now_iso(), payload, stream)
        return {"event_id": event_id, "seq": seq, "kind": kind, "device_id": device_id}

    # ---------------------------------------------------------- task framing

    def begin_task(self, task_id: str, intent: str, targets: Optional[List[str]] = None) -> Dict[str, Any]:
        """Mutation intent: declare what you are about to touch, before touching it."""
        payload = {"task_id": task_id, "intent": intent, "targets": targets or []}
        event = self.append_event("task.begin", payload)
        # The outbox entry carries the *same* event identity. It is the same
        # logical event, waiting to be delivered - never a second copy of it.
        self.store.enqueue(event["event_id"], self.device_id, "task.begin", payload, now_iso())
        return {"state": "open", "task_id": task_id, **event, "payload": payload}

    def end_task(self, task_id: str, result: str, changed: Optional[List[str]] = None) -> Dict[str, Any]:
        payload = {"task_id": task_id, "result": result, "changed": changed or []}
        event = self.append_event("task.end", payload)
        self.store.enqueue(event["event_id"], self.device_id, "task.end", payload, now_iso())
        return {"state": "closed", "task_id": task_id, **event, "payload": payload}

    def open_tasks(self) -> List[str]:
        open_ids: List[str] = []
        for event in self.store.all_events():
            if event["kind"] == "task.begin":
                open_ids.append(event["payload"].get("task_id", ""))
            elif event["kind"] == "task.end":
                tid = event["payload"].get("task_id", "")
                if tid in open_ids:
                    open_ids.remove(tid)
        return [t for t in open_ids if t]

    # --------------------------------------------------------- outbox / sync

    def drain_outbox(self, limit: int = 500) -> Dict[str, Any]:
        """Deliver/applicate pending local work. Idempotent, and never duplicates.

        The ledger is the truth and already holds these events (they were
        appended when the work was created). Draining delivers them into the
        projection; it must not insert a second ledger copy.
        """
        applied = 0
        skipped = 0
        failed = 0
        for item in self.store.pending_outbox(limit):
            event_id = item["outbox_id"]
            try:
                if self.store.already_applied(event_id):
                    skipped += 1
                else:
                    if not self.store.has_event(event_id):
                        # Only reachable for work queued directly into the outbox
                        # without a matching ledger row; keep it append-once.
                        self.store.append_event(
                            event_id, item["device_id"], item["kind"], now_iso(), item["payload"]
                        )
                    self._apply_event(
                        {"event_id": event_id, "device_id": item["device_id"], "kind": item["kind"],
                         "payload": item["payload"], "ts": now_iso()}
                    )
                    self.store.mark_applied(event_id, now_iso())
                    applied += 1
                self.store.mark_outbox(event_id, "done", "", now_iso())
            except Exception as exc:  # fail-closed: leave pending for next attempt
                failed += 1
                self.store.mark_outbox(event_id, "pending", str(exc), now_iso())
        self.store.commit()
        return {"applied": applied, "skipped": skipped, "failed": failed}

    # ------------------------------------------------------------ projection

    def _apply_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        kind = event["kind"]
        payload = event["payload"] or {}
        device_id = event["device_id"]
        object_key = payload.get("object_key")
        if not object_key:
            if kind in FILE_KINDS:
                # A file-state event with no target is not "applied" - it is
                # malformed. Fail closed so it stays pending instead of being
                # counted as success and quietly dropped.
                raise ValueError("event kind %r requires a non-empty 'object_key'" % kind)
            return None

        existing = self.store.get_index(object_key, device_id)
        version = (existing[0]["version"] + 1) if existing else 1

        if kind in ("file.upsert", "file.write", "file.update"):
            state = {"status": "present", "checksum": payload.get("checksum", ""), "size": payload.get("size")}
        elif kind in ("file.delete", "file.remove"):
            state = {"status": "deleted"}
        elif kind == "file.move":
            state = {"status": "moved", "to": payload.get("to", "")}
        else:
            state = payload.get("state", {"status": kind})

        state["last_event"] = event["event_id"]
        state["updated_at"] = event.get("ts", now_iso())
        self.store.put_index(object_key, device_id, state, version, now_iso())
        return {"object_key": object_key, "state": state, "version": version}

    def apply_all(self) -> int:
        count = 0
        for event in self.store.all_events():
            if self.store.already_applied(event["event_id"]):
                continue
            try:
                self._apply_event(event)
            except Exception:
                # fail-closed: a malformed event is not applied and not marked
                # applied, so it can never be reported as a success.
                continue
            self.store.mark_applied(event["event_id"], now_iso())
            count += 1
        self.store.commit()
        return count

    def rebuild_shared_index(self) -> Dict[str, Any]:
        """Rebuild the projection from the event log. Last-good on failure."""
        last_good = self.store.snapshot_index()
        try:
            self.store.conn.execute("DELETE FROM applied")
            rows: Dict[tuple, Dict[str, Any]] = {}
            for event in self.store.all_events():
                object_key = (event["payload"] or {}).get("object_key")
                if not object_key:
                    if event["kind"] in FILE_KINDS:
                        raise ValueError(
                            "event kind %r requires a non-empty 'object_key'" % event["kind"]
                        )
                    continue
                key = (object_key, event["device_id"])
                row = rows.get(key, {"object_key": object_key, "device_id": event["device_id"],
                                     "state": {}, "version": 0, "updated_at": event["ts"]})
                kind = event["kind"]
                payload = event["payload"] or {}
                if kind in ("file.upsert", "file.write", "file.update"):
                    row["state"] = {"status": "present", "checksum": payload.get("checksum", ""),
                                    "size": payload.get("size")}
                elif kind in ("file.delete", "file.remove"):
                    row["state"] = {"status": "deleted"}
                elif kind == "file.move":
                    row["state"] = {"status": "moved", "to": payload.get("to", "")}
                else:
                    row["state"] = payload.get("state", {"status": kind})
                row["state"]["last_event"] = event["event_id"]
                row["state"]["updated_at"] = event["ts"]
                row["version"] += 1
                row["updated_at"] = event["ts"]
                rows[key] = row

            self.store.replace_index(list(rows.values()))
            for event in self.store.all_events():
                self.store.mark_applied(event["event_id"], now_iso())
            self.store.set_checkpoint("last_good_rebuild", now_iso())
            self.store.commit()
            return {"rebuilt": len(rows), "last_good_used": False}
        except Exception as exc:
            # last-good behaviour: restore the previous known-good index
            self.store.conn.execute("DELETE FROM shared_index")
            for row in last_good:
                self.store.conn.execute(
                    "INSERT INTO shared_index (object_key, device_id, state, version, updated_at) VALUES (?,?,?,?,?)",
                    (row["object_key"], row["device_id"],
                     json.dumps(row["state"], ensure_ascii=False, sort_keys=True),
                     row["version"], row["updated_at"]),
                )
            self.store.commit()
            return {"rebuilt": len(last_good), "last_good_used": True, "error": str(exc)}

    # ----------------------------------------------------------------- query

    def query(self, object_key: Optional[str] = None, device_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if object_key:
            return self.store.get_index(object_key, device_id)
        return self.store.all_index(device_id)

    def status(self) -> Dict[str, Any]:
        pending = self.store.pending_outbox()
        return {
            "device_id": self.device_id,
            "device_role": self.device_role,
            "devices": self.store.list_devices(),
            "event_count": len(self.store.all_events()),
            "max_seq": self.store.max_seq(),
            "pending_outbox": len(pending),
            "index_rows": len(self.store.all_index()),
            "open_tasks": self.open_tasks(),
            "last_good_rebuild": self.store.get_checkpoint("last_good_rebuild"),
        }

    def offline_recovery(self) -> Dict[str, Any]:
        """The one call you make after being offline for a while."""
        drained = self.drain_outbox()
        rebuilt = self.rebuild_shared_index()
        return {"drained": drained, "rebuild": rebuilt, "converged": drained["failed"] == 0}
