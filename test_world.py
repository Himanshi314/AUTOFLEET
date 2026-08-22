"""Tests for the simulation itself: the delivery lifecycle and the clock.

These lock down behaviour that was wrong for a long time and looked fine while
it was wrong, which is the dangerous kind:

  · the ETA was a flat countdown floored at 1.0, so every delivery parked at
    "1 min" for ever and never arrived;
  · nothing ever completed, so slack drained to zero and stayed there, which
    pinned schedule_pressure at 1.0 and drove the risk score to "critical" on
    nothing but elapsed time;
  · fatigue and vehicle wear had no recovery path at all.

A dashboard reading 89% critical on an idle demo is not a visible crash — it
just quietly discredits the model. So the invariants are asserted rather than
eyeballed.

    python test_world.py
"""

from __future__ import annotations

import unittest

from autofleet.geo import coord, road_km
from autofleet.world import (ARRIVAL_KM, ESCALATION_TIMEOUT_TICKS, FLEET_TARGET,
                             EMERGENCY_SHIFT_HORIZON_MINUTES, SIM_MINUTES_PER_TICK,
                             World)
from autofleet.world import DISRUPTIONS


class ClockTests(unittest.TestCase):
    def test_the_clock_starts_in_the_evening_peak(self):
        """Stated cutoffs cannot bite if the day starts mid-afternoon."""
        self.assertEqual(World().clock, "17:20")

    def test_the_clock_advances_with_the_simulation(self):
        w = World()
        for _ in range(100):
            w.drift()
        self.assertAlmostEqual(w.clock_minutes,
                               17 * 60 + 20 + 100 * SIM_MINUTES_PER_TICK, places=1)
        self.assertEqual(w.clock, "18:20")   # 100 x 0.6 min = 1 hour

    def test_the_clock_is_published_to_the_client(self):
        snap = World().snapshot()
        self.assertIn("clock", snap)
        self.assertIn("clock_minutes", snap)


class LayeredRecoveryTests(unittest.TestCase):
    def _deadline(self, world, delivery_id, minutes_from_now):
        for intent in world.intents.all():
            if intent.scope == delivery_id and intent.kind == "delivery_deadline":
                intent.params["by_minutes"] = world.clock_minutes + minutes_from_now
                return
        self.fail("delivery deadline intent missing")

    def _layer2_world(self):
        world = World()
        target = world.deliveries["D-101"]
        target_driver = world.drivers[target["driver_id"]]
        target_driver["status"] = "unavailable"
        self._deadline(world, "D-101", 240)
        route_driver_id = world.deliveries["D-103"]["driver_id"]
        for driver in world.drivers.values():
            if driver["id"] not in (target_driver["id"], route_driver_id):
                driver["status"] = "unavailable"
        return world

    def test_on_route_insertion_is_accepted_when_windows_fit(self):
        world = self._layer2_world()
        requirement = world.build_requirement("D-101", DISRUPTIONS["bike_breakdown"])
        results = world.route_reallocation_candidates("D-101", requirement)
        accepted = [r for r in results if r["status"] == "accepted"]
        self.assertTrue(accepted)
        self.assertIn("pickup", accepted[0]["new_route"])
        self.assertIn("new", accepted[0]["new_route"])

    def test_on_route_insertion_rejects_a_tight_existing_window(self):
        world = self._layer2_world()
        carrying = world.drivers[world.deliveries["D-103"]["driver_id"]]
        self._deadline(world, carrying["assigned_delivery"], 1)
        requirement = world.build_requirement("D-101", DISRUPTIONS["bike_breakdown"])
        results = world.route_reallocation_candidates("D-101", requirement)
        self.assertTrue(results)
        self.assertTrue(all(r["status"] == "rejected" for r in results))
        self.assertTrue(all(r["reason"] for r in results))

    def test_available_soon_candidate_uses_shift_start_in_deadline(self):
        world = World()
        target = world.deliveries["D-101"]
        world.drivers[target["driver_id"]]["status"] = "unavailable"
        for driver in world.drivers.values():
            driver["status"] = "unavailable"
            driver["assigned_delivery"] = None
        future = next(driver for driver in world.drivers.values()
                  if driver["id"] != target["driver_id"])
        future["shift_start_minutes"] = world.clock_minutes + 18
        future["at"] = world.drivers[target["driver_id"]]["at"]
        self._deadline(world, "D-101", 240)
        requirement = world.build_requirement("D-101", DISRUPTIONS["bike_breakdown"])
        results = world.available_soon_candidates("D-101", requirement,
                                                  EMERGENCY_SHIFT_HORIZON_MINUTES)
        selected = next(r for r in results if r["driver_id"] == future["id"])
        self.assertTrue(selected["feasible"])
        self._deadline(world, "D-101", 1)
        selected = next(r for r in world.available_soon_candidates("D-101", requirement)
                        if r["driver_id"] == future["id"])
        self.assertFalse(selected["feasible"])


