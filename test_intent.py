"""Tests for the pre-commit conflict check.

A conflict checker that reports the wrong verdict is worse than not having one:
it launders a bad decision through a credibility surface. So each evaluator is
tested on both sides of its boundary, and the gate is tested for the two things
that actually matter — that a hard violation blocks a commit, and that a soft
one does not.

    python test_intent.py
"""

from __future__ import annotations

import unittest

from autofleet.intent import IntentRegister

CLOCK = 17 * 60 + 30  # 17:30 in the simulated day


def ctx(*, shift=180.0, cold=0.0, promised=60.0, doses=0, cold_chain=False,
        original="Priya Nair"):
    return {
        "clock_minutes": CLOCK,
        "driver": {"shift_remaining_minutes": shift},
        "delivery": {
            "cold_minutes_remaining": cold,
            "promised_minutes": promised,
            "doses": doses,
            "cold_chain": cold_chain,
            "original_driver_name": original,
            "driver_name": original,
        },
    }


def action(kind="reassign", eta=20.0, journey=None, approach_km=1.0,
           driver_id="DR-12", driver_name="Meera Joshi"):
    return {
        "kind": kind,
        "delivery_id": "D-101",
        "driver_id": driver_id,
        "driver_name": driver_name,
        "eta_minutes": eta,
        "journey_minutes": journey if journey is not None else eta,
        "approach_km": approach_km,
    }


class DeadlineTests(unittest.TestCase):
    def register(self):
        r = IntentRegister()
        r.add(holder="Ananya Iyer", holder_type="recipient",
              kind="delivery_deadline", statement="Nothing after 18:00.",
              params={"by_minutes": 18 * 60}, hardness="hard", scope="D-101")
        return r

    def test_comfortably_inside_the_window_is_satisfied(self):
        # 17:30 + 20 min = 17:50, ten minutes clear of 18:00 -> but the
        # at_risk band is 10 min, so this is the boundary. Use 15 to be inside.
        out = self.register().check(action=action(eta=15.0), ctx=ctx())
        self.assertEqual(out["results"][0]["verdict"], "satisfied")
        self.assertTrue(out["clear"])

    def test_arriving_after_the_cutoff_violates_and_blocks(self):
        out = self.register().check(action=action(eta=45.0), ctx=ctx())
        r = out["results"][0]
        self.assertEqual(r["verdict"], "violated")
        self.assertEqual(r["evidence"]["deadline"], "18:00")
        self.assertEqual(r["evidence"]["projected_arrival"], "18:15")
        self.assertEqual(r["evidence"]["margin_minutes"], -15.0)
        self.assertFalse(out["clear"], "a hard violation must block the commit")

    def test_thin_margin_is_flagged_without_blocking(self):
        out = self.register().check(action=action(eta=25.0), ctx=ctx())
        self.assertEqual(out["results"][0]["verdict"], "at_risk")
        self.assertTrue(out["clear"], "at_risk is a warning, not a veto")


class ShiftLimitTests(unittest.TestCase):
    def register(self, scope="DR-12"):
        r = IntentRegister()
        r.add(holder="Meera Joshi", holder_type="courier", kind="shift_limit",
              statement="Leave me 30 minutes at the end of my shift.",
              params={"buffer_minutes": 30.0}, hardness="hard", scope=scope)
        return r

    def test_job_leaving_the_requested_buffer_is_fine(self):
        # 40 min job, 180 min shift -> 140 min left, well past a 30 min buffer.
        out = self.register().check(action=action(journey=40.0), ctx=ctx(shift=180.0))
        self.assertEqual(out["results"][0]["verdict"], "satisfied")

    def test_a_job_that_FITS_but_eats_the_buffer_still_violates(self):
        """The distinction that makes this an intent and not the ranker's
        feasibility constraint: 50 min of work inside a 70 min shift is
        perfectly possible, and still breaks what the rider asked for."""
        out = self.register().check(action=action(journey=50.0), ctx=ctx(shift=70.0))
        r = out["results"][0]
        self.assertEqual(r["verdict"], "violated")
        self.assertEqual(r["evidence"]["buffer_left_minutes"], 20.0)
        self.assertEqual(r["evidence"]["requested_buffer_minutes"], 30.0)
        self.assertEqual(r["evidence"]["margin_minutes"], -10.0)
        self.assertFalse(out["clear"])

    def test_a_couriers_intent_does_not_bind_a_different_courier(self):
        """Suresh's shift limit says nothing about a job handed to Meera."""
        r = self.register(scope="DR-11")           # Suresh's intent
        out = r.check(action=action(driver_id="DR-12", journey=999.0),
                      ctx=ctx(shift=5.0))
        self.assertEqual(out["checked"], 0,
                         "another courier's shift limit must not be evaluated")
        self.assertTrue(out["clear"])


