"""Documentation consistency gate.

This exists because numbers in prose drift. It is deliberately small: it checks
only the things that have actually broken before.

    * documented test counts equal the real collected test count
    * documented benchmark case counts equal cases.json
    * every `contextcanon ...` command shown in docs actually parses
    * MCP tool names in docs equal the server's real tool specs
    * no document hard-codes a volatile commit count
    * honest multi-device wording is present in the first screen and the skill
    * the README states the public release

Run it like any other test: `python tests/run_all.py`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))

README = "README.md"
SKILL = os.path.join("skills", "contextcanon", "SKILL.md")

DOCS = [README, "ARCHITECTURE.md", "TRADEMARKS.md",
        "benchmark/README.md", os.path.join("docs", "quickstart", "local.md"),
        os.path.join("docs", "MCP_TOOLS.md"), os.path.join("docs", "SECRET_SCAN.md"),
        os.path.join("docs", "THIRD_PARTY_NOTICES.md"),
        os.path.join("docs", "architecture", "overview.md"),
        os.path.join("docs", "concepts", "profile.md"),
        os.path.join("docs", "concepts", "registry.md"),
        os.path.join("docs", "concepts", "privacy.md"),
        os.path.join("docs", "concepts", "release-guard.md"),
        os.path.join("deploy", "release-guard", "README.md"),
        os.path.join("deploy", "local", "README.md"),
        "SECURITY.md", "CONTRIBUTING.md"]


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8") as handle:
        return handle.read()


def all_markdown() -> list:
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "__pycache__", "data", "pip", "build", "dist", ".mcp-test", "build", "dist", ".mcp-test")
                       and not os.path.join(dirpath, d).endswith(os.path.join("benchmark", "results"))]
        for name in filenames:
            if name.endswith(".md"):
                out.append(os.path.relpath(os.path.join(dirpath, name), ROOT).replace("\\", "/"))
    return sorted(out)


def real_test_count() -> int:
    loader = unittest.TestLoader()
    tests_dir = os.path.join(ROOT, "tests")
    suite = loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir)
    return suite.countTestCases()


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def cli_choices():
    """Map top-level subcommand -> set of its sub-subcommands, from the real parser."""
    from contextcanon_cli.cli import build_parser
    parser = build_parser()
    mapping = {}
    for action in parser._actions:
        if not hasattr(action, "choices") or not action.choices:
            continue
        for name, sub in action.choices.items():
            subs = set()
            for sub_action in getattr(sub, "_actions", []):
                if hasattr(sub_action, "choices") and sub_action.choices:
                    subs |= set(sub_action.choices)
            mapping[name] = subs
    return mapping


def mcp_tool_names() -> list:
    """Read the real tool names from a throwaway server instance."""
    import tempfile
    from mcp_server.server import build_server
    tmp = tempfile.mkdtemp(prefix="contextcanon-docs-check-")
    try:
        server = build_server(None, tmp)
        try:
            return sorted(server.tools.keys())
        finally:
            server.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class DocsConsistencyTests(unittest.TestCase):
    maxDiff = None

    # ------------------------------------------------------------- test counts

    def test_documented_test_counts_are_real(self):
        real = real_test_count()
        offenders = []
        for rel in all_markdown():
            for number in re.findall(r"\b(\d+)\s+tests\b", read(rel)):
                if int(number) != real:
                    offenders.append("%s claims %s tests (real: %d)" % (rel, number, real))
        self.assertEqual(offenders, [], "\n".join(offenders))

    # ---------------------------------------------------------- commit counts

    def test_no_volatile_commit_count_in_docs(self):
        """No document may hard-code a commit count.

        The release-candidate receipt that used to hold this number is archived
        outside the repository on purpose, so the public tree must carry no
        volatile counter at all. Nothing in a public HEAD needs a commit count;
        `git rev-list --all --count` is one command away for anyone who wants it.
        """
        offenders = []
        for rel in all_markdown():
            for number in re.findall(r"\b(\d+)\s+commits\b", read(rel)):
                offenders.append("%s hard-codes '%s commits'" % (rel, number))
        self.assertEqual(offenders, [],
                         "a public document must not hard-code a commit count:\n%s"
                         % "\n".join(offenders))

    def test_public_distribution_files_exist(self):
        # A public clone has origin; forks and normal merges are supported.
        for name in ("README.md", "LICENSE", "NOTICE", "TRADEMARKS.md", "pyproject.toml"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, name)), name)

    # -------------------------------------------------------- benchmark counts

    def test_benchmark_case_counts_are_real(self):
        with open(os.path.join(ROOT, "benchmark", "cases", "cases.json"), encoding="utf-8") as handle:
            cases = json.load(handle)["cases"]
        full = len(cases)
        subset = sum(1 for c in cases if c.get("smoke"))
        self.assertEqual(full, 9, "full suite case count changed; update the docs")
        self.assertEqual(subset, 7, "smoke subset size changed; update the docs")
        bench_readme = read(os.path.join("benchmark", "README.md"))
        self.assertIn("| **{}** |".format(full), bench_readme)
        self.assertIn("| **{}** |".format(subset), bench_readme)
        self.assertIn("full suite, {} cases".format(full), read(README))
        self.assertIn("{}-case subset".format(subset), read(README))

    def test_benchmark_case_ids_are_honest(self):
        """The multi-agent case was really a shared-store read; the name must say so."""
        with open(os.path.join(ROOT, "benchmark", "cases", "cases.json"), encoding="utf-8") as handle:
            ids = {c["id"] for c in json.load(handle)["cases"]}
        self.assertIn("shared_store_consistency", ids)
        self.assertNotIn("multi_agent_convergence", ids)
        self.assertIn("shared_store_consistency", read(os.path.join("benchmark", "README.md")))
        for rel in all_markdown():
            self.assertNotIn("multi_agent_convergence", read(rel),
                             "%s still references the old benchmark case name" % rel)

    # ----------------------------------------------------------- CLI commands

    def test_documented_cli_commands_exist(self):
        choices = cli_choices()
        pattern = re.compile(r"\bcontextcanon ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?")
        offenders = []
        for rel in all_markdown():
            for match in pattern.finditer(read(rel)):
                top, sub = match.group(1), match.group(2)
                if top not in choices:
                    offenders.append("%s: `contextcanon %s` is not a command" % (rel, top))
                    continue
                if sub and choices[top] and sub not in choices[top]:
                    offenders.append("%s: `contextcanon %s %s` is not a command" % (rel, top, sub))
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_skill_only_uses_real_commands(self):
        choices = cli_choices()
        for match in re.finditer(r"\bcontextcanon ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", read(SKILL)):
            top, sub = match.group(1), match.group(2)
            self.assertIn(top, choices, "skill uses unknown command: contextcanon %s" % top)
            if sub and choices[top]:
                self.assertIn(sub, choices[top],
                              "skill uses unknown command: contextcanon %s %s" % (top, sub))

    # ------------------------------------------------------------- MCP surface

    def test_mcp_tool_names_match_docs(self):
        tools = mcp_tool_names()
        self.assertEqual(len(tools), 8, "the MCP surface is deliberately 8 tools")
        mcp_docs = read(os.path.join("docs", "MCP_TOOLS.md"))
        skill = read(SKILL)
        readme = read(README)
        for name in tools:
            self.assertIn(name, mcp_docs, "%s missing from docs/MCP_TOOLS.md" % name)
            self.assertIn(name, skill, "%s missing from the skill" % name)
            self.assertIn(name, readme, "%s missing from README" % name)
        for text, where in ((mcp_docs, "docs/MCP_TOOLS.md"), (skill, "skill"), (readme, "README")):
            self.assertRegex(text, r"(?i)\b(?:eight|8)\b[\s—-]{0,3}(?:MCP\s+)?tools\b",
                             "%s must state the tool count" % where)

    # --------------------------------------------------- multi-device honesty

    def test_first_screen_states_p1_scope(self):
        readme = read(README)
        head = readme[:readme.index("## Why it exists")]
        self.assertIn("Public release", head)
        self.assertIn("real cross-machine transport is not shipped", head.lower())
        self.assertNotIn("**more than one** device", readme,
                         "'Who it is for' must not imply multi-machine support today")

    def test_skill_warns_about_cross_machine(self):
        skill = read(SKILL).lower()
        self.assertIn("no network between machines", skill)
        self.assertIn("do not tell a user", skill)

    def test_concept_docs_disclaim_transport(self):
        self.assertIn("do not mean two computers", read(os.path.join("docs", "concepts", "registry.md")))

    def test_published_clone_url_present(self):
        readme = read(README).lower()
        for banned in ("available on github", "install from github", "released on github"):
            self.assertNotIn(banned, readme)
        self.assertIn("git clone https://github.com/markingtang/wxt-contextcanon.git", readme,
                      "the real public clone URL must appear in the README")

    # ------------------------------------------------------ release guard scope

    def test_documented_guard_steps_are_implemented(self):
        guard_src = read(os.path.join("deploy", "release-guard", "guard.py"))
        steps = sorted(set(re.findall(r'self\._step\(\s*"([a-z_]+)"', guard_src)))
        self.assertGreaterEqual(len(steps), 9)
        for doc in (os.path.join("docs", "concepts", "release-guard.md"),
                    os.path.join("deploy", "release-guard", "README.md")):
            text = read(doc)
            for step in steps:
                self.assertIn(step, text, "%s does not document guard step `%s`" % (doc, step))


if __name__ == "__main__":
    unittest.main()
