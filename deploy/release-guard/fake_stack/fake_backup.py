"""Fake backup command used by the release-guard test fixtures.

Stands in for whatever a real deployment uses (a volume snapshot, a dump,
a copy). The guard only cares whether it exits 0.
"""

from __future__ import annotations

import os
import sys

TARGET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backup.marker")


def main() -> int:
    with open(TARGET, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("backup completed\n")
    print("fake backup ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
