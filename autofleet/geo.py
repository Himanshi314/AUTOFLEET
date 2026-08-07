"""Geography: real coordinates, great-circle distance, a stylised road graph.

Distances are computed, never invented. Every node below is a real place; the
`CIRCUITY_FACTOR` converts straight-line distance into on-road distance and is
an assumption surfaced in the UI (see `impact.ASSUMPTIONS`).
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Tuple

Coord = Tuple[float, float]  # (lat, lon)

EARTH_RADIUS_KM = 6371.0088

# Straight-line km -> road km. Urban road networks are not straight; 1.35 is a
# mid-range circuity factor for dense Indian metros. ASSUMPTION.
CIRCUITY_FACTOR = 1.35

# Free-flow urban speed for a two-wheeler courier, km/h. ASSUMPTION.
BASE_SPEED_KMH = 22.0

# Free-flow speed on the semi-rural corridors used in humanitarian mode.
RURAL_SPEED_KMH = 38.0


# --------------------------------------------------------------------------
# Nodes. Approximate real coordinates.
# --------------------------------------------------------------------------

NODES: Dict[str, Dict] = {
    # --- Bengaluru metro (commercial scenario) ---
    "hub_yeshwanthpur": {"name": "Yeshwanthpur Hub", "at": (13.0234, 77.5500), "kind": "hub"},
    "malleshwaram": {"name": "Malleshwaram", "at": (13.0035, 77.5647), "kind": "urban"},
    "rajajinagar": {"name": "Rajajinagar", "at": (12.9916, 77.5522), "kind": "urban"},
    "mg_road": {"name": "MG Road", "at": (12.9750, 77.6062), "kind": "urban"},
    "indiranagar": {"name": "Indiranagar", "at": (12.9784, 77.6408), "kind": "urban"},
    "koramangala": {"name": "Koramangala", "at": (12.9352, 77.6245), "kind": "urban"},
    "hsr_layout": {"name": "HSR Layout", "at": (12.9116, 77.6389), "kind": "urban"},
    "jayanagar": {"name": "Jayanagar", "at": (12.9250, 77.5938), "kind": "urban"},
    "banashankari": {"name": "Banashankari", "at": (12.9250, 77.5460), "kind": "urban"},
    "marathahalli": {"name": "Marathahalli", "at": (12.9591, 77.6974), "kind": "urban"},
    "whitefield": {"name": "Whitefield", "at": (12.9698, 77.7500), "kind": "urban"},
    "hebbal": {"name": "Hebbal", "at": (13.0358, 77.5970), "kind": "urban"},
    "electronic_city": {"name": "Electronic City", "at": (12.8452, 77.6602), "kind": "urban"},
    # --- Health corridors (humanitarian scenario) ---
    "hub_bowring": {"name": "Bowring Cold Store", "at": (12.9832, 77.6035), "kind": "hub"},
    "anekal_phc": {"name": "Anekal PHC", "at": (12.7106, 77.6963), "kind": "phc"},
    "hoskote_phc": {"name": "Hoskote PHC", "at": (13.0707, 77.7980), "kind": "phc"},
    "doddaballapur_chc": {"name": "Doddaballapur CHC", "at": (13.2257, 77.5376), "kind": "phc"},
    "magadi_phc": {"name": "Magadi PHC", "at": (12.9573, 77.2242), "kind": "phc"},
    "ramanagara_dh": {"name": "Ramanagara Dist. Hospital", "at": (12.7217, 77.2807), "kind": "phc"},
    "nelamangala_phc": {"name": "Nelamangala PHC", "at": (13.0996, 77.3936), "kind": "phc"},
}

# Stylised road network — pairs of nodes drawn as corridors on the map. These
# are visual/routing abstractions of real arterial roads.
ROADS: List[Tuple[str, str, str]] = [
    ("hub_yeshwanthpur", "malleshwaram", "Tumkur Rd"),
    ("malleshwaram", "rajajinagar", "Sampige Rd"),
    ("malleshwaram", "hebbal", "Bellary Rd"),
    ("malleshwaram", "mg_road", "Seshadripuram Link"),
    ("rajajinagar", "banashankari", "Outer Ring Rd W"),
    ("mg_road", "indiranagar", "MG Road"),
    ("mg_road", "jayanagar", "Richmond Rd"),
    ("indiranagar", "koramangala", "80ft Rd"),
    ("indiranagar", "marathahalli", "Old Airport Rd"),
    ("koramangala", "hsr_layout", "Sarjapur Rd"),
    ("koramangala", "jayanagar", "Sarakki Link"),
    ("jayanagar", "banashankari", "Kanakapura Rd"),
    ("hsr_layout", "electronic_city", "Hosur Rd"),
    ("marathahalli", "whitefield", "Whitefield Rd"),
    ("hebbal", "marathahalli", "Outer Ring Rd E"),
    ("hub_bowring", "mg_road", "Shivajinagar Link"),
    ("hub_bowring", "hebbal", "Bellary Rd N"),
    ("hsr_layout", "anekal_phc", "Anekal Rd"),
    ("electronic_city", "anekal_phc", "Attibele Rd"),
    ("whitefield", "hoskote_phc", "Old Madras Rd"),
    ("hebbal", "doddaballapur_chc", "Doddaballapur Rd"),
    ("rajajinagar", "nelamangala_phc", "NH-48"),
    ("nelamangala_phc", "magadi_phc", "Magadi Rd"),
    ("banashankari", "ramanagara_dh", "Mysuru Rd"),
]


def node(node_id: str) -> Dict:
    return NODES[node_id]


def coord(node_id: str) -> Coord:
    return NODES[node_id]["at"]


def haversine_km(a: Coord, b: Coord) -> float:
    """Great-circle distance between two (lat, lon) pairs, in km."""
    lat1, lon1 = a
    lat2, lon2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    d_phi = p2 - p1
    d_lambda = math.radians(lon2 - lon1)
    h = math.sin(d_phi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def road_km(a: Coord, b: Coord) -> float:
    """On-road distance estimate: great-circle inflated by the circuity factor."""
    return haversine_km(a, b) * CIRCUITY_FACTOR


def via_km(a: Coord, via: Coord, b: Coord) -> float:
    """On-road distance for a two-leg path through an intermediate point."""
    return road_km(a, via) + road_km(via, b)


def travel_minutes(distance_km: float, traffic_index: float, rural: bool = False) -> float:
    """Minutes to cover `distance_km` given a 0..1 congestion index.

    Congestion scales the free-flow speed down by up to 45%. ASSUMPTION.
    """
    base = RURAL_SPEED_KMH if rural else BASE_SPEED_KMH
    effective = base * (1.0 - 0.45 * max(0.0, min(1.0, traffic_index)))
    effective = max(effective, 5.0)
    return (distance_km / effective) * 60.0


def bounds(node_ids: Iterable[str]) -> Dict[str, float]:
    """Lat/lon bounding box for a set of nodes — used to project the SVG map."""
    lats = [NODES[n]["at"][0] for n in node_ids]
    lons = [NODES[n]["at"][1] for n in node_ids]
    pad_lat = (max(lats) - min(lats)) * 0.10 or 0.01
    pad_lon = (max(lons) - min(lons)) * 0.10 or 0.01
    return {
        "min_lat": min(lats) - pad_lat,
        "max_lat": max(lats) + pad_lat,
        "min_lon": min(lons) - pad_lon,
        "max_lon": max(lons) + pad_lon,
    }


def nearest_nodes(origin: Coord, candidates: Iterable[str], limit: int = 3) -> List[Tuple[str, float]]:
    """Rank candidate nodes by on-road distance from `origin`."""
    scored = [(n, road_km(origin, coord(n))) for n in candidates]
    scored.sort(key=lambda item: item[1])
    return scored[:limit]
