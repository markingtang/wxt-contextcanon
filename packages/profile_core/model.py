"""Core data model for WXT ContextCanon Profile Core.

A fact is not a string in a text file. It is a versioned, sourced,
time-bounded claim about a subject, with an explicit lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from typing import Any, Dict, Optional

SENSITIVITY_LEVELS = ("public", "personal", "sensitive", "restricted")
DURABILITY_KINDS = ("durable", "temporary", "scheduled")
FACT_STATUSES = ("active", "superseded", "rejected", "expired")

# How a new fact relates to an existing active fact on the same (subject, key).
CONFLICT_POLICIES = ("supersede", "reject", "keep")


@dataclass
class Provenance:
    """Where a fact came from. A fact without provenance is not trustworthy."""

    source: str = "unknown"          # user-stated | observed | inferred | document | demo-seed
    ref: str = ""                    # free-form pointer, never required to be personal data
    method: str = ""                 # e.g. "explicit-answer", "derived", "seed"
    observed_at: str = ""
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ref": self.ref,
            "method": self.method,
            "observed_at": self.observed_at,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, raw: Optional[Dict[str, Any]]) -> "Provenance":
        raw = raw or {}
        return cls(
            source=str(raw.get("source", "unknown")),
            ref=str(raw.get("ref", "")),
            method=str(raw.get("method", "")),
            observed_at=str(raw.get("observed_at", "")),
            confidence=float(raw.get("confidence", 1.0)),
        )


@dataclass
class Fact:
    """A single versioned claim."""

    fact_id: str
    subject: str
    key: str
    value: Any
    status: str = "active"
    sensitivity: str = "personal"
    durability: str = "durable"
    certainty: float = 1.0
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    provenance: Provenance = field(default_factory=Provenance)
    revision: int = 1
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    conflicts_with: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self, include_internals: bool = True) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "fact_id": self.fact_id,
            "subject": self.subject,
            "key": self.key,
            "value": self.value,
            "status": self.status,
            "sensitivity": self.sensitivity,
            "durability": self.durability,
            "certainty": self.certainty,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "revision": self.revision,
        }
        if include_internals:
            data.update(
                {
                    "provenance": self.provenance.to_dict(),
                    "supersedes": self.supersedes,
                    "superseded_by": self.superseded_by,
                    "conflicts_with": self.conflicts_with,
                    "created_at": self.created_at,
                    "updated_at": self.updated_at,
                }
            )
        return data


def validate_fact_input(value: Any, sensitivity: str, durability: str) -> None:
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("value must be finite JSON data") from None
    if value is None:
        raise ValueError("value must not be null (use an empty string instead)")
    if sensitivity not in SENSITIVITY_LEVELS:
        raise ValueError(
            "sensitivity must be one of %s, got %r" % (list(SENSITIVITY_LEVELS), sensitivity)
        )
    if durability not in DURABILITY_KINDS:
        raise ValueError(
            "durability must be one of %s, got %r" % (list(DURABILITY_KINDS), durability)
        )


def normalize_timestamp(value: str) -> str:
    """Canonical UTC seconds make SQLite text comparisons timezone-correct."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be an ISO string with timezone")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, OverflowError):
        raise ValueError("timestamp must be an ISO string with timezone") from None


def validate_identity(subject: str, key: str) -> None:
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject must be a non-empty string")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("key must be a non-empty string")


def validate_score(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("confidence and certainty must be finite numbers between 0 and 1")
