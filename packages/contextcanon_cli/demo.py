"""Demo persona seeding.

The persona is FICTIONAL. No real person, device, project, company, address or
identifier appears here. Everything is marked DEMO / SYNTHETIC.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from profile_core import now_iso

DEMO_SUBJECT = "demo:alex-chen"
PERSONA_RELPATH = os.path.join("examples", "demo-persona", "alex-chen.facts.json")


def _iso(offset_days: Optional[float] = None) -> Optional[str]:
    if offset_days is None:
        return None
    stamp = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_persona(path: Optional[str] = None, root: Optional[str] = None) -> Dict[str, Any]:
    candidates: List[str] = []
    if path:
        candidates.append(path)
    else:
        root = root or os.getcwd()
        candidates.append(os.path.join(root, PERSONA_RELPATH))
        candidates.append(os.path.join(root, "examples", "demo-persona", "alex-chen.facts.json"))
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidates.append(os.path.join(here, PERSONA_RELPATH))
    for candidate in candidates:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                return json.load(handle)
    raise FileNotFoundError(
        "demo persona not found; looked in: %s" % ", ".join(candidates)
    )


def seed(service, persona_path: Optional[str] = None, reset: bool = False) -> Dict[str, Any]:
    persona = load_persona(persona_path)
    subject = persona.get("subject", DEMO_SUBJECT)

    if reset:
        _reset(service, subject)

    created = 0
    for item in persona.get("facts", []):
        # Durable facts are back-dated by default so that `profile as-of` has
        # something meaningful to answer about the past.
        if not item.get("valid_from") and item.get("valid_from_offset_days") is None:
            if item.get("durability", "durable") == "durable":
                item = dict(item, valid_from_offset_days=-120)
        service.upsert_fact(
            subject=subject,
            key=item["key"],
            value=item["value"],
            sensitivity=item.get("sensitivity", "personal"),
            durability=item.get("durability", "durable"),
            certainty=float(item.get("certainty", 1.0)),
            valid_from=item.get("valid_from") or _iso(item.get("valid_from_offset_days")),
            valid_until=item.get("valid_until") or _iso(item.get("valid_until_offset_days")),
            provenance=item.get("provenance", {"source": "demo-seed"}),
            on_conflict=item.get("on_conflict", "supersede"),
            actor="demo-seed",
            nonce="seed:" + item["key"],
        )
        created += 1

    scripted: List[Dict[str, Any]] = []
    for op in persona.get("scripted", []):
        action = op.get("op")
        if action == "supersede":
            result = service.upsert_fact(
                subject=subject,
                key=op["key"],
                value=op["value"],
                sensitivity=op.get("sensitivity", "personal"),
                durability=op.get("durability", "durable"),
                provenance=op.get("provenance", {"source": "user-stated", "method": "correction"}),
                on_conflict="supersede",
                actor="demo-seed",
                nonce="scripted:" + op["key"],
            )
            scripted.append({"op": "supersede", "key": op["key"], "action": result["action"],
                             "supersedes": result.get("supersedes")})
        elif action == "reject":
            result = service.upsert_fact(
                subject=subject,
                key=op["key"],
                value=op["value"],
                sensitivity=op.get("sensitivity", "personal"),
                durability=op.get("durability", "durable"),
                provenance=op.get("provenance", {"source": "inferred", "confidence": 0.3}),
                on_conflict="reject",
                actor="demo-seed",
                nonce="scripted-reject:" + op["key"],
            )
            scripted.append({"op": "reject", "key": op["key"], "action": result["action"],
                             "conflicts_with": result.get("conflicts_with"),
                             "reason": op.get("reason", "")})
        elif action == "expire":
            # Seed with a validity window that is already in the past, then let
            # the lifecycle sweep mark it expired (never deleted).
            service.upsert_fact(
                subject=subject,
                key=op["key"],
                value=op["value"],
                sensitivity=op.get("sensitivity", "personal"),
                durability="temporary",
                valid_from=op.get("valid_from") or _iso(op.get("valid_from_offset_days", -30)),
                valid_until=op.get("valid_until") or _iso(op.get("valid_until_offset_days", -2)),
                provenance=op.get("provenance", {"source": "document", "method": "permit"}),
                actor="demo-seed",
                nonce="scripted-expire:" + op["key"],
            )
            expired = service.expire_due_facts(now_iso(), actor="demo-seed")
            scripted.append({"op": "expire", "key": op["key"],
                             "expired_count": len(expired)})
        else:
            raise ValueError("unknown scripted op: %s" % action)

    swept = service.expire_due_facts(now_iso(), actor="demo-seed")
    report = service.lifecycle_report(subject)
    return {
        "subject": subject,
        "synthetic": True,
        "seeded_facts": created,
        "scripted": scripted,
        "expired_by_sweep": [f["key"] for f in swept],
        "lifecycle": report,
    }


def _reset(service, subject: str) -> None:
    """Demo-only reset. Deletes rows for this subject so seeding is repeatable."""
    conn = service.store.conn
    conn.execute("DELETE FROM facts WHERE subject = ?", (subject,))
    conn.execute("DELETE FROM fact_events WHERE subject = ?", (subject,))
    conn.commit()
