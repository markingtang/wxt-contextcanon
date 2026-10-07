import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))

from contextcanon_config import DEFAULTS, ensure_dirs, load_config, resolve_paths, write_example_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-config-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_defaults_are_local(self):
        self.assertEqual(DEFAULTS["profile"]["host"], "127.0.0.1")
        self.assertEqual(DEFAULTS["registry"]["device_id"], "demo-device")
        self.assertTrue(DEFAULTS["profile"]["database"].startswith("./"))

    def test_underscore_keys_are_ignored(self):
        """Documentation keys such as '_comment' must not be treated as sections."""
        path = os.path.join(self.tmp, "c.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"_comment": "just a note", "profile": {"host": "127.0.0.1"}}, handle)
        config = load_config(path)
        self.assertNotIn("_comment", config)
        self.assertEqual(config["profile"]["host"], "127.0.0.1")

    def test_shipped_example_config_loads(self):
        path = os.path.join(ROOT, "examples", "configs", "contextcanon.example.json")
        config = load_config(path)
        self.assertEqual(config["registry"]["device_id"], "demo-device")
        self.assertEqual(config["deploy"]["project_name"], "wxt-contextcanon")

    def test_env_override(self):
        os.environ["WXT_CONTEXTCANON_REGISTRY_DEVICE_ID"] = "unit-test-device"
        try:
            config = load_config(None)
            self.assertEqual(config["registry"]["device_id"], "unit-test-device")
        finally:
            os.environ.pop("WXT_CONTEXTCANON_REGISTRY_DEVICE_ID", None)

    def test_paths_resolve_against_root_and_dirs_created(self):
        config = load_config(None)
        resolve_paths(config, self.tmp)
        self.assertTrue(os.path.isabs(config["profile"]["database"]))
        self.assertTrue(config["profile"]["database"].startswith(self.tmp))
        ensure_dirs(config)
        self.assertTrue(os.path.isdir(config["profile"]["data_dir"]))

    def test_write_example_config_roundtrip(self):
        path = os.path.join(self.tmp, "contextcanon.json")
        write_example_config(path)
        again = load_config(path)
        self.assertEqual(again["profile"]["host"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
