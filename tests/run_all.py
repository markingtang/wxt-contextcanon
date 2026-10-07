"""Run the whole test suite: `python tests/run_all.py`."""

import os
import sys
import unittest
import warnings

warnings.simplefilter("ignore", ResourceWarning)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    loader = unittest.TestLoader()
    tests_dir = os.path.join(ROOT, "tests")
    suite = loader.discover(tests_dir, pattern="test_*.py", top_level_dir=tests_dir)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
