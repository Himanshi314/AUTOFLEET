"""Tests for the chain's own safeguards.

Three things that were each wrong in a live build, and each wrong in a way that
made the system look MORE trustworthy than it was:

  · the fact-checker parsed "D-102" as the number -102, so every incident failed
    its own check — and once the ids were handled, a model writing "D‑101" with a
    NON-BREAKING HYPHEN slipped past the fix and flagged the Coordinator for
    fabricating "101" on every single incident;
  · the routing-efficiency counter was read before the last agent ran, so a
    six-agent chain logged as five calls — understating calls used, which
    overstates the saving the pitch claims;
  · a courier already carrying a job was dropped before scoring, so the
    dashboard could not say why a courier visible on the map was not considered.

    python test_agents.py
"""

from __future__ import annotations

import unittest

from autofleet.agents import (RANKER, _candidates_for_prompt, _numbers_in,
                              verify_numbers)
from autofleet.llm import LLM
from autofleet.routing import ALL_AGENTS
from autofleet.world import DISRUPTIONS, World


class FactCheckerTests(unittest.TestCase):
    """Every number the Coordinator states must trace to one it was given."""

    def test_a_clean_summary_passes(self):
        out = verify_numbers("D-101 reassigned to DR-12, ETA 28 minutes.", [28.0])
        self.assertTrue(out["passed"])
        self.assertEqual(out["unverified"], [])

    def test_an_ascii_identifier_is_not_read_as_a_number(self):
        """"D-102" parsed as -102 and failed every incident."""
        self.assertNotIn(-102.0, _numbers_in("D-102 handled by DR-11."))

    def test_typographic_dashes_in_identifiers_are_normalised(self):
        """gpt-oss writes D‑101 with U+2011. The ASCII-only pattern missed it and
        the Coordinator was flagged for fabricating 101 on every incident."""
        for dash in ("‐", "‑", "‒", "–", "—",
                     "―", "−"):
            text = f"Delivery D{dash}101 reassigned, ETA 28 minutes."
            out = verify_numbers(text, [28.0])
            self.assertTrue(out["passed"],
                            f"U+{ord(dash):04X} leaked an id into the numbers: "
                            f"{out['unverified']}")

    def test_no_break_spaces_inside_numbers_are_handled(self):
        text = "Avoided 23.8 km and 0.51 kg CO2e, ETA 28 min."
        out = verify_numbers(text, [23.8, 0.51, 28.0])
        self.assertTrue(out["passed"], out["unverified"])

    def test_a_fabricated_figure_is_still_caught(self):
        out = verify_numbers(
            "D‑101 reassigned, ETA 28 minutes, saving 99.9 km.", [28.0])
        self.assertFalse(out["passed"])
        self.assertIn(99.9, out["unverified"])

    def test_a_fabricated_percentage_is_still_caught(self):
        """0.03 and 0.14 both round to 0, so integer rounding must not apply
        below 1 or any two small fractions match each other."""
        out = verify_numbers("Risk fell to 3% after reassignment.", [0.14])
        self.assertFalse(out["passed"])

    def test_comma_grouped_numbers_are_read_whole(self):
        self.assertIn(1270.0, _numbers_in("1,270 km avoided"))
        self.assertNotIn(270.0, _numbers_in("1,270 km avoided"))

    def test_rounding_a_source_value_is_accepted(self):
        for said, source in (("21 minutes", 21.0), ("27.4 km", 27.44),
                             ("28 min", 27.9)):
            out = verify_numbers(f"ETA {said}.", [source])
            self.assertTrue(out["passed"], f"{said} vs {source}")

    def test_small_integers_in_prose_are_not_treated_as_claims(self):
        out = verify_numbers(
            "One failed attempt prevented and a second trip avoided.", [])
        self.assertTrue(out["passed"])

    def test_the_check_reports_how_many_claims_it_looked_at(self):
        out = verify_numbers("ETA 28 min, 23.8 km, 0.51 kg.", [28.0, 23.8, 0.51])
        self.assertGreaterEqual(out["claims_checked"], 3)