class ColdWindowTests(unittest.TestCase):
    def register(self):
        r = IntentRegister()
        r.add(holder="Anekal PHC", holder_type="payload", kind="cold_window",
              statement="We need 20 minutes to receive it into the cold room.",
              params={"handling_margin_minutes": 20.0},
              hardness="hard", scope="D-101")
        return r

    def test_arrival_with_ample_handling_margin(self):
        out = self.register().check(action=action(eta=30.0),
                                    ctx=ctx(cold=90.0, doses=240))
        self.assertEqual(out["results"][0]["verdict"], "satisfied")

    def test_arriving_inside_the_window_but_without_margin_violates(self):
        """Feasible — it arrives before the window shuts — and still refused,
        because the facility needs time to receive it."""
        out = self.register().check(action=action(eta=70.0),
                                    ctx=ctx(cold=80.0, doses=240))
        r = out["results"][0]
        self.assertEqual(r["verdict"], "violated")
        self.assertEqual(r["evidence"]["doses"], 240)
        self.assertEqual(r["evidence"]["window_left_on_arrival_minutes"], 10.0)
        self.assertEqual(r["evidence"]["margin_minutes"], -10.0)
        self.assertFalse(out["clear"])


class SubstitutionTests(unittest.TestCase):
    def register(self, hardness="hard"):
        r = IntentRegister()
        r.add(holder="Rohan Mehta", holder_type="recipient",
              kind="no_substitute_handoff",
              statement="Only the courier I was told about.",
              params={}, hardness=hardness, scope="D-101")
        return r

    def test_reassignment_violates_it(self):
        out = self.register().check(action=action(kind="reassign"), ctx=ctx())
        self.assertEqual(out["results"][0]["verdict"], "violated")
        self.assertFalse(out["clear"])

    def test_retaining_the_original_courier_satisfies_it(self):
        out = self.register().check(action=action(kind="retain"), ctx=ctx())
        self.assertEqual(out["results"][0]["verdict"], "satisfied")
        self.assertTrue(out["clear"])

    def test_a_soft_version_records_the_cost_but_still_allows_commit(self):
        out = self.register(hardness="soft").check(
            action=action(kind="reassign"), ctx=ctx())
        self.assertEqual(len(out["violations"]), 1)
        self.assertEqual(len(out["blocking"]), 0)
        self.assertTrue(out["clear"], "a soft violation is a disclosed cost, not a veto")


class OperationsTests(unittest.TestCase):
    def test_sla_breach_is_reported(self):
        r = IntentRegister()
        r.add(holder="Operations", holder_type="operations", kind="sla_promise",
              statement="Do not breach the promised window.", params={},
              hardness="soft", scope="*")
        out = r.check(action=action(eta=75.0), ctx=ctx(promised=60.0))
        res = out["results"][0]
        self.assertEqual(res["verdict"], "violated")
        self.assertEqual(res["evidence"]["margin_minutes"], -15.0)
        self.assertTrue(out["clear"], "soft ops preference must not block")

    def test_approach_ceiling(self):
        r = IntentRegister()
        r.add(holder="Operations", holder_type="operations",
              kind="approach_ceiling", statement="Cap empty running at 6 km.",
              params={"max_approach_km": 6.0}, hardness="hard", scope="*")
        ok = r.check(action=action(approach_km=3.2), ctx=ctx())
        bad = r.check(action=action(approach_km=9.4), ctx=ctx())
        self.assertEqual(ok["results"][0]["verdict"], "satisfied")
        self.assertEqual(bad["results"][0]["verdict"], "violated")
        self.assertEqual(bad["results"][0]["evidence"]["margin_km"], -3.4)


