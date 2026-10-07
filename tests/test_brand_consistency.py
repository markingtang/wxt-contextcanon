"""Brand consistency gate.

The public name, the public command, the public MCP server name, the skill
name, the environment-variable prefix and the license are all things a stranger
sees in the first minute. They are also easy to half-rename, which is worse
than not renaming at all: a reader who sees two names assumes one of them is
stale.

This test therefore pins the whole public surface at once. It is intentionally
one small file - it is a consistency check, not a framework.

What it does NOT do: it does not police prose. It checks identifiers, files
and metadata, and it fails on any surviving old-brand token.

Scope note: it scans the working tree (tracked + untracked-but-not-ignored).
Git *history* is out of scope on purpose - the published history will be a
fresh squashed branch, and rewriting history is explicitly not this project's
job.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "packages"))

PROJECT_NAME = "WXT ContextCanon"
REPO_SLUG = "wxt-contextcanon"
PUBLIC_CLI = "contextcanon"
PUBLIC_MCP_NAME = "wxt-contextcanon"
PUBLIC_SKILL_NAME = "wxt-contextcanon"
ENV_PREFIX = "WXT_CONTEXTCANON_"
LICENSE_ID = "Apache-2.0"
AUTHOR = "Xiaotang"
DESCRIPTION = "Canonical context and state for AI agents."

# sha256 of the unmodified licence text published by the Apache Software
# Foundation (apache.org/licenses/LICENSE-2.0.txt). The URL is deliberately
# written without a scheme: this repository must contain no non-loopback host
# reference at all, and tools/prove_isolation.py enforces that.
# Pinning the hash is how we prove the licence terms were not reworded.
APACHE_2_0_SHA256 = "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"

# Tokens from the previous public brand. Case-insensitive: the bare short token
# catches every spelling of it, so one scan is enough. It is assembled from
# fragments so that this file does not itself contain the string it forbids -
# a self-referencing allowlist would weaken the gate it exists to provide.
OLD_BRAND_TOKEN = "pa" + "is"
OLD_BRAND_TOKENS = [OLD_BRAND_TOKEN]
EXPECTED_REPO_URL = "github.com/markingtang/wxt-contextcanon"
# The previous generic product name, retired at the same time. Also assembled.
OLD_PRODUCT_NAME_TOKENS = ["public " + "core", "public" + "-core", "public_" + "core"]
# The retired receipt files and internal task numbering must not ship either.
RETIRED_RECEIPT_PREFIX = "^" + "PA" + "IS_"
RETIRED_RECEIPT_SUFFIX = "_RECEIPT\\.md$"
RETIRED_READINESS = "^PUBLIC_RELEASE_READINESS\\.md$"
RETIRED_LICENSE_CANDIDATE = "^LICENSE-CANDIDATE\\.md$"
INTERNAL_TASK_ID = r"T-\d{8}-\d{3}"

# Internal symbols that are allowed to keep an old name, mapped to the reason.
# Empty on purpose: the migration reached zero, so nothing needs an exemption.
# If a future change must keep one, add it here with a real justification
# rather than loosening the scan.
ALLOWED_OLD_BRAND: dict = {}
ALLOWED_OLD_PRODUCT_NAME: dict = {}

BINARY_SUFFIXES = (".db", ".png", ".ico", ".woff", ".woff2", ".ttf", ".pyc", ".pdf", ".zip")


def public_files() -> list:
    """Every file a stranger could see: tracked + untracked, git-ignored excluded."""
    out = subprocess.run(
        ["git", "-C", ROOT, "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return sorted(p for p in out if p.strip())


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), "r", encoding="utf-8", errors="ignore") as handle:
        return handle.read()


def read_bytes(rel: str) -> bytes:
    with open(os.path.join(ROOT, rel), "rb") as handle:
        return handle.read()


class BrandConsistencyTests(unittest.TestCase):
    maxDiff = None

    # ------------------------------------------------------- old brand is gone

    def _scan(self, tokens, allowlist, label):
        offenders = []
        for rel in public_files():
            if rel.endswith(BINARY_SUFFIXES):
                continue
            lowered = rel.lower()
            if lowered in allowlist:
                continue
            text = read(rel).lower()
            for token in tokens:
                if token.lower() in text:
                    for number, line in enumerate(text.splitlines(), start=1):
                        if token.lower() in line:
                            offenders.append("%s:%d [%s] %s"
                                             % (rel, number, label, line.strip()[:110]))
                            break
        return offenders

    def test_no_old_public_brand_survives(self):
        offenders = self._scan(OLD_BRAND_TOKENS, ALLOWED_OLD_BRAND, "old-brand")
        self.assertEqual(offenders, [],
                         "old public brand found in the public tree:\n%s" % "\n".join(offenders))

    def test_no_old_product_name_survives(self):
        offenders = self._scan(OLD_PRODUCT_NAME_TOKENS, ALLOWED_OLD_PRODUCT_NAME, "old-name")
        self.assertEqual(offenders, [],
                         "retired product name found in the public tree:\n%s" % "\n".join(offenders))

    def test_no_internal_receipts_in_public_head(self):
        """Internal acceptance receipts live outside the repository, by design."""
        patterns = (RETIRED_RECEIPT_PREFIX, RETIRED_RECEIPT_SUFFIX, RETIRED_READINESS,
                    RETIRED_LICENSE_CANDIDATE)
        offenders = [rel for rel in public_files()
                     if any(re.search(p, rel) for p in patterns)]
        self.assertEqual(offenders, [],
                         "internal project artefacts must not ship in the public tree: %s"
                         % offenders)

    def test_no_internal_task_ids_in_public_text(self):
        offenders = []
        for rel in public_files():
            if rel.endswith(BINARY_SUFFIXES):
                continue
            if re.search(INTERNAL_TASK_ID, read(rel)):
                offenders.append(rel)
        self.assertEqual(offenders, [],
                         "internal task ids must not appear in a public document: %s" % offenders)

    # --------------------------------------------------------------- licensing

    def test_license_is_the_unmodified_official_apache_2(self):
        path = os.path.join(ROOT, "LICENSE")
        self.assertTrue(os.path.exists(path), "LICENSE is required")
        digest = hashlib.sha256(read_bytes("LICENSE")).hexdigest()
        self.assertEqual(digest, APACHE_2_0_SHA256,
                         "LICENSE must be the official Apache-2.0 text, unmodified "
                         "(expected sha256 %s, got %s)" % (APACHE_2_0_SHA256, digest))

    def test_notice_declares_attribution(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "NOTICE")), "NOTICE is required")
        notice = read("NOTICE")
        self.assertIn(PROJECT_NAME, notice)
        self.assertIn("Copyright 2026 Xiaotang", notice)
        self.assertIn("王小堂", notice)

    def test_license_candidate_document_is_gone(self):
        self.assertFalse(os.path.exists(os.path.join(ROOT, "LICENSE-CANDIDATE.md")),
                         "the licence is decided; the candidate document must not ship")

    def test_trademark_position_is_stated(self):
        path = os.path.join(ROOT, "TRADEMARKS.md")
        self.assertTrue(os.path.exists(path), "TRADEMARKS.md closes the naming/attribution blocker")
        text = read("TRADEMARKS.md")
        # compare on whitespace-normalised, emphasis-stripped text so the check
        # does not depend on where a sentence happens to wrap
        flat = re.sub(r"\s+", " ", text.replace("**", ""))
        self.assertIn("Xiaotang (王小堂)", flat, "must name the maintainer")
        self.assertIn("maintained by", flat.lower())
        self.assertIn("not a registered trademark", flat.lower(),
                      "must not claim a registered trademark")
        self.assertIn("Apache-2.0", flat, "must say the licence does not grant trademark rights")

    # ---------------------------------------------------------------- metadata

    def test_pyproject_metadata(self):
        text = read("pyproject.toml")
        self.assertIn('name = "%s"' % REPO_SLUG, text)
        self.assertIn('version = "0.1.1"', text)
        self.assertIn('description = "%s"' % DESCRIPTION, text)
        self.assertIn(LICENSE_ID, text)
        self.assertIn('name = "%s"' % AUTHOR, text)
        self.assertIn('%s = "contextcanon_cli.cli:main"' % PUBLIC_CLI, text)
        for package in ("contextcanon_cli", "contextcanon_config",
                        "profile_core", "registry_core", "mcp_server"):
            self.assertIn('"%s"' % package, text)

    def test_repository_url_is_real_and_unique(self):
        """The repository now exists; only the real, agreed URL may appear."""
        offenders = []
        found_expected = False
        for rel in public_files():
            if rel.endswith(BINARY_SUFFIXES):
                continue
            for number, line in enumerate(read(rel).splitlines(), start=1):
                m = re.search(r"github\.com/([A-Za-z0-9_-]+)/([A-Za-z0-9_.-]+)", line)
                if m:
                    owner = m.group(1)
                    repo = m.group(2)
                    if repo.endswith(".git"):
                        repo = repo[:-4]
                    repo = repo.rstrip(".")
                    if (owner, repo) != ("markingtang", "wxt-contextcanon"):
                        offenders.append("%s:%d %s" % (rel, number, line.strip()[:110]))
                    else:
                        found_expected = True
        self.assertTrue(found_expected,
                         "the real repository URL must appear: %s" % EXPECTED_REPO_URL)
        self.assertEqual(offenders, [],
                         "only the real repository URL may appear; found:\n%s"
                         % "\n".join(offenders))

    # ------------------------------------------------------------ public surface

    def test_public_entrypoints_exist(self):
        for rel in (PUBLIC_CLI, PUBLIC_CLI + ".cmd"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), "%s must ship" % rel)

    def test_posix_launcher_is_executable_in_the_index(self):
        """The POSIX launcher must carry mode 100755 in the git index.

        This is checked against HEAD, not the filesystem, on purpose. On Windows
        `core.fileMode` defaults to false, so git ignores the filesystem's
        execute bit entirely: a launcher can be chmod +x locally and still be
        recorded as 100644, which then fails with "Permission denied" for the
        first person who clones it on macOS or Linux. The README's very first
        command is `./contextcanon ...`, so this bit is part of the product.

        A test that only looked at the local file would pass on the machine that
        broke it, so it would not be a regression test at all.
        """
        proc = subprocess.run(["git", "-C", ROOT, "ls-tree", "HEAD", PUBLIC_CLI],
                              capture_output=True, text=True, check=True)
        line = proc.stdout.strip()
        self.assertTrue(line, "git ls-tree returned nothing for %s" % PUBLIC_CLI)
        mode = line.split()[0]
        self.assertEqual(mode, "100755",
                         "%s must be mode 100755 in the index, found %s. On a fresh "
                         "macOS/Linux clone the README's first command would fail with "
                         "Permission denied. Fix with: git update-index --chmod=+x %s"
                         % (PUBLIC_CLI, mode, PUBLIC_CLI))

    def test_launchers_invoke_the_public_module(self):
        for rel in (PUBLIC_CLI, PUBLIC_CLI + ".cmd"):
            text = read(rel)
            self.assertIn("contextcanon_cli", text,
                          "%s must launch the public module" % rel)
            self.assertNotIn("p" + "ais_cli", text,
                             "%s still references the retired module" % rel)

    def test_documented_launcher_actually_runs(self):
        """The documented entry point must work, not merely exist.

        A launcher that cannot resolve its own package dies with
        "No module named ...", which reads like a packaging bug rather than the
        path bug it is, and it is invisible to every other gate. So execute the
        launcher this platform's README actually tells the user to run.
        """
        if os.name == "nt":
            launcher = os.path.join(ROOT, PUBLIC_CLI + ".cmd")
            if not os.path.exists(launcher):
                self.skipTest("no Windows launcher to execute")
            proc = subprocess.run('"%s" --version' % launcher, shell=True, cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
        else:
            launcher = os.path.join(ROOT, PUBLIC_CLI)
            proc = subprocess.run([launcher, "--version"], cwd=ROOT,
                                  capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 0,
                         "the documented launcher failed:\n%s"
                         % ((proc.stderr or "")[-600:] or (proc.stdout or "")[-600:]))
        self.assertIn(REPO_SLUG, proc.stdout or "",
                      "the launcher must report the project slug")

    def test_posix_launcher_uses_the_platform_pythonpath_separator(self):
        """Windows Python splits PYTHONPATH with ';', not ':'.

        The POSIX launcher is documented for Git Bash on Windows, where the
        interpreter is a native Windows build. Joining with ':' there yields one
        nonexistent entry and the launcher cannot import its own package. This
        check is static so it also holds on machines where bash is unavailable.
        """
        text = read(PUBLIC_CLI)
        self.assertIn("MINGW", text, "the launcher must detect a Windows POSIX shell")
        self.assertIn("cygpath", text, "the launcher must translate the path for Windows Python")
        self.assertIn("SEP=';'", text, "the launcher must use the Windows separator")
        self.assertNotIn('PYTHONPATH="$ROOT/packages:${PYTHONPATH:-}"', text,
                         "the POSIX-only separator is broken under Git Bash")

    def test_public_packages_exist(self):
        for package in ("contextcanon_cli", "contextcanon_config"):
            self.assertTrue(os.path.isdir(os.path.join(ROOT, "packages", package)),
                            "packages/%s must ship" % package)
        for package in ("profile_core", "registry_core", "mcp_server"):
            self.assertTrue(os.path.isdir(os.path.join(ROOT, "packages", package)),
                            "packages/%s must ship" % package)

    def test_cli_prog_name(self):
        from contextcanon_cli.cli import build_parser
        parser = build_parser()
        self.assertEqual(parser.prog, PUBLIC_CLI)

    def test_cli_reports_the_project_slug(self):
        from contextcanon_config import DEFAULTS
        self.assertEqual(DEFAULTS["server"]["name"], REPO_SLUG)
        self.assertEqual(DEFAULTS["deploy"]["project_name"], REPO_SLUG)

    def test_mcp_server_name(self):
        import tempfile
        from mcp_server.server import build_server
        tmp = tempfile.mkdtemp(prefix="wxt-brand-")
        try:
            server = build_server(None, tmp)
            init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
            self.assertEqual(init["result"]["serverInfo"]["name"], PUBLIC_MCP_NAME)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skill_name(self):
        rel = os.path.join("skills", "contextcanon", "SKILL.md")
        self.assertTrue(os.path.exists(os.path.join(ROOT, rel)), "the skill must ship")
        match = re.search(r"^name:\s*(\S+)\s*$", read(rel), re.MULTILINE)
        self.assertIsNotNone(match, "SKILL.md needs a frontmatter name")
        self.assertEqual(match.group(1), PUBLIC_SKILL_NAME)

    def test_environment_variable_prefix(self):
        from contextcanon_config import ENV_MAP
        self.assertTrue(ENV_MAP, "ENV_MAP must not be empty")
        wrong = [name for name in ENV_MAP if not name.startswith(ENV_PREFIX)]
        self.assertEqual(wrong, [],
                         "every public environment variable must use the %s prefix: %s"
                         % (ENV_PREFIX, wrong))

    def test_env_example_uses_the_prefix(self):
        text = read(".env.example")
        names = re.findall(r"^([A-Z][A-Z0-9_]*)\s*=", text, re.MULTILINE)
        self.assertTrue(names, ".env.example must declare variables")
        wrong = [n for n in names if not n.startswith(ENV_PREFIX)]
        self.assertEqual(wrong, [], "wrong prefix in .env.example: %s" % wrong)

    def test_readme_first_screen_states_the_project(self):
        head = read("README.md")
        first_screen = head[:head.index("## Why it exists")]
        self.assertIn("# " + PROJECT_NAME, first_screen)
        self.assertIn(DESCRIPTION, first_screen)
        self.assertIn("Public release", first_screen)


if __name__ == "__main__":
    unittest.main()
