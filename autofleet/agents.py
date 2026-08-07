"""The five-agent resolution chain.

The chain runs on a detected event, not on a human prompt. Each agent owns one
decision, sees every prior agent's decision, and acts. Deterministic models
supply the arithmetic (route alternates, driver ranking) as tool results before
the agent that needs them, so no agent is ever asked to guess a distance.

Ordering matters and is deliberate: the customer commitment is made first
because it constrains everything downstream (a safe-drop authorisation changes
what a reassignment has to achieve), and the coordinator speaks last because it
is the only agent that has seen all four.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, Dict, Iterator, List, Optional

from .geo import NODES, coord, road_km, travel_minutes
from .llm import LLM
from .scoring import RANKER
from .world import DISRUPTIONS, World

Emit = Callable[[Dict], None]

# --------------------------------------------------------------------------
# Agent roster
# --------------------------------------------------------------------------

AGENT_SPECS: List[Dict] = [
    {
        "id": "customer",
        "label": "Customer Agent",
        "icon": "👤",
        "owns": "What the recipient is told and asked",
    },
    {
        "id": "route",
        "label": "Route Agent",
        "icon": "📍",
        "owns": "Route feasibility and time impact",
    },
    {
        "id": "reallocation",
        "label": "Reallocation Agent",
        "icon": "🔄",
        "owns": "Which driver takes the job",
    },
    {
        "id": "driver",
        "label": "Driver Agent",
        "icon": "🚚",
        "owns": "Original driver status, support and earnings",
    },
    {
        "id": "coordinator",
        "label": "Coordinator Agent",
        "icon": "🧠",
        "owns": "Final authoritative resolution",
    },
]

BASE_SYSTEM = (
    "You are one specialist agent inside AutoFleet AI, an autonomous last-mile "
    "disruption resolution system. A disruption was detected by telemetry and the "
    "agent chain woke automatically. There is no human coordinator in this loop: "
    "you decide and act, you never recommend that someone else act, and you never "
    "ask for approval.\n\n"
    "All distances, ETAs and driver rankings in your input were computed by "
    "deterministic models from live coordinates. Treat them as ground truth. Never "
    "invent a number that is not in your input.\n\n"
    "Output format, strictly: plain prose, no markdown, no bullet points, no "
    "headings, no preamble, no sign-off. State the decision you have taken in the "
    "past or present tense. Never say 'I would' or 'we should'."
)

HUMANITARIAN_SYSTEM = (
    "\n\nThis fleet is running in humanitarian mode. The payload is temperature-"
    "sensitive medical stock moving to primary health centres. The binding "
    "constraint is the cold-chain window, not customer convenience: a consignment "
    "that arrives late arrives spoiled, and spoiled doses are doses nobody "
    "receives. Optimise for time-to-spoilage and speak in terms of consignment "
    "integrity and doses preserved."
)


def _system_for(spec: Dict, world: World) -> str:
    parts = [BASE_SYSTEM]
    if world.is_humanitarian:
        parts.append(HUMANITARIAN_SYSTEM)
    parts.append("\n\n" + _ROLE_PROMPTS[spec["id"]])
    return "".join(parts)


_ROLE_PROMPTS: Dict[str, str] = {
    "customer": (
        "YOUR ROLE — Customer Agent. You own the recipient side of this disruption "
        "and you go first, so your commitment constrains every agent after you. "
        "Decide exactly one course of action: notify of delay, request a new time "
        "slot, authorise a safe drop at the door, or arrange collection. Then state "
        "it in one or two sentences, naming the recipient and the specific action "
        "already taken on their behalf."
    ),
    "route": (
        "YOUR ROLE — Route Agent. You own route feasibility. The alternates in your "
        "input were computed from live coordinates and the current congestion index; "
        "each carries its own added minutes against the disrupted direct path. "
        "State whether rerouting is feasible and give the specific minute impact of "
        "the option you select, naming the corridor it runs through. One or two "
        "sentences."
    ),
    "reallocation": (
        "YOUR ROLE — Reallocation Agent. You own the reassignment. A deterministic "
        "suitability model has already applied the hard constraints and ranked every "
        "eligible driver, and you are given each candidate's score plus the feature "
        "contributions that produced it. Pick exactly one driver — a specific named "
        "person, never a category.\n\n"
        "Your first line must be exactly:\nPICK: <driver_id>\n\n"
        "Then, on the next line, one or two sentences naming the driver, their "
        "distance from the pickup point, and the single strongest reason drawn from "
        "the feature contributions. If the incumbent driver is still the best "
        "choice, pick them and say the assignment is retained."
    ),
    "driver": (
        "YOUR ROLE — Driver Agent. You own the original driver's status and welfare. "
        "Set their availability, log the reason, release them from the assignment, "
        "and dispatch whatever support they are owed. This driver did not cause the "
        "disruption, so their completed-leg earnings and reliability score are "
        "protected — say so explicitly when it applies. One or two sentences."
    ),
    "coordinator": (
        "YOUR ROLE — Coordinator Agent. You are the final authority and you have "
        "seen all four prior decisions. Issue the single authoritative resolution in "
        "two or three sentences: the delivery id, who is now carrying it, the "
        "recipient's status, and the updated ETA. Then add one final sentence "
        "stating the avoided-redelivery impact, using only the figures given to you "
        "and describing them as estimates. Do not restate the other agents' "
        "reasoning and do not thank anyone."
    ),
}


# --------------------------------------------------------------------------
# Context builders
# --------------------------------------------------------------------------

def _incident_context(world: World, delivery_id: str, disruption_key: str, risk: Dict) -> Dict:
    d = world.deliveries[delivery_id]
    driver = world.drivers.get(d["driver_id"])
    dis = DISRUPTIONS[disruption_key]
    ctx = {
        "delivery_id": d["id"],
        "recipient": d["recipient"],
        "payload": d["payload"],
        "destination": NODES[d["destination"]]["name"],
        "current_status": d["status"],
        "eta_minutes_before": round(d["eta_minutes"], 1),
        "schedule_slack_minutes": round(d["slack_minutes"], 1),
        "disruption": dis["label"],
        "severity": dis["severity"],
        "detected_by": dis["detected_as"],
        "current_driver": {
            "id": driver["id"], "name": driver["name"],
            "vehicle": driver["vehicle_label"],
            "hours_on_shift": round(driver["hours_on_shift"], 1),
            "on_time_rate": driver["on_time_rate"],
        } if driver else None,
        "congestion_index": round(d["telemetry"]["traffic_index"], 2),
        "address_confidence": d["address_confidence"],
        "recipient_absence_history": d["recipient_absence_rate"],
        "predicted_failure_risk": risk["risk"],
        "risk_band": risk["band"],
        "dominant_risk_factor": risk["top_driver"],
    }
    if world.is_humanitarian:
        ctx["cold_chain"] = True
        ctx["cold_chain_minutes_remaining"] = round(d.get("cold_minutes_remaining", 0), 0)
        ctx["doses_at_risk"] = d.get("doses", 0)
    return ctx


def _prior_block(prior: List[Dict]) -> str:
    if not prior:
        return "No prior agent decisions — you are first in the chain."
    return "\n".join(f"{p['label']} decided: {p['text']}" for p in prior)


def _user_prompt(*, incident: Dict, prior: List[Dict], extra: Optional[Dict] = None) -> str:
    blocks = [
        "INCIDENT (computed from live fleet telemetry):",
        json.dumps(incident, indent=2),
        "",
        "PRIOR AGENT DECISIONS THIS INCIDENT:",
        _prior_block(prior),
    ]
    if extra:
        for title, payload in extra.items():
            blocks += ["", f"{title}:", json.dumps(payload, indent=2)]
    blocks += ["", "Make your decision now."]
    return "\n".join(blocks)


# --------------------------------------------------------------------------
# Deterministic fallbacks — real numbers, no LLM required
# --------------------------------------------------------------------------

def _fallback_customer(world: World, incident: Dict, dis: Dict) -> str:
    who = incident["recipient"]
    if world.is_humanitarian:
        return (
            f"{who} has been notified that consignment {incident['delivery_id']} is "
            f"affected by a {dis['label'].lower()} and that a cold-chain transfer is "
            f"already in progress; the receiving cold room is being held open with "
            f"{incident.get('cold_chain_minutes_remaining', 0):.0f} minutes of "
            f"integrity window remaining."
        )
    if dis["needs_replacement_stock"]:
        return (
            f"{who} has been notified that the item was damaged in transit and a "
            f"replacement is being dispatched from the depot today at no charge; no "
            f"action is required from them."
        )
    if dis["label"] == "Recipient Not Home":
        return (
            f"{who} has been sent a slot-selection link for the next available "
            f"window and offered an authorised safe drop at the door as the faster "
            f"alternative."
        )
    return (
        f"{who} has been notified of a delay to {incident['delivery_id']} caused by "
        f"a {dis['label'].lower()}, with a revised ETA to follow as soon as "
        f"reassignment is confirmed."
    )


def _fallback_route(alternates: List[Dict]) -> str:
    direct = alternates[0]["direct"]
    options = [a for a in alternates[1:] if "via" in a]
    if not options:
        return (
            f"No viable alternate improves on the direct path at "
            f"{direct['distance_km']:.1f} km and {direct['minutes']:.0f} minutes, so "
            f"the existing route is retained."
        )
    best = min(options, key=lambda o: o["minutes"])
    if best["added_minutes"] <= 0:
        return (
            f"Rerouting via {best['via_name']} covers {best['distance_km']:.1f} km in "
            f"{best['minutes']:.0f} minutes, {abs(best['added_minutes']):.0f} minutes "
            f"faster than the disrupted direct path, so the reroute is applied."
        )
    return (
        f"The alternate via {best['via_name']} adds only "
        f"{best['added_minutes']:.0f} minutes over the direct path, so rerouting is "
        f"feasible with minimal impact."
    )


def _fallback_reallocation(chosen: Dict, incumbent_id: Optional[str]) -> str:
    factor = (chosen.get("decisive_factor") or "proximity").lower()
    if chosen["driver_id"] == incumbent_id:
        return (
            f"PICK: {chosen['driver_id']}\n{chosen['name']} remains the best "
            f"available option at {chosen['distance_km']:.1f} km with a suitability "
            f"score of {chosen['suitability']:.2f}, so the assignment is retained "
            f"rather than moved."
        )
    return (
        f"PICK: {chosen['driver_id']}\nDriver {chosen['name']} is "
        f"{chosen['distance_km']:.1f} km from the pickup point with a suitability "
        f"score of {chosen['suitability']:.2f}, led by {factor}, and is taking the "
        f"job with an ETA of {chosen['eta_minutes']:.0f} minutes."
    )


def _fallback_driver(world: World, incident: Dict, dis: Dict, reassigned: bool) -> str:
    drv = incident.get("current_driver") or {"name": "the assigned driver"}
    if not dis["disables_driver"]:
        if reassigned:
            return (
                f"{drv['name']} stays available and has been released from "
                f"{incident['delivery_id']} with their completed leg credited in full."
            )
        return (
            f"{drv['name']} remains on the assignment with no status change; their "
            f"reliability score is unaffected by this disruption."
        )
    support = dis["driver_support"] or "no field support"
    return (
        f"{drv['name']} is marked unavailable due to {dis['label'].lower()} and "
        f"released from {incident['delivery_id']}, with {support} dispatched to their "
        f"location; earnings for the completed leg are protected and no reliability "
        f"penalty is logged."
    )


def _fallback_coordinator(world: World, incident: Dict, outcome: Dict, entry: Dict) -> str:
    carrier = world.drivers[outcome["new_driver_id"]]["name"]
    if outcome["reassigned"]:
        lead = (
            f"{incident['delivery_id']} has been reassigned to {carrier}. "
            f"The recipient has been notified and the ETA is updated to "
            f"{outcome['eta_minutes']:.0f} minutes."
        )
    else:
        lead = (
            f"{incident['delivery_id']} stays with {carrier} under a revised plan. "
            f"The recipient has been notified and the ETA is updated to "
            f"{outcome['eta_minutes']:.0f} minutes."
        )
    if world.is_humanitarian and entry["doses_preserved"]:
        tail = (
            f" Resolved without human involvement, preserving "
            f"{entry['doses_preserved']} doses and avoiding an estimated "
            f"{entry['km_avoided']:.1f} km of repeat transport "
            f"(~{entry['co2e_kg_avoided']:.2f} kg CO2e)."
        )
    else:
        tail = (
            f" One failed attempt prevented, avoiding an estimated "
            f"{entry['km_avoided']:.1f} km redelivery trip and roughly "
            f"{entry['co2e_kg_avoided']:.2f} kg CO2e."
        )
    return lead + tail


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------

_PICK_RE = re.compile(r"PICK\s*:\s*([A-Za-z]{2,3}-\d{1,4})", re.IGNORECASE)

# Hard wall-clock budget for a whole incident. Past it, the chain stops asking the
# model and finishes from deterministic model output instead.
#
# This is what guarantees an incident always terminates. The language layer is NOT
# load-bearing for the resolution — the hard-constraint filter and the ranker
# already produce a complete, actionable answer, and every agent has a
# deterministic fallback derived from it. So a stalled or failing model costs the
# prose and the nuance, never the resolution itself.
CHAIN_BUDGET_SECONDS = float(os.environ.get("AUTOFLEET_CHAIN_BUDGET", "45"))


def _strip_pick(text: str) -> str:
    return _PICK_RE.sub("", text, count=1).strip().lstrip(":").strip()


def run_chain(
    world: World,
    llm: LLM,
    *,
    delivery_id: str,
    disruption_key: str,
    trigger: str = "manual",
    emit: Emit,
) -> Dict:
    """Run all five agents against one disruption and commit the resolution."""
    started = time.perf_counter()
    dis = DISRUPTIONS[disruption_key]

    if delivery_id not in world.deliveries:
        emit({
            "type": "log", "level": "warn",
            "msg": f"skipped · {delivery_id} no longer exists in the current scenario",
        })
        return {"aborted": True, "reason": "delivery not present"}

    generation = world.generation

    def stale() -> bool:
        """True once the world has been reset or the scenario switched."""
        return world.generation != generation or delivery_id not in world.deliveries

    def abort(stage: str) -> Dict:
        emit({
            "type": "aborted",
            "delivery_id": delivery_id,
            "stage": stage,
            "reason": "fleet state was reset or the scenario changed mid-incident",
            "seconds": round(time.perf_counter() - started, 1),
        })
        emit({
            "type": "log", "level": "warn",
            "msg": f"aborted at {stage} · {delivery_id} · fleet state changed "
                   f"underneath the chain; no partial decision was applied",
        })
        return {"aborted": True, "reason": "generation changed"}

    incident_id = world.next_incident_id()
    risk_before = world.risk_for(delivery_id)
    incident = _incident_context(world, delivery_id, disruption_key, risk_before)
    d = world.deliveries[delivery_id]
    incumbent_id = d["driver_id"]

    emit({
        "type": "chain_start",
        "incident_id": incident_id,
        "delivery_id": delivery_id,
        "disruption": disruption_key,
        "disruption_label": dis["label"],
        "disruption_icon": dis["icon"],
        "severity": dis["severity"],
        "detected_as": dis["detected_as"],
        "trigger": trigger,
        "risk_before": risk_before,
        "agents": AGENT_SPECS,
        "mode": world.mode,
        "llm": llm.status,
    })
    emit({
        "type": "log", "level": "warn",
        "msg": f"{incident_id} · {dis['label']} on {delivery_id} · detected via "
               f"{dis['detected_as'].lower()} · trigger={trigger}",
    })
    world.deliveries[delivery_id]["status"] = "Resolving"
    emit({"type": "state", "state": world.snapshot()})

    prior: List[Dict] = []

    degraded_announced = False

    def run_agent(spec: Dict, *, extra: Optional[Dict], fallback: str) -> str:
        nonlocal degraded_announced
        over_budget = (time.perf_counter() - started) > CHAIN_BUDGET_SECONDS
        if over_budget and not degraded_announced:
            degraded_announced = True
            emit({
                "type": "degraded",
                "delivery_id": delivery_id,
                "budget_seconds": CHAIN_BUDGET_SECONDS,
                "from_agent": spec["id"],
            })
            emit({
                "type": "log", "level": "warn",
                "msg": f"{incident_id} · {CHAIN_BUDGET_SECONDS:.0f}s chain budget spent · "
                       f"finishing from deterministic model output · the resolution "
                       f"still completes, without the language layer",
            })

        emit({
            "type": "agent_start",
            "agent": spec["id"], "label": spec["label"],
            "icon": spec["icon"], "owns": spec["owns"],
        })
        text = ""
        for event in llm.stream(
            system=_system_for(spec, world),
            user=_user_prompt(incident=incident, prior=prior, extra=extra),
            fallback=fallback,
            force_fallback=over_budget,
        ):
            # Order matters: the terminal event also carries a "text" key, so
            # test for `done` first or the summary is mistaken for a delta.
            if event.get("done"):
                text = event["text"]
                emit({
                    "type": "agent_done",
                    "agent": spec["id"], "label": spec["label"],
                    "text": text, "ms": event.get("ms"),
                    "source": event.get("source"), "note": event.get("note"),
                    "tokens": event.get("tokens"), "model": event.get("model"),
                })
            elif "text" in event:
                emit({"type": "agent_delta", "agent": spec["id"], "text": event["text"]})
        return text

    if stale():
        return abort("customer")

    # ---- 1. Customer -----------------------------------------------------
    customer_text = run_agent(
        AGENT_SPECS[0],
        extra=None,
        fallback=_fallback_customer(world, incident, dis),
    )
    prior.append({"label": "Customer Agent", "text": customer_text})

    if stale():
        return abort("route")

    # ---- 2. Route (model first, then judgement) --------------------------
    alternates = world.route_alternates(delivery_id, dis["route_penalty_min"])
    emit({
        "type": "tool",
        "name": "route.alternates",
        "title": "Route alternates computed from live coordinates",
        "detail": f"{len(alternates) - 1} viable detours evaluated against the "
                  f"disrupted direct path",
        "result": alternates,
    })
    route_text = run_agent(
        AGENT_SPECS[1],
        extra={"ROUTE ALTERNATES (computed, minutes are against the disrupted direct path)": alternates},
        fallback=_fallback_route(alternates),
    )
    prior.append({"label": "Route Agent", "text": route_text})

    chosen_route = None
    detours = [a for a in alternates[1:] if "via" in a]
    if detours:
        best = min(detours, key=lambda o: o["minutes"])
        if best["minutes"] < alternates[0]["direct"]["minutes"]:
            chosen_route = best

    if stale():
        return abort("reallocation")

    # ---- 3. Reallocation (ranker first, then judgement) ------------------
    requirement = world.build_requirement(delivery_id, dis)
    pool = world.eligible_drivers(delivery_id, dis)
    ranking = RANKER.rank(pool, requirement)
    emit({
        "type": "tool",
        "name": "reassignment.rank",
        "title": "Driver suitability ranked",
        "detail": f"{ranking['eligible']} of {ranking['evaluated']} drivers passed "
                  f"hard constraints · model {ranking['model']}",
        "result": {
            "model": ranking["model"],
            "kind": ranking["kind"],
            "weights": ranking["weights"],
            "pickup_label": requirement["pickup_label"],
            "candidates": ranking["candidates"][:5],
            "rejected": ranking["rejected"][:6],
        },
    })

    if not ranking["candidates"]:
        emit({
            "type": "log", "level": "error",
            "msg": f"{incident_id} · no driver passes hard constraints; escalating "
                   f"to a human dispatcher. This is a genuine escalation, not a "
                   f"resolution.",
        })
        world.deliveries[delivery_id]["status"] = "Escalated"
        emit({"type": "state", "state": world.snapshot()})
        emit({
            "type": "escalated",
            "incident_id": incident_id,
            "delivery_id": delivery_id,
            "reason": "No eligible driver satisfied the hard constraints "
                      "(cold chain, shift time, capacity).",
            "rejected": ranking["rejected"],
            "seconds": round(time.perf_counter() - started, 1),
        })
        return {"escalated": True, "incident_id": incident_id}

    realloc_text = run_agent(
        AGENT_SPECS[2],
        extra={
            "RANKED CANDIDATES (hard constraints already applied)": {
                "pickup_point": requirement["pickup_label"],
                "model": ranking["model"],
                "feature_weights": ranking["weights"],
                "candidates": ranking["candidates"][:5],
                "excluded": ranking["rejected"][:6],
                "incumbent_driver_id": incumbent_id,
            }
        },
        fallback=_fallback_reallocation(ranking["candidates"][0], incumbent_id),
    )

    match = _PICK_RE.search(realloc_text)
    by_id = {c["driver_id"]: c for c in ranking["candidates"]}
    chosen = by_id.get(match.group(1).upper()) if match else None
    if chosen is None:
        chosen = ranking["candidates"][0]
        emit({
            "type": "log", "level": "warn",
            "msg": f"{incident_id} · reallocation pick unparsed or ineligible; "
                   f"defaulting to top-ranked candidate {chosen['driver_id']}.",
        })
    prior.append({"label": "Reallocation Agent", "text": _strip_pick(realloc_text)})
    emit({
        "type": "selection",
        "agent": "reallocation",
        "driver_id": chosen["driver_id"],
        "driver_name": chosen["name"],
        "distance_km": chosen["distance_km"],
        "eta_minutes": chosen["eta_minutes"],
        "suitability": chosen["suitability"],
        "rank": chosen["rank"],
        "margin_over_next": chosen["margin_over_next"],
        "contributions": chosen["contributions"],
        "decisive_factor": chosen["decisive_factor"],
        "retained": chosen["driver_id"] == incumbent_id,
    })

    will_reassign = chosen["driver_id"] != incumbent_id

    if stale():
        return abort("driver")

    # ---- 4. Driver -------------------------------------------------------
    driver_text = run_agent(
        AGENT_SPECS[3],
        extra={
            "ORIGINAL DRIVER DISPOSITION": {
                "driver": incident.get("current_driver"),
                "disruption_disables_driver": dis["disables_driver"],
                "support_available": dis["driver_support"],
                "job_reassigned_away": will_reassign,
                "welfare_policy": "Completed-leg earnings are protected and no "
                                  "reliability penalty is logged when the driver "
                                  "did not cause the disruption.",
            }
        },
        fallback=_fallback_driver(world, incident, dis, will_reassign),
    )
    prior.append({"label": "Driver Agent", "text": driver_text})

    if stale():
        return abort("commit")

    # ---- Commit the decision --------------------------------------------
    if will_reassign:
        new_eta = chosen["eta_minutes"]
    elif chosen_route:
        new_eta = chosen_route["minutes"]
    else:
        new_eta = alternates[0]["direct"]["minutes"]

    outcome = world.apply_resolution(
        delivery_id=delivery_id,
        incident_id=incident_id,
        disruption_key=disruption_key,
        chosen=chosen,
        reroute=chosen_route,
        new_eta=new_eta,
        support=dis["driver_support"],
        handover_at=requirement["pickup"] if will_reassign else None,
    )
    entry = outcome["impact_entry"]
    emit({"type": "state", "state": world.snapshot()})
    emit({
        "type": "impact",
        "entry": entry,
        "totals": world.ledger.totals(),
        "derivation": (
            f"Depot to destination {outcome['hub_to_customer_km']:.2f} km on-road; "
            f"a failed attempt costs a round trip, discounted to "
            f"{entry['km_avoided']:.2f} km at the redelivery-trip fraction; "
            f"x {entry['vehicle_type']} emission factor = "
            f"{entry['co2e_kg_avoided']:.3f} kg CO2e. All factors are estimates."
        ),
    })
    emit({
        "type": "log", "level": "ok",
        "msg": f"{incident_id} · committed · {delivery_id} -> "
               f"{world.drivers[outcome['new_driver_id']]['name']} · "
               f"ETA {outcome['eta_minutes']:.0f} min",
    })

    if stale():
        return abort("coordinator")

    # ---- 5. Coordinator --------------------------------------------------
    coordinator_text = run_agent(
        AGENT_SPECS[4],
        extra={
            "COMMITTED RESOLUTION (already applied to fleet state)": {
                "delivery_id": delivery_id,
                "reassigned": outcome["reassigned"],
                "now_carried_by": world.drivers[outcome["new_driver_id"]]["name"],
                "previous_driver": incident.get("current_driver", {}).get("name"),
                "new_status": outcome["status"],
                "new_eta_minutes": outcome["eta_minutes"],
                "reroute_via": chosen_route["via_name"] if chosen_route else None,
            },
            "IMPACT (estimates, documented factors)": {
                "failed_attempts_prevented": entry["failed_attempts_prevented"],
                "redelivery_km_avoided": entry["km_avoided"],
                "co2e_kg_avoided": entry["co2e_kg_avoided"],
                "coordinator_minutes_saved": entry["coordinator_minutes_saved"],
                "doses_preserved": entry["doses_preserved"],
            },
        },
        fallback=_fallback_coordinator(world, incident, outcome, entry),
    )
    prior.append({"label": "Coordinator Agent", "text": coordinator_text})

    elapsed = time.perf_counter() - started
    risk_after = world.risk_for(delivery_id)
    emit({
        "type": "resolved",
        "incident_id": incident_id,
        "delivery_id": delivery_id,
        "seconds": round(elapsed, 1),
        "human_interventions": 0,
        "summary": coordinator_text,
        "risk_before": risk_before["risk"],
        "risk_after": risk_after["risk"],
        "reassigned": outcome["reassigned"],
        "new_driver": world.drivers[outcome["new_driver_id"]]["name"],
        "eta_minutes": outcome["eta_minutes"],
        "entry": entry,
        "totals": world.ledger.totals(),
    })
    return {
        "escalated": False,
        "incident_id": incident_id,
        "seconds": round(elapsed, 1),
        "outcome": outcome,
    }
