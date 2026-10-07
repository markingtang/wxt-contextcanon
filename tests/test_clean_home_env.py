"""Tests for the clean-home acceptance harness's environment isolation.

Only the pure helpers are exercised here; the full clone-and-run acceptance is
executed directly as a gate (`python tools/accept_clean_home.py --watch ...`).
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "packages"))

import accept_clean_home  # noqa: E402
from contextcanon_config import ENV_MAP  # noqa: E402


class CleanHomeEnvTests(unittest.TestCase):
    def test_clean_env_removes_every_mapped_override(self):
        names = list(ENV_MAP) + ["WXT_CONTEXTCANON_CONFIG", "WXT_CONTEXTCANON_DEPLOY_CONFIG", "PYTHONPATH"]
        saved = {name: os.environ.get(name) for name in names}
        for name in names:
            os.environ[name] = "leak-value"
        try:
            env = accept_clean_home.clean_env("H")
            for name in names:
                self.assertNotIn(name, env, "%s must not leak into a clean environment" % name)
            self.assertEqual(env["HOME"], "H")
            self.assertEqual(env["USERPROFILE"], "H")
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

    def test_verdict_requires_watch(self):
        self.assertEqual(accept_clean_home.verdict_for(["PASS", "PASS"]), "PASS")
        self.assertEqual(
            accept_clean_home.verdict_for(["PASS", "NOT_CHECKED"]), "PARTIAL",
            "a run that watched nothing must not report a green gate",
        )
        self.assertEqual(accept_clean_home.verdict_for(["PASS", "FAIL"]), "FAIL")


if __name__ == "__main__":
    unittest.main()
