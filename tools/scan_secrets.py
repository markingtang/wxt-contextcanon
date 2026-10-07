"""Secret and private-identifier scanner for the public repository.

Usage:
    python tools/scan_secrets.py                     # scan the working tree
    python tools/scan_secrets.py --history           # also scan all git history
    python tools/scan_secrets.py --extra-patterns ../private-patterns.json
    python tools/scan_secrets.py --json report.json

Every finding is classified:

    REAL_SECRET         - a credential that must never be published
    PRIVATE_IDENTIFIER  - a person, device, host, path or id from a private system
    SAFE_EXAMPLE        - a line carrying an explicit, narrow allow annotation
    FALSE_POSITIVE      - matched text that is not what the pattern looks for

The gate passes only when REAL_SECRET == 0 and PRIVATE_IDENTIFIER == 0.

How a line can be allowed
-------------------------
There is exactly **one** way to exempt a finding, and it names a single pattern:

    <your text>  WXT_SCAN_ALLOW:<pattern-id>

The marker must name the pattern it exempts. A stray word such as "e.g." or
"example" no longer disarms anything, and whole-file exemptions were removed
entirely - a file that talks about scanning is scanned like any other.

Why only generic patterns are committed: publishing a list of private
identifiers would leak them. Site-specific identifiers are supplied at scan
time with --extra-patterns from a file that lives OUTSIDE this repository.
See docs/SECRET_SCAN.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

# id, regex, default class
GENERIC_PATTERNS: List[Tuple[str, str, str]] = [
    ("private-key-block", r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----", "REAL_SECRET"),
    ("ssh-public-key", r"ssh-(?:rsa|ed25519) AAAA[0-9A-Za-z+/=]{20,}", "REAL_SECRET"),
    ("openai-style-key", r"\bsk-[A-Za-z0-9_-]{20,}", "REAL_SECRET"),
    ("anthropic-style-key", r"\bsk-ant-[A-Za-z0-9_-]{20,}", "REAL_SECRET"),
    ("aws-access-key", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", "REAL_SECRET"),
    ("github-token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})", "REAL_SECRET"),
    ("slack-token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}", "REAL_SECRET"),
    ("google-api-key", r"\bAIza[0-9A-Za-z_-]{35}\b", "REAL_SECRET"),
    ("bearer-token", r"(?i)\bbearer\s+[A-Za-z0-9._-]{24,}", "REAL_SECRET"),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", "REAL_SECRET"),
    ("credential-assignment",
     r"(?i)\b(?:token|password|passwd|secret|api[_-]?key|access[_-]?key|client[_-]?secret)"
     r"\s*[:=]\s*[\"']?[A-Za-z0-9._\-]{12,}[\"']?", "REAL_SECRET"),
    ("private-ipv4",
     r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
     r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b", "PRIVATE_IDENTIFIER"),
    ("cn-mobile-number", r"(?<!\d)1[3-9]\d{9}(?!\d)", "PRIVATE_IDENTIFIER"),
    ("email-address",
     r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net|invalid)\b|localhost\b)"
     r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "PRIVATE_IDENTIFIER"),
    ("mac-address", r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b", "PRIVATE_IDENTIFIER"),
    ("windows-user-path", r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[A-Za-z0-9._-]+", "PRIVATE_IDENTIFIER"),
    ("windows-absolute-path", r"(?<![\w/])[CDEF]:[\\/]{1,2}(?!\\)[A-Za-z0-9._-]+", "PRIVATE_IDENTIFIER"),
    ("unix-home-path", r"/home/[A-Za-z0-9._-]{2,}", "PRIVATE_IDENTIFIER"),
    ("unix-mac-home-path", r"/Users/[A-Za-z0-9._-]{2,}", "PRIVATE_IDENTIFIER"),
    ("google-sheet-id", r"(?i)docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]{20,}", "PRIVATE_IDENTIFIER"),
    ("unix-data-mount", r"(?<![\w])/data_[a-z0-9]{2,}", "PRIVATE_IDENTIFIER"),
]

ALLOW_PREFIX = "WXT_SCAN_ALLOW:"

SKIP_DIRS = {".git", "__pycache__", "data", ".venv", "venv", "node_modules", ".contextcanon-private-scan"}
SKIP_SUFFIXES = (".db", ".lock", ".pyc", ".pid", ".png", ".ico", ".woff", ".woff2", ".ttf")
MAX_FILE_BYTES = 2_000_000


def iter_files(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(SKIP_SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path


def load_extra_patterns(path: str) -> List[Tuple[str, str, str]]:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    out = []
    for item in raw.get("patterns", []):
        out.append((item["id"], item["regex"], item.get("class", "PRIVATE_IDENTIFIER")))
    return out


def classify(line: str, pattern_id: str, default_class: str) -> str:
    """Only an explicit ``WXT_SCAN_ALLOW:<pattern-id>`` marker can exempt a match."""
    if (ALLOW_PREFIX + pattern_id) in line:
        return "SAFE_EXAMPLE"
    return default_class


def _compile(patterns: List[Tuple[str, str, str]]):
    return [(pid, re.compile(regex), cls) for pid, regex, cls in patterns]


def _scan_lines(
    compiled, label: str, lines: List[str], findings: List[Dict[str, Any]]
) -> None:
    for lineno, line in enumerate(lines, start=1):
        for pid, regex, cls in compiled:
            if not regex.search(line):
                continue
            findings.append({
                "pattern": pid,
                "file": label,
                "line": lineno,
                "class": classify(line, pid, cls),
                "excerpt": line.strip()[:160],
            })


def _tally(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"REAL_SECRET": 0, "PRIVATE_IDENTIFIER": 0, "SAFE_EXAMPLE": 0, "FALSE_POSITIVE": 0}
    for finding in findings:
        counts[finding["class"]] = counts.get(finding["class"], 0) + 1
    return counts


def _passed(counts: Dict[str, int]) -> bool:
    return counts["REAL_SECRET"] == 0 and counts["PRIVATE_IDENTIFIER"] == 0


def scan(root: str, extra_patterns_path: str = "") -> Dict[str, Any]:
    patterns = list(GENERIC_PATTERNS)
    if extra_patterns_path:
        patterns += load_extra_patterns(extra_patterns_path)

    compiled = _compile(patterns)
    findings: List[Dict[str, Any]] = []
    files_scanned = 0

    for path in iter_files(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                lines = handle.read().splitlines()
        except OSError:
            continue
        files_scanned += 1
        _scan_lines(compiled, rel, lines, findings)

    counts = _tally(findings)
    return {
        "mode": "working-tree",
        "root": os.path.abspath(root),
        "files_scanned": files_scanned,
        "patterns_used": len(compiled),
        "extra_patterns": extra_patterns_path or "(none)",
        "counts": counts,
        "pass": _passed(counts),
        "findings": findings,
    }


# --------------------------------------------------------------- git history


def _git(root: str, *args: str, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=text)


def _history_blobs(root: str) -> List[Tuple[str, str]]:
    """Every text blob reachable from any ref, as (path, content)."""
    rev = _git(root, "rev-list", "--objects", "--all")
    if rev.returncode != 0:
        return []
    objects: List[Tuple[str, str]] = []
    seen = set()
    for line in (rev.stdout or "").splitlines():
        if not line.strip():
            continue
        sha, _, path = line.partition(" ")
        if sha in seen:
            continue
        seen.add(sha)
        objects.append((sha, path))
    if not objects:
        return []

    # One call to learn the type and size of every object.
    check_input = "\n".join(sha for sha, _ in objects) + "\n"
    checked = subprocess.run(
        ["git", "-C", root, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        input=check_input, capture_output=True, text=True,
    )
    blobs: List[Tuple[str, str, int]] = []
    info = {}
    for line in (checked.stdout or "").splitlines():
        parts = line.split(" ")
        if len(parts) != 3:
            continue
        info[parts[0]] = (parts[1], parts[2])
    for sha, path in objects:
        entry = info.get(sha)
        if not entry or entry[0] != "blob":
            continue
        try:
            size = int(entry[1])
        except ValueError:
            continue
        if size > MAX_FILE_BYTES:
            continue
        blobs.append((sha, path, size))

    if not blobs:
        return []

    # One call to read every blob's bytes.
    batch_input = ("\n".join(sha for sha, _, _ in blobs) + "\n").encode("utf-8")
    batch = subprocess.run(
        ["git", "-C", root, "cat-file", "--batch"], input=batch_input, capture_output=True
    )
    data = batch.stdout or b""
    contents: Dict[str, bytes] = {}
    cursor = 0
    while cursor < len(data):
        newline = data.find(b"\n", cursor)
        if newline == -1:
            break
        header = data[cursor:newline].decode("utf-8", "replace")
        cursor = newline + 1
        parts = header.split(" ")
        if len(parts) != 3:
            continue
        sha, _otype, size_text = parts
        try:
            size = int(size_text)
        except ValueError:
            continue
        contents[sha] = data[cursor:cursor + size]
        cursor += size
        if data[cursor:cursor + 1] == b"\n":
            cursor += 1

    out: List[Tuple[str, str]] = []
    for sha, path, _size in blobs:
        raw = contents.get(sha)
        if raw is None or b"\x00" in raw[:8000]:
            continue
        out.append((path or sha, raw.decode("utf-8", "ignore")))
    return out


def scan_history(root: str, extra_patterns_path: str = "") -> Dict[str, Any]:
    patterns = list(GENERIC_PATTERNS)
    if extra_patterns_path:
        patterns += load_extra_patterns(extra_patterns_path)
    compiled = _compile(patterns)

    findings: List[Dict[str, Any]] = []
    blobs = _history_blobs(root)
    for path, text in blobs:
        _scan_lines(compiled, path, text.splitlines(), findings)

    counts = _tally(findings)
    return {
        "mode": "git-history",
        "root": os.path.abspath(root),
        "objects_scanned": len(blobs),
        "patterns_used": len(compiled),
        "extra_patterns": extra_patterns_path or "(none)",
        "counts": counts,
        "pass": _passed(counts),
        "findings": findings,
    }


# ---------------------------------------------------------------------- CLI


def _print_report(report: Dict[str, Any]) -> None:
    if report["mode"] == "git-history":
        print("mode          : git history (all reachable objects)")
        print("objects scanned: %d" % report["objects_scanned"])
    else:
        print("mode          : working tree")
        print("files scanned : %d" % report["files_scanned"])
    print("patterns used : %d" % report["patterns_used"])
    print("extra patterns: %s" % report["extra_patterns"])
    for key, value in report["counts"].items():
        print("  %-18s %d" % (key, value))
    if not report["pass"]:
        print("\nBlocking findings:")
        for finding in report["findings"]:
            if finding["class"] in ("REAL_SECRET", "PRIVATE_IDENTIFIER"):
                print("  [%s] %s:%d (%s)" % (finding["class"], finding["file"],
                                             finding["line"], finding["pattern"]))
                print("      %s" % finding["excerpt"])
    print("\nGATE: %s" % ("PASS" if report["pass"] else "FAIL"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan the repo for secrets and private identifiers")
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--extra-patterns", default="",
                        help="JSON file OUTSIDE this repo with site-specific identifiers")
    parser.add_argument("--history", action="store_true",
                        help="also scan every git object reachable from all refs")
    parser.add_argument("--json", dest="json_out", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    work = scan(args.root, args.extra_patterns)
    reports = [work]
    if args.history:
        reports.append(scan_history(args.root, args.extra_patterns))

    if args.json_out:
        payload = reports[0] if len(reports) == 1 else reports
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)

    passed = all(r["pass"] for r in reports)
    if not args.quiet:
        for index, report in enumerate(reports):
            if index:
                print()
            _print_report(report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