class RegisterBehaviourTests(unittest.TestCase):
    def test_deactivating_an_intent_removes_the_conflict(self):
        """This is the interaction a judge performs, so it is tested."""
        r = IntentRegister()
        i = r.add(holder="Ananya Iyer", holder_type="recipient",
                  kind="delivery_deadline", statement="Nothing after 18:00.",
                  params={"by_minutes": 18 * 60}, hardness="hard", scope="D-101")
        before = r.check(action=action(eta=45.0), ctx=ctx())
        self.assertFalse(before["clear"])
        r.set_active(i.id, False)
        after = r.check(action=action(eta=45.0), ctx=ctx())
        self.assertTrue(after["clear"])
        self.assertEqual(after["checked"], 0)

    def test_fleet_wide_scope_applies_to_any_delivery(self):
        r = IntentRegister()
        r.add(holder="Operations", holder_type="operations", kind="sla_promise",
              statement="Windows matter.", params={}, hardness="soft", scope="*")
        out = r.check(action=dict(action(), delivery_id="D-999"), ctx=ctx())
        self.assertEqual(out["checked"], 1)

    def test_other_deliveries_intents_are_not_evaluated(self):
        r = IntentRegister()
        r.add(holder="Someone Else", holder_type="recipient",
              kind="delivery_deadline", statement="Not my delivery.",
              params={"by_minutes": 1}, hardness="hard", scope="D-777")
        out = r.check(action=action(), ctx=ctx())
        self.assertEqual(out["checked"], 0)

    def test_a_malformed_intent_cannot_break_the_chain(self):
        r = IntentRegister()
        r.add(holder="Broken", holder_type="recipient", kind="delivery_deadline",
              statement="Missing its parameter.", params={}, hardness="hard",
              scope="D-101")
        out = r.check(action=action(), ctx=ctx())
        self.assertEqual(out["results"][0]["verdict"], "satisfied")
        self.assertIn("skipped", out["results"][0]["evidence"])
        self.assertTrue(out["clear"])

    def test_the_check_reports_what_passed_not_only_what_failed(self):
        """Judges need the whole evaluation to believe it ran at all."""
        r = IntentRegister()
        r.add(holder="Ananya Iyer", holder_type="recipient",
              kind="delivery_deadline", statement="Nothing after 18:00.",
              params={"by_minutes": 18 * 60}, hardness="hard", scope="D-101")
        r.add(holder="Operations", holder_type="operations", kind="sla_promise",
              statement="Windows matter.", params={}, hardness="soft", scope="*")
        out = r.check(action=action(eta=15.0), ctx=ctx(promised=60.0))
        self.assertEqual(out["checked"], 2)
        self.assertEqual(len(out["results"]), 2)
        self.assertTrue(all("evidence" in x for x in out["results"]))




# ==========================================================================
# Chain-level: the gate has to change what gets committed, or it is decoration
# ==========================================================================

