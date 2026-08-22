"""Fleet state: deliveries, drivers, telemetry drift, and disruption effects.

Two scenarios share one engine. Commercial mode moves parcels; humanitarian mode
moves cold-chain medical consignments. The agent chain, the models and the
impact ledger are identical — only the payload and the objective change. That
shared-engine property is the point: the same coordination layer that reroutes a
parcel reroutes a blood bag.
"""

from __future__ import annotations

import random
import threading
from typing import Dict, List, Optional

from .geo import (NODES, ROADS, bounds, coord, nearest_nodes, road_km,
                  travel_minutes)
from .impact import ImpactLedger, avoided_redelivery_km
from .intent import IntentRegister
from .scoring import RISK_MODEL

# Doorstep / handover time added to every ETA, in minutes. ASSUMPTION.
SERVICE_MINUTES = 6.0

# Simulation clock. One drift tick is DRIFT_INTERVAL_SECONDS of real time (2.2s
# in server.py) and this many simulated minutes. Every time-based quantity —
# ETA, slack, shift, fatigue, cold-chain window — is scaled by this single
# constant so they cannot drift out of step with each other. The old code used
# four different rates (0.35, 0.30, 2.0, 0.03/h) which is why slack hit zero
# while the ETA was still counting.
SIM_MINUTES_PER_TICK = 0.6

# On-road distance at which a courier counts as arrived.
ARRIVAL_KM = 0.25

# The simulated day starts here (minutes since midnight). Stated intents like
# "nothing after 18:00" need a wall clock to be checkable, and a wall clock is
# also far more legible to a reader than "in 43 minutes".
# 17:20. Deliberately inside the evening peak, which is both when last-mile
# delivery actually fails and the only time a stated cutoff can bite: starting
# the day at 15:40 left every 18:00 deadline two hours of slack, so the conflict
# check had nothing to find until the demo had been running for an hour.
SIM_START_MINUTES = 17 * 60 + 20

# How long a delivered job stays on the board before being retired, so an
# operator actually sees it land rather than having rows vanish mid-glance.
DELIVERED_LINGER_TICKS = 6

# Active jobs the sim keeps in flight. A completed delivery is replaced so the
# board never empties during a demo.
FLEET_TARGET = 4

# How long an escalated delivery waits for a human before the simulation stops
# holding it open. An escalation used to be terminal: the delivery kept a fleet
# slot forever, never advanced and never retired, so escalating four deliveries
# froze the board — no new work, no completions, dead until Reset. A real
# dispatcher queue has a timeout, and so does this one.
ESCALATION_TIMEOUT_TICKS = 90        # ~3.3 min of real time

# How far a human "extend the window" decision pushes the promise out.
RESCHEDULE_MINUTES = 45.0

# Shift length and the rest between shifts, in simulated minutes / ticks.
SHIFT_MINUTES = 210
REST_TICKS = 25

# Not every delivery is routine. A real book has a tail: an address the geocoder
# is unsure of, a recipient with a history of being out, a corridor that is
# already bad. Drawing every spawned job from one benign distribution left the
# risk model with nothing to flag and the autonomous watchdog firing about once
# an hour — the model is calibrated to sit healthy deliveries well below the
# alert line and stressed ones near it, which only means something if stressed
# deliveries actually occur. This is the tail, not a thumb on the scale: the
# features are worse, and the score is whatever the model makes of them.
DIFFICULT_JOB_SHARE = 0.28

# Recipients and payloads for respawned jobs. Names only — no addresses, no
# real people.
_COMMERCIAL_JOBS = [
    ("Rohan Mehta", "1 parcel · electronics return", 2),
    ("Sneha Kulkarni", "2 parcels · retail", 4),
    ("Vikram Shetty", "1 pallet · bulk plastics", 30),
    ("Ananya Iyer", "1 parcel · e-waste pickup", 3),
    ("Deepa Rao", "3 parcels · retail", 6),
    ("Karthik Nair", "1 crate · appliance return", 12),
    ("Meghna Bose", "1 parcel · documents", 1),
    ("Arvind Menon", "2 crates · e-waste pickup", 14),
]

_HUMANITARIAN_JOBS = [
    ("Anekal PHC · cold room", "cold-chain vaccine consignment", 18),
    ("Hoskote PHC · blood bank", "blood products consignment", 22),
    ("Magadi PHC · Dr. Ramesh K", "cold-chain vaccine consignment", 12),
    ("Ramanagara DH · cold room", "cold-chain vaccine consignment", 30),
    ("Nelamangala PHC · Dr. Asha R", "insulin and cold stock", 15),
    ("Doddaballapur CHC · cold room", "cold-chain vaccine consignment", 26),
]

COMMERCIAL_NODES = [
    "hub_yeshwanthpur", "malleshwaram", "rajajinagar", "mg_road", "indiranagar",
    "koramangala", "hsr_layout", "jayanagar", "banashankari", "marathahalli",
    "whitefield", "hebbal", "electronic_city",
]

HUMANITARIAN_NODES = [
    "hub_bowring", "mg_road", "hebbal", "rajajinagar", "banashankari",
    "hsr_layout", "electronic_city", "whitefield", "anekal_phc", "hoskote_phc",
    "doddaballapur_chc", "magadi_phc", "ramanagara_dh", "nelamangala_phc",
]


# ==========================================================================
# Disruption catalogue
# ==========================================================================

DISRUPTIONS: Dict[str, Dict] = {
    "bike_breakdown": {
        "needs_customer_decision": True,
        "label": "Vehicle Breakdown",
        "icon": "🔧",
        "severity": "high",
        "disables_driver": True,
        "needs_replacement_stock": False,
        "route_penalty_min": 0.0,
        "driver_support": "roadside assistance",
        "reported_by": "courier",
        "reported_why": "Rider reports the bike will not start; telematics corroborates",
        "detected_as": "Telematics: engine fault code, zero motion for 4 min",
        "customer_frame": "delay caused by a courier vehicle failure",
    },
    "customer_not_home": {
        "needs_customer_decision": True,
        "label": "Recipient Not Home",
        "icon": "🚪",
        "severity": "medium",
        "disables_driver": False,
        "needs_replacement_stock": False,
        "route_penalty_min": 4.0,
        "driver_support": None,
        "reported_by": "courier",
        "reported_why": "Rider is at the door and nobody answers",
        "detected_as": "Two failed contact attempts at the doorstep geofence",
        "customer_frame": "recipient unavailable at the delivery window",
    },
    "wrong_address": {
        "needs_customer_decision": True,
        "label": "Address Mismatch",
        "icon": "📍",
        "severity": "medium",
        "disables_driver": False,
        "needs_replacement_stock": False,
        "route_penalty_min": 9.0,
        "driver_support": None,
        "reported_by": "courier",
        "reported_why": "Rider is at the pin and the address does not match",
        "detected_as": "Geocode confidence dropped below threshold at approach",
        "customer_frame": "address could not be resolved on arrival",
    },
    "traffic_gridlock": {
        "needs_customer_decision": False,
        "label": "Corridor Gridlock",
        "icon": "🚧",
        "severity": "medium",
        "disables_driver": False,
        "needs_replacement_stock": False,
        "route_penalty_min": 16.0,
        "driver_support": None,
        "reported_by": "system",
        "reported_why": "Corridor speed feed; the rider cannot see the whole corridor",
        "detected_as": "Corridor speed collapsed to under 4 km/h for 6 min",
        "customer_frame": "unexpected road closure on the delivery corridor",
    },
    "package_damaged": {
        "needs_customer_decision": True,
        "label": "Payload Damaged",
        "icon": "📦",
        "severity": "high",
        "disables_driver": False,
        "needs_replacement_stock": True,
        "route_penalty_min": 0.0,
        "driver_support": None,
        "reported_by": "courier",
        "reported_why": "Rider sees the damage while handling the payload",
        "detected_as": "Courier-reported damage, payload integrity check failed",
        "customer_frame": "the item was damaged in transit and is being replaced",
    },
    "conflicting_assignment": {
        "needs_customer_decision": False,
        "label": "Conflicting Assignment",
        "icon": "⚡",
        "severity": "medium",
        "disables_driver": False,
        "needs_replacement_stock": False,
        "route_penalty_min": 6.0,
        "driver_support": None,
        "reported_by": "system",
        "reported_why": "Dispatch detects two active jobs in one window",
        "detected_as": "Two active jobs assigned to one courier in the same window",
        "customer_frame": "a scheduling conflict on the courier's route",
    },
    "priority_override": {
        "needs_customer_decision": True,
        "label": "Priority Override",
        "icon": "⏫",
        "severity": "high",
        "disables_driver": False,
        "needs_replacement_stock": False,
        "route_penalty_min": 3.0,
        "driver_support": None,
        "reported_by": "system",
        "reported_why": "Ops injects a higher-priority consignment",
        "detected_as": "Higher-priority consignment injected into the same corridor",
        "customer_frame": "a re-sequenced delivery window",
    },
    "cold_chain_breach": {
        "needs_customer_decision": True,
        "label": "Cold Chain At Risk",
        "icon": "🌡️",
        "severity": "critical",
        "disables_driver": True,
        "needs_replacement_stock": False,
        "route_penalty_min": 0.0,
        "driver_support": "cold-box swap and vehicle recovery",
        "reported_by": "system",
        "reported_why": "Payload probe telemetry",
        "detected_as": "Payload probe rising 0.4 C/min, breach window closing",
        "customer_frame": "consignment integrity risk requiring immediate transfer",
    },
}