class EtaTests(unittest.TestCase):
    """The ETA has to be a function of the world, not a countdown."""

    def test_congestion_pushes_the_eta_out(self):
        w = World()
        d = w.deliveries["D-103"]
        etas = []
        for ti in (0.10, 0.50, 0.90):
            d["telemetry"]["traffic_index"] = ti
            w._recompute_eta(d)
            etas.append(d["eta_minutes"])
        self.assertEqual(etas, sorted(etas))
        self.assertGreater(etas[-1], etas[0] * 1.2,
                           "a nine-fold jump in congestion must move the ETA")

    def test_the_eta_tracks_the_courier_closing_in(self):
        w = World()
        d = w.deliveries["D-103"]
        first = d["eta_minutes"]
        for _ in range(30):
            w.drift()
        if d["status"] not in ("Delivered", "Cancelled"):
            self.assertLess(d["eta_minutes"], first,
                            "a courier who has travelled must be closer")

    def test_the_eta_is_never_parked_at_a_floor(self):
        """The old bug: max(1.0, eta - 0.35) meant "1 min" for ever."""
        w = World()
        stuck = 0
        for _ in range(400):
            w.drift()
            for d in w.deliveries.values():
                if d["status"] in ("On Route", "Rerouted", "Reassigned") \
                        and abs(d["eta_minutes"] - 1.0) < 0.01:
                    stuck += 1
        self.assertEqual(stuck, 0, "an in-flight delivery sat at exactly 1.0 min")