class GateIntegrationTests(unittest.TestCase):
    """The two behaviours that make this functional rather than cosmetic:
    a blocked proposal is replaced by a clean one, and a genuinely
    irreconcilable set of intents stops the commit and asks a person.

    The substitution case uses a COURIER-scoped intent, because a recipient
    deadline cannot single out the top-ranked option — rank 1 has the shortest
    ETA, so any cutoff that excludes it excludes everyone. A named courier's
    shift limit binds only that courier, which is exactly the shape needed:
    the best option is unavailable for a reason that belongs to a person.
    """

    def _setup(self):
        from autofleet.world import World, DISRUPTIONS
        from autofleet.agents import RANKER
        w = World()
        dis = DISRUPTIONS["bike_breakdown"]
        rk = RANKER.rank(w.eligible_drivers("D-101", dis),
                         w.build_requirement("D-101", dis))
        return w, rk["candidates"][0], rk["candidates"][1]

    def _run(self, w):
        from autofleet.llm import LLM
        from autofleet.agents import run_chain
        evs = []
        out = run_chain(w, LLM(), delivery_id="D-101",
                        disruption_key="bike_breakdown", trigger="test",
                        emit=evs.append)
        return evs, out

    def _block_top_only(self):
        """Top-ranked courier's shift ends before this job would finish."""
        w, top, second = self._setup()
        # Block the top-ranked courier WITHOUT touching any ranker input.
        # Editing their shift would work on the intent but also moves
        # shift_headroom, which re-orders the ranking and drops them out of
        # first place — so the gate would never see them. Setting the buffer
        # they asked for changes nothing the suitability model reads, which is
        # precisely the property being tested: the intent catches something no
        # feasibility constraint can.
        shift = w.drivers[top["driver_id"]]["shift_remaining_minutes"]
        buffer = round(shift - top["eta_minutes"] + 5.0, 1)
        w.intents.add(holder=top["name"], holder_type="courier",
                      kind="shift_limit",
                      statement=f"Leave me {buffer:.0f} minutes at the end of "
                                f"my shift.",
                      params={"buffer_minutes": buffer}, hardness="hard",
                      scope=top["driver_id"], declared="rider agreement")
        return w, top, second

    def _block_everything(self):
        """A cutoff already in the past: no option can satisfy it."""
        w, top, second = self._setup()
        for i in w.intents.for_delivery("D-101"):
            if i.kind == "delivery_deadline":
                i.params["by_minutes"] = w.clock_minutes - 1.0
                i.hardness = "hard"
        return w, top, second

    def test_a_blocked_proposal_is_replaced_by_a_clean_one(self):
        w, top, second = self._block_top_only()
        evs, out = self._run(w)
        gate = next((e for e in evs if e.get("type") == "intent_gate"), None)
        sel = next((e for e in evs if e.get("type") == "selection"), None)

        self.assertIsNotNone(gate, "the gate must fire when the pick breaks an intent")
        self.assertEqual(gate["resolution"], "substituted")
        self.assertEqual(gate["blocked_driver_id"], top["driver_id"])
        self.assertIsNotNone(sel)
        self.assertNotEqual(sel["driver_id"], top["driver_id"],
                            "the blocked courier must not be the one committed")
        self.assertIsNotNone(sel["intent_substituted_from"])
        self.assertTrue(any(e.get("type") == "resolved" for e in evs),
                        "it should still resolve, just differently")
        self.assertEqual(w.ledger.totals()["human_interventions"], 0,
                         "routing around a conflict is still autonomous")

    def test_the_blocking_reason_carries_checkable_arithmetic(self):
        w, top, _ = self._block_top_only()
        evs, _ = self._run(w)
        gate = next(e for e in evs if e.get("type") == "intent_gate")
        block = gate["blocking"][0]
        self.assertEqual(block["kind"], "shift_limit")
        ev = block["evidence"]
        self.assertIn("shift_remaining_minutes", ev)
        self.assertIn("journey_minutes", ev)
        self.assertLess(ev["margin_minutes"], 0,
                        "a violation must show a negative margin")
        self.assertTrue(block["hint"], "a violation must say what to do about it")

    def test_the_check_runs_before_any_proposal_is_made(self):
        """Early detection: the screen precedes the Resource agent's turn."""
        w, _, _ = self._block_top_only()
        evs, _ = self._run(w)
        kinds = [e.get("type") for e in evs]
        first_check = kinds.index("intent_check")
        resource_start = next(
            i for i, e in enumerate(evs)
            if e.get("type") == "agent_start" and e.get("agent") == "resource"
        )
        self.assertLess(first_check, resource_start,
                        "conflicts must be found before the action is proposed")

    def test_irreconcilable_intents_stop_the_commit_and_ask_a_person(self):
        w, _, _ = self._block_everything()
        evs, out = self._run(w)
        gate = next((e for e in evs if e.get("type") == "intent_gate"), None)
        esc = next((e for e in evs if e.get("type") == "escalated"), None)

        self.assertIsNotNone(gate)
        self.assertEqual(gate["resolution"], "escalated")
        self.assertIsNotNone(esc, "an unsatisfiable conflict must escalate")
        self.assertTrue(esc.get("intent_conflict"))
        self.assertTrue(out.get("escalated"))
        self.assertEqual(w.deliveries["D-101"]["status"], "Escalated")
        self.assertEqual(w.ledger.totals()["human_interventions"], 1,
                         "handing a conflict to a person is a human intervention")
        self.assertEqual(w.ledger.totals()["incidents_resolved"], 0)

    def test_nothing_is_committed_when_the_conflict_escalates(self):
        w, _, _ = self._block_everything()
        evs, _ = self._run(w)
        self.assertFalse(any(e.get("type") == "resolved" for e in evs))
        d = w.deliveries["D-101"]
        self.assertEqual(d["driver_id"], d["original_driver_id"],
                         "an escalated conflict must not reassign anyone")


