"""Deterministic, synthetic benchmark runner.

Rules:
  * synthetic fixtures only - never a real profile
  * deterministic - no sampling, no randomness, no timestamps in expectations
  * no LLM judge by default - every expectation is an exact value
  * a Markdown baseline runs the same cases, honestly

The point is not "WXT ContextCanon beats Markdown at remembering". On simple recall it does
not - a text file is hard to beat. The point is to show exactly where the two
diverge: time, conflict, provenance, lifecycle, and offline convergence.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
for _p in (os.path.join(_ROOT, "packages"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from profile_core import ProfileService, ProfileStore, now_iso  # noqa: E402
from registry_core import RegistryService, RegistryStore  # noqa: E402

UNSUPPORTED = "unsupported:markdown-baseline"

SUBJECT = "bench:synthetic"


def _iso(offset_days: float) -> str:
    stamp = datetime.now(timezone.utc) + timedelta(days=offset_days)
    return stamp.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _norm(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


# --------------------------------------------------------------------- WXT ContextCanon


class ContextCanonSystem:
    def __init__(self, workdir: str):
        self.dir = workdir
        self.profile = ProfileService(
            ProfileStore(os.path.join(workdir, "profile.db")), actor="bench"
        )
        self.registry = RegistryService(
            RegistryStore(os.path.join(workdir, "registry.db")),
            device_id="bench-device-a",
            device_role="primary",
        )
        self.registry.ensure_device()
        self.seed()

    def seed(self) -> None:
        fixture_path = os.path.join(_ROOT, "benchmark", "fixtures", "synthetic-persona.json")
        with open(fixture_path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        for item in fixture["facts"]:
            self.profile.upsert_fact(
                subject=SUBJECT,
                key=item["key"],
                value=item["value"],
                sensitivity=item.get("sensitivity", "personal"),
                durability=item.get("durability", "durable"),
                valid_from=item.get("valid_from")
                or _iso(item.get("valid_from_offset_days", -120 if item.get("durability", "durable") == "durable" else 0)),
                valid_until=item.get("valid_until") or _iso(item["valid_until_offset_days"])
                if item.get("valid_until_offset_days") is not None else None,
                provenance=item.get("provenance"),
                actor="bench-seed",
                nonce="seed:" + item["key"],
            )
        for op in fixture.get("scripted", []):
            if op["op"] == "supersede":
                self.profile.upsert_fact(
                    subject=SUBJECT, key=op["key"], value=op["value"],
                    provenance=op.get("provenance"), on_conflict="supersede",
                    actor="bench-seed", nonce="scripted:" + op["key"],
                )
            elif op["op"] == "reject":
                self.profile.upsert_fact(
                    subject=SUBJECT, key=op["key"], value=op["value"],
                    provenance=op.get("provenance"), on_conflict="reject",
                    actor="bench-seed", nonce="scripted-reject:" + op["key"],
                )

    # cases
    def recall(self) -> Any:
        fact = self.profile.get_fact(SUBJECT, "display_name")
        return fact["value"] if fact else None

    def update(self) -> Any:
        self.profile.upsert_fact(SUBJECT, "communication.style", "paragraphs", actor="bench")
        fact = self.profile.get_fact(SUBJECT, "communication.style")
        return fact["value"] if fact else None

    def temporal(self) -> Any:
        facts = self.profile.as_of(SUBJECT, _iso(-90))
        for fact in facts:
            if fact["key"] == "tooling.editor":
                return fact["value"]
        return None

    def history(self) -> Any:
        return [f["value"] for f in self.profile.history(SUBJECT, "tooling.editor")]

    def conflict(self) -> Any:
        active = self.profile.get_fact(SUBJECT, "timezone")
        all_facts = self.profile.store.all_facts()
        rejected = sum(1 for f in all_facts if f["subject"] == SUBJECT and f["status"] == "rejected")
        return {"timezone": active["value"] if active else None, "rejected": rejected}

    def provenance(self) -> Any:
        return [
            f["value"]
            for f in self.profile.list_facts(SUBJECT, include_inactive=True)
            if (f.get("provenance") or {}).get("source") == "inferred"
        ]

    def lifecycle(self) -> Any:
        self.profile.upsert_fact(
            SUBJECT, "travel.season_pass", "winter pass",
            durability="temporary", valid_from=_iso(-60), valid_until=_iso(-1),
            actor="bench",
        )
        self.profile.expire_due_facts()
        fact = self.profile.get_fact(SUBJECT, "travel.season_pass", include_inactive=True)
        return fact["status"] if fact else None

    def convergence(self) -> Any:
        # Two independent service objects over one local store: a value written
        # through the first must be visible to the second. This is shared-store
        # consistency on one machine - it is NOT a cross-machine sync claim.
        agent_b = ProfileService(ProfileStore(os.path.join(self.dir, "profile.db")), actor="agent-b")
        self.profile.upsert_fact(SUBJECT, "agent.probe", "visible", actor="agent-a",
                                 provenance={"source": "agent-stated"})
        seen_by_b = agent_b.get_fact(SUBJECT, "agent.probe")
        if not seen_by_b or seen_by_b["value"] != "visible":
            return "not-shared"
        first = self.profile.get_fact(SUBJECT, "display_name")
        other = agent_b.get_fact(SUBJECT, "display_name")
        if not first or not other:
            return None
        return first["value"] if first["value"] == other["value"] else "diverged"

    def registry_offline(self) -> Any:
        second = "bench-device-b"
        for key in ("bench/notes/x.md", "bench/notes/y.md"):
            self.registry.append_event("file.upsert", {"object_key": key, "checksum": "b1"})
        self.registry.apply_all()
        for index, key in enumerate(("bench/notes/y.md", "bench/notes/z.md")):
            self.registry.store.enqueue(
                "bench-ob-%d" % index, second, "file.upsert",
                {"object_key": key, "checksum": "b2"}, _iso(-1),
            )
        self.registry.drain_outbox()
        # deliberate duplicate delivery
        self.registry.store.mark_outbox("bench-ob-0", "pending", "", _iso(0))
        self.registry.drain_outbox()
        before = len(self.registry.query())
        self.registry.rebuild_shared_index()
        after = len(self.registry.query())
        return before == after and self.registry.status()["pending_outbox"] == 0


# ----------------------------------------------------------------- Markdown


class MarkdownBaseline:
    """An honest baseline: one plain markdown file, last write wins."""

    def __init__(self, workdir: str):
        self.path = os.path.join(workdir, "MEMORY.md")
        self.lines: List[str] = []
        self.seed()

    def seed(self) -> None:
        fixture_path = os.path.join(_ROOT, "benchmark", "fixtures", "synthetic-persona.json")
        with open(fixture_path, "r", encoding="utf-8") as handle:
            fixture = json.load(handle)
        for item in fixture["facts"]:
            self.lines.append("- %s: %s" % (item["key"], item["value"]))
        for op in fixture.get("scripted", []):
            if op["op"] == "supersede":
                self._write(op["key"], op["value"])
            elif op["op"] == "reject":
                # No conflict model exists; the last writer simply wins.
                self._write(op["key"], op["value"])
        self._flush()

    def _write(self, key: str, value: Any) -> None:
        pattern = re.compile(r"^- %s: " % re.escape(key))
        for index, line in enumerate(self.lines):
            if pattern.match(line):
                self.lines[index] = "- %s: %s" % (key, value)
                return
        self.lines.append("- %s: %s" % (key, value))

    def _get(self, key: str) -> Optional[str]:
        pattern = re.compile(r"^- %s: (.*)$" % re.escape(key))
        for line in self.lines:
            match = pattern.match(line)
            if match:
                return match.group(1)
        return None

    def _flush(self) -> None:
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Memory (Markdown baseline)\n\n")
            handle.write("\n".join(self.lines) + "\n")

    def recall(self) -> Any:
        return self._get("display_name")

    def update(self) -> Any:
        self._write("communication.style", "paragraphs")
        self._flush()
        return self._get("communication.style")

    def temporal(self) -> Any:
        return UNSUPPORTED

    def history(self) -> Any:
        return []

    def conflict(self) -> Any:
        return {"timezone": self._get("timezone"), "rejected": 0}

    def provenance(self) -> Any:
        return []

    def lifecycle(self) -> Any:
        return UNSUPPORTED

    def convergence(self) -> Any:
        with open(self.path, "r", encoding="utf-8") as handle:
            text = handle.read()
        match = re.search(r"^- display_name: (.*)$", text, re.M)
        return match.group(1) if match else None

    def registry_offline(self) -> Any:
        return False


# --------------------------------------------------------------------- run

HANDLERS = {
    "recall": "recall",
    "update": "update",
    "temporal": "temporal",
    "history": "history",
    "conflict": "conflict",
    "provenance": "provenance",
    "lifecycle": "lifecycle",
    "convergence": "convergence",
    "registry": "registry_offline",
}


def load_cases(root: str = _ROOT) -> List[Dict[str, Any]]:
    with open(os.path.join(root, "benchmark", "cases", "cases.json"), "r", encoding="utf-8") as handle:
        return json.load(handle)["cases"]


def list_cases(root: str = _ROOT) -> Dict[str, Any]:
    cases = load_cases(root)
    return {"count": len(cases), "cases": [{"id": c["id"], "kind": c["kind"],
                                            "capability": c["capability"], "smoke": c["smoke"]}
                                           for c in cases]}


def run(root: str = _ROOT, case_filter: Optional[str] = None,
        out_path: Optional[str] = None) -> Dict[str, Any]:
    cases = load_cases(root)
    if case_filter == "smoke":
        cases = [c for c in cases if c.get("smoke")]

    workdir = tempfile.mkdtemp(prefix="contextcanon-bench-")
    try:
        os.makedirs(os.path.join(workdir, "contextcanon"), exist_ok=True)
        contextcanon = ContextCanonSystem(os.path.join(workdir, "contextcanon"))
        md_dir = os.path.join(workdir, "markdown")
        os.makedirs(md_dir, exist_ok=True)
        md = MarkdownBaseline(md_dir)

        results = []
        for case in cases:
            method = HANDLERS[case["kind"]]
            contextcanon_answer = getattr(contextcanon, method)()
            md_answer = getattr(md, method)()
            expected = case["expected"]
            results.append({
                "id": case["id"],
                "kind": case["kind"],
                "capability": case["capability"],
                "question": case["question"],
                "expected": expected,
                "contextcanon": contextcanon_answer,
                "markdown": md_answer,
                "contextcanon_pass": _norm(contextcanon_answer) == _norm(expected),
                "markdown_pass": _norm(md_answer) == _norm(expected),
            })

        contextcanon_score = sum(1 for r in results if r["contextcanon_pass"])
        md_score = sum(1 for r in results if r["markdown_pass"])
        report = {
            "synthetic": True,
            "llm_judge": False,
            "cases": len(results),
            "contextcanon_score": contextcanon_score,
            "markdown_score": md_score,
            "results": results,
        }
        markdown = render_markdown(report)
        report["report_markdown"] = markdown
        if out_path:
            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(markdown)
            report["report_path"] = os.path.abspath(out_path)
        return report
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def render_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# WXT ContextCanon benchmark report (synthetic)",
        "",
        "_All fixtures are fictional. No LLM judge. Deterministic exact-match scoring._",
        "",
        "**WXT ContextCanon: %d/%d**   |   **Markdown baseline: %d/%d**"
        % (report["contextcanon_score"], report["cases"], report["markdown_score"], report["cases"]),
        "",
        "| Case | Capability | WXT ContextCanon | Markdown |",
        "|---|---|---|---|",
    ]
    for row in report["results"]:
        lines.append(
            "| %s | %s | %s | %s |"
            % (row["id"], row["capability"],
               "PASS" if row["contextcanon_pass"] else "FAIL",
               "PASS" if row["markdown_pass"] else "FAIL")
        )
    lines += [
        "",
        "## Why not just Markdown?",
        "",
        "Markdown wins or ties on plain recall and write-then-read. That is real,",
        "and pretending otherwise would be dishonest. WXT ContextCanon only pulls ahead where the",
        "shipped last-write-wins Markdown model has nothing to say: time, conflict,",
        "provenance, lifecycle, and a rebuildable projection.",
        "",
        "## Where the two diverge",
        "",
    ]
    for row in report["results"]:
        if row["contextcanon_pass"] and not row["markdown_pass"]:
            lines.append(
                "- **%s** (%s): WXT ContextCanon `%s` vs Markdown `%s`"
                % (row["id"], row["capability"], _short(row["contextcanon"]), _short(row["markdown"]))
            )
    lines.append("")
    return "\n".join(lines)


def _short(value: Any) -> str:
    text = _norm(value)
    return text if len(text) <= 60 else text[:57] + "..."


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "list":
        print(json.dumps(list_cases(), indent=2))
    else:
        out = sys.argv[2] if len(sys.argv) > 2 else None
        result = run(case_filter="smoke" if mode == "smoke" else None, out_path=out)
        print(json.dumps({k: v for k, v in result.items() if k != "report_markdown"}, indent=2, default=str))
