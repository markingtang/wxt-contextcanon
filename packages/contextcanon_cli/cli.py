"""WXT ContextCanon command line interface.

The CLI is the complete surface. MCP exposes 8 tools for agents; everything
else (seeding, lifecycle sweeps, registry recovery, guard, benchmark) lives here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from .context import Context
from .demo import DEMO_SUBJECT, seed as demo_seed


def _emit(data: Any) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextcanon",
        description="WXT ContextCanon - one personal context and file-state ledger "
                    "for trusted AI agents on one machine.",
    )
    parser.add_argument("--config", help="path to contextcanon.json (defaults are all local)")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    sub = parser.add_subparsers(dest="command")

    # ------------------------------------------------------------- config
    p = sub.add_parser("config", help="show or write configuration")
    p_sub = p.add_subparsers(dest="action")
    p_sub.add_parser("show", help="print the effective configuration")
    init = p_sub.add_parser("init", help="write contextcanon.json with default (local) values")
    init.add_argument("--path", default="contextcanon.json")

    # --------------------------------------------------------------- demo
    p = sub.add_parser("demo", help="synthetic demo persona")
    p_sub = p.add_subparsers(dest="action")
    s = p_sub.add_parser("seed", help="load the fictional demo persona")
    s.add_argument("--reset", action="store_true", help="delete existing demo rows first")
    s.add_argument("--persona", help="path to a persona JSON file")
    p_sub.add_parser("info", help="describe the demo persona")

    # ------------------------------------------------------------- profile
    p = sub.add_parser("profile", help="profile core operations")
    p_sub = p.add_subparsers(dest="action")
    g = p_sub.add_parser("get", help="read one fact")
    g.add_argument("--subject", default=DEMO_SUBJECT)
    g.add_argument("--key", required=True)
    g.add_argument("--include-inactive", action="store_true")
    ls = p_sub.add_parser("list", help="list facts")
    ls.add_argument("--subject", default=DEMO_SUBJECT)
    ls.add_argument("--all", action="store_true", help="include superseded/rejected/expired")
    se = p_sub.add_parser("search", help="search facts")
    se.add_argument("--subject", default=DEMO_SUBJECT)
    se.add_argument("--query", required=True)
    se.add_argument("--limit", type=int, default=20)
    st = p_sub.add_parser("set", help="create or replace a fact")
    st.add_argument("--subject", default=DEMO_SUBJECT)
    st.add_argument("--key", required=True)
    st.add_argument("--value", required=True, help="JSON value (e.g. \"zed\" or 40 or true)")
    st.add_argument("--sensitivity", default="personal",
                    choices=["public", "personal", "sensitive", "restricted"])
    st.add_argument("--durability", default="durable", choices=["durable", "temporary", "scheduled"])
    st.add_argument("--valid-from")
    st.add_argument("--valid-until")
    st.add_argument("--source", default="user-stated")
    st.add_argument("--on-conflict", default="supersede", choices=["supersede", "reject", "keep"])
    hi = p_sub.add_parser("history", help="all revisions of a key")
    hi.add_argument("--subject", default=DEMO_SUBJECT)
    hi.add_argument("--key", required=True)
    ao = p_sub.add_parser("as-of", help="what did we believe at time T?")
    ao.add_argument("--subject", default=DEMO_SUBJECT)
    temporal = ao.add_mutually_exclusive_group(required=True)
    temporal.add_argument("--at", help="ISO timestamp with timezone")
    temporal.add_argument("--days-ago", type=int, help="relative history query, e.g. 30")
    au = p_sub.add_parser("audit", help="audit trail")
    au.add_argument("--subject", default=DEMO_SUBJECT)
    au.add_argument("--limit", type=int, default=50)
    p_sub.add_parser("expire", help="sweep facts whose valid_until has passed")
    lc = p_sub.add_parser("lifecycle", help="status/durability/sensitivity summary")
    lc.add_argument("--subject", default=DEMO_SUBJECT)

    # ------------------------------------------------------------ registry
    p = sub.add_parser("registry", help="registry core operations")
    p_sub = p.add_subparsers(dest="action")
    p_sub.add_parser("init", help="register this device")
    p_sub.add_parser("status", help="ledger status")
    d = p_sub.add_parser("demo", help="run a scripted multi-device offline demo")
    d.add_argument("--reset", action="store_true", help="clear the ledger first (repeatable)")
    q = p_sub.add_parser("query", help="query the shared index")
    q.add_argument("--object-key")
    q.add_argument("--device-id")
    b = p_sub.add_parser("begin", help="declare mutation intent before writing")
    b.add_argument("--task-id", required=True)
    b.add_argument("--intent", required=True)
    b.add_argument("--targets", default="", help="comma separated object keys")
    e = p_sub.add_parser("end", help="close a task")
    e.add_argument("--task-id", required=True)
    e.add_argument("--result", default="ok")
    e.add_argument("--changed", default="")
    ev = p_sub.add_parser("event", help="append a file-state event")
    ev.add_argument("--kind", required=True,
                    choices=["file.upsert", "file.delete", "file.move"])
    ev.add_argument("--object-key", required=True)
    ev.add_argument("--checksum", default="")
    ev.add_argument("--to", help="destination object key for file.move")
    ev.add_argument("--device-id")
    p_sub.add_parser("sync", help="drain the local outbox")
    p_sub.add_parser("rebuild", help="rebuild the shared index from the event log")
    p_sub.add_parser("recover", help="sync + rebuild (call this after being offline)")
    mf = p_sub.add_parser("manifest", help="publish a manifest for this device")
    mf.add_argument("--scope", default="default")
    mf.add_argument("--entries", default="", help="comma separated object keys")

    # --------------------------------------------------------------- guard
    p = sub.add_parser("guard", help="release guard (dry-run by default)")
    p.add_argument("action", choices=["plan", "apply"])
    p.add_argument("--deploy-config", help="path to a deploy config JSON")
    p.add_argument("--intent", help="why this deployment is happening (required for apply)")
    p.add_argument("--skip-backup", action="store_true", help="explicitly skip the backup gate")

    # ----------------------------------------------------------- benchmark
    p = sub.add_parser("benchmark", help="deterministic synthetic benchmark")
    p.add_argument("action", choices=["run", "smoke", "list"])
    p.add_argument("--out", help="write the report markdown to this path")

    # ----------------------------------------------------------------- mcp
    sub.add_parser("mcp", help="start the MCP stdio server")

    # -------------------------------------------------------------- doctor
    sub.add_parser("doctor", help="check that this machine can run WXT ContextCanon")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return _main(argv)
    except KeyboardInterrupt:
        print(json.dumps({"error": "interrupted"}), file=sys.stderr)
        return 130
    except Exception as exc:
        # Never echo config values, SQL payloads, or private paths in errors.
        print(json.dumps({"error": type(exc).__name__, "message": "operation failed; check arguments and local configuration"}), file=sys.stderr)
        return 1


def _main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(json.dumps({"name": "wxt-contextcanon", "version": "0.1.1"}))
        return 0
    if not args.command:
        parser.print_help()
        return 1

    ctx = Context(getattr(args, "config", None))
    command = args.command

    if command == "config":
        if args.action == "show":
            return _emit(ctx.dump())
        if args.action == "init":
            from contextcanon_config import write_example_config
            write_example_config(args.path)
            return _emit({"written": os.path.abspath(args.path)})
        parser.print_help()
        return 1

    if command == "demo":
        service = ctx.profile_service
        if args.action == "seed":
            return _emit(demo_seed(service, getattr(args, "persona", None), args.reset))
        if args.action == "info":
            from .demo import load_persona
            persona = load_persona(getattr(args, "persona", None))
            return _emit({
                "subject": persona.get("subject"),
                "synthetic": True,
                "warning": persona.get("_warning"),
                "fact_count": len(persona.get("facts", [])),
                "scripted": [op.get("op") for op in persona.get("scripted", [])],
            })
        parser.print_help()
        return 1

    if command == "profile":
        return _profile(ctx, args)

    if command == "registry":
        return _registry(ctx, args)

    if command == "guard":
        return _guard(ctx, args)

    if command == "benchmark":
        return _benchmark(ctx, args)

    if command == "mcp":
        from mcp_server.server import ContextCanonMcpServer
        server = ContextCanonMcpServer(ctx.config)
        try:
            server.serve()
        finally:
            server.close()
        return 0

    if command == "doctor":
        return _doctor(ctx)

    parser.print_help()
    return 1


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _profile(ctx: Context, args: Any) -> int:
    service = ctx.profile_service
    action = args.action

    if action == "get":
        fact = service.get_fact(args.subject, args.key, include_inactive=args.include_inactive)
        return _emit({"found": fact is not None, "fact": fact})

    if action == "list":
        facts = service.list_facts(args.subject, include_inactive=args.all)
        return _emit({"subject": args.subject, "count": len(facts), "facts": facts})

    if action == "search":
        facts = service.search(args.subject, args.query, args.limit)
        return _emit({"count": len(facts), "facts": facts})

    if action == "set":
        result = service.upsert_fact(
            subject=args.subject,
            key=args.key,
            value=_parse_value(args.value),
            sensitivity=args.sensitivity,
            durability=args.durability,
            valid_from=args.valid_from,
            valid_until=args.valid_until,
            provenance={"source": args.source, "method": "cli.set"},
            on_conflict=args.on_conflict,
        )
        _emit(result)
        return 1 if result["action"] == "rejected" else 0

    if action == "history":
        facts = service.history(args.subject, args.key)
        return _emit({"count": len(facts), "facts": facts})

    if action == "as-of":
        from datetime import datetime, timedelta, timezone
        at = args.at or (datetime.now(timezone.utc) - timedelta(days=args.days_ago)).isoformat()
        facts = service.as_of(args.subject, at)
        return _emit({"at": at, "count": len(facts), "facts": facts})

    if action == "audit":
        events = service.audit(args.subject, args.limit)
        return _emit({"count": len(events), "events": events})

    if action == "expire":
        expired = service.expire_due_facts()
        return _emit({"expired_count": len(expired), "facts": expired})

    if action == "lifecycle":
        return _emit(service.lifecycle_report(args.subject))

    return 1


def _registry(ctx: Context, args: Any) -> int:
    service = ctx.registry_service
    action = args.action

    if action == "init":
        return _emit(service.ensure_device())

    if action == "status":
        return _emit(service.status())

    if action == "demo":
        return _emit(_registry_demo(service, ctx, reset=args.reset))

    if action == "query":
        return _emit({"rows": service.query(args.object_key, args.device_id)})

    if action == "begin":
        targets = [t for t in args.targets.split(",") if t]
        return _emit(service.begin_task(args.task_id, args.intent, targets))

    if action == "end":
        changed = [c for c in args.changed.split(",") if c]
        return _emit(service.end_task(args.task_id, args.result, changed))

    if action == "event":
        payload: Dict[str, Any] = {"object_key": args.object_key}
        if args.to:
            payload["to"] = args.to
        if args.checksum:
            payload["checksum"] = args.checksum
        event = service.append_event(args.kind, payload, device_id=args.device_id)
        service.apply_all()
        return _emit({"event": event, "applied": True})

    if action == "sync":
        result = service.drain_outbox()
        _emit(result)
        return 1 if result["failed"] else 0

    if action == "rebuild":
        result = service.rebuild_shared_index()
        _emit(result)
        return 1 if result["last_good_used"] else 0

    if action == "recover":
        result = service.offline_recovery()
        _emit(result)
        return 0 if result["converged"] else 1

    if action == "manifest":
        entries = [{"object_key": k} for k in args.entries.split(",") if k]
        return _emit(service.record_manifest(args.scope, entries))

    return 1


def _registry_demo(service, ctx: Context, reset: bool = False) -> Dict[str, Any]:
    """Scripted demo: two devices, one goes offline, both converge.

    Uses only synthetic object keys such as 'demo/notes/a.md'.
    """
    second_device = ctx.config["registry"]["device_id"] + "-b"
    steps: List[Dict[str, Any]] = []

    if reset:
        conn = service.store.conn
        for table in ("events", "outbox", "applied", "shared_index", "manifests", "devices"):
            conn.execute("DELETE FROM %s" % table)
        conn.commit()
        steps.append({"step": "ledger.reset"})

    service.ensure_device()
    steps.append({"step": "device.registered", "device_id": service.device_id})

    task = service.begin_task("demo-task-1", "reorganise demo notes", ["demo/notes/a.md"])
    steps.append({"step": "task.begin", "task_id": task["task_id"]})

    for key in ("demo/notes/a.md", "demo/notes/b.md", "demo/notes/c.md"):
        service.append_event("file.upsert", {"object_key": key, "checksum": "demo-" + key[-5:-3], "size": 3})
    service.apply_all()
    steps.append({"step": "local.writes", "objects": 3})

    service.end_task("demo-task-1", "ok", ["demo/notes/a.md"])
    steps.append({"step": "task.end", "open_tasks": service.open_tasks()})

    # second device produces work while "offline": queued only in its outbox
    offline_ids = []
    for key in ("demo/notes/b.md", "demo/notes/d.md"):
        oid = "ob_demo_%s" % key.replace("/", "_").replace(".", "_")
        service.store.enqueue(oid, second_device, "file.upsert",
                              {"object_key": key, "checksum": "demo-b2", "size": 4},
                              __import__("profile_core").now_iso())
        offline_ids.append(oid)
    steps.append({"step": "offline.queued", "pending": len(service.store.pending_outbox())})

    drained = service.drain_outbox()
    steps.append({"step": "reconnect.drained", "result": drained})

    # Re-delivery of the same work (network retry, double sync) must not
    # double-apply. Put the same outbox ids back into 'pending' and drain again.
    for oid in offline_ids:
        service.store.mark_outbox(oid, "pending", "", __import__("profile_core").now_iso())
    replay = service.drain_outbox()
    steps.append({"step": "idempotent.replay", "result": replay})

    rebuild = service.rebuild_shared_index()
    steps.append({"step": "index.rebuild", "result": rebuild})

    manifest = service.record_manifest("demo", [{"object_key": k} for k in
                                                ("demo/notes/a.md", "demo/notes/b.md",
                                                 "demo/notes/c.md", "demo/notes/d.md")])
    steps.append({"step": "manifest.published", "checksum": manifest["checksum"]})

    return {
        "synthetic": True,
        "steps": steps,
        "index": service.query(),
        "status": service.status(),
        "idempotent": replay["skipped"] >= 1 and replay["applied"] == 0,
    }


def _benchmark(ctx: Context, args: Any) -> int:
    root = ctx.root
    runner_dir = os.path.join(root, "benchmark", "runner")
    if runner_dir not in sys.path:
        sys.path.insert(0, runner_dir)
    import run as benchmark_run  # type: ignore

    if args.action == "list":
        return _emit(benchmark_run.list_cases(root))
    if args.action == "smoke":
        result = benchmark_run.run(root, case_filter="smoke")
    else:
        result = benchmark_run.run(root, out_path=args.out)
    _emit(result)
    return 0 if result["contextcanon_score"] == result["cases"] else 1


def _guard(ctx: Context, args: Any) -> int:
    root = ctx.root
    guard_dir = os.path.join(root, "deploy", "release-guard")
    if guard_dir not in sys.path:
        sys.path.insert(0, guard_dir)
    import guard as release_guard  # type: ignore

    config_path = args.deploy_config
    if not config_path:
        candidate = os.path.join(root, "deploy", "release-guard", "fake_stack", "fake_deploy.json")
        env_override = os.environ.get("WXT_CONTEXTCANON_DEPLOY_CONFIG")
        config_path = env_override or (candidate if os.path.exists(candidate) else None)
    result = release_guard.run(
        config_path=config_path,
        root=root,
        apply=args.action == "apply",
        intent=args.intent,
        skip_backup=args.skip_backup,
    )
    _emit(result)
    return 1 if result["outcome"] == "aborted" else 0


def _doctor(ctx: Context) -> int:
    import platform
    import sqlite3
    checks = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "cwd": os.getcwd(),
        "config_path": ctx.config_path or "(defaults)",
        "profile_db": ctx.config["profile"]["database"],
        "registry_store": ctx.config["registry"]["shared_store"],
        "device_id": ctx.config["registry"]["device_id"],
        "project_name": ctx.config["deploy"]["project_name"],
    }
    problems = []
    for endpoint in ctx.config["deploy"].get("health_endpoints", []):
        if "localhost" not in endpoint and "127.0.0.1" not in endpoint:
            problems.append("non-local health endpoint configured: %s" % endpoint)
    checks["problems"] = problems
    checks["ok"] = not problems
    _emit(checks)
    return 0 if checks["ok"] else 1
