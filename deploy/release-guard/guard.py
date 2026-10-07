"""Release Guard - deployment safety as configuration plus a transport adapter.

Nothing here knows about any real host, container, project or path. Every value
comes from a deployment config (see deploy.example.json). The same guard can run
against a local shell, an ssh shell, or a fake stack used by the tests.

Steps, in order. Any failure aborts the run and the lock is released:
    project_guard      - the compose project name matches the config
    integrity          - deployment inputs hash matches the recorded hash
    lock               - one deployment at a time (stale locks are detected)
    mutation_intent    - a real deployment requires --apply and a stated intent
    backup_gate        - a backup must succeed before anything is replaced
    migration_test     - legacy migration path is exercised before rollout
    deploy             - the deploy command, via the transport adapter
    post_health        - configured health endpoints must answer
    smoke              - configured smoke command must pass
    fail_closed        - a partial failure is reported, never hidden
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_TIMEOUT = 300
LOCK_STALE_SECONDS = 3600


class GuardError(Exception):
    pass


# --------------------------------------------------------------- transports


class LocalShell:
    name = "local-shell"

    def __init__(self, config: Dict[str, Any]):
        self.workdir = config.get("workdir") or None

    @staticmethod
    def quote(value: str) -> str:
        """Quote one argument for this shell, so a path with a space stays one token."""
        if os.name == "nt":
            # cmd.exe: double quotes; embedded double quotes are doubled.
            return '"' + value.replace('"', '""') + '"'
        import shlex
        return shlex.quote(value)

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT, dry_run: bool = False) -> Dict[str, Any]:
        if dry_run:
            return {"ok": True, "dry_run": True, "command": command, "returncode": 0}
        try:
            completed = subprocess.run(
                command, shell=True, cwd=self.workdir, timeout=timeout,
                capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "command": command, "returncode": -1, "error": "timeout"}
        return {
            "ok": completed.returncode == 0,
            "command": command,
            "returncode": completed.returncode,
            "stdout": (completed.stdout or "")[-2000:],
            "stderr": (completed.stderr or "")[-2000:],
        }


class SshShell:
    """Remote shell adapter.

    The host alias and working directory come from config. WXT ContextCanon never
    ships a real alias; the value is empty by default and guard refuses to run
    over ssh without one.
    """

    name = "ssh-shell"

    def __init__(self, config: Dict[str, Any]):
        self.alias = (config.get("ssh") or {}).get("host_alias", "")
        self.workdir = (config.get("ssh") or {}).get("workdir", "")

    @staticmethod
    def quote(value: str) -> str:
        """Quote one argument for a POSIX remote shell."""
        import shlex
        return shlex.quote(value)

    def run(self, command: str, timeout: int = DEFAULT_TIMEOUT, dry_run: bool = False) -> Dict[str, Any]:
        if not self.alias:
            raise GuardError("ssh transport selected but no host_alias is configured")
        remote = command
        if self.workdir:
            remote = "cd %s && %s" % (self.workdir, remote)
        full = "ssh %s %s" % (self.alias, _quote(remote))
        if dry_run:
            return {"ok": True, "dry_run": True, "command": full, "returncode": 0}
        return LocalShell({"workdir": None}).run(full, timeout)


TRANSPORTS = {"local-shell": LocalShell, "ssh-shell": SshShell}


def _quote(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


# ------------------------------------------------------------------- config

DEPLOY_DEFAULTS: Dict[str, Any] = {
    "project_name": "wxt-contextcanon",
    "compose_binary": "docker compose",
    "compose_files": [],
    "services": [],
    "lock_path": "./data/deploy.lock",
    "backup_command": "",
    "migration_test_command": "",
    "deploy_command": "",
    "smoke_command": "",
    "stop_command": "",
    "health_endpoints": [],
    "transport": "local-shell",
    "ssh": {"host_alias": "", "workdir": ""},
    "health_timeout_seconds": 20,
    "integrity_file": "",
}


def load_deploy_config(path: Optional[str]) -> Dict[str, Any]:
    config = dict(DEPLOY_DEFAULTS)
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            config.update(json.load(handle))
    return config


def _abs(root: str, value: str) -> str:
    return value if os.path.isabs(value) else os.path.normpath(os.path.join(root, value))


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------- guard


class ReleaseGuard:
    def __init__(self, config: Dict[str, Any], root: str, transport=None):
        self.config = config
        self.root = root
        transport_name = config.get("transport", "local-shell")
        adapter = TRANSPORTS.get(transport_name)
        if adapter is None:
            raise GuardError("unknown transport: %s" % transport_name)
        self.transport = transport or adapter(config)
        self.steps: List[Dict[str, Any]] = []
        self.lock_acquired = False
        self.lock_path = _abs(root, config.get("lock_path", "./data/deploy.lock"))

    def _step(self, name: str, status: str, **extra: Any) -> None:
        entry = {"step": name, "status": status}
        entry.update(extra)
        self.steps.append(entry)

    # ------------------------------------------------------------ primitives

    def project_guard(self) -> None:
        name = self.config.get("project_name", "")
        if not name:
            raise GuardError("project_name is required")
        if not _valid_project_name(name):
            raise GuardError("project_name must match [a-z0-9][a-z0-9_-]*, got %r" % name)
        self._step("project_guard", "ok", project_name=name)

    def integrity(self) -> None:
        files = self.config.get("compose_files") or []
        if not files:
            self._step("integrity", "skipped", reason="no deployment inputs configured")
            return
        actual = {}
        for rel in files:
            path = _abs(self.root, rel)
            if not os.path.exists(path):
                raise GuardError("deployment input missing: %s" % rel)
            try:
                actual[rel] = _sha256(path)
            except OSError as exc:
                raise GuardError("cannot hash deployment input %s: %s" % (rel, exc))
        integrity_file = self.config.get("integrity_file")
        if not integrity_file:
            self._step("integrity", "recorded", files=actual)
            return
        integrity_path = _abs(self.root, integrity_file)
        parent = os.path.dirname(integrity_path)
        if parent:
            try:
                # A fresh clone has no data/ directory yet; create it rather than
                # failing with a raw FileNotFoundError on the very first apply.
                os.makedirs(parent, exist_ok=True)
            except OSError as exc:
                raise GuardError("cannot create integrity directory %s: %s" % (parent, exc))
        if not os.path.exists(integrity_path):
            try:
                with open(integrity_path, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(actual, handle, indent=2, sort_keys=True)
            except OSError as exc:
                raise GuardError("cannot write integrity baseline %s: %s" % (integrity_path, exc))
            self._step("integrity", "baseline_written", path=integrity_path)
            return
        try:
            with open(integrity_path, "r", encoding="utf-8") as handle:
                expected = json.load(handle)
        except (OSError, ValueError) as exc:
            raise GuardError("cannot read integrity baseline %s: %s" % (integrity_path, exc))
        if expected != actual:
            diff = sorted(set(actual) ^ set(expected)) or [
                k for k in actual if expected.get(k) != actual[k]
            ]
            raise GuardError("deployment inputs changed since baseline: %s" % ", ".join(diff))
        self._step("integrity", "ok", files=len(actual))

    def acquire_lock(self) -> None:
        parent = os.path.dirname(self.lock_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.exists(self.lock_path):
            age = time.time() - os.path.getmtime(self.lock_path)
            if age > LOCK_STALE_SECONDS:
                os.remove(self.lock_path)
                self._step("lock", "stale_removed", age_seconds=int(age))
            else:
                raise GuardError("another deployment holds the lock: %s" % self.lock_path)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        handle = os.open(self.lock_path, flags)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"pid": os.getpid(), "user": getpass.getuser(), "at": time.time()},
                      stream)
        self.lock_acquired = True
        self._step("lock", "acquired", path=self.lock_path)

    def release_lock(self) -> None:
        if self.lock_acquired and os.path.exists(self.lock_path):
            os.remove(self.lock_path)
            self.lock_acquired = False
            self._step("lock", "released")

    def check_intent(self, apply: bool, intent: Optional[str]) -> None:
        if apply and not intent:
            raise GuardError("mutation intent is required for --apply: pass --intent \"why\"")
        if not apply:
            self._step("mutation_intent", "dry_run", note="no changes will be made")
        else:
            self._step("mutation_intent", "ok", intent=intent)

    def backup_gate(self, skip: bool, dry_run: bool) -> None:
        command = self.config.get("backup_command", "")
        if not command:
            if skip:
                self._step("backup_gate", "skipped_by_flag")
            else:
                self._step("backup_gate", "skipped", reason="no backup_command configured")
            return
        if skip:
            self._step("backup_gate", "skipped_by_flag", warning="backup explicitly skipped")
            return
        result = self.transport.run(command, dry_run=dry_run)
        if not result["ok"]:
            raise GuardError("backup gate failed: %s" % result.get("stderr") or result.get("error"))
        self._step("backup_gate", "ok" if not dry_run else "dry_run")

    def migration_test(self, dry_run: bool) -> None:
        command = self.config.get("migration_test_command", "")
        if not command:
            self._step("migration_test", "skipped", reason="not configured")
            return
        result = self.transport.run(command, dry_run=dry_run)
        if not result["ok"]:
            raise GuardError("migration legacy test failed")
        self._step("migration_test", "ok" if not dry_run else "dry_run")

    def deploy(self, dry_run: bool) -> None:
        command = self.config.get("deploy_command") or self._compose_command()
        if not command:
            self._step("deploy", "skipped", reason="no deploy command configured")
            return
        result = self.transport.run(command, dry_run=dry_run)
        if not result["ok"]:
            raise GuardError("deploy step failed: %s" % (result.get("stderr") or result.get("error")))
        self._step("deploy", "ok" if not dry_run else "dry_run", returncode=result.get("returncode"))

    def _compose_command(self) -> str:
        binary = self.config.get("compose_binary", "docker compose")
        files = self.config.get("compose_files") or []
        if not files:
            return ""
        parts = [binary, "-p", self.config["project_name"]]
        for rel in files:
            # Quote the path for the transport's shell: an absolute path may
            # contain a space (e.g. a checkout under ".../Some Project/...").
            parts += ["-f", self.transport.quote(_abs(self.root, rel))]
        parts += ["up", "-d"] + list(self.config.get("services") or [])
        return " ".join(parts)

    def post_health(self) -> None:
        endpoints = self.config.get("health_endpoints") or []
        if not endpoints:
            self._step("post_health", "skipped", reason="no endpoints configured")
            return
        timeout = float(self.config.get("health_timeout_seconds", 20))
        deadline = time.time() + timeout
        checked = []
        for url in endpoints:
            ok = False
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(url, timeout=3) as response:
                        if 200 <= response.status < 400:
                            ok = True
                        break
                except (urllib.error.URLError, OSError):
                    time.sleep(0.4)
            checked.append({"url": url, "ok": ok})
            if not ok:
                raise GuardError("health check failed: %s" % url)
        self._step("post_health", "ok", endpoints=checked)

    def smoke(self, dry_run: bool) -> None:
        command = self.config.get("smoke_command", "")
        if not command:
            self._step("smoke", "skipped", reason="not configured")
            return
        result = self.transport.run(command, dry_run=dry_run)
        if not result["ok"]:
            raise GuardError("smoke test failed")
        self._step("smoke", "ok" if not dry_run else "dry_run")

    # ------------------------------------------------------------------ run

    def run(self, apply: bool, intent: Optional[str], skip_backup: bool) -> Dict[str, Any]:
        dry_run = not apply
        failed_step = None
        error = None
        try:
            self.project_guard()
            self.integrity()
            self.acquire_lock()
            self.check_intent(apply, intent)
            self.backup_gate(skip_backup, dry_run)
            self.migration_test(dry_run)
            self.deploy(dry_run)
            if not dry_run:
                self.post_health()
                self.smoke(dry_run)
            else:
                self._step("post_health", "dry_run")
                self._step("smoke", "dry_run")
            outcome = "applied" if apply else "planned"
        except GuardError as exc:
            failed_step = self.steps[-1]["step"] if self.steps else "project_guard"
            error = str(exc)
            outcome = "aborted"
            self._step("fail_closed", "engaged", failed_step=failed_step, error=error)
        except Exception as exc:  # noqa: BLE001 - fail closed on anything unexpected
            error = "%s: %s" % (type(exc).__name__, exc)
            outcome = "aborted"
            self._step("fail_closed", "engaged", failed_step="unexpected", error=error)
        finally:
            self.release_lock()

        return {
            "mode": "apply" if apply else "plan",
            "outcome": outcome,
            "project_name": self.config.get("project_name"),
            "transport": getattr(self.transport, "name", "unknown"),
            "steps": self.steps,
            "error": error,
            "fail_closed": outcome == "aborted",
        }


def _valid_project_name(name: str) -> bool:
    if not name:
        return False
    head = name[0]
    if not (head.isdigit() or ("a" <= head <= "z")):
        return False
    return all(ch.isdigit() or ("a" <= ch <= "z") or ch in "-_" for ch in name)


def run(config_path: Optional[str] = None, root: str = ".", apply: bool = False,
        intent: Optional[str] = None, skip_backup: bool = False) -> Dict[str, Any]:
    config = load_deploy_config(config_path)
    return ReleaseGuard(config, root).run(apply, intent, skip_backup)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WXT ContextCanon release guard")
    parser.add_argument("action", choices=["plan", "apply"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--root", default=os.getcwd())
    parser.add_argument("--intent")
    args = parser.parse_args()
    print(json.dumps(run(args.config, args.root, args.action == "apply", args.intent),
                     indent=2, default=str))