class CompletionTests(unittest.TestCase):
    def test_a_delivery_arrives_and_is_marked_delivered(self):
        w = World()
        for _ in range(200):
            w.drift()
            if w.completed:
                break
        self.assertGreater(w.completed, 0, "nothing ever arrived")

    def test_completion_requires_actually_reaching_the_drop(self):
        """Asserted on the rule, not after the fact.

        A courier freed by a completion is dispatched onto fresh work inside the
        SAME drift() call, and a new job starts at the depot — so by the time an
        outside observer looks, the courier has already been relocated and their
        distance from the old destination means nothing.
        """
        # Just outside the radius: must NOT complete.
        w = World()
        d = w.deliveries["D-101"]
        drv = w.drivers[d["driver_id"]]
        dest = coord(d["destination"])
        drv["at"] = (dest[0] + 0.05, dest[1])          # ~5 km short
        self.assertGreater(w._remaining_km(d), ARRIVAL_KM)
        d["status"] = "On Route"
        w._recompute_eta(d)
        self.assertNotEqual(d["status"], "Delivered")

        # On the doorstep: must complete, with the bookkeeping tidy.
        w2 = World()
        d2 = w2.deliveries["D-101"]
        w2.drivers[d2["driver_id"]]["at"] = coord(d2["destination"])
        self.assertLessEqual(w2._remaining_km(d2), ARRIVAL_KM)
        w2.drift()
        self.assertEqual(d2["status"], "Delivered")
        self.assertEqual(d2["eta_minutes"], 0.0)
        self.assertEqual(d2["progress"], 1.0)

    def test_a_completed_delivery_frees_its_courier(self):
        w = World()
        for _ in range(200):
            w.drift()
            done = [d for d in w.deliveries.values() if d["status"] == "Delivered"]
            if done:
                drv = w.drivers[done[0]["driver_id"]]
                self.assertNotEqual(drv["assigned_delivery"], done[0]["id"])
                return
        self.skipTest("no delivery completed within 200 ticks")

    def test_completed_deliveries_are_retired_and_replaced(self):
        w = World()
        for _ in range(200):
            w.drift()
        working = [d for d in w.deliveries.values()
                   if d["status"] not in ("Delivered", "Cancelled", "Escalated")]
        self.assertEqual(len(working), FLEET_TARGET, "the board stopped refilling")
        fresh = [k for k in w.deliveries if k not in
                 ("D-101", "D-102", "D-103", "D-104")]
        self.assertTrue(fresh, "no replacement work was ever dispatched")

    def test_respawns_follow_the_mode_id_prefix(self):
        for mode, prefix in (("commercial", "D-"), ("humanitarian", "V-")):
            w = World(mode=mode)
            for _ in range(260):
                w.drift()
            wrong = [k for k in w.deliveries if not k.startswith(prefix)]
            self.assertEqual(wrong, [], f"{mode} spawned a foreign id prefix")

    def test_humanitarian_respawns_carry_a_cold_chain(self):
        w = World(mode="humanitarian")
        for _ in range(260):
            w.drift()
        fresh = [d for d in w.deliveries.values()
                 if int(d["id"].split("-")[1]) > 204]
        self.assertTrue(fresh)
        for d in fresh:
            self.assertTrue(d["cold_chain"])
            self.assertGreater(d["cold_minutes_remaining"], 0)


class SlackTests(unittest.TestCase):
    """Slack is time to spare against a promise, not a countdown."""

    def test_slack_is_not_drained_by_elapsed_time_alone(self):
        w = World()
        pinned = 0
        for _ in range(400):
            w.drift()
            for d in w.deliveries.values():
                if d["status"] in ("On Route", "Rerouted", "Reassigned") \
                        and d["slack_minutes"] <= 0:
                    pinned += 1
        self.assertEqual(pinned, 0,
                         "slack hit zero on a delivery that was on schedule")

    def test_slack_shrinks_when_the_courier_actually_falls_behind(self):
        w = World()
        d = w.deliveries["D-103"]
        d["telemetry"]["traffic_index"] = 0.10
        w._recompute_eta(d)
        d["promised_minutes"] = d["eta_minutes"] + 20.0
        d["slack_minutes"] = 20.0
        d["telemetry"]["traffic_index"] = 0.95      # corridor collapses
        w._recompute_eta(d)
        d["slack_minutes"] = max(0.0, round(d["promised_minutes"] - d["eta_minutes"], 1))
        self.assertLess(d["slack_minutes"], 20.0,
                        "congestion must eat into the buffer")

    def test_a_fresh_job_starts_with_a_proportional_promise(self):
        w = World()
        for _ in range(200):
            w.drift()
        fresh = [d for d in w.deliveries.values()
                 if d["id"] not in ("D-101", "D-102", "D-103", "D-104")
                 and d["status"] == "On Route"]
        self.assertTrue(fresh)
        for d in fresh:
            self.assertGreater(d["promised_minutes"], d["eta_minutes"],
                               "a job cannot be late the moment it is dispatched")