class PromptBudgetTests(unittest.TestCase):
    """The Resource prompt was 13,170 chars against 1,200-2,500 for every other
    agent, because each candidate carried a ~1.1k per-feature breakdown that
    only the UI needs. That was a third of Groq's per-minute budget in one call."""

    def _ranking(self):
        w = World()
        dis = DISRUPTIONS["bike_breakdown"]
        return RANKER.rank(w.eligible_drivers("D-101", dis),
                           w.build_requirement("D-101", dis))

    def test_only_the_winning_candidate_keeps_its_breakdown(self):
        cands = self._ranking()["candidates"][:5]
        trimmed = _candidates_for_prompt(cands)
        self.assertIn("contributions", trimmed[0],
                      "the pick must still be explainable in feature terms")
        for c in trimmed[1:]:
            self.assertNotIn("contributions", c)

    def test_the_fields_needed_to_justify_a_pick_all_survive(self):
        trimmed = _candidates_for_prompt(self._ranking()["candidates"][:5])
        for field in ("driver_id", "name", "suitability", "decisive_factor",
                      "distance_km", "eta_minutes", "on_time_rate"):
            for c in trimmed:
                self.assertIn(field, c, field)

    def test_trimming_actually_saves_a_material_amount(self):
        import json
        cands = self._ranking()["candidates"][:5]
        full = len(json.dumps(cands))
        trim = len(json.dumps(_candidates_for_prompt(cands)))
        self.assertLess(trim, full * 0.7,
                        f"expected a substantial cut, got {full} -> {trim}")


class RoutingEfficiencyLedgerTests(unittest.TestCase):
    """used + saved must equal the number of roles available, or the cost claim
    in the pitch is wrong. It used to be read before the Coordinator ran."""

    def _entry(self, disruption):
        w = World()
        events = []
        from autofleet.agents import run_chain
        run_chain(w, LLM(), delivery_id="D-101", disruption_key=disruption,
                  trigger="test", emit=events.append)
        impact = next((e for e in events if e.get("type") == "impact"), None)
        return impact["entry"] if impact else None, events

    def test_a_full_chain_accounts_for_every_role(self):
        entry, events = self._entry("bike_breakdown")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["llm_calls_used"] + entry["llm_calls_saved"],
                         len(ALL_AGENTS))

    def test_used_matches_the_agents_that_actually_ran(self):
        entry, events = self._entry("bike_breakdown")
        ran = sum(1 for e in events if e.get("type") == "agent_done")
        self.assertEqual(entry["llm_calls_used"], ran)

    def test_a_partial_chain_records_a_real_saving(self):
        entry, events = self._entry("customer_not_home")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["llm_calls_used"] + entry["llm_calls_saved"],
                         len(ALL_AGENTS))
        skipped = sum(1 for e in events if e.get("type") == "agent_skipped")
        self.assertEqual(entry["llm_calls_saved"], skipped,
                         "saved must equal the roles the router actually skipped")


class CandidateVisibilityTests(unittest.TestCase):
    """A courier the operator can see on the map must get a stated reason."""

    def test_a_courier_on_another_job_is_rejected_out_loud(self):
        w = World()
        dis = DISRUPTIONS["bike_breakdown"]
        busy = w.deliveries["D-103"]["driver_id"]
        target = "D-101"
        ranking = RANKER.rank(w.eligible_drivers(target, dis),
                              w.build_requirement(target, dis))
        rejected = {r["driver_id"]: r["reason"] for r in ranking["rejected"]}
        self.assertIn(busy, rejected,
                      "a courier mid-run vanished instead of being explained")
        self.assertIn("already carrying", rejected[busy])

    def test_a_busy_courier_is_never_selectable(self):
        w = World()
        dis = DISRUPTIONS["bike_breakdown"]
        busy = w.deliveries["D-103"]["driver_id"]
        ranking = RANKER.rank(w.eligible_drivers("D-101", dis),
                              w.build_requirement("D-101", dis))
        self.assertNotIn(busy, [c["driver_id"] for c in ranking["candidates"]])

    def test_the_incumbent_is_not_rejected_for_carrying_this_very_job(self):
        """The courier already on D-101 must stay eligible for D-101 when the
        disruption does not disable them."""
        w = World()
        dis = DISRUPTIONS["customer_not_home"]      # does not disable
        incumbent = w.deliveries["D-101"]["driver_id"]
        ranking = RANKER.rank(w.eligible_drivers("D-101", dis),
                              w.build_requirement("D-101", dis))
        ids = [c["driver_id"] for c in ranking["candidates"]]
        self.assertIn(incumbent, ids,
                      "the incumbent was rejected for holding their own job")

    def test_every_rejection_states_a_reason(self):
        w = World()
        dis = DISRUPTIONS["bike_breakdown"]
        ranking = RANKER.rank(w.eligible_drivers("D-101", dis),
                              w.build_requirement("D-101", dis))
        for r in ranking["rejected"]:
            self.assertTrue(r.get("reason"), r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