def _lerp(a, b, t: float):
    """Interpolate between two (lat, lon) pairs — an in-flight driver's position."""
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _driver(
    did: str, name: str, node: str, vehicle_type: str, vehicle_label: str,
    *, status="available", on_time=0.94, cold=False, capacity=4, load=0,
    shift_remaining=210, hours_on_shift=3.0, health_risk=0.10,
    payload_units=12, zones=(), nudge=(0.0, 0.0), at_override=None,
) -> Dict:
    # `nudge` offsets a driver from the node centroid in degrees, so two drivers
    # in the same locality are not at an identical coordinate. ~0.0019 deg is
    # roughly 0.4 km of on-road distance. `at_override` places a driver at an
    # arbitrary point — used to put a standby courier on a live corridor rather
    # than parked on a node centroid.
    base = coord(node)
    at = tuple(at_override) if at_override else (base[0] + nudge[0], base[1] + nudge[1])
    return {
        "id": did,
        "name": name,
        "located_at": node,
        "at": at,
        "vehicle_type": vehicle_type,
        "vehicle_label": vehicle_label,
        "status": status,
        "on_time_rate": on_time,
        "cold_chain_capable": cold,
        "capacity": capacity,
        "active_load": load,
        "shift_remaining_minutes": float(shift_remaining),
        "hours_on_shift": hours_on_shift,
        "vehicle_health_risk": health_risk,
        "payload_capacity_units": payload_units,
        "familiar_zones": list(zones),
        "assigned_delivery": None,
        "unavailable_reason": None,
        "support_dispatched": None,
        "earnings_protected": False,
    }


def _commercial_state() -> Dict:
    # A standby courier working the same arterial road as D-102, positioned just
    # behind that delivery's driver. Reassignment realism depends on this: a
    # replacement must collect the payload from wherever the breakdown happened,
    # so a driver parked next to the *customer* would still owe a long round trip.
    suresh_at = _lerp(coord("hub_yeshwanthpur"), coord("koramangala"), 0.755)

    drivers = [
        _driver("DR-01", "Priya Nair", "indiranagar", "2w_petrol", "Petrol two-wheeler",
                status="on_route", on_time=0.96, health_risk=0.08, hours_on_shift=2.5,
                zones=("indiranagar", "mg_road")),
        _driver("DR-02", "Arjun Singh", "koramangala", "2w_petrol", "Petrol two-wheeler",
                status="on_route", on_time=0.91, health_risk=0.42, hours_on_shift=6.5,
                zones=("koramangala", "hsr_layout")),
        _driver("DR-03", "Imran Khan", "hsr_layout", "2w_electric", "Electric two-wheeler",
                status="on_route", on_time=0.93, health_risk=0.12, hours_on_shift=4.0,
                zones=("hsr_layout", "koramangala")),
        _driver("DR-04", "Kavya Reddy", "marathahalli", "3w_electric", "Electric three-wheeler",
                status="on_route", on_time=0.89, health_risk=0.18, hours_on_shift=5.0,
                capacity=6, payload_units=30, zones=("whitefield", "marathahalli")),
        # Standby pool
        _driver("DR-11", "Suresh Kumar", "koramangala", "2w_petrol", "Petrol two-wheeler",
                on_time=0.97, health_risk=0.06, hours_on_shift=1.5, load=1,
                shift_remaining=245, at_override=suresh_at,
                zones=("koramangala", "hsr_layout", "jayanagar")),
        _driver("DR-12", "Meera Joshi", "indiranagar", "2w_electric", "Electric two-wheeler",
                on_time=0.95, health_risk=0.09, hours_on_shift=2.0, load=2,
                nudge=(-0.0042, 0.0031), zones=("indiranagar", "mg_road")),
        _driver("DR-13", "Farhan Ali", "hsr_layout", "2w_petrol", "Petrol two-wheeler",
                on_time=0.90, health_risk=0.15, hours_on_shift=7.5, shift_remaining=55,
                nudge=(0.0038, -0.0044), zones=("hsr_layout",)),
        _driver("DR-14", "Nikhil Verma", "marathahalli", "2w_petrol", "Petrol two-wheeler",
                on_time=0.92, health_risk=0.11, hours_on_shift=3.5, load=1,
                nudge=(-0.0035, 0.0040), zones=("marathahalli", "whitefield")),
        _driver("DR-15", "Lakshmi Devi", "jayanagar", "3w_electric", "Electric three-wheeler",
                on_time=0.94, health_risk=0.10, hours_on_shift=2.0, capacity=6,
                payload_units=30, nudge=(0.0044, 0.0036),
                zones=("jayanagar", "banashankari")),
        _driver("DR-16", "Ravi Shankar", "whitefield", "van_diesel", "Diesel LGV",
                on_time=0.88, health_risk=0.22, hours_on_shift=4.5, capacity=12,
                payload_units=90, nudge=(-0.0040, -0.0037),
                zones=("whitefield", "marathahalli")),
    ]

    deliveries = [
        {
            "progress": 0.80, "id": "D-101", "driver_id": "DR-01", "recipient": "Ananya Iyer",
            "origin": "hub_yeshwanthpur", "destination": "indiranagar",
            "zone": "indiranagar", "status": "On Route", "eta_minutes": 9.0,
            "payload": "1 parcel · electronics return", "payload_units": 2,
            "cold_chain": False, "address_confidence": 0.93,
            "recipient_absence_rate": 0.11, "slack_minutes": 10.0,
            "telemetry": {"traffic_index": 0.38, "weather_risk": 0.12},
        },
        {
            "progress": 0.78, "id": "D-102", "driver_id": "DR-02", "recipient": "Rohan Mehta",
            "origin": "hub_yeshwanthpur", "destination": "koramangala",
            "zone": "koramangala", "status": "On Route", "eta_minutes": 12.0,
            "payload": "1 parcel · e-waste pickup", "payload_units": 3,
            "cold_chain": False, "address_confidence": 0.88,
            "recipient_absence_rate": 0.19, "slack_minutes": 11.0,
            "telemetry": {"traffic_index": 0.52, "weather_risk": 0.15},
        },
        {
            "progress": 0.50, "id": "D-103", "driver_id": "DR-03", "recipient": "Deepa Rao",
            "origin": "hub_yeshwanthpur", "destination": "hsr_layout",
            "zone": "hsr_layout", "status": "On Route", "eta_minutes": 21.0,
            "payload": "2 parcels · retail", "payload_units": 4,
            "cold_chain": False, "address_confidence": 0.71,
            "recipient_absence_rate": 0.28, "slack_minutes": 8.0,
            "telemetry": {"traffic_index": 0.61, "weather_risk": 0.22},
        },
        {
            "progress": 0.40, "id": "D-104", "driver_id": "DR-04", "recipient": "Vikram Shetty",
            "origin": "hub_yeshwanthpur", "destination": "whitefield",
            "zone": "whitefield", "status": "On Route", "eta_minutes": 34.0,
            "payload": "1 pallet · bulk plastics", "payload_units": 22,
            "cold_chain": False, "address_confidence": 0.90,
            "recipient_absence_rate": 0.09, "slack_minutes": 22.0,
            "telemetry": {"traffic_index": 0.44, "weather_risk": 0.10},
        },
    ]
    return {"drivers": drivers, "deliveries": deliveries}