# ==========================================================================
# Escalation must not wedge the fleet
# ==========================================================================

class EscalationLifecycleTests(unittest.TestCase):
    """An escalation used to be terminal: the delivery held a fleet slot for
    ever, never advanced and never retired, so four of them froze the board.
    A dispatcher queue has a timeout, and these are the properties that matter
    when it fires."""

    def _escalate(self, disruption):
        from autofleet.world import World
        from autofleet.llm import LLM
        from autofleet.agents import run_chain
        w = World()
        for i in w.intents.for_delivery("D-101"):
            if i.kind == "delivery_deadline":
                i.params["by_minutes"] = w.clock_minutes - 1.0
                i.hardness = "hard"
        original = w.deliveries["D-101"]["driver_id"]
        run_chain(w, LLM(), delivery_id="D-101", disruption_key=disruption,
                  trigger="test", emit=lambda e: None)
        return w, original

    def test_an_escalated_delivery_does_not_hold_a_fleet_slot(self):
        from autofleet.world import FLEET_TARGET
        w, _ = self._escalate("bike_breakdown")
        for _ in range(20):
            w.drift()
        working = [d for d in w.deliveries.values()
                   if d["status"] not in ("Delivered", "Cancelled", "Escalated")]
        self.assertEqual(len(working), FLEET_TARGET,
                         "new work must be dispatched around an escalation")

    def test_a_disabled_courier_is_released_rather_than_left_carrying(self):
        w, original = self._escalate("bike_breakdown")
        drv = w.drivers[original]
        self.assertEqual(drv["status"], "unavailable")
        self.assertIsNone(drv["assigned_delivery"])
        self.assertTrue(drv["earnings_protected"],
                        "the rider did not cause the breakdown")

    def test_an_unanswered_escalation_reverts_to_the_original_courier(self):
        from autofleet.world import ESCALATION_TIMEOUT_TICKS
        w, original = self._escalate("wrong_address")   # does not disable them
        while w.tick < ESCALATION_TIMEOUT_TICKS + 2:
            w.drift()
        d = w.deliveries["D-101"]
        self.assertEqual(d["status"], "On Route")
        self.assertEqual(d["driver_id"], original)
        self.assertTrue(d.get("timed_out_to_original"))

    def test_the_timeout_does_not_erase_the_human_intervention(self):
        from autofleet.world import ESCALATION_TIMEOUT_TICKS
        w, _ = self._escalate("wrong_address")
        while w.tick < ESCALATION_TIMEOUT_TICKS + 2:
            w.drift()
        totals = w.ledger.totals()
        self.assertEqual(totals["human_interventions"], 1,
                         "a person was needed; a timeout does not undo that")
        self.assertEqual(totals["incidents_resolved"], 0,
                         "a timeout is not an autonomous resolution")

    def test_an_escalation_with_no_courier_left_is_cancelled_honestly(self):
        from autofleet.world import ESCALATION_TIMEOUT_TICKS
        w, original = self._escalate("bike_breakdown")   # disables the rider
        while w.tick < ESCALATION_TIMEOUT_TICKS + 2:
            w.drift()
        d = w.deliveries.get("D-101")
        # Either cancelled outright, or already retired off the board.
        self.assertTrue(d is None or d["status"] == "Cancelled",
                        "with no courier available it must not stay pending")

    def test_the_blocking_intents_are_kept_for_whoever_picks_it_up(self):
        w, _ = self._escalate("wrong_address")
        d = w.deliveries["D-101"]
        self.assertTrue(d["escalation_reason"])
        self.assertTrue(d["escalation_blocking"],
                        "a person needs to see which intents collided")
        self.assertIn("awaiting_decision_since", d)


