"""Mechanism-crossing integration regressions.

Each test drives two or more mechanisms that are correct on their own and were
found to interact badly: temporal write vs temporal read, registry task framing
vs recovery, the MCP loop vs envelope parsing, the release guard vs a fresh
filesystem, and the scanner's allow marker vs a real secret (working tree and
git history).
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "deploy", "release-guard"))

from profile_core import ProfileService, ProfileStore, now_iso  # noqa: E402
from registry_core import RegistryService, RegistryStore  # noqa: E402
from mcp_server.server import ContextCanonMcpServer  # noqa: E402
from contextcanon_config import load_config, resolve_paths, ensure_dirs  # noqa: E402
from contextcanon_cli import demo as demo_mod  # noqa: E402
import scan_secrets  # noqa: E402
import secret_fixtures as fx  # noqa: E402
import guard as release_guard  # noqa: E402


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-integ-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------- temporal write + read + as_of

    def test_temporal_upsert_current_and_as_of_cross(self):
        service = ProfileService(ProfileStore(os.path.join(self.tmp, "p.db")), actor="t")
        service.upsert_fact("s", "city", "Porto", valid_from="2020-01-01T00:00:00Z", nonce="p")
        service.upsert_fact("s", "city", "Tokyo", valid_from="2999-01-01T00:00:00Z", nonce="t")

        self.assertEqual(service.get_fact("s", "city")["value"], "Porto")
        now_view = {f["key"]: f["value"] for f in service.as_of("s", now_iso())}
        self.assertEqual(now_view["city"], "Porto")
        later = {f["key"]: f["value"] for f in service.as_of("s", "2999-06-01T00:00:00Z")}
        self.assertEqual(later["city"], "Tokyo")
        self.assertEqual([f["value"] for f in service.history("s", "city")], ["Porto", "Tokyo"])

    def test_demo_persona_scheduled_fact_is_not_current(self):
        service = ProfileService(ProfileStore(os.path.join(self.tmp, "p.db")), actor="t")
        persona = os.path.join(ROOT, "examples", "demo-persona", "alex-chen.facts.json")
        demo_mod.seed(service, persona_path=persona)
        subject = demo_mod.DEMO_SUBJECT
        # a fact scheduled ~25 days in the future is not "true now"
        self.assertIsNone(service.get_fact(subject, "event.conference_attendance"))
        # ... but it is not deleted: its history is intact
        self.assertEqual(len(service.history(subject, "event.conference_attendance")), 1)

    # ------------------------------------------- registry framing + recovery

    def test_registry_begin_end_recover_status_cross(self):
        registry = RegistryService(RegistryStore(os.path.join(self.tmp, "r.db")), device_id="d")
        registry.ensure_device()
        for index in range(3):
            registry.begin_task("t%d" % index, "work")
            registry.end_task("t%d" % index, "ok")

        recovery = registry.offline_recovery()
        status = registry.status()
        self.assertEqual(status["open_tasks"], [])
        self.assertEqual(recovery["drained"]["failed"], 0)
        self.assertEqual(status["event_count"], 6, "each task event appears exactly once")

    # ------------------------------------------- MCP loop + envelope parsing

    def test_mcp_bad_line_then_good_line_survives(self):
        config = load_config(None)
        resolve_paths(config, self.tmp)
        ensure_dirs(config)
        server = ContextCanonMcpServer(config)
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1, 2]}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
        out = io.StringIO()
        server.serve(io.StringIO("\n".join(lines) + "\n"), out)
        responses = [json.loads(line) for line in out.getvalue().strip().split("\n") if line]
        self.assertEqual(len(responses), 2)
        self.assertIn("error", responses[0])
        self.assertIn("tools", responses[1]["result"])

    # ------------------------------------------- release guard + fresh root

    def test_guard_apply_from_fresh_root_with_example_integrity(self):
        with open(os.path.join(ROOT, "deploy", "release-guard", "deploy.example.json"),
                  encoding="utf-8") as handle:
            config = json.load(handle)
        config["compose_files"] = ["compose.yml"]
        with open(os.path.join(self.tmp, "compose.yml"), "w", encoding="utf-8") as handle:
            handle.write("services: {}\n")
        path = os.path.join(self.tmp, "deploy.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        result = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "planned", result.get("error"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "data", "deploy-integrity.json")))

    # ------------------------------------------- scanner marker + real secret

    def test_scanner_marker_is_narrow_across_working_tree_and_history(self):
        # 1. An allow marker exempts only the pattern it names.
        with open(os.path.join(self.tmp, "a.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(fx.assignment_line("  WXT_SCAN_ALLOW:credential-assignment") + "\n")
        self.assertTrue(scan_secrets.scan(self.tmp)["pass"])

        # 2. A different real secret on a marker line is still blocked.
        with open(os.path.join(self.tmp, "b.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(fx.aws_access_key() + "  WXT_SCAN_ALLOW:credential-assignment\n")
        self.assertFalse(scan_secrets.scan(self.tmp)["pass"])

        # 3. The same secret committed then deleted is caught by history mode.
        repo = os.path.join(self.tmp, "histrepo")
        os.makedirs(repo, exist_ok=True)

        def git(*args):
            subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)

        git("init")
        git("config", "user.email", "tester@example.invalid")
        git("config", "user.name", "Tester")
        with open(os.path.join(repo, "cfg.txt"), "w", encoding="utf-8") as handle:
            handle.write("aws = " + fx.aws_access_key() + "\n")
        git("add", "-A")
        git("commit", "-m", "add")
        with open(os.path.join(repo, "cfg.txt"), "w", encoding="utf-8") as handle:
            handle.write("aws = (removed)\n")
        git("add", "-A")
        git("commit", "-m", "remove")
        self.assertTrue(scan_secrets.scan(repo)["pass"])
        self.assertFalse(scan_secrets.scan_history(repo)["pass"])


if __name__ == "__main__":
    unittest.main()
