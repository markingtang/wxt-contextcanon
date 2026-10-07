"""Credential-shaped fixtures, assembled at run time.

This module lives *inside* the scanned repository, so it must contain no literal
credential shape of its own - only pieces that are harmless alone. Every string
the adversarial scanner tests need is built here from parts, so the repository
needs no allow-marker for its own test code.
"""


def aws_access_key():
    return "AKIA" + "IOSFODNN7EXAMPLE"


def github_token():
    return "ghp_" + "A" * 36


def slack_token():
    return "xoxb-" + "123456789012" + "-" + "abcdefghijklmnop"


def google_api_key():
    return "AIza" + "B" * 35


def assignment_line(marker=""):
    """A ``key = value`` credential assignment, optionally allow-marked."""
    name = "api" + "_" + "key"
    value = "supersecret" + "value" + "12345"
    return '%s = "%s"%s' % (name, value, marker)


def private_ip():
    return ".".join(["192", "168", "31", "77"])


def unix_home_path():
    return "/home/" + "johndoe" + "/notes"


def mac_address():
    return ":".join(["00", "1B", "44", "11", "3A", "B7"])


def email_address():
    return "alex" + "." + "person" + "@" + "somecorp" + ".io"
