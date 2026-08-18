"""Unit tests for routing.py — one per row of the Part 1 routing table.

    python -m unittest test_routing -v
"""

from __future__ import annotations

import unittest

from autofleet.routing import ALL_AGENTS, NO_REASSIGNMENT, plan_chain


def _disruption(disables_driver=False, needs_replacement_stock=False,
                 needs_customer_decision=False):
    return {
        "disables_driver": disables_driver,
        "needs_replacement_stock": needs_replacement_stock,
        "needs_customer_decision": needs_customer_decision,
    }


def _risk(band="nominal"):
    return {"band": band}


def _ranking(candidates):
    return {"candidates": candidates, "evaluated": max(len(candidates), 1)}


def _candidate(driver_id, name="Driver"):
    return {"driver_id": driver_id, "name": name}


class RoutingTableTests(unittest.TestCase):

    def test_row1_internal_only_no_eta_shift_runs_zero_agents(self):
        result = plan_chain(
            _disruption(), _risk("nominal"),
            _ranking([_candidate("DR-02", "Incumbent")]),
            incumbent_id="DR-02", eta_delta_minutes=2.0, current_eta_minutes=60.0,
        )
        self.assertEqual(result["agents"], [])
        self.assertEqual(result["path"], "deterministic")
        self.assertFalse(result["escalate"])
        self.assertEqual(result["saved"], len(ALL_AGENTS))

    def test_row1_significant_relative_eta_shift_is_not_deterministic(self):
        result = plan_chain(
            _disruption(), _risk("nominal"),
            _ranking([_candidate("DR-02", "Incumbent")]),
            incumbent_id="DR-02", eta_delta_minutes=6.0, current_eta_minutes=12.0,
        )
        self.assertNotEqual(result["path"], "deterministic")

    def test_row2_customer_decision_incumbent_keeps_job_runs_partial_chain(self):
        result = plan_chain(
            _disruption(needs_customer_decision=True), _risk("nominal"),
            _ranking([_candidate("DR-02", "Incumbent")]),
            incumbent_id="DR-02", eta_delta_minutes=1.0, current_eta_minutes=30.0,
        )
        self.assertEqual(set(result["agents"]), set(NO_REASSIGNMENT))
        self.assertEqual(len(result["agents"]), 4)
        self.assertEqual(result["path"], "partial chain")
        self.assertEqual(result["saved"], 2)

    def test_row3a_disabled_driver_runs_full_chain(self):
        result = plan_chain(
            _disruption(disables_driver=True), _risk("critical"),
            _ranking([_candidate("DR-11", "Replacement")]),
            incumbent_id="DR-02", eta_delta_minutes=8.0, current_eta_minutes=20.0,
        )
        self.assertEqual(set(result["agents"]), set(ALL_AGENTS))
        self.assertEqual(result["path"], "full chain")
        self.assertEqual(result["saved"], 0)

    def test_row3b_better_driver_outranks_incumbent_runs_full_chain(self):
        result = plan_chain(
            _disruption(), _risk("elevated"),
            _ranking([_candidate("DR-05", "Better driver"), _candidate("DR-02", "Incumbent")]),
            incumbent_id="DR-02", eta_delta_minutes=3.0, current_eta_minutes=25.0,
        )
        self.assertEqual(set(result["agents"]), set(ALL_AGENTS))
        self.assertEqual(result["path"], "full chain")
        self.assertIn("outrank", result["reason"])

    def test_row4_needs_replacement_stock_runs_full_chain(self):
        result = plan_chain(
            _disruption(needs_replacement_stock=True), _risk("critical"),
            _ranking([_candidate("DR-16", "Depot run")]),
            incumbent_id="DR-04", eta_delta_minutes=15.0, current_eta_minutes=40.0,
        )
        self.assertEqual(set(result["agents"]), set(ALL_AGENTS))
        self.assertEqual(result["path"], "full chain")

    def test_row5_no_eligible_driver_escalates(self):
        result = plan_chain(
            _disruption(disables_driver=True), _risk("critical"), _ranking([]),
            incumbent_id="DR-02", eta_delta_minutes=20.0, current_eta_minutes=25.0,
        )
        self.assertEqual(result["agents"], [])
        self.assertEqual(result["path"], "escalate")
        self.assertTrue(result["escalate"])
        self.assertEqual(result["saved"], len(ALL_AGENTS))


class SkippedAgentReasonsTests(unittest.TestCase):

    def test_every_dropped_agent_has_a_reason(self):
        result = plan_chain(
            _disruption(), _risk("nominal"),
            _ranking([_candidate("DR-02", "Incumbent")]),
            incumbent_id="DR-02", eta_delta_minutes=0.0, current_eta_minutes=30.0,
        )
        dropped = set(ALL_AGENTS) - set(result["agents"])
        reasons = {s["agent"]: s["reason"] for s in result["skipped"]}
        self.assertEqual(dropped, set(reasons.keys()))
        for reason in reasons.values():
            self.assertTrue(reason and isinstance(reason, str))


if __name__ == "__main__":
    unittest.main(verbosity=2)
