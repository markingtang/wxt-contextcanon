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


def validate_event(kind, payload):
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("event kind must be a non-empty string")
    if not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    if kind.startswith("file.") and kind not in FILE_KINDS:
        raise ValueError("unsupported file event kind")
    if kind in FILE_KINDS:
        if not isinstance(payload.get("object_key"), str) or not payload["object_key"].strip():
            raise ValueError("file event requires a non-empty object_key")
        if kind == "file.move" and (not isinstance(payload.get("to"), str) or not payload["to"].strip()):
            raise ValueError("file.move requires a non-empty to destination")
    if "state" in payload and not isinstance(payload["state"], dict):
        raise ValueError("event state must be an object")


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
        payload = {} if payload is None else payload
        validate_event(kind, payload)
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
        applied = skipped = failed = 0
        for item in self.store.pending_outbox(limit):
            event_id = item["outbox_id"]
            try:
                validate_event(item["kind"], item["payload"])
                # append_event verifies identity even on duplicate delivery.
                self.store.append_event(event_id, item["device_id"], item["kind"],
                                        item["created_at"], item["payload"])
                was_applied = self.store.already_applied(event_id)
                self.apply_all()
                if not self.store.already_applied(event_id):
                    raise ValueError("event projection failed")
                if was_applied:
                    skipped += 1
                else:
                    applied += 1
                self.store.mark_outbox(event_id, "done", "", now_iso())
            except Exception:
                failed += 1
                self.store.mark_outbox(event_id, "pending", "event validation or projection failed", now_iso())
        return {"applied": applied, "skipped": skipped, "failed": failed}

    # ------------------------------------------------------------ projection

    def _apply_event(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        kind = event["kind"]
        payload = event["payload"]
        validate_event(kind, payload)
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
            # Carry the authoring metadata the event accepted (file version tag,
            # who updated it, the authoring date) into the projection. These are
            # payload fields and must not be confused with - or overwrite - the
            # index's own numeric event counter (`version` column). Events that
            # never carried these fields project exactly as before.
            for meta_key in ("version", "updated_by", "date"):
                if payload.get(meta_key) is not None:
                    state[meta_key] = payload[meta_key]
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
        # Keep index updates and idempotency markers in one writer transaction.
        with self.store.conn:
            self.store.conn.execute("BEGIN IMMEDIATE")
            count = 0
            for event in self.store.all_events():
                if self.store.already_applied(event["event_id"]):
                    continue
                self._apply_event(event)
                self.store.mark_applied(event["event_id"], now_iso())
                count += 1
        return count

    def rebuild_shared_index(self) -> Dict[str, Any]:
        """Atomically rebuild index AND markers; rollback both on any failure."""
        try:
            with self.store.conn:
                self.store.conn.execute("BEGIN IMMEDIATE")
                self.store.conn.execute("DELETE FROM applied")
                self.store.conn.execute("DELETE FROM shared_index")
                for event in self.store.all_events():
                    self._apply_event(event)
                    self.store.mark_applied(event["event_id"], now_iso())
                self.store.conn.execute(
                    "INSERT INTO checkpoints(name,value) VALUES (?,?) "
                    "ON CONFLICT(name) DO UPDATE SET value=excluded.value",
                    ("last_good_rebuild", now_iso()),
                )
                count = len(self.store.all_index())
            return {"rebuilt": count, "last_good_used": False}
        except Exception:
            return {"rebuilt": len(self.store.all_index()), "last_good_used": True,
                    "error": "event validation or projection failed; last-good index retained"}

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
        return {"drained": drained, "rebuild": rebuilt, "converged": (drained["failed"] == 0 and not rebuilt["last_good_used"]
                                                                  and not self.store.pending_outbox())}
