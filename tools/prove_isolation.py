"""Static/config host checks and optional directory metadata comparison.

This is not a sandbox or network monitor. No metadata snapshot proves that a
configured command cannot read data or contact production. Use synthetic watches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

LOOPBACK = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}
DOC_HOSTS = {"example.com", "example.org", "example.invalid", "invalid.local",
             "your-host", "host.example", "api.github.com", "github.com",
             "raw.githubusercontent.com", "pypi.org", "docs.python.org", "modelcontextprotocol.io"}

HOST_URL_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")
# The negative lookahead rejects Python attribute access such as
# `host = match.group(1)`, which is not a host assignment.
HOST_ASSIGN_RE = re.compile(
    r"(?i)(?<![.\w])(?:host|hostname|endpoint|alias|server)\b[ \t]*[:=][ \t]*[\"']?"
    r"([A-Za-z0-9._-]+)(?![A-Za-z0-9._-])[\"']?(?!\s*\()"
)

SKIP_DIRS = {".git", "__pycache__", "data", ".venv", "venv", "build", "dist", ".mcp-test"}
TEXT_SUFFIXES = (".json", ".yml", ".yaml", ".md", ".py", ".toml", ".env", ".example", ".cfg", ".ini")


def iter_files(root: str) -> List[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(TEXT_SUFFIXES) or name.endswith(".example") or name == ".env.example":
                out.append(os.path.join(dirpath, name))
    return out


def find_host_references(root: str) -> Dict[str, Any]:
    offenders: List[Dict[str, str]] = []
    seen = set()
    for path in iter_files(root):
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read()
        except OSError:
            continue
        for match in HOST_URL_RE.finditer(text):
            host = match.group(1).lower()
            if host in LOOPBACK or host in DOC_HOSTS or host.endswith(".example"):
                continue
            key = (rel, host)
            if key in seen:
                continue
            seen.add(key)
            offenders.append({"file": rel, "host": host, "kind": "url"})
        for match in HOST_ASSIGN_RE.finditer(text):
            host = match.group(1).lower()
            if host in LOOPBACK or host in DOC_HOSTS or host in ("", "true", "false", "none", "null"):
                continue
            if not ("." in host or host.endswith(".local")):
                continue
            key = (rel, host)
            if key in seen:
                continue
            seen.add(key)
            offenders.append({"file": rel, "host": host, "kind": "assignment"})
    return {"offenders": offenders, "count": len(offenders)}


def shipped_ssh_aliases(root: str) -> List[str]:
    aliases = []
    for path in iter_files(root):
        if not path.endswith(".json"):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        ssh = (data.get("ssh") or (data.get("deploy") or {}).get("ssh")) if isinstance(data, dict) else None
        if isinstance(ssh, dict) and ssh.get("host_alias"):
            aliases.append(os.path.relpath(path, root).replace("\\", "/"))
    return aliases


def snapshot(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    entries = []
    for dirpath, dirnames, filenames in os.walk(path):
        for name in sorted(dirnames + filenames):
            full = os.path.join(dirpath, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            entries.append("%s|%s|%s" % (os.path.relpath(full, path), stat.st_size,
                                         stat.st_mtime_ns))
    digest = hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()
    return {"path": path, "entry_count": len(entries), "digest": digest}


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove WXT ContextCanon cannot reach production")
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--watch", action="append", default=[],
                        help="directory whose metadata must not change (repeatable)")
    parser.add_argument("--compare-snapshot", default="")
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args()

    hosts = find_host_references(args.root)
    aliases = shipped_ssh_aliases(args.root)
    watched = {path: snapshot(path) for path in args.watch}

    report: Dict[str, Any] = {
        "root": os.path.abspath(args.root),
        "non_loopback_host_references": hosts,
        "shipped_ssh_aliases": aliases,
        "watched": watched,
    }

    if args.compare_snapshot:
        with open(args.compare_snapshot, "r", encoding="utf-8") as handle:
            before = json.load(handle)
        changed = []
        for path, snap in (before.get("watched") or {}).items():
            now = snapshot(path)
            if snap is None or now is None or snap["digest"] != now["digest"]:
                changed.append(path)
        report["watched_changed"] = changed
        report["WATCHED_METADATA_UNCHANGED"] = not changed
        report["PRODUCTION_CONNECTIONS"] = "NOT_MEASURED"

    report["STATIC_NO_REMOTE_HOST"] = hosts["count"] == 0
    report["NO_SHIPPED_SSH_ALIAS"] = len(aliases) == 0
    report["pass"] = report["STATIC_NO_REMOTE_HOST"] and report["NO_SHIPPED_SSH_ALIAS"] and not report.get("watched_changed")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
