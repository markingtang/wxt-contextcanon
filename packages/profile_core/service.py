"""Business rules for Profile Core.

Everything an agent is allowed to do to a profile goes through this module, so
that provenance, revision chains and audit events can never be skipped.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from functools import wraps
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .model import (
    CONFLICT_POLICIES,
    Fact,
    Provenance,
    validate_fact_input, normalize_timestamp, validate_identity, validate_score,
)
from .store import ProfileStore

ACTIVE = "active"
SUPERSEDED = "superseded"
REJECTED = "rejected"
EXPIRED = "expired"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_fact_id(subject: str, key: str, value: Any, nonce: str = "") -> str:
    """Deterministic id so demo seeds and benchmarks are reproducible."""
    raw = "%s|%s|%s|%s" % (subject, key, repr(value), nonce)
    return "f_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def unique_nonce() -> str:
    """A nonce with enough entropy that two writes never collide.

    The old default reused the second-granular timestamp, so correcting a fact
    A -> B -> A inside one second produced a duplicate ``fact_id`` and a raw
    ``sqlite3.IntegrityError``. Callers that need reproducibility (demo seeds,
    the benchmark) pass an explicit nonce; everyone else gets a fresh one.
    """
    return uuid.uuid4().hex


def atomic_write(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        self.store.conn.execute("BEGIN IMMEDIATE")
        try:
            result = method(self, *args, **kwargs)
            self.store.conn.commit()
            return result
        except BaseException:
            self.store.conn.rollback()
            raise
    return wrapped


class ProfileService:
    def __init__(self, store: ProfileStore, actor: str = "system"):
        self.store = store
        self.actor = actor

    # ------------------------------------------------------------------ write

    @atomic_write
    def upsert_fact(
        self,
        subject: str,
        key: str,
        value: Any,
        sensitivity: str = "personal",
        durability: str = "durable",
        certainty: float = 1.0,
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        provenance: Optional[Dict[str, Any]] = None,
        on_conflict: str = "supersede",
        actor: Optional[str] = None,
        nonce: str = "",
        fact_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create or replace a fact.

        on_conflict controls what happens when an *active* fact already exists
        for (subject, key) with a different value:
            supersede - old fact becomes 'superseded', new fact becomes active
            reject    - incoming claim is stored with status 'rejected'
            keep      - existing active fact wins, nothing is written
        """
        validate_identity(subject, key)
        validate_fact_input(value, sensitivity, durability)
        validate_score(certainty)
        try:
            valid_from = normalize_timestamp(valid_from) if valid_from is not None else None
        except ValueError:
            raise ValueError(
                "valid_from must be an ISO timestamp with timezone, "
                "e.g. 2026-10-13T12:00:00Z"
            ) from None
        try:
            valid_until = normalize_timestamp(valid_until) if valid_until is not None else None
        except ValueError:
            raise ValueError(
                "valid_until must be an ISO timestamp with timezone, "
                "e.g. 2026-10-13T12:00:00Z"
            ) from None
        if on_conflict not in CONFLICT_POLICIES:
            raise ValueError("on_conflict must be one of %s" % (list(CONFLICT_POLICIES),))

        actor = actor or self.actor
        at = normalize_timestamp(now_iso())
        if valid_until and valid_from and valid_until <= valid_from:
            raise ValueError("valid_until must be after valid_from")
        if valid_until and not valid_from and valid_until <= at:
            raise ValueError(
                "valid_until is already in the past; without a valid_from, only a "
                "future valid_until is accepted. To record a fact that has already "
                "ended, either pass valid_from before valid_until (a back-dated "
                "window for as_of queries) or omit valid_until and note the end "
                "in provenance"
            )
        existing = self.store.current_fact(subject, key, at)
        prov = Provenance.from_dict(provenance)
        validate_score(prov.confidence)

        if (existing is not None and _same_value(existing["value"], value)
                and existing["sensitivity"] == sensitivity and existing["durability"] == durability
                and existing["certainty"] == certainty
                and (valid_from is None or normalize_timestamp(existing["valid_from"]) == valid_from)
                and (normalize_timestamp(existing["valid_until"]) if existing["valid_until"] else None) == valid_until):
            # Idempotent re-statement: refresh provenance, do not create noise.
            self.store.update_fact_fields(
                existing["fact_id"], provenance=prov.to_dict(), updated_at=at
            )
            self.store.upsert_source(prov.source, prov.source, prov.confidence, prov.method)
            self.store.append_event(
                existing["fact_id"], subject, "fact.reasserted", actor, at,
                {"key": key, "value": value, "previous_provenance": existing["provenance"],
                 "provenance": prov.to_dict()},
            )
            self.store.commit()
            return {"action": "unchanged", "fact": self.store.get_fact(existing["fact_id"])}

        if existing is not None and on_conflict == "keep":
            self.store.append_event(
                existing["fact_id"], subject, "fact.conflict_kept", actor, at,
                {"key": key, "incoming_value": value},
            )
            self.store.commit()
            return {"action": "kept", "fact": existing}

        is_conflict = existing is not None
        status = ACTIVE
        supersedes = None
        conflicts_with = None

        if is_conflict and on_conflict == "reject":
            status = REJECTED
            conflicts_with = existing["fact_id"]
        elif is_conflict:
            supersedes = existing["fact_id"]

        prior_revision = self.store.conn.execute(
            "SELECT COALESCE(MAX(revision), 0) FROM facts WHERE subject = ? AND key = ?",
            (subject, key),
        ).fetchone()[0]
        new_id = fact_id or make_fact_id(subject, key, value, nonce or unique_nonce())

        fact = Fact(
            fact_id=new_id,
            subject=subject,
            key=key,
            value=value,
            status=status,
            sensitivity=sensitivity,
            durability=durability,
            certainty=certainty,
            valid_from=valid_from or at,
            valid_until=valid_until,
            provenance=prov,
            revision=prior_revision + 1,
            supersedes=supersedes,
            conflicts_with=conflicts_with,
            created_at=at,
            updated_at=at,
        )
        self.store.insert_fact(fact.to_dict())
        self.store.upsert_source(prov.source, prov.source, prov.confidence, prov.method)

        if status == REJECTED:
            self.store.append_event(
                new_id, subject, "fact.rejected", actor, at,
                {"key": key, "value": value, "conflicts_with": conflicts_with,
                 "reason": "conflict policy = reject"},
            )
        else:
            self.store.append_event(
                new_id, subject, "fact.created", actor, at,
                {"key": key, "value": value, "revision": fact.revision},
            )

        if supersedes:
            self.store.set_status(supersedes, SUPERSEDED)
            self.store.update_fact_fields(supersedes, superseded_by=new_id, updated_at=at)
            self.store.append_event(
                supersedes, subject, "fact.superseded", actor, at,
                {"by": new_id, "key": key, "prior_value": existing["value"]},
            )

        self.store.commit()
        return {
            "action": "rejected" if status == REJECTED else ("superseded" if supersedes else "created"),
            "fact": self.store.get_fact(new_id),
            "supersedes": supersedes,
            "conflicts_with": conflicts_with,
        }

    def supersede_fact(
        self,
        fact_id: str,
        value: Any,
        provenance: Optional[Dict[str, Any]] = None,
        actor: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Explicitly replace a known fact id (used when the caller knows better)."""
        old = self.store.get_fact(fact_id)
        if old is None:
            raise KeyError("unknown fact_id: %s" % fact_id)
        return self.upsert_fact(
            subject=old["subject"],
            key=old["key"],
            value=value,
            sensitivity=kwargs.get("sensitivity", old["sensitivity"]),
            durability=kwargs.get("durability", old["durability"]),
            certainty=kwargs.get("certainty", old["certainty"]),
            valid_from=kwargs.get("valid_from"),
            valid_until=kwargs.get("valid_until"),
            provenance=provenance or old.get("provenance"),
            on_conflict="supersede",
            actor=actor or self.actor,
        )

    @atomic_write
    def reject_conflict(
        self, fact_id: str, reason: str = "contradicted by trusted source", actor: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark an existing fact as rejected while keeping it auditable."""
        fact = self.store.get_fact(fact_id)
        if fact is None:
            raise KeyError("unknown fact_id: %s" % fact_id)
        at = now_iso()
        self.store.set_status(fact_id, REJECTED)
        self.store.update_fact_fields(fact_id, updated_at=at)
        self.store.append_event(
            fact_id, fact["subject"], "fact.rejected", actor or self.actor, at, {"reason": reason}
        )
        self.store.commit()
        return {"action": "rejected", "fact": self.store.get_fact(fact_id), "reason": reason}

    @atomic_write
    def expire_due_facts(self, now: Optional[str] = None, actor: Optional[str] = None) -> List[Dict[str, Any]]:
        """Move facts whose valid_until has passed to 'expired' (never delete)."""
        now = normalize_timestamp(now or now_iso())
        expired: List[Dict[str, Any]] = []
        for fact in self.store.all_facts():
            if fact["status"] != ACTIVE:
                continue
            if fact.get("valid_until") and normalize_timestamp(fact["valid_until"]) <= now:
                at = now
                self.store.set_status(fact["fact_id"], EXPIRED)
                self.store.update_fact_fields(fact["fact_id"], updated_at=at)
                self.store.append_event(
                    fact["fact_id"], fact["subject"], "fact.expired", actor or self.actor, at,
                    {"valid_until": fact["valid_until"]},
                )
                expired.append(self.store.get_fact(fact["fact_id"]))
        if expired:
            self.store.commit()
        return expired

    # ------------------------------------------------------------------- read

    def get_fact(self, subject: str, key: str, include_inactive: bool = False) -> Optional[Dict[str, Any]]:
        """The fact that is true for ``key`` right now.

        "Now" is resolved with the same validity-window rule as ``as_of``: a
        fact whose ``valid_from`` is still in the future is not current, and a
        value that a future revision will eventually supersede stays current
        until that revision actually takes effect.
        """
        fact = self.store.current_fact(subject, key, now_iso())
        if fact or not include_inactive:
            return fact
        candidates = [f for f in self.store.list_subject(subject, include_inactive=True) if f["key"] == key]
        return candidates[0] if candidates else None

    def list_facts(
        self, subject: str, include_inactive: bool = False, sensitivity_max: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if include_inactive:
            facts = self.store.list_subject(subject, include_inactive=True)
        else:
            facts = self.store.facts_effective_at(subject, now_iso())
        if sensitivity_max:
            facts = [f for f in facts if _sensitivity_rank(f["sensitivity"]) <= _sensitivity_rank(sensitivity_max)]
        return facts

    def search(self, subject: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Substring search over the facts that are current right now."""
        if not isinstance(query, str) or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("query must be a string and limit must be between 1 and 1000")
        needle = query.lower()
        out: List[Dict[str, Any]] = []
        for fact in self.store.facts_effective_at(subject, now_iso()):
            haystack = (fact["key"] + "\x00"
                        + json.dumps(fact["value"], ensure_ascii=False, sort_keys=True, default=str)).lower()
            if needle in haystack:
                out.append(fact)
                if len(out) >= limit:
                    break
        return out

    def history(self, subject: str, key: str) -> List[Dict[str, Any]]:
        facts = [f for f in self.store.list_subject(subject, include_inactive=True) if f["key"] == key]
        return sorted(facts, key=lambda f: f["revision"])

    def audit(self, subject: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.store.events_for_subject(subject, limit)

    def fact_events(self, fact_id: str) -> List[Dict[str, Any]]:
        return self.store.events_for_fact(fact_id)

    def as_of(self, subject: str, timestamp: str, include_rejected: bool = False) -> List[Dict[str, Any]]:
        """Answer: what did we believe at time T?

        Uses valid_from / valid_until (not created_at), so back-dated and
        scheduled facts resolve correctly. This is the capability a plain
        Markdown note simply does not have.

        This shares one implementation with the "current" read: both call
        ``store.facts_effective_at`` with a different timestamp.
        """
        return self.store.facts_effective_at(subject, timestamp, include_rejected)

    def lifecycle_report(self, subject: str) -> Dict[str, Any]:
        facts = self.store.list_subject(subject, include_inactive=True)
        by_durability: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        by_sensitivity: Dict[str, int] = {}
        for fact in facts:
            by_durability[fact["durability"]] = by_durability.get(fact["durability"], 0) + 1
            by_status[fact["status"]] = by_status.get(fact["status"], 0) + 1
            by_sensitivity[fact["sensitivity"]] = by_sensitivity.get(fact["sensitivity"], 0) + 1
        return {
            "subject": subject,
            "total": len(facts),
            "by_status": by_status,
            "by_durability": by_durability,
            "by_sensitivity": by_sensitivity,
        }


def _value_kind(value: Any) -> str:
    """The JSON type of a value, with bool kept distinct from number."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _same_value(left: Any, right: Any) -> bool:
    """Type-aware equality.

    Comparing with ``str()`` made ``1`` vs ``"1"`` and ``True`` vs ``"True"``
    look identical, so a real type change was silently swallowed as
    ``unchanged``. Only values of the same JSON kind are ever equal.
    """
    if _value_kind(left) != _value_kind(right):
        return False
    if isinstance(left, (list, dict)):
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    return left == right


def _sensitivity_rank(level: str) -> int:
    order = {"public": 0, "personal": 1, "sensitive": 2, "restricted": 3}
    return order.get(level, 1)
