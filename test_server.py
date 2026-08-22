"""Tests for the HTTP layer, and regressions for everything found by attacking it.

Every case in AdversarialRegressionTests is a defect that was live in a running
build. They are the ones worth guarding, because each was invisible until
something specific was tried:

  · a JSON array body killed the request thread and printed a traceback wall;
  · a humanitarian-only disruption was accepted against a commercial parcel;
  · twelve impatient clicks queued nine incidents and locked the demo out;
  · "Human interventions: 0" was a hardcoded literal, not a count.

The server is booted in-process on an ephemeral port with a deterministic
fallback model, so nothing here spends an API call or touches the network.

    python test_server.py
"""

from __future__ import annotations

import json
import socket
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import server as srv
from autofleet.llm import LLM


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerCase(unittest.TestCase):
    """One server per test class, shared by its tests."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        srv.ENGINE = srv.Engine()
        # Force the deterministic path: these tests are about HTTP and state,
        # not about the model, and they must not cost tokens or need a network.
        srv.ENGINE.llm = LLM()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", cls.port), srv.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    # -- helpers -----------------------------------------------------------

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str):
        with urllib.request.urlopen(self.url(path), timeout=10) as r:
            return r.status, json.loads(r.read().decode())

    def post(self, path: str, body, raw: bool = False):
        data = body.encode() if raw else json.dumps(body).encode()
        req = urllib.request.Request(
            self.url(path), data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())


class RoutingTests(ServerCase):
    def test_the_dashboard_and_its_assets_are_served(self):
        for path in ("/", "/static/styles.css", "/static/app.js"):
            with urllib.request.urlopen(self.url(path), timeout=10) as r:
                self.assertEqual(r.status, 200, path)
                self.assertGreater(len(r.read()), 200, path)

    def test_state_exposes_what_the_client_needs(self):
        status, body = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertIn("state", body)
        self.assertIn("meta", body)
        for key in ("deliveries", "drivers", "impact", "clock", "map"):
            self.assertIn(key, body["state"], key)

    def test_unknown_routes_are_404_not_500(self):
        for path in ("/api/nope", "/nothing-here"):
            try:
                urllib.request.urlopen(self.url(path), timeout=10)
                self.fail(f"{path} should not have succeeded")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 404, path)

    def test_static_paths_cannot_escape_the_web_root(self):
        for path in ("/static/../server.py",
                     "/static/..%2f..%2fserver.py",
                     "/static/../../../../Windows/win.ini"):
            try:
                with urllib.request.urlopen(self.url(path), timeout=10) as r:
                    body = r.read()
                self.assertNotIn(b"ThreadingHTTPServer", body,
                                 f"{path} served source")
                self.assertNotIn(b"[fonts]", body, f"{path} escaped the root")
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (403, 404), path)


class AdversarialRegressionTests(ServerCase):
    """Each of these was a live defect."""

    def test_a_json_body_that_is_not_an_object_does_not_kill_the_thread(self):
        """`[1,2,3]` used to raise AttributeError inside do_POST: the connection
        died with no status and a traceback wall hit the console."""
        for raw in ("[1,2,3]", '"hello"', "42", "true", "null"):
            code, body = self.post("/api/disrupt", raw, raw=True)
            self.assertEqual(code, 400, f"body {raw!r} should be a clean 400")
            self.assertIn("error", body)
        # and the server is still answering
        self.assertEqual(self.get("/api/state")[0], 200)

    def test_malformed_and_empty_bodies_are_handled(self):
        for raw in ("", "hello{{{", "{", "{'single': 'quotes'}"):
            code, _ = self.post("/api/disrupt", raw, raw=True)
            self.assertEqual(code, 400, f"body {raw!r}")

    def test_a_humanitarian_only_disruption_is_refused_in_commercial_mode(self):
        """It used to be accepted and resolved: the agents reasoned about
        consignment integrity and doses for a box of electronics."""
        target = self.get("/api/state")[1]["state"]["deliveries"][0]["id"]
        code, body = self.post("/api/disrupt", {
            "delivery_id": target, "disruption": "cold_chain_breach",
        })
        self.assertEqual(code, 400)
        self.assertIn("does not apply", body["error"])

    def test_mode_gating_is_the_same_for_the_ui_and_the_guard(self):
        """meta() published the gating and enqueue() ignored it."""
        meta = self.get("/api/state")[1]["meta"]
        published = {d["key"]: d["modes"] for d in meta["disruptions"]}
        enforced = srv.ENGINE.disruptions_for_mode()
        mode = srv.ENGINE.world.mode
        for key, modes in published.items():
            self.assertEqual(mode in modes, key in enforced, key)

    def test_the_same_delivery_cannot_be_queued_twice(self):
        """Twelve clicks queued nine incidents and locked the demo out for
        minutes with no way to clear it short of a reset."""
        target = next(d["id"] for d in self.get("/api/state")[1]["state"]["deliveries"]
                      if d["status"] == "On Route")
        first = self.post("/api/disrupt", {
            "delivery_id": target, "disruption": "customer_not_home"})
        self.assertEqual(first[0], 200)
        accepted = 1
        for _ in range(5):
            code, _ = self.post("/api/disrupt", {
                "delivery_id": target, "disruption": "customer_not_home"})
            if code == 200:
                accepted += 1
        self.assertEqual(accepted, 1,
                         "repeat clicks on one delivery must not stack up")

    def test_unknown_ids_and_actions_are_rejected(self):
        cases = [
            ("/api/disrupt", {"delivery_id": "D-999", "disruption": "bike_breakdown"}),
            ("/api/disrupt", {"delivery_id": "D-101", "disruption": "alien_invasion"}),
            ("/api/mode", {"mode": "chaos"}),
            ("/api/intents/toggle", {"id": "INT-999", "active": False}),
            ("/api/decisions/resolve", {"delivery_id": "D-999", "action": "cancel"}),
        ]
        for path, body in cases:
            code, payload = self.post(path, body)
            self.assertEqual(code, 400, f"{path} {body}")
            self.assertIn("error", payload)

    def test_human_interventions_is_counted_not_hardcoded(self):
        """It was `"human_interventions": 0` unconditionally, while the dashboard
        headlined it as coordinators involved."""
        impact = self.get("/api/state")[1]["state"]["impact"]
        self.assertEqual(impact["human_interventions"], 0)
        srv.ENGINE.world.escalate(
            delivery_id=next(iter(srv.ENGINE.world.deliveries)),
            incident_id="INC-T", reason="test", disruption_key="wrong_address",
        )
        after = self.get("/api/state")[1]["state"]["impact"]
        self.assertEqual(after["human_interventions"], 1,
                         "an escalation must show up as a human being involved")


class IntentApiTests(ServerCase):
    def test_the_register_is_published_with_the_clock(self):
        status, body = self.get("/api/intents")
        self.assertEqual(status, 200)
        self.assertIn("clock", body)
        self.assertTrue(body["intents"])
        for i in body["intents"]:
            for field in ("id", "holder", "holder_type", "kind", "statement",
                          "hardness", "scope", "active"):
                self.assertIn(field, i, field)

    def test_an_intent_can_be_withdrawn_and_restored(self):
        target = self.get("/api/intents")[1]["intents"][0]["id"]
        code, body = self.post("/api/intents/toggle",
                               {"id": target, "active": False})
        self.assertEqual(code, 200)
        self.assertFalse(body["intent"]["active"])
        after = {i["id"]: i for i in self.get("/api/intents")[1]["intents"]}
        self.assertFalse(after[target]["active"])

        self.post("/api/intents/toggle", {"id": target, "active": True})
        restored = {i["id"]: i for i in self.get("/api/intents")[1]["intents"]}
        self.assertTrue(restored[target]["active"])

    def test_a_withdrawn_intent_stops_binding(self):
        """The judge interaction: this is what makes the check demonstrable."""
        world = srv.ENGINE.world
        target = next(i for i in world.intents.all()
                      if i.kind == "delivery_deadline")
        delivery_id = target.scope
        self.assertIn(target, world.intents.for_delivery(delivery_id))
        self.post("/api/intents/toggle", {"id": target.id, "active": False})
        self.assertNotIn(target, world.intents.for_delivery(delivery_id))
        self.post("/api/intents/toggle", {"id": target.id, "active": True})


class DecisionApiTests(ServerCase):
    def _escalate(self):
        world = srv.ENGINE.world
        delivery_id = next(
            d["id"] for d in world.deliveries.values()
            if d["status"] not in ("Delivered", "Cancelled", "Escalated")
        )
        world.escalate(
            delivery_id=delivery_id, incident_id="INC-T",
            reason="test conflict", disruption_key="wrong_address",
            blocking=[{
                "intent_id": next(i.id for i in world.intents.all()
                                  if i.kind == "delivery_deadline"),
                "holder": "Test Recipient", "kind": "delivery_deadline",
                "statement": "Nothing after 18:00.", "hardness": "hard",
                "hint": "arrives late", "evidence": {"margin_minutes": -12.0},
            }],
        )
        return delivery_id

    def test_a_pending_decision_is_published_with_its_options(self):
        delivery_id = self._escalate()
        status, body = self.get("/api/decisions")
        self.assertEqual(status, 200)
        entry = next(p for p in body["pending"] if p["delivery_id"] == delivery_id)
        self.assertTrue(entry["reason"])
        self.assertTrue(entry["blocking"])
        actions = {o["action"] for o in entry["options"]}
        self.assertIn("cancel", actions)
        self.assertIn("reschedule", actions)

    def test_resolving_records_who_decided_and_clears_the_queue(self):
        delivery_id = self._escalate()
        code, body = self.post("/api/decisions/resolve", {
            "delivery_id": delivery_id, "action": "cancel",
            "actor": "ops:test", "note": "unit test",
        })
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["decision"]["actor"], "ops:test")
        self.assertEqual(body["decision"]["note"], "unit test")
        pending = self.get("/api/decisions")[1]["pending"]
        self.assertNotIn(delivery_id, [p["delivery_id"] for p in pending])

    def test_the_decision_trail_is_readable(self):
        delivery_id = self._escalate()
        self.post("/api/decisions/resolve", {
            "delivery_id": delivery_id, "action": "cancel", "actor": "ops:test"})
        history = self.get("/api/decisions")[1]["history"]
        self.assertTrue(history)
        self.assertIn("outcome", history[0])
        self.assertIn("clock", history[0])

    def test_a_delivery_not_awaiting_a_decision_is_refused(self):
        live = next(d["id"] for d in srv.ENGINE.world.deliveries.values()
                    if d["status"] == "On Route")
        code, body = self.post("/api/decisions/resolve", {
            "delivery_id": live, "action": "cancel"})
        self.assertEqual(code, 400)
        self.assertIn("not awaiting", body["error"])

    def test_the_same_escalation_cannot_be_decided_twice(self):
        delivery_id = self._escalate()
        first = self.post("/api/decisions/resolve", {
            "delivery_id": delivery_id, "action": "cancel", "actor": "a"})
        second = self.post("/api/decisions/resolve", {
            "delivery_id": delivery_id, "action": "cancel", "actor": "b"})
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 400)


class ControlTests(ServerCase):
    def test_reset_clears_the_board_and_the_ledger(self):
        for _ in range(30):
            srv.ENGINE.world.drift()
        code, _ = self.post("/api/reset", {})
        self.assertEqual(code, 200)
        state = self.get("/api/state")[1]["state"]
        self.assertEqual(state["tick"], 0)
        self.assertEqual(state["clock"], "17:20")
        self.assertEqual(state["impact"]["incidents_resolved"], 0)
        self.assertEqual(state["impact"]["human_interventions"], 0)

    def test_mode_switch_swaps_the_scenario(self):
        code, _ = self.post("/api/mode", {"mode": "humanitarian"})
        self.assertEqual(code, 200)
        state = self.get("/api/state")[1]["state"]
        self.assertEqual(state["mode"], "humanitarian")
        self.assertTrue(all(d["id"].startswith("V-") for d in state["deliveries"]))
        self.post("/api/mode", {"mode": "commercial"})

    def test_autonomous_can_be_armed_and_disarmed(self):
        self.assertEqual(self.post("/api/autonomous", {"enabled": True})[0], 200)
        self.assertTrue(self.get("/api/state")[1]["meta"]["autonomous"])
        self.post("/api/autonomous", {"enabled": False})
        self.assertFalse(self.get("/api/state")[1]["meta"]["autonomous"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