def _humanitarian_state() -> Dict:
    drivers = [
        _driver("DR-51", "Sunil Gowda", "hsr_layout", "refrigerated_van", "Refrigerated van",
                status="on_route", on_time=0.95, cold=True, health_risk=0.10,
                hours_on_shift=3.0, capacity=8, payload_units=60,
                zones=("anekal_phc", "electronic_city")),
        _driver("DR-52", "Fatima Sheikh", "whitefield", "refrigerated_van", "Refrigerated van",
                status="on_route", on_time=0.92, cold=True, health_risk=0.38,
                hours_on_shift=6.0, capacity=8, payload_units=60,
                zones=("hoskote_phc", "whitefield")),
        _driver("DR-53", "Vinod Kamath", "hebbal", "refrigerated_van", "Refrigerated van",
                status="on_route", on_time=0.94, cold=True, health_risk=0.14,
                hours_on_shift=4.5, capacity=8, payload_units=60,
                zones=("doddaballapur_chc", "hebbal")),
        _driver("DR-54", "Anita Bhat", "rajajinagar", "3w_electric", "Electric cold-box three-wheeler",
                status="on_route", on_time=0.90, cold=True, health_risk=0.16,
                hours_on_shift=5.0, capacity=4, payload_units=20,
                zones=("nelamangala_phc", "magadi_phc")),
        # Standby pool
        _driver("DR-61", "Suresh Kumar", "electronic_city", "refrigerated_van", "Refrigerated van",
                on_time=0.97, cold=True, health_risk=0.05, hours_on_shift=1.0,
                shift_remaining=250, capacity=8, payload_units=60,
                nudge=(-0.0180, 0.0150),
                zones=("anekal_phc", "electronic_city", "hsr_layout")),
        _driver("DR-62", "Geeta Pillai", "hebbal", "refrigerated_van", "Refrigerated van",
                on_time=0.96, cold=True, health_risk=0.08, hours_on_shift=2.0,
                capacity=8, payload_units=60, nudge=(0.0052, -0.0041),
                zones=("doddaballapur_chc", "hebbal")),
        _driver("DR-63", "Mahesh Rao", "whitefield", "refrigerated_van", "Refrigerated van",
                on_time=0.93, cold=True, health_risk=0.12, hours_on_shift=3.0, load=1,
                capacity=8, payload_units=60, nudge=(0.0061, 0.0048),
                zones=("hoskote_phc",)),
        _driver("DR-64", "Joseph Mathew", "banashankari", "van_diesel", "Diesel van (no cold box)",
                on_time=0.91, cold=False, health_risk=0.13, hours_on_shift=2.5,
                capacity=10, payload_units=80, nudge=(-0.0050, -0.0045),
                zones=("ramanagara_dh",)),
        _driver("DR-65", "Shalini Prasad", "rajajinagar", "refrigerated_van", "Refrigerated van",
                on_time=0.95, cold=True, health_risk=0.09, hours_on_shift=1.5,
                capacity=8, payload_units=60, nudge=(0.0044, 0.0052),
                zones=("nelamangala_phc", "magadi_phc")),
        _driver("DR-66", "Basavaraj T", "mg_road", "2w_electric", "Electric two-wheeler",
                on_time=0.89, cold=False, health_risk=0.10, hours_on_shift=4.0,
                capacity=3, payload_units=6, nudge=(-0.0038, 0.0035),
                zones=("mg_road",)),
    ]

    deliveries = [
        {
            "progress": 0.45, "id": "V-201", "driver_id": "DR-51", "recipient": "Anekal PHC · Dr. Latha M",
            "origin": "hub_bowring", "destination": "anekal_phc",
            "zone": "anekal_phc", "status": "On Route", "eta_minutes": 26.0,
            "payload": "47 doses · measles-rubella", "payload_units": 12,
            "doses": 47, "cold_chain": True, "cold_minutes_remaining": 158.0,
            "address_confidence": 0.95, "recipient_absence_rate": 0.05,
            "slack_minutes": 18.0,
            "telemetry": {"traffic_index": 0.41, "weather_risk": 0.14},
        },
        {
            "progress": 0.31, "id": "V-202", "driver_id": "DR-52", "recipient": "Hoskote PHC · blood bank",
            "origin": "hub_bowring", "destination": "hoskote_phc",
            "zone": "hoskote_phc", "status": "On Route", "eta_minutes": 31.0,
            "payload": "2 units · O-negative whole blood", "payload_units": 6,
            "doses": 2, "cold_chain": True, "cold_minutes_remaining": 94.0,
            "address_confidence": 0.92, "recipient_absence_rate": 0.04,
            "slack_minutes": 9.0,
            "telemetry": {"traffic_index": 0.57, "weather_risk": 0.20},
        },
        {
            "progress": 0.22, "id": "V-203", "driver_id": "DR-53", "recipient": "Doddaballapur CHC · cold room",
            "origin": "hub_bowring", "destination": "doddaballapur_chc",
            "zone": "doddaballapur_chc", "status": "On Route", "eta_minutes": 44.0,
            "payload": "120 doses · pentavalent", "payload_units": 24,
            "doses": 120, "cold_chain": True, "cold_minutes_remaining": 212.0,
            "address_confidence": 0.88, "recipient_absence_rate": 0.06,
            "slack_minutes": 25.0,
            "telemetry": {"traffic_index": 0.35, "weather_risk": 0.11},
        },
        {
            "progress": 0.18, "id": "V-204", "driver_id": "DR-54", "recipient": "Magadi PHC · Dr. Ramesh K",
            "origin": "hub_bowring", "destination": "magadi_phc",
            "zone": "magadi_phc", "status": "On Route", "eta_minutes": 58.0,
            "payload": "insulin + anti-venom consignment", "payload_units": 8,
            "doses": 36, "cold_chain": True, "cold_minutes_remaining": 240.0,
            "address_confidence": 0.79, "recipient_absence_rate": 0.08,
            "slack_minutes": 15.0,
            "telemetry": {"traffic_index": 0.48, "weather_risk": 0.18},
        },
    ]
    return {"drivers": drivers, "deliveries": deliveries}


