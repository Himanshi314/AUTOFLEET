"""AutoFleet AI server — stdlib only, so `python server.py` just works.

Serves the dashboard, broadcasts a single Server-Sent Events channel, drifts
fleet telemetry on a background thread, and runs the five-agent chain in a
worker thread. The watchdog on that same thread is what makes the system
genuinely event-driven: when a delivery's predicted failure risk crosses the
threshold, it fires the chain itself with nobody clicking anything.

    python server.py            # http://127.0.0.1:8600
    python server.py --port 9000
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autofleet.agents import AGENT_SPECS, run_chain
from autofleet.impact import ASSUMPTIONS, EMISSION_FACTORS, EMISSION_SOURCES
from autofleet.llm import make_llm
from autofleet.scoring import MODEL_CARDS
from autofleet.world import DISRUPTIONS, World

WEB_ROOT = Path(__file__).resolve().parent / "web"

# Predicted-failure-risk threshold at which the watchdog self-triggers.
AUTONOMOUS_THRESHOLD = 0.68
DRIFT_INTERVAL_SECONDS = 2.2


# ==========================================================================
# Event bus
# ==========================================================================

class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: List[queue.Queue] = []

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: Dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # slow client; drop rather than stall the chain

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


# ==========================================================================
# Engine
# ==========================================================================

class Engine:
    def __init__(self) -> None:
        self.bus = EventBus()
        self.world = World(mode="commercial")
        self.llm = make_llm()
        self.autonomous = False
        self.incidents: queue.Queue = queue.Queue()
        self._auto_fired: set[str] = set()
        self._chain_active = threading.Event()
        self._stop = threading.Event()

        threading.Thread(target=self._simulate, name="simulator", daemon=True).start()
        threading.Thread(target=self._work, name="incident-worker", daemon=True).start()

    # -- public actions -----------------------------------------------------

    def enqueue(self, delivery_id: str, disruption_key: str, trigger: str = "manual") -> Dict:
        if delivery_id not in self.world.deliveries:
            return {"ok": False, "error": f"unknown delivery {delivery_id}"}
        if disruption_key not in DISRUPTIONS:
            return {"ok": False, "error": f"unknown disruption {disruption_key}"}
        status = self.world.deliveries[delivery_id]["status"]
        if status == "Resolving":
            return {"ok": False, "error": f"{delivery_id} is already being resolved"}
        self.incidents.put((delivery_id, disruption_key, trigger))
        depth = self.incidents.qsize()
        if depth > 1 or self._chain_active.is_set():
            self.bus.publish({
                "type": "log", "level": "info",
                "msg": f"queued · {DISRUPTIONS[disruption_key]['label']} on "
                       f"{delivery_id} · {depth} incident(s) waiting",
            })
        return {"ok": True, "queued": depth}

    def _drain(self) -> int:
        """Discard queued incidents. Reset and mode-switch must not let a stale
        incident fire against freshly loaded state a second later."""
        dropped = 0
        while True:
            try:
                self.incidents.get_nowait()
                self.incidents.task_done()
                dropped += 1
            except queue.Empty:
                return dropped

    def set_mode(self, mode: str) -> Dict:
        if mode not in ("commercial", "humanitarian"):
            return {"ok": False, "error": "mode must be commercial or humanitarian"}
        self._drain()
        self.world.set_mode(mode)
        self._auto_fired.clear()
        self.bus.publish({
            "type": "mode", "mode": mode,
            "state": self.world.snapshot(), "meta": self.meta(),
        })
        self.bus.publish({
            "type": "log", "level": "info",
            "msg": f"scenario switched to {mode} mode · same agents, same models, "
                   f"different payload and objective",
        })
        return {"ok": True, "mode": mode}

    def reset(self) -> Dict:
        dropped = self._drain()
        self.world.reset()
        self._auto_fired.clear()
        self.bus.publish({"type": "reset", "state": self.world.snapshot()})
        self.bus.publish({
            "type": "log", "level": "info",
            "msg": "fleet state reset" + (f" · {dropped} queued incident(s) discarded" if dropped else ""),
        })
        return {"ok": True}

    def set_autonomous(self, enabled: bool) -> Dict:
        self.autonomous = bool(enabled)
        self._auto_fired.clear()
        self.bus.publish({"type": "autonomous", "enabled": self.autonomous})
        self.bus.publish({
            "type": "log",
            "level": "warn" if self.autonomous else "info",
            "msg": (
                f"autonomous mode ARMED · watchdog will self-trigger the chain when "
                f"predicted failure risk exceeds {AUTONOMOUS_THRESHOLD:.2f}"
                if self.autonomous else "autonomous mode disarmed"
            ),
        })
        return {"ok": True, "enabled": self.autonomous}

    # -- metadata -----------------------------------------------------------

    def meta(self) -> Dict:
        return {
            "agents": AGENT_SPECS,
            "disruptions": [
                {
                    "key": k, "label": v["label"], "icon": v["icon"],
                    "severity": v["severity"],
                    "detected_as": v["detected_as"],
                    "modes": (
                        ["humanitarian"] if k == "cold_chain_breach"
                        else ["commercial", "humanitarian"]
                    ),
                }
                for k, v in DISRUPTIONS.items()
            ],
            "assumptions": ASSUMPTIONS,
            "emission_factors": [
                {"vehicle": k, "kg_co2e_per_km": v, "source": EMISSION_SOURCES[k]}
                for k, v in EMISSION_FACTORS.items()
            ],
            "models": MODEL_CARDS,
            "llm": self.llm.status,
            "autonomous": self.autonomous,
            "autonomous_threshold": AUTONOMOUS_THRESHOLD,
        }

    # -- background threads -------------------------------------------------

    def _simulate(self) -> None:
        while not self._stop.is_set():
            time.sleep(DRIFT_INTERVAL_SECONDS)
            try:
                self.world.drift()
                snapshot = self.world.snapshot()
                self.bus.publish({"type": "telemetry", "state": snapshot})
                if self.autonomous and not self._chain_active.is_set():
                    self._watchdog(snapshot)
            except Exception:
                traceback.print_exc()

    def _watchdog(self, snapshot: Dict) -> None:
        """Self-trigger the chain on a delivery predicted to fail."""
        for d in snapshot["deliveries"]:
            if d["status"] != "On Route":
                continue
            if d["id"] in self._auto_fired:
                continue
            if d["risk"] < AUTONOMOUS_THRESHOLD:
                continue
            key = self._infer_disruption(d)
            self._auto_fired.add(d["id"])
            self.bus.publish({
                "type": "risk_alert",
                "delivery_id": d["id"],
                "risk": d["risk"],
                "band": d["risk_band"],
                "dominant_factor": d["risk_top_driver"],
                "threshold": AUTONOMOUS_THRESHOLD,
                "inferred_disruption": key,
                "label": DISRUPTIONS[key]["label"],
            })
            self.bus.publish({
                "type": "log", "level": "warn",
                "msg": f"watchdog · {d['id']} risk {d['risk']:.2f} exceeded "
                       f"{AUTONOMOUS_THRESHOLD:.2f} · dominant factor "
                       f"'{d['risk_top_driver']}' · self-triggering chain, no human input",
            })
            self.enqueue(d["id"], key, trigger="autonomous-watchdog")
            return  # one at a time

    def _infer_disruption(self, d: Dict) -> str:
        """Map the dominant risk factor onto the disruption it predicts."""
        factor = (d.get("risk_top_driver") or "").lower()
        if self.world.is_humanitarian and d.get("cold_minutes_remaining", 999) < 60:
            return "cold_chain_breach"
        if "vehicle" in factor:
            return "cold_chain_breach" if self.world.is_humanitarian else "bike_breakdown"
        if "absence" in factor:
            return "customer_not_home"
        if "address" in factor:
            return "wrong_address"
        if "congestion" in factor:
            return "traffic_gridlock"
        if "fatigue" in factor:
            return "cold_chain_breach" if self.world.is_humanitarian else "bike_breakdown"
        return "traffic_gridlock"

    def _work(self) -> None:
        while not self._stop.is_set():
            try:
                delivery_id, disruption_key, trigger = self.incidents.get(timeout=0.5)
            except queue.Empty:
                continue
            self._chain_active.set()
            try:
                run_chain(
                    self.world, self.llm,
                    delivery_id=delivery_id,
                    disruption_key=disruption_key,
                    trigger=trigger,
                    emit=self.bus.publish,
                )
            except Exception as exc:
                traceback.print_exc()
                self.bus.publish({
                    "type": "log", "level": "error",
                    "msg": f"chain failed on {delivery_id}: {type(exc).__name__}: {exc}",
                })
                try:
                    self.world.deliveries[delivery_id]["status"] = "On Route"
                    self.bus.publish({"type": "state", "state": self.world.snapshot()})
                except Exception:
                    pass
            finally:
                # Last-resort guarantee: an incident must never leave a delivery
                # parked in "Resolving", which would disable its controls forever.
                # run_chain always sets a terminal status on every path, so this is
                # belt-and-braces against a path we haven't thought of.
                try:
                    d = self.world.deliveries.get(delivery_id)
                    if d is not None and d["status"] == "Resolving":
                        d["status"] = "On Route"
                        self.bus.publish({
                            "type": "log", "level": "error",
                            "msg": f"{delivery_id} was left mid-resolution; released "
                                   f"back to On Route. This is a bug — check the logs.",
                        })
                        self.bus.publish({"type": "state", "state": self.world.snapshot()})
                except Exception:
                    pass
                self._chain_active.clear()
                self.incidents.task_done()


ENGINE: Optional[Engine] = None


# ==========================================================================
# HTTP
# ==========================================================================

DISCONNECTS = (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)


class QuietServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that doesn't dump a traceback when a client hangs up.

    A long-lived SSE connection is closed by the browser on every page reload and
    on every navigation, which the socket layer surfaces as a connection reset
    mid-read. That is normal operation here, not an error worth printing.
    """

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, DISCONNECTS):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "AutoFleetAI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # keep the console clean
        pass

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except DISCONNECTS:
            self.close_connection = True

    # -- helpers ------------------------------------------------------------

    def _json(self, payload: Dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._json({"error": "not found"}, 404)
            return
        ctype, _ = mimetypes.guess_type(str(path))
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    # -- routes -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        route = self.path.split("?")[0]
        try:
            if route in ("/", "/index.html"):
                self._file(WEB_ROOT / "index.html")
            elif route in ("/react", "/react.html"):
                # The Figma-derived React frontend, served alongside rather than
                # instead of the dashboard. It mounts and streams, but does not
                # yet render the agent feed, the router card, the tool call or
                # the fact check — so it is not the demo default.
                self._file(WEB_ROOT / "react.html")
            elif route.startswith("/static/"):
                name = route[len("/static/"):]
                target = (WEB_ROOT / name).resolve()
                if WEB_ROOT.resolve() not in target.parents:
                    self._json({"error": "forbidden"}, 403)
                    return
                self._file(target)
            elif route == "/api/state":
                self._json({"state": ENGINE.world.snapshot(), "meta": ENGINE.meta()})
            elif route == "/api/stream":
                self._stream()
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?")[0]
        body = self._body()
        try:
            if route == "/api/disrupt":
                result = ENGINE.enqueue(
                    body.get("delivery_id", ""),
                    body.get("disruption", ""),
                    trigger=body.get("trigger", "manual"),
                )
                self._json(result, 200 if result.get("ok") else 400)
            elif route == "/api/mode":
                result = ENGINE.set_mode(body.get("mode", ""))
                self._json(result, 200 if result.get("ok") else 400)
            elif route == "/api/autonomous":
                self._json(ENGINE.set_autonomous(body.get("enabled", False)))
            elif route == "/api/reset":
                self._json(ENGINE.reset())
            else:
                self._json({"error": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    # -- SSE ----------------------------------------------------------------

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = ENGINE.bus.subscribe()
        try:
            self._send_event({
                "type": "hello",
                "state": ENGINE.world.snapshot(),
                "meta": ENGINE.meta(),
            })
            last_beat = time.time()
            while True:
                try:
                    event = q.get(timeout=1.0)
                    self._send_event(event)
                except queue.Empty:
                    if time.time() - last_beat > 12:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        last_beat = time.time()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            ENGINE.bus.unsubscribe(q)

    def _send_event(self, event: Dict) -> None:
        payload = json.dumps(event, default=str)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


def main() -> None:
    global ENGINE
    parser = argparse.ArgumentParser(description="AutoFleet AI dashboard server")
    parser.add_argument("--port", type=int, default=8600)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    ENGINE = Engine()
    status = ENGINE.llm.status

    httpd = QuietServer((args.host, args.port), Handler)

    lines = [
        "",
        "=" * 68,
        "  AutoFleet AI — autonomous last-mile disruption resolution",
        "=" * 68,
        f"  Dashboard   http://{args.host}:{args.port}",
        f"  Agents      {'LIVE · ' + status['model'] if status['live'] else 'SIMULATED'}",
        f"  {status['note']}",
    ]
    if not status["live"]:
        lines.append("  Set ANTHROPIC_API_KEY (or copy .env.example to .env) for live agents.")
    lines += ["=" * 68, ""]
    # flush explicitly: stdout is block-buffered when redirected to a file.
    print("\n".join(lines), flush=True)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
