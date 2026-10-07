import io
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))

from mcp_server.server import ContextCanonMcpServer  # noqa: E402
from contextcanon_config import load_config, resolve_paths, ensure_dirs  # noqa: E402


class McpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-mcp-")
        config = load_config(None)
        resolve_paths(config, self.tmp)
        ensure_dirs(config)
        self.server = ContextCanonMcpServer(config)
        self.server.profile.upsert_fact(
            "demo:alex-chen", "timezone", "America/Los_Angeles",
            provenance={"source": "observed"}, actor="test",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, method, params=None):
        return self.server.handle({"jsonrpc": "2.0", "id": 1, "method": method,
                                   "params": params or {}})

    def test_initialize(self):
        response = self.call("initialize")
        result = response["result"]
        self.assertEqual(result["serverInfo"]["name"], "wxt-contextcanon")
        self.assertIn("tools", result["capabilities"])

    def test_tools_list_size_and_coverage(self):
        tools = self.call("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertTrue(5 <= len(tools) <= 10)
        for required in ("profile_get", "profile_search", "profile_upsert",
                         "profile_as_of", "profile_history", "profile_audit",
                         "registry_query", "registry_event"):
            self.assertIn(required, names)

    def test_tools_call_roundtrip(self):
        response = self.call("tools/call", {"name": "profile_get",
                                            "arguments": {"subject": "demo:alex-chen",
                                                          "key": "timezone"}})
        self.assertFalse(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["fact"]["value"], "America/Los_Angeles")

    def test_upsert_then_as_of(self):
        self.call("tools/call", {"name": "profile_upsert",
                                 "arguments": {"subject": "demo:alex-chen", "key": "editor",
                                               "value": "vscode"}})
        self.call("tools/call", {"name": "profile_upsert",
                                 "arguments": {"subject": "demo:alex-chen", "key": "editor",
                                               "value": "zed"}})
        response = self.call("tools/call", {"name": "profile_history",
                                            "arguments": {"subject": "demo:alex-chen",
                                                          "key": "editor"}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual([f["value"] for f in payload["facts"]], ["vscode", "zed"])

    def test_registry_event_and_query(self):
        self.call("tools/call", {"name": "registry_event",
                                 "arguments": {"kind": "file.upsert",
                                               "payload": {"object_key": "demo/a.md",
                                                           "checksum": "abc"}}})
        response = self.call("tools/call", {"name": "registry_query",
                                            "arguments": {"object_key": "demo/a.md"}})
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertEqual(payload["count"], 1)

    def test_missing_argument_is_error_not_crash(self):
        response = self.call("tools/call", {"name": "profile_get", "arguments": {"subject": "x"}})
        self.assertTrue(response["result"]["isError"])

    def test_stdio_roundtrip(self):
        requests = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ]) + "\n"
        out = io.StringIO()
        self.server.serve(stdin=io.StringIO(requests), stdout=out)
        lines = [line for line in out.getvalue().strip().split("\n") if line]
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["id"], 1)
        self.assertEqual(json.loads(lines[1])["id"], 2)

    # ------------------------------------------------------------- MAJOR-3

    def test_malformed_params_do_not_kill_the_session(self):
        """The documented guarantee: one bad line cannot end the session."""
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": [1, 2]}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ]
        out = io.StringIO()
        self.server.serve(stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
        responses = [json.loads(line) for line in out.getvalue().strip().split("\n") if line]
        self.assertEqual(len(responses), 2, "a valid request after a bad one must still be answered")
        self.assertIn("error", responses[0])
        self.assertEqual(responses[0]["id"], 1)
        self.assertIn("tools", responses[1]["result"])
        self.assertEqual(responses[1]["id"], 2)

    def test_non_json_and_non_object_lines_return_errors(self):
        lines = [
            "not json at all",
            json.dumps([1, 2, 3]),
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "tools/list"}),
        ]
        out = io.StringIO()
        self.server.serve(stdin=io.StringIO("\n".join(lines) + "\n"), stdout=out)
        responses = [json.loads(line) for line in out.getvalue().strip().split("\n") if line]
        self.assertEqual(len(responses), 3)
        self.assertEqual(responses[0]["error"]["code"], -32700)
        self.assertEqual(responses[1]["error"]["code"], -32600)
        self.assertEqual(responses[2]["id"], 5)
        self.assertIn("tools", responses[2]["result"])

    def test_method_not_found_uses_top_level_error(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 9, "method": "foo/bar", "params": {}})
        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_arguments_not_object_is_tool_error(self):
        response = self.call("tools/call", {"name": "profile_get", "arguments": [1, 2]})
        self.assertTrue(response["result"]["isError"])

    def test_unknown_tool_and_missing_argument(self):
        unknown = self.call("tools/call", {"name": "nope", "arguments": {}})
        self.assertTrue(unknown["result"]["isError"])
        missing = self.call("tools/call", {"name": "profile_get", "arguments": {}})
        self.assertTrue(missing["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
