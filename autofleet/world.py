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

from .geo import NODES, ROADS, bounds, coord, road_km, travel_minutes
from .impact import ImpactLedger, avoided_redelivery_km
from .scoring import RISK_MODEL

# Doorstep / handover time added to every ETA, in minutes. ASSUMPTION.
SERVICE_MINUTES = 6.0

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
        self.incident_seq = 0
        self.mode = mode
        self.tick = 0
        # Bumped on every (re)load. An in-flight agent chain captures this and
        # aborts if the world is reset or the scenario switched underneath it,
        # rather than half-applying a decision to state that no longer exists.
        self.generation = 0
        self._load(mode)

    # -- lifecycle ----------------------------------------------------------

    def _load(self, mode: str) -> None:
        state = _humanitarian_state() if mode == "humanitarian" else _commercial_state()
        self.mode = mode
        self.generation = getattr(self, "generation", 0) + 1
        self.drivers = {d["id"]: d for d in state["drivers"]}
        self.deliveries = {d["id"]: d for d in state["deliveries"]}
        for d in self.deliveries.values():
            drv = self.drivers[d["driver_id"]]
            drv["assigned_delivery"] = d["id"]
            d["original_driver_id"] = d["driver_id"]
            d["incidents"] = []
            d["reroute"] = None
            d["handover_at"] = None
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

    def drift(self) -> None:
        """One simulation step: bounded random walk on live telemetry.

        This stands in for a real telematics feed. It moves congestion, weather
        and fatigue; it does not move any figure that appears in the impact
        ledger.
        """
        with self.lock:
            self.tick += 1
            for d in self.deliveries.values():
                if d["status"] in ("Delivered", "Cancelled"):
                    continue
                t = d["telemetry"]
                t["traffic_index"] = self._walk(t["traffic_index"], 0.055, 0.05, 0.97, 0.48)
                t["weather_risk"] = self._walk(t["weather_risk"], 0.02, 0.02, 0.85, 0.18)
                if d["status"] in ("On Route", "Rerouted", "Reassigned"):
                    d["eta_minutes"] = max(1.0, d["eta_minutes"] - 0.35)
                    d["slack_minutes"] = max(0.0, d["slack_minutes"] - 0.30)
                    d["progress"] = min(0.94, d["progress"] + 0.012)
                    drv = self.drivers.get(d["driver_id"])
                    # Only the original carrier tracks the corridor; a newly
                    # assigned driver is still approaching from where they were.
                    if drv and drv["id"] == d["original_driver_id"]:
                        drv["at"] = _lerp(
                            coord(d["origin"]), coord(d["destination"]), d["progress"]
                        )
                if d.get("cold_chain"):
                    d["cold_minutes_remaining"] = max(
                        0.0, d.get("cold_minutes_remaining", 0.0) - 2.0
                    )
            for drv in self.drivers.values():
                if drv["status"] == "on_route":
                    drv["hours_on_shift"] = min(11.0, drv["hours_on_shift"] + 0.03)
                    drv["shift_remaining_minutes"] = max(
                        0.0, drv["shift_remaining_minutes"] - 2.0
                    )
                    # Vehicle wear only accumulates during a shift — no reversion.
                    drv["vehicle_health_risk"] = min(
                        0.95,
                        max(0.02, drv["vehicle_health_risk"]
                            + self.rng.uniform(-0.004, 0.014)),
                    )

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
                        "risk_top_driver": risk["top_driver"],
                        "risk_contributions": risk["contributions"][:4],
                        "incidents": d["incidents"],
                        "reroute": d["reroute"],
                        "handover_at": d.get("handover_at"),
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
            return {
                "pickup": pickup,
                "pickup_label": "depot (replacement stock)"
                if disruption["needs_replacement_stock"] else "current payload location",
                "dropoff": coord(d["destination"]),
                "traffic_index": d["telemetry"]["traffic_index"],
                "cold_chain": bool(d.get("cold_chain")),
                "service_minutes": SERVICE_MINUTES,
                "target_eta_minutes": max(d["eta_minutes"], 12.0),
                "zone": d["zone"],
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
                if drv["assigned_delivery"] is not None:
                    continue  # busy on another live job
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
        llm_calls_used: int = 0,
        llm_calls_saved: int = 0,
    ) -> Dict:
        """Commit the chain's decision to fleet state and the impact ledger."""
        disruption = DISRUPTIONS[disruption_key]
        with self.lock:
            d = self.deliveries[delivery_id]
            previous_driver_id = d["driver_id"]
            previous_driver = self.drivers.get(previous_driver_id)
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
            else:
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