class World:
    """Mutable fleet state with a background telemetry drift and a risk view."""

    def __init__(self, mode: str = "commercial", seed: int = 7) -> None:
        self.lock = threading.RLock()
        self.rng = random.Random(seed)
        self.ledger = ImpactLedger()
        # Stated goals, checked before any commit. Seeded per scenario in
        # _seed_intents(); editable at runtime so the check can be demonstrated
        # to change a decision rather than just described.
        self.intents = IntentRegister()
        # Every decision a person took on an escalation, with who, when and why.
        # An override that leaves no trace is worse than no override at all.
        self.decisions: List[Dict] = []
        self.incident_seq = 0
        self.mode = mode
        self.tick = 0
        # Bumped on every (re)load. An in-flight agent chain captures this and
        # aborts if the world is reset or the scenario switched underneath it,
        # rather than half-applying a decision to state that no longer exists.
        self.generation = 0
        # Ids for respawned deliveries continue past the seeded ones, so a job
        # number is never reused within a session.
        self.delivery_seq = 0
        self.completed = 0
        self._load(mode)

    # -- lifecycle ----------------------------------------------------------

    def _load(self, mode: str) -> None:
        state = _humanitarian_state() if mode == "humanitarian" else _commercial_state()
        self.mode = mode
        self.generation = getattr(self, "generation", 0) + 1
        self.drivers = {d["id"]: d for d in state["drivers"]}
        self.deliveries = {d["id"]: d for d in state["deliveries"]}
        self.delivery_seq = len(state["deliveries"])
        self._seed_intents()
        self.completed = 0
        for d in self.deliveries.values():
            drv = self.drivers[d["driver_id"]]
            drv["assigned_delivery"] = d["id"]
            d["original_driver_id"] = d["driver_id"]
            d["incidents"] = []
            d["reroute"] = None
            d["handover_at"] = None
            d["handover"] = None
            # An en-route driver sits partway along their corridor, not on top of
            # the destination node — otherwise remaining distance reads as zero.
            if drv["status"] == "on_route":
                drv["at"] = _lerp(coord(d["origin"]), coord(d["destination"]), d["progress"])
            # Derive the ETA from geometry rather than seeding it, so the number on
            # the card and the path on the map can never disagree.
            d["eta_minutes"] = round(
                travel_minutes(
                    road_km(drv["at"], coord(d["destination"])),
                    d["telemetry"]["traffic_index"],
                    self.is_humanitarian,
                ) + SERVICE_MINUTES,
                1,
            )
            # Seeded jobs carry a hand-set slack; turn it into the same
            # promise-based representation the rest of the sim uses.
            d["promised_minutes"] = round(
                d["eta_minutes"] + d.get("slack_minutes", 12.0), 1
            )
        self.tick = 0

    def set_mode(self, mode: str) -> None:
        with self.lock:
            self._load(mode)
            self.ledger.reset()
            self.incident_seq = 0

    def reset(self) -> None:
        with self.lock:
            self._load(self.mode)
            self.ledger.reset()
            self.incident_seq = 0

    def _seed_intents(self) -> None:
        """Stated goals for the deliveries currently on the board.

        Written as the holder would say them, because that is the difference
        between an intent and a constraint: a person said this, owns it, and can
        withdraw it. The recipient deadlines are deliberately set so that ONE of
        them is already tight against a realistic reassignment — a conflict
        check that never finds anything proves nothing.
        """
        self.intents.clear()
        active = [d for d in self.deliveries.values()
                  if d["status"] not in ("Delivered", "Cancelled")]

        # Operations holds fleet-wide policy. Soft: a breach is a disclosed cost,
        # not a veto, or the system could never trade anything off.
        self.intents.add(
            holder="Operations", holder_type="operations", kind="sla_promise",
            statement="Do not breach a promised delivery window without saying so.",
            params={}, hardness="soft", scope="*",
            declared="dispatch policy",
        )
        self.intents.add(
            holder="Operations", holder_type="operations", kind="approach_ceiling",
            statement="No reassignment may add more than 8 km of empty running.",
            params={"max_approach_km": 8.0}, hardness="hard", scope="*",
            declared="cost policy",
        )

        if self.is_humanitarian:
            for d in active:
                self.intents.add(
                    holder=d["recipient"], holder_type="payload",
                    kind="cold_window",
                    statement="We need 20 minutes to receive a consignment and "
                              "get it into the cold room.",
                    params={"handling_margin_minutes": 20.0},
                    hardness="hard", scope=d["id"],
                    declared="consignment manifest",
                )
            return

        # Commercial: one hard cutoff, one refusal of substitution, one courier
        # who will not work past their shift. Between them, the three most
        # common real-world objections to an automated reassignment.
        cutoffs = [18 * 60, 18 * 60 + 45, 19 * 60 + 30, 20 * 60]
        for i, d in enumerate(active):
            self.intents.add(
                holder=d["recipient"], holder_type="recipient",
                kind="delivery_deadline",
                statement=f"Nothing after {cutoffs[i % len(cutoffs)] // 60:02d}:"
                          f"{cutoffs[i % len(cutoffs)] % 60:02d} — I am out after that.",
                params={"by_minutes": cutoffs[i % len(cutoffs)]},
                hardness="hard", scope=d["id"],
                declared="stated at booking",
            )
        if active:
            first = active[0]
            self.intents.add(
                holder=first["recipient"], holder_type="recipient",
                kind="no_substitute_handoff",
                statement="Only the courier I was notified about — do not send "
                          "someone else.",
                params={}, hardness="soft", scope=first["id"],
                declared="stated at booking",
            )
        # A named courier's own boundary, scoped to them so it cannot leak onto
        # anyone else's job.
        for drv in list(self.drivers.values())[:1]:
            self.intents.add(
                holder=drv["name"], holder_type="courier", kind="shift_limit",
                statement="Leave me 30 minutes at the end of my shift — I have "
                          "to get home.",
                params={"buffer_minutes": 30.0}, hardness="hard", scope=drv["id"],
                declared="rider agreement",
            )

    @property
    def clock_minutes(self) -> float:
        """Simulated time of day, in minutes since midnight."""
        return SIM_START_MINUTES + self.tick * SIM_MINUTES_PER_TICK

    @property
    def clock(self) -> str:
        m = int(round(self.clock_minutes)) % (24 * 60)
        return f"{m // 60:02d}:{m % 60:02d}"

    @property
    def is_humanitarian(self) -> bool:
        return self.mode == "humanitarian"

    @property
    def hub(self) -> str:
        return "hub_bowring" if self.is_humanitarian else "hub_yeshwanthpur"

    @property
    def nodes(self) -> List[str]:
        return HUMANITARIAN_NODES if self.is_humanitarian else COMMERCIAL_NODES

    # -- telemetry ----------------------------------------------------------

    def _remaining_km(self, d: Dict) -> float:
        """On-road distance the carrier still has to cover for this delivery.

        A reassigned courier has two legs — ride to the payload, then carry it —
        so the remaining distance is the sum. Measuring from the driver's live
        position rather than counting down a stored number is what keeps the ETA,
        the map and the courier's route agreeing with each other.
        """
        drv = self.drivers.get(d["driver_id"])
        if not drv:
            return 0.0
        dest = coord(d["destination"])
        collect = d.get("handover_at")
        if collect and d.get("status") == "Reassigned":
            return road_km(drv["at"], tuple(collect)) + road_km(tuple(collect), dest)
        return road_km(drv["at"], dest)

    def _recompute_eta(self, d: Dict) -> None:
        """Derive the ETA from live geometry and live congestion.

        The old drift subtracted a flat 0.35 from a stored value and floored it
        at 1.0, which meant the ETA was a countdown disconnected from the world:
        it ignored congestion entirely and every delivery ended up parked at
        "1 min" forever without arriving. Now it is a function of where the
        courier actually is and how bad the corridor actually is, so it can rise
        when traffic worsens — which is the entire point of showing it.
        """
        d["eta_minutes"] = round(
            travel_minutes(
                self._remaining_km(d),
                d["telemetry"]["traffic_index"],
                self.is_humanitarian,
            ) + SERVICE_MINUTES,
            1,
        )

    def _advance(self, d: Dict) -> None:
        """Move the carrier along their route by one tick's worth of travel."""
        drv = self.drivers.get(d["driver_id"])
        if not drv:
            return
        remaining = self._remaining_km(d)
        if remaining <= 0:
            return
        speed_kmh = remaining / max(
            travel_minutes(remaining, d["telemetry"]["traffic_index"],
                           self.is_humanitarian) / 60.0,
            1e-6,
        )
        step_km = speed_kmh * (SIM_MINUTES_PER_TICK / 60.0)

        # Aim at the collection point first if the payload is not yet in hand.
        collect = d.get("handover_at")
        if collect and d.get("status") == "Reassigned":
            to_collect = road_km(drv["at"], tuple(collect))
            if to_collect > ARRIVAL_KM:
                drv["at"] = _lerp(drv["at"], tuple(collect),
                                  min(1.0, step_km / max(to_collect, 1e-6)))
                return
            # Payload collected — from here it is a normal run to the drop.
            d["handover_at"] = None

        dest = coord(d["destination"])
        to_dest = road_km(drv["at"], dest)
        drv["at"] = _lerp(drv["at"], dest, min(1.0, step_km / max(to_dest, 1e-6)))
        journey = road_km(coord(d["origin"]), dest)
        d["progress"] = min(1.0, 1.0 - (road_km(drv["at"], dest) / max(journey, 1e-6)))

    def _complete(self, d: Dict) -> None:
        """Deliver it: free the courier and retire the job."""
        d["status"] = "Delivered"
        d["eta_minutes"] = 0.0
        d["progress"] = 1.0
        d["delivered_tick"] = self.tick
        drv = self.drivers.get(d["driver_id"])
        if drv:
            drv["assigned_delivery"] = None
            drv["active_load"] = max(0, drv["active_load"] - 1)
            # A courier who was released earlier stays off the road; anyone else
            # is free for the next job.
            if drv["status"] != "unavailable":
                drv["status"] = "available"
        self.completed += 1

    def escalate(
        self, *, delivery_id: str, incident_id: str, reason: str,
        disruption_key: Optional[str] = None, blocking: Optional[List[Dict]] = None,
    ) -> Dict:
        """Hand a delivery to a human, and leave it in a state that can be acted on.

        Both escalation paths — no eligible driver, and no option satisfying
        every stated intent — come through here so the bookkeeping cannot differ
        between them.

        Two things beyond setting a status. The courier is released honestly: if
        the disruption disabled them, a rider whose bike will not start must not
        keep showing as carrying a job nobody is resolving. And the wait is
        stamped, so the simulation can stop holding the delivery open forever if
        nobody answers.
        """
        with self.lock:
            d = self.deliveries.get(delivery_id)
            if d is None:
                return {"ok": False}
            d["status"] = "Escalated"
            d["escalated_tick"] = self.tick
            d["escalation_reason"] = reason
            d["escalation_incident"] = incident_id
            d["escalation_disruption"] = disruption_key
            d["escalation_blocking"] = blocking or []
            d["awaiting_decision_since"] = self.clock

            disruption = DISRUPTIONS.get(disruption_key or "", {})
            drv = self.drivers.get(d["driver_id"])
            if drv is not None and disruption.get("disables_driver"):
                drv["status"] = "unavailable"
                drv["unavailable_reason"] = disruption.get("label", "incident")
                drv["support_dispatched"] = disruption.get("driver_support")
                drv["earnings_protected"] = True
                drv["assigned_delivery"] = None
                drv["active_load"] = max(0, drv["active_load"] - 1)

            self.ledger.record_escalation(
                incident_id=incident_id, delivery_id=delivery_id, reason=reason,
            )
            return {"ok": True, "delivery": d}

    def _resolve_stale_escalations(self) -> List[Dict]:
        """Close out escalations nobody answered. Called with the lock held.

        Not a resolution the system gets credit for: the human intervention is
        already on the ledger and stays there. This only stops an unattended
        demo from wedging. If the original courier can still carry the job it
        goes back to them; if they were disabled, the delivery is cancelled
        honestly rather than left pending forever.
        """
        closed = []
        for d in self.deliveries.values():
            if d["status"] != "Escalated":
                continue
            waited = self.tick - d.get("escalated_tick", self.tick)
            if waited < ESCALATION_TIMEOUT_TICKS:
                continue
            drv = self.drivers.get(d.get("original_driver_id"))
            if drv is not None and drv["status"] in ("available", "on_route"):
                drv["status"] = "on_route"
                drv["assigned_delivery"] = d["id"]
                d["driver_id"] = drv["id"]
                d["status"] = "On Route"
                d["timed_out_to_original"] = True
                self._recompute_eta(d)
                closed.append({"delivery_id": d["id"], "outcome": "reverted",
                               "driver": drv["name"]})
            else:
                d["status"] = "Cancelled"
                d["delivered_tick"] = self.tick
                closed.append({"delivery_id": d["id"], "outcome": "cancelled",
                               "driver": None})
            for key in ("escalated_tick", "awaiting_decision_since"):
                d.pop(key, None)
        return closed

    # -- human decisions on escalations -------------------------------------

    def pending_decisions(self):
        """Escalations waiting on a person, each with the options actually open.

        The options are derived from the conflict, not a fixed menu: you can only
        override an intent that is genuinely blocking, and you can only hand the
        job back to a courier who can still carry it.
        """
        out = []
        with self.lock:
            for d in self.deliveries.values():
                if d["status"] != "Escalated":
                    continue
                blocking = d.get("escalation_blocking") or []
                original = self.drivers.get(d.get("original_driver_id") or "")
                can_retain = bool(
                    original and original["status"] in ("available", "on_route")
                )
                options = []
                for v in blocking:
                    intent = self.intents.get(v.get("intent_id", ""))
                    if intent is None or not intent.active:
                        continue
                    options.append({
                        "action": "override_intent",
                        "intent_id": intent.id,
                        "label": "Override " + intent.holder + "'s intent",
                        "detail": intent.statement,
                        "cost": v.get("hint", ""),
                        "destructive": False,
                    })
                if can_retain:
                    options.append({
                        "action": "retain_original",
                        "label": "Keep " + original["name"] + " on the job",
                        "detail": "Accept the delay and leave the delivery with "
                                  "the courier who already has it.",
                        "cost": "the stated intent is breached, on the record",
                        "destructive": False,
                    })
                options.append({
                    "action": "reschedule",
                    "label": "Extend the promised window",
                    "detail": "Push the promise out by %.0f minutes and let the "
                              "system decide again." % RESCHEDULE_MINUTES,
                    "cost": "recipient is told the window moved",
                    "destructive": False,
                })
                options.append({
                    "action": "cancel",
                    "label": "Cancel the delivery",
                    "detail": "Nothing is delivered today.",
                    "cost": "the payload does not arrive",
                    "destructive": True,
                })
                out.append({
                    "delivery_id": d["id"],
                    "incident_id": d.get("escalation_incident"),
                    "recipient": d["recipient"],
                    "payload": d["payload"],
                    "destination_name": d.get("destination_name"),
                    "reason": d.get("escalation_reason", ""),
                    "blocking": blocking,
                    "since": d.get("awaiting_decision_since"),
                    "waited_ticks": self.tick - d.get("escalated_tick", self.tick),
                    "timeout_ticks": ESCALATION_TIMEOUT_TICKS,
                    "options": options,
                })
        return out

    def apply_decision(self, *, delivery_id, action, intent_id="",
                       actor="operations", note=""):
        """Record and apply one human decision on an escalated delivery.

        Returns `requeue` when the decision changes the INPUTS rather than
        imposing an outcome. Overriding an intent, or moving the promise, means
        the chain should decide again with the new facts — a person withdrawing a
        constraint is not the same as a person picking the courier.
        """
        with self.lock:
            d = self.deliveries.get(delivery_id)
            if d is None:
                return {"ok": False, "error": "unknown delivery " + str(delivery_id)}
            if d["status"] != "Escalated":
                return {"ok": False,
                        "error": str(delivery_id) + " is not awaiting a decision"}

            record = {
                "delivery_id": delivery_id,
                "incident_id": d.get("escalation_incident"),
                "action": action,
                "actor": actor,
                "clock": self.clock,
                "tick": self.tick,
                "note": note,
                "intent_id": intent_id or None,
                "intent_statement": None,
            }
            requeue = False
            original = self.drivers.get(d.get("original_driver_id") or "")

            if action == "override_intent":
                intent = self.intents.get(intent_id)
                if intent is None:
                    return {"ok": False, "error": "unknown intent " + str(intent_id)}
                intent.active = False
                record["intent_statement"] = intent.statement
                record["outcome"] = (
                    actor + " overrode " + intent.holder + "'s stated intent; "
                    "the system re-decided with it withdrawn"
                )
                requeue = True

            elif action == "retain_original":
                if not original or original["status"] not in ("available", "on_route"):
                    return {"ok": False,
                            "error": "the original courier can no longer carry it"}
                original["status"] = "on_route"
                original["assigned_delivery"] = delivery_id
                d["driver_id"] = original["id"]
                d["status"] = "On Route"
                self._recompute_eta(d)
                record["outcome"] = (
                    actor + " kept " + original["name"] + " on the job and "
                    "accepted the breach"
                )

            elif action == "reschedule":
                d["promised_minutes"] = round(
                    float(d.get("promised_minutes") or 0.0) + RESCHEDULE_MINUTES, 1
                )
                d["slack_minutes"] = round(
                    max(0.0, d["promised_minutes"] - d["eta_minutes"]), 1
                )
                record["outcome"] = (
                    actor + " extended the promised window by %.0f min; the "
                    "system re-decided" % RESCHEDULE_MINUTES
                )
                requeue = True

            elif action == "cancel":
                d["status"] = "Cancelled"
                d["delivered_tick"] = self.tick
                if original and original.get("assigned_delivery") == delivery_id:
                    original["assigned_delivery"] = None
                    original["active_load"] = max(0, original["active_load"] - 1)
                    if original["status"] != "unavailable":
                        original["status"] = "available"
                record["outcome"] = actor + " cancelled the delivery"

            else:
                return {"ok": False, "error": "unknown action " + str(action)}

            for key in ("escalated_tick", "awaiting_decision_since"):
                d.pop(key, None)
            self.decisions.append(record)
            return {
                "ok": True, "decision": record, "requeue": requeue,
                "disruption_key": d.get("escalation_disruption"),
            }

    def _add_intent_for(self, d):
        """Give a newly dispatched delivery the intent its recipient stated.

        Without this the register went stale within minutes: every seeded intent
        pointed at a delivery that had already been completed and retired, and
        every delivery actually on the board had no stated intent at all — so
        the conflict check quietly stopped applying to anything. New work has to
        arrive with its goals attached.

        A difficult job gets a tight cutoff and a routine one a comfortable
        cutoff, both measured from the journey it actually faces. That is what
        keeps conflicts occurring naturally instead of being staged.
        """
        if self.is_humanitarian:
            self.intents.add(
                holder=d["recipient"], holder_type="payload", kind="cold_window",
                statement="We need 20 minutes to receive a consignment and get "
                          "it into the cold room.",
                params={"handling_margin_minutes": 20.0},
                hardness="hard", scope=d["id"], declared="consignment manifest",
            )
            return
        eta = float(d.get("eta_minutes") or 20.0)
        if d.get("difficult"):
            head = self.rng.uniform(1.02, 1.25) * eta      # barely achievable
        else:
            head = self.rng.uniform(1.6, 2.6) * eta        # comfortable
        cutoff = self.clock_minutes + head
        # Round to the next quarter hour: people state times, not offsets.
        cutoff = 15.0 * round(cutoff / 15.0)
        hh, mm = int(cutoff // 60) % 24, int(cutoff % 60)
        self.intents.add(
            holder=d["recipient"], holder_type="recipient",
            kind="delivery_deadline",
            statement="Nothing after %02d:%02d - I am out after that." % (hh, mm),
            params={"by_minutes": cutoff},
            hardness="hard", scope=d["id"], declared="stated at booking",
        )

    def _prune_intents(self):
        """Drop intents scoped to a delivery that no longer exists.

        Called with the lock held. Fleet-wide and courier-scoped intents are
        untouched; only delivery-scoped ones can go stale.
        """
        live = set(self.deliveries)
        for intent in list(self.intents.all()):
            scope = intent.scope
            if scope == "*" or scope in self.drivers or scope in live:
                continue
            self.intents.remove(intent.id)

    def _rest_driver(self, drv):
        """End of shift: the courier goes home and a rested one takes over.

        Without this, fatigue and vehicle wear only ever went up. Three of the
        risk model's seven features had no recovery path, so every delivery
        drifted to "critical" on nothing but elapsed time — and the autonomous
        watchdog, which fires at 0.68, would eventually trigger on the whole
        fleet by itself. Shifts end in reality; now they end here too.
        """
        drv["status"] = "off_shift"
        drv["assigned_delivery"] = None
        drv["rest_until_tick"] = self.tick + REST_TICKS
        drv["hours_on_shift"] = 0.0
        drv["shift_remaining_minutes"] = float(SHIFT_MINUTES)
        # Pre-shift inspection: wear is serviced between shifts, not mid-route.
        drv["vehicle_health_risk"] = round(self.rng.uniform(0.04, 0.12), 3)

    def drift(self) -> None:
        """One simulation step: bounded random walk on live telemetry.

        This stands in for a real telematics feed. It moves congestion, weather,
        fatigue and position, completes deliveries that have arrived and starts
        replacements; it does not move any figure that appears in the impact
        ledger.
        """
        with self.lock:
            self.tick += 1

            for d in list(self.deliveries.values()):
                if d["status"] in ("Delivered", "Cancelled"):
                    continue
                t = d["telemetry"]
                t["traffic_index"] = self._walk(t["traffic_index"], 0.055, 0.05, 0.97, 0.48)
                t["weather_risk"] = self._walk(t["weather_risk"], 0.02, 0.02, 0.85, 0.18)

                if d["status"] in ("On Route", "Rerouted", "Reassigned"):
                    self._advance(d)
                    self._recompute_eta(d)
                    # Slack is time to spare against the promised window:
                    # whatever is left of the promise, minus the journey still
                    # ahead. Decrementing it every tick (as this used to) made
                    # it drain to zero even when the courier was dead on
                    # schedule, which pinned schedule_pressure at 1.0 for the
                    # rest of the delivery's life. Now it only shrinks when they
                    # genuinely fall behind — congestion rising, or a disruption
                    # adding a penalty — which is what the feature is meant to
                    # detect.
                    d["promised_minutes"] = round(max(
                        0.0, d.get("promised_minutes", d["eta_minutes"]) - SIM_MINUTES_PER_TICK
                    ), 1)
                    d["slack_minutes"] = max(
                        0.0, round(d["promised_minutes"] - d["eta_minutes"], 1)
                    )
                    if self._remaining_km(d) <= ARRIVAL_KM and not d.get("handover_at"):
                        self._complete(d)

                if d.get("cold_chain") and d["status"] not in ("Delivered", "Cancelled"):
                    d["cold_minutes_remaining"] = round(max(
                        0.0, d.get("cold_minutes_remaining", 0.0) - SIM_MINUTES_PER_TICK
                    ), 1)

            for drv in self.drivers.values():
                if drv["status"] == "off_shift":
                    if self.tick >= drv.get("rest_until_tick", 0):
                        drv["status"] = "available"
                        drv.pop("rest_until_tick", None)
                    continue
                if drv["status"] != "on_route":
                    continue
                drv["hours_on_shift"] = round(
                    min(11.0, drv["hours_on_shift"] + SIM_MINUTES_PER_TICK / 60.0), 4
                )
                drv["shift_remaining_minutes"] = round(max(
                    0.0, drv["shift_remaining_minutes"] - SIM_MINUTES_PER_TICK
                ), 1)
                # Wear accumulates within a shift and is serviced between them.
                drv["vehicle_health_risk"] = min(
                    0.95,
                    max(0.02, drv["vehicle_health_risk"]
                        + self.rng.uniform(-0.0004, 0.0016)),
                )

            # A courier whose shift ran out goes home once they are not carrying.
            for drv in self.drivers.values():
                if (drv["status"] == "available"
                        and drv["shift_remaining_minutes"] <= 0.0):
                    self._rest_driver(drv)

            self._resolve_stale_escalations()
            self._retire_and_refill()

    def _retire_and_refill(self) -> None:
        """Drop delivered jobs off the board and keep the fleet working.

        Called with the lock held.
        """
        # Keep a completed job visible briefly so the operator sees it land.
        for did, d in list(self.deliveries.items()):
            if (d["status"] == "Delivered"
                    and self.tick - d.get("delivered_tick", self.tick) >= DELIVERED_LINGER_TICKS):
                del self.deliveries[did]

        # An escalated delivery is waiting on a person, not on the fleet, so it
        # must not count against the target — otherwise four escalations mean no
        # new work is ever dispatched and the board stops moving.
        self._prune_intents()

        # An escalated delivery is waiting on a person, not on the fleet, so it
        # must not count against the target - otherwise four escalations mean no
        # new work is ever dispatched and the board stops moving.
        active = [d for d in self.deliveries.values()
                  if d["status"] not in ("Delivered", "Cancelled", "Escalated")]
        while len(active) < FLEET_TARGET:
            new = self._spawn_delivery()
            if new is None:
                break
            active.append(new)

    def _spawn_delivery(self) -> Optional[Dict]:
        """Create a fresh outbound job for an idle courier, or None if none free."""
        free = [
            v for v in self.drivers.values()
            if v["status"] == "available" and not v.get("assigned_delivery")
            and v["shift_remaining_minutes"] > 0
        ]
        if not free:
            return None
        drv = self.rng.choice(free)

        taken = {d["destination"] for d in self.deliveries.values()
                 if d["status"] not in ("Delivered", "Cancelled")}
        options = [n for n in self.nodes if n != self.hub and n not in taken]
        if not options:
            options = [n for n in self.nodes if n != self.hub]
        dest = self.rng.choice(options)

        # Humanitarian consignments are V-2xx, commercial parcels D-1xx. Using
        # one hardcoded prefix would drop a "D-105" into a cold-chain fleet.
        self.delivery_seq += 1
        prefix, base = ("V", 200) if self.is_humanitarian else ("D", 100)
        did = f"{prefix}-{base + self.delivery_seq}"
        recipient, payload, units = self.rng.choice(
            _HUMANITARIAN_JOBS if self.is_humanitarian else _COMMERCIAL_JOBS
        )
        difficult = self.rng.random() < DIFFICULT_JOB_SHARE
        origin = self.hub
        # A new job starts at the depot, so the courier is dispatched from there.
        drv["at"] = coord(origin)
        drv["located_at"] = origin
        drv["status"] = "on_route"
        drv["assigned_delivery"] = did
        drv["active_load"] = min(drv["capacity"], drv["active_load"] + 1)

        d = {
            "id": did,
            "driver_id": drv["id"],
            "original_driver_id": drv["id"],
            "recipient": recipient,
            "origin": origin,
            "destination": dest,
            "zone": dest,
            "status": "On Route",
            "progress": 0.0,
            "payload": payload,
            "payload_units": units,
            "cold_chain": self.is_humanitarian,
            "address_confidence": round(
                self.rng.uniform(0.42, 0.68) if difficult
                else self.rng.uniform(0.78, 0.97), 2),
            "recipient_absence_rate": round(
                self.rng.uniform(0.28, 0.52) if difficult
                else self.rng.uniform(0.04, 0.18), 2),
            # Set once the ETA is known, just below — the promise has to scale
            # with the journey, or a cross-city run is "late" the moment it
            # leaves the depot.
            "slack_minutes": 0.0,
            "telemetry": {
                "traffic_index": round(
                    self.rng.uniform(0.55, 0.82) if difficult
                    else self.rng.uniform(0.28, 0.55), 2),
                "weather_risk": round(
                    self.rng.uniform(0.18, 0.38) if difficult
                    else self.rng.uniform(0.06, 0.20), 2),
            },
            # Recorded so the UI can say why a delivery looks bad, and so this
            # is auditable rather than an invisible dice roll.
            "difficult": difficult,
            "incidents": [],
            "reroute": None,
            "handover_at": None,
            "handover": None,
        }
        if d["cold_chain"]:
            d["doses"] = int(self.rng.choice([120, 240, 300, 480]))
            d["cold_minutes_remaining"] = round(self.rng.uniform(95.0, 165.0), 1)
        else:
            d["doses"] = 0
            d["cold_minutes_remaining"] = 0.0
        self.deliveries[did] = d
        self._recompute_eta(d)
        # The promised window is the expected journey plus a commercial buffer,
        # so slack starts positive and proportional rather than flat.
        d["promised_minutes"] = round(d["eta_minutes"] * self.rng.uniform(1.25, 1.6), 1)
        d["slack_minutes"] = round(d["promised_minutes"] - d["eta_minutes"], 1)
        self._add_intent_for(d)
        return d

    def _walk(self, value: float, step: float, lo: float, hi: float, center: float) -> float:
        nudge = self.rng.uniform(-step, step)
        # Mild mean reversion so a long demo does not drift into a corner.
        nudge += (center - value) * 0.04
        return max(lo, min(hi, value + nudge))

    # -- views --------------------------------------------------------------

    def risk_for(self, delivery_id: str) -> Dict:
        d = self.deliveries[delivery_id]
        driver = self.drivers.get(d["driver_id"]) or {
            "vehicle_health_risk": 0.0, "hours_on_shift": 0.0
        }
        return RISK_MODEL.score(d, driver)

    def snapshot(self) -> Dict:
        with self.lock:
            deliveries = []
            for d in self.deliveries.values():
                risk = self.risk_for(d["id"])
                driver = self.drivers.get(d["driver_id"])
                dest = d["destination"]
                deliveries.append(
                    {
                        "id": d["id"],
                        "status": d["status"],
                        "recipient": d["recipient"],
                        "payload": d["payload"],
                        "eta_minutes": round(d["eta_minutes"], 1),
                        "slack_minutes": round(d["slack_minutes"], 1),
                        "destination": dest,
                        "destination_name": NODES[dest]["name"],
                        "destination_at": coord(dest),
                        "origin": d["origin"],
                        "origin_at": coord(d["origin"]),
                        "driver_id": d["driver_id"],
                        "driver_name": driver["name"] if driver else "unassigned",
                        "driver_at": driver["at"] if driver else None,
                        "vehicle_label": driver["vehicle_label"] if driver else None,
                        "original_driver_id": d["original_driver_id"],
                        "reassigned": d["driver_id"] != d["original_driver_id"],
                        "cold_chain": bool(d.get("cold_chain")),
                        "cold_minutes_remaining": round(d.get("cold_minutes_remaining", 0.0), 0),
                        "doses": d.get("doses", 0),
                        "traffic_index": round(d["telemetry"]["traffic_index"], 3),
                        "weather_risk": round(d["telemetry"]["weather_risk"], 3),
                        "address_confidence": d["address_confidence"],
                        "risk": risk["risk"],
                        "risk_band": risk["band"],
                        # Surfaced so an operator can see WHY a delivery looks
                        # bad, and so a demo can be pointed at a job that will
                        # genuinely produce a conflict rather than hunting.
                        "difficult": bool(d.get("difficult")),
                        "risk_top_driver": risk["top_driver"],
                        "risk_contributions": risk["contributions"][:4],
                        "incidents": d["incidents"],
                        "reroute": d["reroute"],
                        "handover_at": d.get("handover_at"),
                        # Briefing for the courier who received this job.
                        "handover": d.get("handover"),
                    }
                )
            deliveries.sort(key=lambda x: x["id"])

            drivers = [
                {
                    "id": drv["id"], "name": drv["name"], "status": drv["status"],
                    "at": drv["at"], "located_at": drv["located_at"],
                    "vehicle_label": drv["vehicle_label"],
                    "vehicle_type": drv["vehicle_type"],
                    "cold_chain_capable": drv["cold_chain_capable"],
                    "on_time_rate": drv["on_time_rate"],
                    "active_load": drv["active_load"], "capacity": drv["capacity"],
                    "shift_remaining_minutes": round(drv["shift_remaining_minutes"], 0),
                    "assigned_delivery": drv["assigned_delivery"],
                    "unavailable_reason": drv["unavailable_reason"],
                    "support_dispatched": drv["support_dispatched"],
                    "earnings_protected": drv["earnings_protected"],
                }
                for drv in self.drivers.values()
            ]

            return {
                "mode": self.mode,
                "tick": self.tick,
                # Simulated time of day. Stated intents carry wall-clock
                # deadlines, so the clock has to be on screen for a reader to
                # check a conflict rather than take it on trust.
                "clock": self.clock,
                "clock_minutes": round(self.clock_minutes, 1),
                "hub": self.hub,
                "deliveries": deliveries,
                "drivers": drivers,
                "impact": self.ledger.totals(),
                "map": self.map_geometry(),
            }

    def map_geometry(self) -> Dict:
        ids = self.nodes
        return {
            "bounds": bounds(ids),
            "nodes": [
                {
                    "id": n, "name": NODES[n]["name"],
                    "at": NODES[n]["at"], "kind": NODES[n]["kind"],
                }
                for n in ids
            ],
            "roads": [
                {"from": a, "to": b, "name": name}
                for a, b, name in ROADS
                if a in ids and b in ids
            ],
        }

    # -- mutations ----------------------------------------------------------

    def next_incident_id(self) -> str:
        with self.lock:
            self.incident_seq += 1
            return f"INC-{self.incident_seq:03d}"

    def route_alternates(self, delivery_id: str, penalty_min: float) -> List[Dict]:
        """Enumerate real two-leg alternates and their added minutes.

        Direct path is the baseline. Each alternate detours via a network node;
        added time is computed from coordinates plus the disruption's own penalty
        on the direct path.
        """
        with self.lock:
            d = self.deliveries[delivery_id]
            driver = self.drivers.get(d["driver_id"])
            start = driver["at"] if driver else coord(d["origin"])
            end = coord(d["destination"])
            traffic = d["telemetry"]["traffic_index"]
            rural = self.is_humanitarian

            direct_km = road_km(start, end)
            direct_min = travel_minutes(direct_km, traffic, rural) + penalty_min

            options = []
            for n in self.nodes:
                if n in (d["destination"], d["origin"]) or NODES[n]["kind"] == "hub":
                    continue
                via = coord(n)
                km = road_km(start, via) + road_km(via, end)
                if km > direct_km * 2.1:
                    continue
                # A detour dodges the blocked segment, so it does not carry the
                # direct path's disruption penalty. It sees marginally lighter
                # traffic for choosing a less-congested corridor — but only
                # marginally: discounting the whole alternate route heavily would
                # let any long detour beat a clear road, which is not how roads
                # work. The penalty being avoided is what makes a reroute pay.
                mins = travel_minutes(km, max(0.05, traffic - 0.06), rural)
                options.append(
                    {
                        "via": n,
                        "via_name": NODES[n]["name"],
                        "distance_km": round(km, 2),
                        "minutes": round(mins, 1),
                        "added_minutes": round(mins - direct_min, 1),
                    }
                )
            options.sort(key=lambda o: o["minutes"])
            return [
                {
                    "direct": {
                        "distance_km": round(direct_km, 2),
                        "minutes": round(direct_min, 1),
                        "penalty_minutes": penalty_min,
                    }
                }
            ] + options[:3]

    def build_requirement(self, delivery_id: str, disruption: Dict) -> Dict:
        """Requirement object handed to the suitability ranker."""
        with self.lock:
            d = self.deliveries[delivery_id]
            pickup = (
                coord(self.hub)
                if disruption["needs_replacement_stock"]
                else (self.drivers[d["driver_id"]]["at"] if d["driver_id"] in self.drivers
                      else coord(d["origin"]))
            )
            # "current payload location" is useless to the courier who has to ride
            # there. The payload sits wherever the stranded rider stopped, which is
            # rarely a node centroid, so name the nearest known locality and say
            # how far off it is — something a person can actually navigate to.
            if disruption["needs_replacement_stock"]:
                pickup_label = "the depot (replacement stock)"
            else:
                near = nearest_nodes(pickup, self.nodes, limit=1)
                if near:
                    node_id, km = near[0]
                    place = NODES[node_id]["name"]
                    pickup_label = (
                        place if km < 0.4
                        else f"{place} (payload is {km:.1f} km off the node)"
                    )
                else:
                    pickup_label = "the payload's current location"

            return {
                "pickup": pickup,
                "pickup_label": pickup_label,
                "dropoff": coord(d["destination"]),
                "traffic_index": d["telemetry"]["traffic_index"],
                "cold_chain": bool(d.get("cold_chain")),
                "service_minutes": SERVICE_MINUTES,
                "target_eta_minutes": max(d["eta_minutes"], 12.0),
                "zone": d["zone"],
                "delivery_id": d["id"],
                "min_capacity_units": d["payload_units"],
                "rural": self.is_humanitarian,
                "cold_window_minutes": (
                    d.get("cold_minutes_remaining") if d.get("cold_chain") else None
                ),
            }

    def eligible_drivers(self, delivery_id: str, disruption: Dict) -> List[Dict]:
        """Candidate pool. Retains the incumbent unless the disruption disables them."""
        with self.lock:
            d = self.deliveries[delivery_id]
            pool = []
            for drv in self.drivers.values():
                if drv["id"] == d["driver_id"]:
                    if disruption["disables_driver"]:
                        continue
                    pool.append(drv)
                    continue
                # Deliberately NOT filtered here. A courier already carrying a
                # different job is ineligible, but skipping them silently meant
                # they never reached the rejected list, so the dashboard could
                # not answer "why wasn't Meera considered?" about someone
                # visibly idle-looking on the map. The ranker rejects them with
                # a stated reason instead.
                pool.append(drv)
            return pool

    def apply_resolution(
        self,
        *,
        delivery_id: str,
        incident_id: str,
        disruption_key: str,
        chosen: Optional[Dict],
        reroute: Optional[Dict],
        new_eta: float,
        support: Optional[str],
        handover_at: Optional[tuple] = None,
        handover_label: Optional[str] = None,
        rationale: Optional[str] = None,
        llm_calls_used: int = 0,
        llm_calls_saved: int = 0,
    ) -> Dict:
        """Commit the chain's decision to fleet state and the impact ledger."""
        disruption = DISRUPTIONS[disruption_key]
        with self.lock:
            d = self.deliveries[delivery_id]
            previous_driver_id = d["driver_id"]
            previous_driver = self.drivers.get(previous_driver_id)
            previous_eta = d["eta_minutes"]
            reassigned = bool(chosen and chosen["driver_id"] != previous_driver_id)

            if reassigned:
                new_driver = self.drivers[chosen["driver_id"]]
                if previous_driver:
                    previous_driver["assigned_delivery"] = None
                    if disruption["disables_driver"]:
                        previous_driver["status"] = "unavailable"
                        previous_driver["unavailable_reason"] = disruption["label"]
                        previous_driver["support_dispatched"] = support
                        previous_driver["earnings_protected"] = True
                    else:
                        previous_driver["status"] = "available"
                new_driver["status"] = "on_route"
                new_driver["assigned_delivery"] = delivery_id
                new_driver["active_load"] = min(
                    new_driver["capacity"], new_driver["active_load"] + 1
                )
                d["driver_id"] = new_driver["id"]
                d["status"] = "Reassigned"
                # The replacement driver collects the payload before delivering
                # it, so the journey is two legs. Record the collection point so
                # the map shows the same path the ETA was computed from.
                d["handover_at"] = list(handover_at) if handover_at else None
                # A briefing for the courier who RECEIVES the job. Without this
                # the replacement rider's screen simply changes underneath them:
                # a new drop, a new ETA, and no statement of where the payload
                # is, who has it, why it moved, or why they were picked. Every
                # field here is already computed by the chain — it just was not
                # being handed to the one person who has to act on it.
                eta_before = previous_eta
                d["handover"] = {
                    "incident_id": incident_id,
                    "from_driver_id": previous_driver_id,
                    "from_driver_name": (previous_driver or {}).get("name"),
                    "reason": disruption["label"],
                    "reason_icon": disruption["icon"],
                    "collect_at": handover_label,
                    "collect_at_coords": list(handover_at) if handover_at else None,
                    "support_for_them": support,
                    # Why THIS rider: the ranker's decisive feature plus the
                    # Resource agent's own sentence, so the rationale shown to
                    # the courier is the same one shown to operations.
                    "why_you": (chosen or {}).get("decisive_factor"),
                    "suitability": (chosen or {}).get("suitability"),
                    "approach_km": (chosen or {}).get("distance_km"),
                    "rationale": rationale,
                    "eta_before": eta_before,
                    "eta_after": round(new_eta, 1),
                }
            else:
                # No transfer happened, so no briefing should be showing.
                d["handover"] = None
                if disruption["disables_driver"] and previous_driver:
                    previous_driver["status"] = "unavailable"
                    previous_driver["unavailable_reason"] = disruption["label"]
                    previous_driver["support_dispatched"] = support
                    previous_driver["earnings_protected"] = True
                    d["status"] = "Awaiting Driver"
                else:
                    d["status"] = "Rerouted" if reroute else "Rescheduled"

            d["eta_minutes"] = round(new_eta, 1)
            d["slack_minutes"] = max(2.0, d["slack_minutes"])
            d["reroute"] = reroute
            # Resolution removes the failure trigger; risk drops accordingly.
            d["address_confidence"] = min(0.99, d["address_confidence"] + 0.08)
            d["recipient_absence_rate"] = max(0.02, d["recipient_absence_rate"] - 0.10)
            d["telemetry"]["traffic_index"] = max(
                0.05, d["telemetry"]["traffic_index"] - 0.16
            )
            d["incidents"].append(
                {
                    "incident_id": incident_id,
                    "disruption": disruption["label"],
                    "icon": disruption["icon"],
                    "reassigned_to": d["driver_id"] if reassigned else None,
                }
            )

            # Impact: the redelivery trip that never happens.
            hub_to_customer = road_km(coord(self.hub), coord(d["destination"]))
            km_avoided = avoided_redelivery_km(hub_to_customer)
            vehicle = self.drivers[d["driver_id"]]["vehicle_type"]
            entry = self.ledger.record(
                incident_id=incident_id,
                delivery_id=delivery_id,
                km_avoided=km_avoided,
                vehicle_type=vehicle,
                doses_preserved=d.get("doses", 0) if self.is_humanitarian else 0,
                payload_note=d["payload"],
                llm_calls_used=llm_calls_used,
                llm_calls_saved=llm_calls_saved,
            )
            return {
                "reassigned": reassigned,
                "previous_driver_id": previous_driver_id,
                "new_driver_id": d["driver_id"],
                "status": d["status"],
                "eta_minutes": d["eta_minutes"],
                "impact_entry": entry,
                "hub_to_customer_km": round(hub_to_customer, 2),
            }
