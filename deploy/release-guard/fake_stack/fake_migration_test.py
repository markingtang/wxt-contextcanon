"""Fake legacy migration test used by the release-guard fixtures.

Real deployments run their legacy migration path here before rollout. The fake
simply proves the guard calls the step and fails closed when it exits non-zero.

    FAKE_MIGRATION_FAIL=1 forces a failure, which the tests use to prove
    fail-closed behaviour on a partial failure.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    if os.environ.get("FAKE_MIGRATION_FAIL") == "1":
        print("fake migration test FAILED (forced)", file=sys.stderr)
        return 1
    print("fake migration legacy test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