# ==========================================================================
# The human decision surface
# ==========================================================================

class DecisionSurfaceTests(unittest.TestCase):
    """An escalation that a person cannot act on is just a stuck delivery, so
    the options offered have to be real, derived from state, and recorded."""

    def _escalated(self, disruption="wrong_address"):
        from autofleet.world import World
        from autofleet.llm import LLM
        from autofleet.agents import run_chain
        w = World()
        for i in w.intents.for_delivery("D-101"):
            if i.kind == "delivery_deadline":
                i.params["by_minutes"] = w.clock_minutes - 1.0
                i.hardness = "hard"
        run_chain(w, LLM(), delivery_id="D-101", disruption_key=disruption,
                  trigger="test", emit=lambda e: None)
        return w

    def test_a_pending_decision_carries_the_conflict_and_its_arithmetic(self):
        w = self._escalated()
        pend = w.pending_decisions()
        self.assertEqual(len(pend), 1)
        d = pend[0]
        self.assertTrue(d["reason"])
        self.assertTrue(d["blocking"])
        self.assertIn("evidence", d["blocking"][0])
        self.assertIn("timeout_ticks", d)

    def test_options_are_derived_from_state_not_a_fixed_menu(self):
        """A courier who cannot carry it must not be offered as an option."""
        able = [o["action"] for o in
                self._escalated("wrong_address").pending_decisions()[0]["options"]]
        disabled = [o["action"] for o in
                    self._escalated("bike_breakdown").pending_decisions()[0]["options"]]
        self.assertIn("retain_original", able)
        self.assertNotIn("retain_original", disabled,
                         "a rider whose bike is broken cannot keep the job")

    def test_override_withdraws_that_intent_and_asks_for_a_re_decision(self):
        w = self._escalated()
        opt = next(o for o in w.pending_decisions()[0]["options"]
                   if o["action"] == "override_intent")
        out = w.apply_decision(delivery_id="D-101", action="override_intent",
                               intent_id=opt["intent_id"], actor="ops:test")
        self.assertTrue(out["ok"])
        self.assertTrue(out["requeue"], "the chain must decide again, not be overruled")
        self.assertFalse(w.intents.get(opt["intent_id"]).active)

    def test_retain_puts_the_original_courier_back_on_the_job(self):
        w = self._escalated()
        original = w.deliveries["D-101"]["original_driver_id"]
        out = w.apply_decision(delivery_id="D-101", action="retain_original",
                               actor="ops:test")
        self.assertTrue(out["ok"])
        self.assertFalse(out["requeue"], "this decision IS the outcome")
        d = w.deliveries["D-101"]
        self.assertEqual(d["status"], "On Route")
        self.assertEqual(d["driver_id"], original)

    def test_reschedule_moves_the_promise_and_re_decides(self):
        w = self._escalated()
        from autofleet.world import RESCHEDULE_MINUTES
        before = w.deliveries["D-101"]["promised_minutes"]
        out = w.apply_decision(delivery_id="D-101", action="reschedule",
                               actor="ops:test")
        self.assertTrue(out["requeue"])
        self.assertAlmostEqual(w.deliveries["D-101"]["promised_minutes"],
                               before + RESCHEDULE_MINUTES, places=1)

    def test_cancel_stops_the_delivery_and_frees_the_courier(self):
        w = self._escalated()
        original = w.drivers[w.deliveries["D-101"]["original_driver_id"]]
        w.apply_decision(delivery_id="D-101", action="cancel", actor="ops:test")
        self.assertEqual(w.deliveries["D-101"]["status"], "Cancelled")
        self.assertIsNone(original["assigned_delivery"])

    def test_every_decision_is_attributed_and_timestamped(self):
        w = self._escalated()
        w.apply_decision(delivery_id="D-101", action="cancel",
                         actor="ops:himanshi", note="recipient unreachable")
        self.assertEqual(len(w.decisions), 1)
        rec = w.decisions[0]
        for field in ("actor", "clock", "tick", "action", "outcome", "note"):
            self.assertIn(field, rec)
        self.assertEqual(rec["actor"], "ops:himanshi")
        self.assertEqual(rec["note"], "recipient unreachable")

    def test_an_override_records_which_intent_was_set_aside(self):
        w = self._escalated()
        opt = next(o for o in w.pending_decisions()[0]["options"]
                   if o["action"] == "override_intent")
        w.apply_decision(delivery_id="D-101", action="override_intent",
                         intent_id=opt["intent_id"], actor="ops:test")
        self.assertTrue(w.decisions[0]["intent_statement"],
                        "the withdrawn goal must be named, not just its id")

    def test_bad_input_is_refused(self):
        w = self._escalated()
        self.assertFalse(w.apply_decision(delivery_id="D-999", action="cancel")["ok"])
        self.assertFalse(w.apply_decision(delivery_id="D-101", action="nope")["ok"])
        self.assertFalse(w.apply_decision(delivery_id="D-101",
                                          action="override_intent",
                                          intent_id="INT-999")["ok"])

    def test_a_delivery_cannot_be_decided_twice(self):
        w = self._escalated()
        self.assertTrue(w.apply_decision(delivery_id="D-101", action="cancel")["ok"])
        again = w.apply_decision(delivery_id="D-101", action="cancel")
        self.assertFalse(again["ok"])
        self.assertEqual(len(w.decisions), 1)


