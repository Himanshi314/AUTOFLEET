"""Interpretable models: disruption risk, and driver suitability for reassignment.

Design note that matters for the architecture: the language agents do NOT do
arithmetic. They never guess which driver is closest or how risky a delivery is.
These models compute it deterministically from coordinates and telemetry, and
the agents receive the ranked, feature-attributed result as input and make the
judgement call on top of it.

Both models are linear in normalised features, which buys two things a black box
would not: every score decomposes into per-feature contributions the UI can
render, and every weight is auditable on this page.

These are hand-calibrated heuristic models, not models fitted on historical
data. They are labelled as such in the UI. Weights encode domain priors; with a
real delivery dataset you would fit them and keep the same interface.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from .geo import coord, road_km, travel_minutes


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


# ==========================================================================
# Model 1 — disruption risk. Predictive, not reactive: this is what lets the
# system flag a delivery *before* it fails.
# ==========================================================================

class DisruptionRiskModel:
    """Logistic risk-of-failure score for an in-flight delivery."""

    NAME = "disruption-risk-v1"
    KIND = "logistic (hand-calibrated, interpretable)"

    # Calibrated so a healthy delivery sits well below the alert threshold and a
    # stressed one sits just under it, leaving the watchdog something real to
    # detect as telemetry drifts. Not a fitted intercept.
    BIAS = -4.60

    WEIGHTS: Dict[str, float] = {
        "traffic_index": 1.95,
        "address_uncertainty": 2.35,
        "recipient_absence_rate": 2.60,
        "vehicle_health_risk": 2.10,
        "driver_fatigue": 1.45,
        "weather_risk": 1.15,
        "schedule_pressure": 1.70,
    }

    LABELS: Dict[str, str] = {
        "traffic_index": "Corridor congestion",
        "address_uncertainty": "Address confidence gap",
        "recipient_absence_rate": "Recipient absence history",
        "vehicle_health_risk": "Vehicle health",
        "driver_fatigue": "Driver fatigue",
        "weather_risk": "Weather",
        "schedule_pressure": "Schedule pressure",
    }

    def features(self, delivery: Dict, driver: Dict) -> Dict[str, float]:
        t = delivery["telemetry"]
        slack = delivery.get("slack_minutes", 20.0)
        return {
            "traffic_index": _clamp(t["traffic_index"]),
            "address_uncertainty": _clamp(1.0 - delivery["address_confidence"]),
            "recipient_absence_rate": _clamp(delivery["recipient_absence_rate"]),
            "vehicle_health_risk": _clamp(driver["vehicle_health_risk"]),
            "driver_fatigue": _clamp(driver["hours_on_shift"] / 10.0),
            "weather_risk": _clamp(t["weather_risk"]),
            "schedule_pressure": _clamp(1.0 - (slack / 25.0)),
        }

    def score(self, delivery: Dict, driver: Dict) -> Dict:
        f = self.features(delivery, driver)
        contributions = {k: self.WEIGHTS[k] * v for k, v in f.items()}
        z = self.BIAS + sum(contributions.values())
        risk = _sigmoid(z)
        ranked = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
        return {
            "model": self.NAME,
            "kind": self.KIND,
            "risk": round(risk, 4),
            "band": self.band(risk),
            "logit": round(z, 3),
            "features": {k: round(v, 3) for k, v in f.items()},
            "contributions": [
                {
                    "key": k,
                    "label": self.LABELS[k],
                    "value": round(f[k], 3),
                    "weight": self.WEIGHTS[k],
                    "contribution": round(c, 3),
                }
                for k, c in ranked
            ],
            "top_driver": self.LABELS[ranked[0][0]] if ranked else None,
        }

    @staticmethod
    def band(risk: float) -> str:
        # "critical" is aligned with the autonomous watchdog threshold, so the
        # band a viewer sees is the same line the system acts on.
        if risk >= 0.68:
            return "critical"
        if risk >= 0.42:
            return "elevated"
        if risk >= 0.15:
            return "watch"
        return "nominal"


# ==========================================================================
# Model 2 — driver suitability. Hard constraints first, then a weighted score.
# ==========================================================================

class DriverSuitabilityRanker:
    """Ranks eligible drivers for a reassignment, with feature attribution."""

    NAME = "reassignment-suitability-v1"
    KIND = "weighted linear utility over normalised features"

    WEIGHTS: Dict[str, float] = {
        "proximity": 0.34,
        "eta_fit": 0.20,
        "reliability": 0.15,
        "load_headroom": 0.11,
        "shift_headroom": 0.09,
        "capability_margin": 0.07,
        "zone_familiarity": 0.04,
    }

    LABELS: Dict[str, str] = {
        "proximity": "Proximity to pickup",
        "eta_fit": "ETA fit",
        "reliability": "On-time record",
        "load_headroom": "Spare capacity",
        "shift_headroom": "Shift time remaining",
        "capability_margin": "Vehicle capability",
        "zone_familiarity": "Zone familiarity",
    }

    # Distance at which the proximity score decays to 1/e. km.
    PROXIMITY_SCALE_KM = 2.2

    def __init__(self) -> None:
        assert abs(sum(self.WEIGHTS.values()) - 1.0) < 1e-9, "weights must sum to 1"

    # -- hard constraints ---------------------------------------------------

    def _reject_reason(self, driver: Dict, req: Dict, eta_min: float) -> Optional[str]:
        if driver["status"] not in ("available", "on_route"):
            return f"status is {driver['status']}"
        if req.get("cold_chain") and not driver["cold_chain_capable"]:
            return "no cold-chain box"
        if driver["active_load"] >= driver["capacity"]:
            return "at full load"
        needed = eta_min + req.get("service_minutes", 6.0)
        if driver["shift_remaining_minutes"] < needed:
            return (
                f"shift ends in {driver['shift_remaining_minutes']:.0f} min, "
                f"job needs {needed:.0f} min"
            )
        if req.get("min_capacity_units", 0) > driver["payload_capacity_units"]:
            return "payload too large for vehicle"
        # Cold chain is a hard deadline, not a preference: a consignment that
        # arrives after the window closes arrives spoiled, so a driver who cannot
        # make it in time is not a candidate at any suitability score.
        window = req.get("cold_window_minutes")
        if window is not None and eta_min > window:
            return (
                f"arrives in {eta_min:.0f} min, past the "
                f"{window:.0f} min cold-chain window"
            )
        return None

    # -- features -----------------------------------------------------------

    def _features(self, driver: Dict, req: Dict, distance_km: float, eta_min: float) -> Dict[str, float]:
        target_eta = max(req.get("target_eta_minutes", 25.0), 1.0)
        return {
            "proximity": math.exp(-distance_km / self.PROXIMITY_SCALE_KM),
            "eta_fit": _clamp(1.0 - (eta_min / (target_eta * 1.8))),
            "reliability": _clamp(driver["on_time_rate"]),
            "load_headroom": _clamp(
                (driver["capacity"] - driver["active_load"]) / max(driver["capacity"], 1)
            ),
            "shift_headroom": _clamp(driver["shift_remaining_minutes"] / 180.0),
            "capability_margin": _clamp(
                driver["payload_capacity_units"]
                / max(req.get("min_capacity_units", 1), 1)
                / 3.0
            ),
            "zone_familiarity": 1.0 if req.get("zone") in driver["familiar_zones"] else 0.0,
        }

    # -- public API ---------------------------------------------------------

    def rank(self, drivers: List[Dict], req: Dict) -> Dict:
        """Score every driver against a reassignment requirement.

        `req` keys: pickup (lat, lon), dropoff (lat, lon), traffic_index,
        cold_chain, service_minutes, target_eta_minutes, zone,
        min_capacity_units, rural.
        """
        pickup = req["pickup"]
        dropoff = req["dropoff"]
        traffic = req.get("traffic_index", 0.4)
        rural = req.get("rural", False)

        candidates: List[Dict] = []
        rejected: List[Dict] = []

        for d in drivers:
            approach_km = road_km(d["at"], pickup)
            leg_km = road_km(pickup, dropoff)
            approach_min = travel_minutes(approach_km, traffic, rural)
            leg_min = travel_minutes(leg_km, traffic, rural)
            eta_min = approach_min + leg_min + req.get("service_minutes", 6.0)

            reason = self._reject_reason(d, req, eta_min)
            if reason:
                rejected.append(
                    {
                        "driver_id": d["id"],
                        "name": d["name"],
                        "reason": reason,
                        "distance_km": round(approach_km, 2),
                    }
                )
                continue

            f = self._features(d, req, approach_km, eta_min)
            contributions = {k: self.WEIGHTS[k] * v for k, v in f.items()}
            score = sum(contributions.values())
            ranked_contrib = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)

            candidates.append(
                {
                    "driver_id": d["id"],
                    "name": d["name"],
                    "vehicle_type": d["vehicle_type"],
                    "vehicle_label": d["vehicle_label"],
                    "at": d["at"],
                    "located_at": d["located_at"],
                    "status": d["status"],
                    "cold_chain_capable": d["cold_chain_capable"],
                    "distance_km": round(approach_km, 2),
                    "approach_minutes": round(approach_min, 1),
                    "eta_minutes": round(eta_min, 1),
                    "on_time_rate": d["on_time_rate"],
                    "suitability": round(score, 4),
                    "features": {k: round(v, 3) for k, v in f.items()},
                    "contributions": [
                        {
                            "key": k,
                            "label": self.LABELS[k],
                            "value": round(f[k], 3),
                            "weight": self.WEIGHTS[k],
                            "contribution": round(c, 4),
                            "share": round(c / score, 3) if score > 0 else 0.0,
                        }
                        for k, c in ranked_contrib
                    ],
                    "decisive_factor": self.LABELS[ranked_contrib[0][0]] if ranked_contrib else None,
                }
            )

        candidates.sort(key=lambda c: c["suitability"], reverse=True)
        for i, c in enumerate(candidates):
            c["rank"] = i + 1
            c["margin_over_next"] = (
                round(c["suitability"] - candidates[i + 1]["suitability"], 4)
                if i + 1 < len(candidates)
                else None
            )

        return {
            "model": self.NAME,
            "kind": self.KIND,
            "weights": self.WEIGHTS,
            "evaluated": len(drivers),
            "eligible": len(candidates),
            "candidates": candidates,
            "rejected": rejected,
        }


RISK_MODEL = DisruptionRiskModel()
RANKER = DriverSuitabilityRanker()


MODEL_CARDS = [
    {
        "name": DisruptionRiskModel.NAME,
        "purpose": "Predicts probability that an in-flight delivery fails, so the "
                   "system can act before it does.",
        "kind": DisruptionRiskModel.KIND,
        "features": list(DisruptionRiskModel.WEIGHTS.keys()),
        "weights": DisruptionRiskModel.WEIGHTS,
        "bias": DisruptionRiskModel.BIAS,
        "caveat": "Hand-calibrated on domain priors, not fitted to historical "
                  "deliveries. Scores are directionally useful and fully "
                  "decomposable, but are not calibrated probabilities.",
    },
    {
        "name": DriverSuitabilityRanker.NAME,
        "purpose": "Ranks eligible drivers for reassignment after hard "
                   "constraints eliminate infeasible ones.",
        "kind": DriverSuitabilityRanker.KIND,
        "features": list(DriverSuitabilityRanker.WEIGHTS.keys()),
        "weights": DriverSuitabilityRanker.WEIGHTS,
        "bias": 0.0,
        "caveat": "Weights encode operational priors. The hard-constraint filter "
                  "(cold chain, shift time, capacity) is absolute and runs before "
                  "any scoring.",
    },
]