class RiskDriftTests(unittest.TestCase):
    """The headline symptom: risk used to ratchet to critical on idle time."""

    def test_risk_does_not_ratchet_on_an_idle_simulation(self):
        w = World()
        peaks = []
        for i in range(1, 901):
            w.drift()
            if i % 100:
                continue
            live = [d for d in w.snapshot()["deliveries"]
                    if d["status"] not in ("Delivered", "Cancelled")]
            if live:
                peaks.append(sum(d["risk"] for d in live) / len(live))
        self.assertTrue(peaks)
        self.assertLess(max(peaks), 0.65,
                        f"average risk climbed to {max(peaks):.2f} with nothing "
                        f"happening: {[round(p, 2) for p in peaks]}")

    def test_a_shift_ends_and_the_courier_comes_back_rested(self):
        w = World()
        rested = False
        for _ in range(1200):
            w.drift()
            if any(v["status"] == "off_shift" for v in w.drivers.values()):
                rested = True
                break
        self.assertTrue(rested, "no courier ever reached the end of a shift")

    def test_fatigue_and_wear_are_serviced_between_shifts(self):
        w = World()
        for _ in range(1200):
            w.drift()
            resting = [v for v in w.drivers.values() if v["status"] == "off_shift"]
            if resting:
                v = resting[0]
                self.assertEqual(v["hours_on_shift"], 0.0)
                self.assertLess(v["vehicle_health_risk"], 0.2,
                                "the vehicle was not serviced between shifts")
                return
        self.skipTest("no shift ended within 1200 ticks")

    def test_accumulating_values_do_not_leak_float_noise(self):
        w = World(mode="humanitarian")
        for _ in range(200):
            w.drift()
        for d in w.deliveries.values():
            val = d.get("cold_minutes_remaining", 0.0)
            self.assertEqual(round(val, 1), val,
                             f"cold window rendered as {val}")
        for v in w.drivers.values():
            val = v["shift_remaining_minutes"]
            self.assertEqual(round(val, 1), val)


class EscalationSlotTests(unittest.TestCase):
    def test_an_escalation_does_not_starve_the_fleet(self):
        w = World()
        for d in list(w.deliveries.values())[:2]:
            w.escalate(delivery_id=d["id"], incident_id="INC-T",
                       reason="test", disruption_key="wrong_address")
        for _ in range(20):
            w.drift()
        working = [d for d in w.deliveries.values()
                   if d["status"] not in ("Delivered", "Cancelled", "Escalated")]
        self.assertEqual(len(working), FLEET_TARGET)

    def test_an_unanswered_escalation_is_eventually_closed(self):
        w = World()
        w.escalate(delivery_id="D-101", incident_id="INC-T", reason="test",
                   disruption_key="wrong_address")
        for _ in range(ESCALATION_TIMEOUT_TICKS + 5):
            w.drift()
        d = w.deliveries.get("D-101")
        self.assertTrue(d is None or d["status"] != "Escalated",
                        "an escalation stayed pending past its timeout")

    def test_escalating_a_breakdown_releases_and_protects_the_courier(self):
        w = World()
        drv_id = w.deliveries["D-101"]["driver_id"]
        w.escalate(delivery_id="D-101", incident_id="INC-T", reason="test",
                   disruption_key="bike_breakdown")
        drv = w.drivers[drv_id]
        self.assertEqual(drv["status"], "unavailable")
        self.assertTrue(drv["earnings_protected"])
        self.assertIsNone(drv["assigned_delivery"])


class ResetTests(unittest.TestCase):
    def test_reset_restores_the_seeded_board(self):
        w = World()
        for _ in range(300):
            w.drift()
        w.reset()
        self.assertEqual(sorted(w.deliveries),
                         ["D-101", "D-102", "D-103", "D-104"])
        self.assertEqual(w.tick, 0)
        self.assertEqual(w.clock, "17:20")
        self.assertEqual(w.completed, 0)
        self.assertEqual(w.ledger.totals()["incidents_resolved"], 0)
        self.assertEqual(w.ledger.totals()["human_interventions"], 0)
        self.assertEqual(w.decisions, [])

    def test_switching_mode_reloads_cleanly(self):
        w = World()
        for _ in range(120):
            w.drift()
        w.set_mode("humanitarian")
        self.assertTrue(all(k.startswith("V-") for k in w.deliveries))
        self.assertTrue(all(d["cold_chain"] for d in w.deliveries.values()))
        self.assertEqual(w.tick, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
