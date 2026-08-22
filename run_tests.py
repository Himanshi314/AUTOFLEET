"""Run every test suite. No network, no API cost, no server to start.

    python run_tests.py            # everything
    python run_tests.py world      # one suite by name

Worth running before a demo: most of what is asserted here was a live defect at
some point, and several of them were invisible from the dashboard while they were
wrong. A green run does not prove the demo looks right — it proves the things
that previously broke quietly are still fixed.
"""

from __future__ import annotations

import sys
import unittest

SUITES = {
    "routing": "test_routing",   # the severity router's decision table
    "intent":  "test_intent",    # conflict check, gate, decisions, lifecycle
    "world":   "test_world",     # delivery lifecycle, ETA, clock, drift
    "agents":  "test_agents",    # fact-checker, prompt budget, ledger counter
    "server":  "test_server",    # HTTP layer and adversarial regressions
}


def main() -> int:
    wanted = sys.argv[1:] or list(SUITES)
    unknown = [w for w in wanted if w not in SUITES]
    if unknown:
        print(f"unknown suite(s): {', '.join(unknown)}")
        print(f"available: {', '.join(SUITES)}")
        return 2

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in wanted:
        suite.addTests(loader.loadTestsFromName(SUITES[name]))

    result = unittest.TextTestRunner(verbosity=1).run(suite)

    print()
    print("=" * 62)
    print(f"  suites   {', '.join(wanted)}")
    print(f"  tests    {result.testsRun}")
    print(f"  failures {len(result.failures)}   errors {len(result.errors)}"
          f"   skipped {len(result.skipped)}")
    print(f"  verdict  {'PASS' if result.wasSuccessful() else 'FAIL'}")
    print("=" * 62)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
