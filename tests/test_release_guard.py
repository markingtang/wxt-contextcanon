import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "deploy", "release-guard"))
sys.path.insert(0, os.path.join(ROOT, "packages"))

import guard as release_guard  # noqa: E402


class ReleaseGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-guard-")
        self.fake_config = os.path.join(ROOT, "deploy", "release-guard", "fake_stack", "fake_deploy.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, **overrides):
        config = dict(release_guard.DEPLOY_DEFAULTS)
        config.update(overrides)
        path = os.path.join(self.tmp, "deploy.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(config, handle)
        return path

    def test_plan_is_dry_run(self):
        result = release_guard.run(self.fake_config, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "planned")
        self.assertFalse(result["fail_closed"])
        self.assertTrue(any(s["step"] == "mutation_intent" and s["status"] == "dry_run"
                            for s in result["steps"]))

    def test_apply_without_intent_fails_closed(self):
        result = release_guard.run(self.fake_config, self.tmp, apply=True, intent=None)
        self.assertEqual(result["outcome"], "aborted")
        self.assertTrue(result["fail_closed"])
        self.assertIn("intent", result["error"])

    def test_invalid_project_name_fails_closed(self):
        path = self._config(project_name="Bad Name!", lock_path="./data/l.lock")
        result = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "aborted")
        self.assertTrue(result["fail_closed"])

    def test_partial_failure_is_fail_closed(self):
        os.environ["FAKE_MIGRATION_FAIL"] = "1"
        try:
            result = release_guard.run(self.fake_config, self.tmp, apply=True, intent="test")
        finally:
            os.environ.pop("FAKE_MIGRATION_FAIL", None)
        self.assertEqual(result["outcome"], "aborted")
        self.assertTrue(result["fail_closed"])
        steps = [s["step"] for s in result["steps"]]
        self.assertIn("backup_gate", steps)
        self.assertNotIn("deploy", steps)

    def test_lock_is_released_after_abort(self):
        lock = os.path.join(self.tmp, "data", "guard.lock")
        path = self._config(project_name="bad name", lock_path=lock)
        release_guard.run(path, self.tmp, apply=False)
        self.assertFalse(os.path.exists(lock))

    def test_ssh_transport_requires_alias(self):
        path = self._config(transport="ssh-shell", project_name="contextcanon-x",
                            lock_path="./data/s.lock", deploy_command="echo hi")
        result = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "aborted")
        self.assertIn("host_alias", result["error"])

    def test_integrity_baseline_then_drift(self):
        target = os.path.join(self.tmp, "compose.yml")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("services: {}\n")
        integrity = os.path.join(self.tmp, "integrity.json")
        path = self._config(project_name="contextcanon-x", compose_files=["compose.yml"],
                            integrity_file=integrity, lock_path="./data/i.lock")
        first = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(first["outcome"], "planned")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write("# drift\n")
        second = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(second["outcome"], "aborted")
        self.assertIn("changed since baseline", second["error"])

    def test_compose_command_built_from_config(self):
        path = self._config(project_name="contextcanon-x", compose_files=["deploy/docker/docker-compose.yml"],
                            services=["contextcanon-api"], lock_path="./data/c.lock")
        config = release_guard.load_deploy_config(path)
        guard_obj = release_guard.ReleaseGuard(config, ROOT)
        command = guard_obj._compose_command()
        self.assertIn("-p contextcanon-x", command)
        self.assertIn("contextcanon-api", command)

    # ------------------------------------------ MAJOR-4 / §7 release guard

    def test_integrity_file_parent_directory_is_created(self):
        """A fresh clone has no data/ dir; the first apply must create it, not crash."""
        target = os.path.join(self.tmp, "compose.yml")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("services: {}\n")
        integrity = os.path.join(self.tmp, "data", "nested", "deploy-integrity.json")
        path = self._config(project_name="contextcanon-x", compose_files=["compose.yml"],
                            integrity_file=integrity, lock_path="./data/i.lock")
        result = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "planned", result.get("error"))
        self.assertTrue(os.path.exists(integrity))

    def test_integrity_filesystem_error_is_a_guard_error(self):
        target = os.path.join(self.tmp, "compose.yml")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("services: {}\n")
        blocker = os.path.join(self.tmp, "blocker")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("not a directory\n")
        integrity = os.path.join(blocker, "sub", "deploy-integrity.json")
        path = self._config(project_name="contextcanon-x", compose_files=["compose.yml"],
                            integrity_file=integrity, lock_path="./data/i.lock")
        result = release_guard.run(path, self.tmp, apply=False)
        self.assertEqual(result["outcome"], "aborted")
        fail_closed = [s for s in result["steps"] if s["step"] == "fail_closed"][0]
        self.assertNotEqual(fail_closed["failed_step"], "unexpected",
                            "filesystem errors must surface as a guard error, not an unexpected crash")
        self.assertIn("integrity", fail_closed["error"].lower())

    def test_shipped_example_config_applies_from_a_fresh_root(self):
        """Reproduces the audit's MAJOR-4: the example config's relative
        integrity_file must work from a root whose data/ dir does not exist yet."""
        example = os.path.join(ROOT, "deploy", "release-guard", "deploy.example.json")
        with open(example, "r", encoding="utf-8") as handle:
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

    def test_compose_path_with_space_is_quoted(self):
        path = self._config(project_name="contextcanon-x", lock_path="./data/s.lock")
        config = release_guard.load_deploy_config(path)
        config["compose_files"] = ["deploy/docker/my compose.yml"]
        guard_obj = release_guard.ReleaseGuard(config, ROOT)
        command = guard_obj._compose_command()
        abs_path = release_guard._abs(ROOT, "deploy/docker/my compose.yml")
        quoted = guard_obj.transport.quote(abs_path)
        self.assertIn(quoted, command)
        self.assertNotEqual(quoted, abs_path, "the path must actually be quoted")


if __name__ == "__main__":
    unittest.main()
