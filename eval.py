"""B4 eval scaffold — scores the Resource Agent's driver pick.

Runs RANKER.rank() against a handful of scenarios and checks the top pick
against an expected driver. No live data / API key needed, just World().

There's no historical outcome log to grade against, so "expected" here means
nearest eligible driver by the same reasoning a coordinator would use (and
the same reasoning TEAM-PLAN.md's own D-102 example uses).

    python eval.py
    python eval.py --verbose
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from autofleet.world import World, DISRUPTIONS
from autofleet.scoring import RANKER


@dataclass
class Case:
    mode: str
    delivery_id: str
    disruption_key: str
    expected_driver_id: str
    why: str


CASES = [
    Case("commercial", "D-102", "bike_breakdown", "DR-11",
         "standby courier parked on the same corridor as D-102's breakdown"),
    Case("commercial", "D-102", "customer_not_home", "DR-02",
         "not a disabling disruption, incumbent stays"),
    Case("commercial", "D-103", "bike_breakdown", "DR-11",
         "same standby courier is also closest once D-103's incumbent drops"),
    Case("commercial", "D-104", "bike_breakdown", "DR-16",
         "22-unit pallet, only the van-class driver has capacity"),
    Case("humanitarian", "V-203", "bike_breakdown", "DR-62",
         "cold-chain window is a hard constraint, filters everyone else out"),
    Case("humanitarian", "V-201", "customer_not_home", "DR-51",
         "incumbent stays, same logic as the commercial case"),
]


def run(verbose: bool = False) -> int:
    worlds = {"commercial": World(mode="commercial"), "humanitarian": World(mode="humanitarian")}
    passed = 0
    failed = []

    for case in CASES:
        w = worlds[case.mode]
        dis = DISRUPTIONS[case.disruption_key]
        req = w.build_requirement(case.delivery_id, dis)
        pool = w.eligible_drivers(case.delivery_id, dis)
        ranking = RANKER.rank(pool, req)

        top = ranking["candidates"][0] if ranking["candidates"] else None
        top_id: Optional[str] = top["driver_id"] if top else None
        ok = top_id == case.expected_driver_id

        if ok:
            passed += 1
        else:
            failed.append((case, top_id, ranking))

        if verbose or not ok:
            status = "PASS" if ok else "FAIL"
            margin = f"{top['margin_over_next']:.4f}" if top and top["margin_over_next"] is not None else "n/a"
            print(f"[{status}] {case.delivery_id} / {case.disruption_key:<20} "
                  f"expected={case.expected_driver_id:<6} got={top_id!s:<6} "
                  f"margin={margin} eligible={ranking['eligible']}")
            if verbose:
                print(f"         {case.why}")

    total = len(CASES)
    print()
    print(f"SCORE: {passed}/{total} ({passed / total:.0%})" if total else "SCORE: n/a")

    if failed:
        print("\nfailures:")
        for case, got, ranking in failed:
            print(f"  {case.delivery_id}/{case.disruption_key}: expected "
                  f"{case.expected_driver_id}, got {got}. pool: "
                  f"{[c['driver_id'] for c in ranking['candidates']]}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(run(verbose="--verbose" in sys.argv or "-v" in sys.argv))
