"""CLEAN TEMP HOME acceptance test.

Simulates a stranger on a clean machine:

  * a brand new empty HOME (no private dotfiles, no private profile)
  * the repository cloned from scratch, exactly as `git clone` would produce it
  * no PYTHONPATH, no inherited config, no env from the developer's machine
  * the documented quickstart, end to end

Anything that reaches outside the temporary tree is a failure.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))

from contextcanon_config import ENV_MAP  # noqa: E402

MCP_SESSION = "\n".join([
    json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
    json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
    json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "profile_get",
                           "arguments": {"subject": "demo:alex-chen", "key": "tooling.editor"}}}),
]) + "\n"


def run(cmd: List[str], cwd: str, env: Dict[str, str], stdin_data: str = "") -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            cmd, cwd=cwd, env=env, input=stdin_data,
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "stdout": "", "stderr": ""}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr[-800:],
    }


def as_json(result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(result["stdout"])
    except (ValueError, KeyError):
        return None


def clean_env(home: str) -> Dict[str, str]:
    """A clean-machine environment: no inherited config, no WXT ContextCanon overrides.

    The set of variables to drop is derived from ``contextcanon_config.ENV_MAP`` (plus
    every ``WXT_CONTEXTCANON_``-prefixed variable), so adding a new override to the map can
    never leave a stale value leaking into the acceptance run.
    """
    drop = set(ENV_MAP.keys()) | {"PYTHONPATH"}
    drop |= {k for k in os.environ if k.startswith("WXT_CONTEXTCANON_")}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["HOME"] = home
    env["USERPROFILE"] = home
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean temp home acceptance test")
    parser.add_argument("--repo", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--watch", action="append", default=[],
                        help="private directory whose metadata must not change")
    parser.add_argument("--json", dest="json_out", default="")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    base = tempfile.mkdtemp(prefix="contextcanon-cleanhome-")
    home = os.path.join(base, "home")
    clone = os.path.join(base, "contextcanon-demo")
    os.makedirs(home, exist_ok=True)
    env = clean_env(home)

    sys.path.insert(0, os.path.join(repo, "tools"))
    import prove_isolation  # noqa: E402

    before_watch = {p: prove_isolation.snapshot(p) for p in args.watch}

    steps: List[Dict[str, Any]] = []

    def step(name: str, ok: bool, **extra: Any) -> bool:
        entry = {"step": name, "status": "PASS" if ok else "FAIL"}
        entry.update(extra)
        steps.append(entry)
        return ok

    # 1. fresh clone, exactly like a stranger
    cloned = run(["git", "clone", "--quiet", repo, clone], cwd=base, env=env)
    if not step("git_clone", cloned["ok"], stderr=cloned.get("stderr", "")[:200]):
        return _finish(steps, base, args, "FAIL")

    python = sys.executable
    pkgs = os.path.join(clone, "packages")

    def contextcanon(*argv: str, stdin_data: str = "") -> Dict[str, Any]:
        child_env = dict(env)
        child_env["PYTHONPATH"] = pkgs
        return run([python, "-m", "contextcanon_cli", *argv], cwd=clone, env=child_env,
                   stdin_data=stdin_data)

    # 2. doctor
    result = contextcanon("doctor")
    doctor = as_json(result) or {}
    step("doctor", result["ok"] and doctor.get("ok") is True,
         python=doctor.get("python"), sqlite=doctor.get("sqlite"))

    # 3. demo seed
    result = contextcanon("demo", "seed", "--reset")
    seeded = as_json(result) or {}
    lifecycle = seeded.get("lifecycle", {})
    step("demo_seed", result["ok"] and seeded.get("seeded_facts", 0) >= 15,
         facts=seeded.get("seeded_facts"),
         by_status=lifecycle.get("by_status"),
         by_durability=lifecycle.get("by_durability"))

    # 4. profile read
    result = contextcanon("profile", "get", "--subject", "demo:alex-chen", "--key", "tooling.editor")
    got = as_json(result) or {}
    step("profile_query", result["ok"] and (got.get("fact") or {}).get("value") == "zed",
         value=(got.get("fact") or {}).get("value"))

    # 5. profile update
    result = contextcanon("profile", "set", "--subject", "demo:alex-chen",
                  "--key", "demo.learned", "--value", "\"hello from a clean machine\"")
    updated = as_json(result) or {}
    result2 = contextcanon("profile", "get", "--subject", "demo:alex-chen", "--key", "demo.learned")
    got2 = as_json(result2) or {}
    step("profile_update", result["ok"] and (got2.get("fact") or {}).get("value") ==
         "hello from a clean machine", action=updated.get("action"))

    # 6. temporal read
    import datetime
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=60)
            ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    result = contextcanon("profile", "as-of", "--subject", "demo:alex-chen", "--at", past)
    asof = as_json(result) or {}
    values = {f["key"]: f["value"] for f in asof.get("facts", [])}
    step("temporal_demo", result["ok"] and values.get("tooling.editor") == "vscode",
         at=past, editor_60d_ago=values.get("tooling.editor"), fact_count=asof.get("count"))

    # 7. registry demo
    result = contextcanon("registry", "demo", "--reset")
    reg = as_json(result) or {}
    step("registry_demo", result["ok"] and reg.get("idempotent") is True,
         idempotent=reg.get("idempotent"),
         event_count=(reg.get("status") or {}).get("event_count"),
         pending_outbox=(reg.get("status") or {}).get("pending_outbox"),
         open_tasks=(reg.get("status") or {}).get("open_tasks"))

    # 8. benchmark smoke
    result = contextcanon("benchmark", "smoke")
    bench = as_json(result) or {}
    step("benchmark_smoke", result["ok"] and bench.get("contextcanon_score") == bench.get("cases"),
         contextcanon_score=bench.get("contextcanon_score"), markdown_score=bench.get("markdown_score"),
         cases=bench.get("cases"))

    # 9. MCP over stdio
    child_env = dict(env)
    child_env["PYTHONPATH"] = pkgs
    mcp = run([python, "-m", "mcp_server"], cwd=clone, env=child_env, stdin_data=MCP_SESSION)
    lines = [line for line in (mcp.get("stdout") or "").strip().split("\n") if line.startswith("{")]
    parsed = [json.loads(line) for line in lines if line]
    tool_names = []
    mcp_value = None
    for message in parsed:
        payload = message.get("result") or {}
        if "tools" in payload:
            tool_names = [t["name"] for t in payload["tools"]]
        if "content" in payload and payload.get("content"):
            try:
                mcp_value = json.loads(payload["content"][0]["text"]).get("fact", {}).get("value")
            except (ValueError, KeyError, IndexError):
                pass
    step("mcp_demo", len(parsed) >= 3 and 5 <= len(tool_names) <= 10 and mcp_value == "zed",
         responses=len(parsed), tools=len(tool_names), profile_get=mcp_value)

    # 10. release guard plan
    result = contextcanon("guard", "plan")
    guard_result = as_json(result) or {}
    step("guard_plan", result["ok"] and guard_result.get("outcome") == "planned",
         outcome=guard_result.get("outcome"),
         steps_run=len(guard_result.get("steps", [])))

    # 11. nothing leaked outside the temp tree
    if args.watch:
        after_watch = {p: prove_isolation.snapshot(p) for p in args.watch}
        changed = [p for p in args.watch
                   if (before_watch.get(p) or {}).get("digest") != (after_watch.get(p) or {}).get("digest")]
        step("production_untouched", not changed, watched=args.watch, changed=changed)
    else:
        # No --watch target was supplied, so nothing was actually observed.
        # Report NOT_CHECKED rather than a green PASS that watched nothing.
        steps.append({"step": "production_untouched", "status": "NOT_CHECKED",
                      "reason": "no --watch directory supplied"})

    # 12. state stayed inside the clone
    inside = os.path.isdir(os.path.join(clone, "data"))
    outside = os.path.isdir(os.path.join(home, "data"))
    step("state_inside_clone", inside and not outside,
         clone_data=inside, home_data=outside)

    statuses = [s["status"] for s in steps]
    verdict = verdict_for(statuses)
    return _finish(steps, base, args, verdict, cleanup=True)


def verdict_for(statuses: List[str]) -> str:
    """PASS only when everything ran; PARTIAL when a step was NOT_CHECKED.

    A missing --watch leaves ``production_untouched`` NOT_CHECKED, which must
    not read as a green release gate.
    """
    if all(s == "PASS" for s in statuses):
        return "PASS"
    if all(s in ("PASS", "NOT_CHECKED") for s in statuses):
        return "PARTIAL"
    return "FAIL"


def _finish(steps: List[Dict[str, Any]], base: str, args: Any, verdict: str,
            cleanup: bool = True) -> int:
    report = {
        "CLEAN_HOME_INSTALL": verdict,
        "PRODUCTION_UNTOUCHED": "CHECKED" if any(
            s["step"] == "production_untouched" and s["status"] in ("PASS", "FAIL") for s in steps
        ) else "NOT_CHECKED",
        "steps": steps,
        "passed": sum(1 for s in steps if s["status"] == "PASS"),
        "total": len(steps),
    }
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if cleanup:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
