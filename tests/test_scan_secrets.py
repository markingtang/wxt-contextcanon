"""Adversarial tests for tools/scan_secrets.py.

These exist because the scanner is the gate that keeps the repository clean.
A clean run only means something if the scanner actually fails on planted
secrets - so every test here plants a known-bad string and demands a finding.

The planted strings are assembled at run time by ``secret_fixtures`` because
this file is itself scanned: a literal credential here would make the gate fail
on its own test suite.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import scan_secrets  # noqa: E402
import secret_fixtures as fx  # noqa: E402


def _write(root, name, text):
    path = os.path.join(root, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    return path


def _classes(report):
    return [f["class"] for f in report["findings"]]


class ScannerAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="contextcanon-scan-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_key_on_a_line_saying_eg_is_still_a_secret(self):
        _write(self.tmp, "README.md", fx.assignment_line("  # e.g. your key goes here") + "\n")
        report = scan_secrets.scan(self.tmp)
        self.assertFalse(report["pass"])
        self.assertIn("REAL_SECRET", _classes(report))

    def test_private_ip_with_the_word_example_is_not_auto_safe(self):
        _write(self.tmp, "registry.md", "nas = %s  # example of a private ip\n" % fx.private_ip())
        report = scan_secrets.scan(self.tmp)
        self.assertFalse(report["pass"])
        self.assertIn("PRIVATE_IDENTIFIER", _classes(report))

    def test_common_credential_shapes_are_detected(self):
        _write(self.tmp, "tokens.txt", "\n".join([
            "aws = " + fx.aws_access_key(),
            "github = " + fx.github_token(),
            "slack = " + fx.slack_token(),
            "google = " + fx.google_api_key(),
        ]) + "\n")
        report = scan_secrets.scan(self.tmp)
        self.assertFalse(report["pass"])
        patterns = {f["pattern"] for f in report["findings"]}
        for expected in ("aws-access-key", "github-token", "slack-token", "google-api-key"):
            self.assertIn(expected, patterns)
        self.assertTrue(all(f["class"] == "REAL_SECRET" for f in report["findings"]))

    def test_private_identifiers_are_detected(self):
        _write(self.tmp, "notes.md", "\n".join([
            "home = " + fx.unix_home_path(),
            "mac = " + fx.mac_address(),
            "mail = " + fx.email_address(),
        ]) + "\n")
        report = scan_secrets.scan(self.tmp)
        self.assertFalse(report["pass"])
        patterns = {f["pattern"] for f in report["findings"]}
        for expected in ("unix-home-path", "mac-address", "email-address"):
            self.assertIn(expected, patterns)

    def test_explicit_allow_marker_is_narrow(self):
        _write(self.tmp, "allow.md", fx.assignment_line("  WXT_SCAN_ALLOW:credential-assignment") + "\n")
        report = scan_secrets.scan(self.tmp)
        self.assertTrue(report["pass"], _classes(report))
        self.assertIn("SAFE_EXAMPLE", _classes(report))

        # A marker naming a different pattern must NOT disarm this one.
        _write(self.tmp, "allow2.md",
               fx.aws_access_key() + "  WXT_SCAN_ALLOW:credential-assignment\n")
        report2 = scan_secrets.scan(self.tmp)
        self.assertFalse(report2["pass"], "a marker must only exempt the pattern it names")

    def test_no_blanket_file_exemption(self):
        _write(self.tmp, "SECURITY.md", "aws = " + fx.aws_access_key() + "\n")
        report = scan_secrets.scan(self.tmp)
        self.assertFalse(report["pass"], "a file that discusses scanning is still scanned")

    def test_history_scan_catches_a_deleted_secret(self):
        repo = os.path.join(self.tmp, "histrepo")
        os.makedirs(repo, exist_ok=True)

        def git(*args):
            subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True)

        git("init")
        git("config", "user.email", "tester@example.invalid")
        git("config", "user.name", "Tester")
        _write(repo, "config.txt", "aws = " + fx.aws_access_key() + "\n")
        git("add", "-A")
        git("commit", "-m", "add a secret")
        _write(repo, "config.txt", "aws = (removed)\n")
        git("add", "-A")
        git("commit", "-m", "remove the secret")

        # The working tree is clean now ...
        working = scan_secrets.scan(repo)
        self.assertTrue(working["pass"], _classes(working))
        # ... but the secret is still in history, and history mode finds it.
        history = scan_secrets.scan_history(repo)
        self.assertFalse(history["pass"])
        self.assertTrue(any(f["class"] == "REAL_SECRET" for f in history["findings"]))


if __name__ == "__main__":
    unittest.main()
