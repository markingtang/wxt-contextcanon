"""Run the whole test suite: `python tests/run_all.py`."""

import os
import json
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
    print(json.dumps({"PASS": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped) - len(result.expectedFailures),
                      "FAIL": len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses),
                      "SKIP": len(result.skipped), "EXPECTED_FAILURE": len(result.expectedFailures),
                      "BLOCKED": 0, "TOTAL": result.testsRun}))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