class IntentLifecycleTests(unittest.TestCase):
    """The register has to track the fleet. Left alone it went stale within
    minutes: every intent pointed at a retired delivery and every delivery on
    the board had none, so the conflict check silently stopped applying."""

    def _run(self, mode="commercial", ticks=300):
        from autofleet.world import World
        w = World(mode=mode)
        for _ in range(ticks):
            w.drift()
        return w

    def test_no_intent_outlives_its_delivery(self):
        w = self._run()
        live = set(w.deliveries)
        stale = [i.scope for i in w.intents.all()
                 if i.scope != "*" and i.scope not in w.drivers
                 and i.scope not in live]
        self.assertEqual(stale, [], "delivery-scoped intents must be pruned")

    def test_every_live_delivery_has_a_stated_intent(self):
        for mode in ("commercial", "humanitarian"):
            w = self._run(mode)
            uncovered = [
                d["id"] for d in w.deliveries.values()
                if d["status"] not in ("Delivered", "Cancelled")
                and not any(i.scope == d["id"] for i in w.intents.all())
            ]
            self.assertEqual(uncovered, [], f"{mode}: new work arrived with no goals")

    def test_fleet_wide_and_courier_intents_survive(self):
        w = self._run()
        scopes = [i.scope for i in w.intents.all()]
        self.assertIn("*", scopes)
        self.assertTrue(any(s in w.drivers for s in scopes),
                        "a courier's own intent must not be pruned")


if __name__ == "__main__":
    unittest.main(verbosity=2)
