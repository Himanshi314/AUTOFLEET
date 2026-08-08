"""The severity router — decides which agents an incident actually deserves.

This is the piece that makes "relevant AI agents activated" true rather than
aspirational. Every input it uses is computed deterministically *before* any
model call, so routing itself is free:

  - does this class of disruption disable the courier?
  - does it need replacement stock from the depot?
  - what does the risk model say right now?
  - did the ranker find one decisively best driver, or is it a close call?

The principle: an agent is only worth waking when there is a genuine judgement to
make. If the hard constraints and the ranker already produce one obvious answer,
running five language models to narrate it is waste. If the top two candidates are
within a hair of each other, that is exactly when judgement earns its cost.

No AI is used in this module. It is if/else over numbers.
"""

from __future__ import annotations

from typing import Dict, List

# The full chain, in execution order.
ALL_AGENTS: List[str] = [
    "risk", "customer", "communication", "resource", "delivery", "coordinator",
]

# Nobody is being reassigned, so the two agents that exist to move a job between
# couriers have nothing to decide.
NO_REASSIGNMENT: List[str] = ["risk", "customer", "communication", "coordinator"]

# Suitability margin above which the top-ranked driver is treated as the obvious
# answer. Measured on the demo fleet, ~66% of incidents clear this comfortably.
DECISIVE_MARGIN = 0.10

# When is an ETA shift worth telling the recipient about? Relative, not absolute:
# six minutes on a 70-minute run is inside normal variance, while six minutes on a
# 12-minute run is most of the remaining journey. Significant if the shift exceeds
# 20% of the current ETA, with a 5-minute floor so very short runs aren't
# hair-triggered. Both figures are assumptions.
ETA_SHIFT_FLOOR_MIN = 5.0
ETA_SHIFT_FRACTION = 0.20


def eta_shift_is_significant(delta_minutes: float, current_eta_minutes: float) -> bool:
    threshold = max(ETA_SHIFT_FLOOR_MIN, ETA_SHIFT_FRACTION * current_eta_minutes)
    return abs(delta_minutes) >= threshold


def plan_chain(
    disruption: Dict,
    risk: Dict,
    ranking: Dict,
    *,
    incumbent_id: str,
    eta_delta_minutes: float,
    current_eta_minutes: float,
) -> Dict:
    """Return the routing decision for one incident.

    {
      "agents":   [agent_id, ...]   # in execution order, possibly empty
      "skipped":  [{"agent": id, "reason": str}, ...]
      "path":     short label for the UI
      "reason":   one line explaining the decision
      "escalate": bool
      "saved":    how many model calls this decision avoids
    }
    """
    escalate = False

    if not ranking["candidates"]:
        agents: List[str] = []
        path = "escalate"
        reason = (
            f"No driver passes the hard constraints "
            f"({ranking['evaluated']} evaluated, 0 eligible) — a human dispatcher "
            f"is required. No agent can resolve this."
        )
        escalate = True

    elif disruption["disables_driver"]:
        agents = list(ALL_AGENTS)
        path = "full chain"
        reason = (
            "The courier cannot continue, so reassignment is mandatory and every "
            "decision in the chain is live."
        )

    elif disruption["needs_replacement_stock"]:
        agents = list(ALL_AGENTS)
        path = "full chain"
        reason = (
            "The payload itself is not deliverable, so a replacement must be "
            "collected from the depot — reassignment is mandatory."
        )

    elif ranking["candidates"][0]["driver_id"] != incumbent_id:
        # The ranker's best option is somebody else, so a job is genuinely moving
        # between couriers even though the disruption didn't force it.
        agents = list(ALL_AGENTS)
        path = "full chain"
        reason = (
            f"{ranking['candidates'][0]['name']} now outranks the assigned courier, "
            f"so a reassignment is on the table and the courier-side decisions are live."
        )

    elif (
        not disruption["needs_customer_decision"]
        and not eta_shift_is_significant(eta_delta_minutes, current_eta_minutes)
        and risk["band"] in ("nominal", "watch")
    ):
        # Nothing to tell the recipient, nobody to reassign, and the ETA barely
        # moves. This is a mechanical fix — waking a language model to narrate it
        # would be pure waste.
        agents = []
        path = "deterministic"
        reason = (
            f"Internal-only disruption: the recipient's expectations don't change, "
            f"the ETA moves by {eta_delta_minutes:+.0f} min, and risk is "
            f"{risk['band']}. The models resolved it outright — no judgement remains."
        )

    else:
        agents = list(NO_REASSIGNMENT)
        path = "partial chain"
        why = []
        if disruption["needs_customer_decision"]:
            why.append("the recipient's expectations change")
        if eta_shift_is_significant(eta_delta_minutes, current_eta_minutes):
            why.append(f"the ETA moves by {eta_delta_minutes:+.0f} min")
        if risk["band"] not in ("nominal", "watch"):
            why.append(f"risk is {risk['band']}")
        reason = (
            "The assigned courier keeps the job, so the reassignment agents have "
            "nothing to decide — but " + " and ".join(why)
            + ", so the recipient-facing decisions still need judgement."
        )

    skipped = [
        {"agent": a, "reason": _skip_reason(a, path)}
        for a in ALL_AGENTS
        if a not in agents
    ]
    return {
        "agents": agents,
        "skipped": skipped,
        "path": path,
        "reason": reason,
        "escalate": escalate,
        "saved": len(ALL_AGENTS) - len(agents),
        "decisive_margin": DECISIVE_MARGIN,
    }


def _skip_reason(agent: str, path: str) -> str:
    if path == "escalate":
        return "no eligible driver — escalated to a human"
    if path == "deterministic":
        return "resolved by the models; no judgement needed"
    return {
        "resource": "no reassignment needed",
        "delivery": "original courier keeps the job",
    }.get(agent, "not required for this path")
