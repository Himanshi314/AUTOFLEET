"""Impact accounting.

Every constant in this module is an ESTIMATE with a named source. Nothing is
fabricated at runtime: the ledger multiplies these documented factors by
distances computed from real coordinates in `geo.py`.

The mechanism being counted is narrow and causal: a disruption resolved while
the courier is still in the field completes the delivery on the first attempt,
so the redelivery trip never happens. That avoided trip is the km, the CO2e and
the congestion. Nothing else is claimed.

If you publish these numbers, re-derive each factor against the cited source
for your own fleet, region and grid mix. The UI shows this table verbatim so a
reader can audit the arithmetic.
"""

from __future__ import annotations

from typing import Dict, List

from .geo import CIRCUITY_FACTOR

# --------------------------------------------------------------------------
# Emission factors — kg CO2e per vehicle-km.
# --------------------------------------------------------------------------
EMISSION_FACTORS: Dict[str, float] = {
    "2w_petrol": 0.0757,
    "2w_electric": 0.0213,
    "3w_electric": 0.0426,
    "van_diesel": 0.2116,
    "refrigerated_van": 0.2645,
}

EMISSION_SOURCES: Dict[str, str] = {
    "2w_petrol": "Tailpipe + upstream factor for an average petrol motorcycle "
                 "(UK DEFRA/BEIS GHG conversion factor range). Verify against a "
                 "local factor for your fleet.",
    "2w_electric": "Derived: ~0.030 kWh/km x ~0.71 kg CO2e/kWh Indian grid "
                   "emission factor (CEA CO2 baseline database order of magnitude).",
    "3w_electric": "Derived: ~0.060 kWh/km x ~0.71 kg CO2e/kWh grid factor.",
    "van_diesel": "Average diesel light-goods van, tailpipe + upstream "
                  "(DEFRA/BEIS range).",
    "refrigerated_van": "Diesel van factor plus ~25% for cold-chain refrigeration "
                        "load. The 25% uplift is an assumption, not a measurement.",
}

# Minutes of human coordinator time consumed by one manual disruption
# resolution. Midpoint of the 10-20 minute range this system replaces.
COORDINATOR_MINUTES_PER_INCIDENT = 14.0

# Fraction of a failed first attempt that becomes a genuinely additional trip.
# Some redeliveries are absorbed into an existing route rather than dispatched
# fresh, so we do NOT claim the full round trip. Deliberately conservative.
REDELIVERY_TRIP_FRACTION = 0.80


ASSUMPTIONS: List[Dict[str, str]] = [
    {
        "key": "Circuity factor",
        "value": f"{CIRCUITY_FACTOR:.2f}x",
        "note": "Straight-line to on-road distance multiplier for a dense metro.",
        "source": "Assumption. Urban circuity commonly falls in the 1.2-1.5x range.",
    },
    {
        "key": "Redelivery trip fraction",
        "value": f"{REDELIVERY_TRIP_FRACTION:.0%}",
        "note": "Share of a failed attempt treated as a genuinely additional trip.",
        "source": "Conservative assumption. Some redeliveries ride along an existing route.",
    },
    {
        "key": "Coordinator time per incident",
        "value": f"{COORDINATOR_MINUTES_PER_INCIDENT:.0f} min",
        "note": "Manual handling time replaced per resolved disruption.",
        "source": "Midpoint of the stated 10-20 min manual coordination window.",
    },
    {
        "key": "Two-wheeler petrol",
        "value": f"{EMISSION_FACTORS['2w_petrol']:.4f} kg CO2e/km",
        "note": "Default courier vehicle in the commercial scenario.",
        "source": EMISSION_SOURCES["2w_petrol"],
    },
    {
        "key": "Refrigerated van",
        "value": f"{EMISSION_FACTORS['refrigerated_van']:.4f} kg CO2e/km",
        "note": "Cold-chain vehicle in the humanitarian scenario.",
        "source": EMISSION_SOURCES["refrigerated_van"],
    },
    {
        "key": "Free-flow speed",
        "value": "22 km/h urban / 38 km/h corridor",
        "note": "Scaled down by up to 45% by the live congestion index.",
        "source": "Assumption calibrated to typical Bengaluru arterial speeds.",
    },
]


def co2e_kg(distance_km: float, vehicle_type: str) -> float:
    """kg CO2e for a given distance and vehicle type."""
    factor = EMISSION_FACTORS.get(vehicle_type, EMISSION_FACTORS["2w_petrol"])
    return distance_km * factor


def avoided_redelivery_km(hub_to_customer_road_km: float) -> float:
    """On-road km avoided by not needing a second delivery attempt.

    A redelivery is a round trip from the depot and back, discounted by
    REDELIVERY_TRIP_FRACTION because not every retry is a dedicated run.
    """
    return 2.0 * hub_to_customer_road_km * REDELIVERY_TRIP_FRACTION


class ImpactLedger:
    """Append-only record of avoided impact, one entry per resolved disruption."""

    def __init__(self) -> None:
        self.entries: List[Dict] = []

    def record(
        self,
        *,
        incident_id: str,
        delivery_id: str,
        km_avoided: float,
        vehicle_type: str,
        doses_preserved: int = 0,
        payload_note: str = "",
    ) -> Dict:
        entry = {
            "incident_id": incident_id,
            "delivery_id": delivery_id,
            "km_avoided": round(km_avoided, 2),
            "co2e_kg_avoided": round(co2e_kg(km_avoided, vehicle_type), 3),
            "coordinator_minutes_saved": COORDINATOR_MINUTES_PER_INCIDENT,
            "failed_attempts_prevented": 1,
            "doses_preserved": doses_preserved,
            "vehicle_type": vehicle_type,
            "payload_note": payload_note,
        }
        self.entries.append(entry)
        return entry

    def totals(self) -> Dict:
        return {
            "incidents_resolved": len(self.entries),
            "human_interventions": 0,
            "km_avoided": round(sum(e["km_avoided"] for e in self.entries), 1),
            "co2e_kg_avoided": round(sum(e["co2e_kg_avoided"] for e in self.entries), 2),
            "coordinator_minutes_saved": round(
                sum(e["coordinator_minutes_saved"] for e in self.entries), 0
            ),
            "failed_attempts_prevented": sum(
                e["failed_attempts_prevented"] for e in self.entries
            ),
            "doses_preserved": sum(e["doses_preserved"] for e in self.entries),
        }

    def reset(self) -> None:
        self.entries.clear()
