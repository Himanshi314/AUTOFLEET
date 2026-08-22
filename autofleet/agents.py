"""The agent resolution chain.

The chain runs on a detected event, not a human prompt. Six specialised roles,
each owning one decision and seeing every prior decision. Deterministic models
supply all arithmetic as tool results before the agent that consumes them, so no
agent is ever asked to guess a distance.

Two properties worth understanding before editing:

1. **The router decides which roles run.** Severity is not a label here — it is a
   branch. A routine disruption with one obviously best driver runs zero agents
   and is resolved by the models alone. See `routing.py`.

2. **The dependency order is a DAG, not a cycle.** Risk → Customer →
   Communication → Resource → Delivery → Coordinator. Each role needs what came
   before and nothing that comes after, which is why this is a pipeline and there
   is nothing to negotiate.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Callable, Dict, List, Optional

from .geo import NODES, coord
from .llm import LLM
from .routing import ALL_AGENTS, plan_chain
from .scoring import RANKER
from .world import DISRUPTIONS, SERVICE_MINUTES, World

Emit = Callable[[Dict], None]

# --------------------------------------------------------------------------
# Agent roster — names match the round-1 pitch deck
# --------------------------------------------------------------------------

AGENT_SPECS: List[Dict] = [
    {
        "id": "risk",
        "label": "Risk Agent",
        "icon": "🧭",
        "owns": "How severe this is, and what kind of problem",
    },
    {
        "id": "customer",
        "label": "Customer Agent",
        "icon": "👤",
        "owns": "What we ask of the recipient",
    },
    {
        "id": "communication",
        "label": "Communication Agent",
        "icon": "📣",
        "owns": "The message that actually goes out",
    },
    {
        "id": "resource",
        "label": "Resource Agent",
        "icon": "🔄",
        "owns": "Which driver takes the job",
    },
    {
        "id": "delivery",
        "label": "Delivery Agent",
        "icon": "🚚",
        "owns": "Original courier's status, support and earnings",
    },
    {
        "id": "coordinator",
        "label": "Coordinator Agent",
        "icon": "🧠",
        "owns": "The final authoritative resolution",
    },
]

SPEC_BY_ID = {s["id"]: s for s in AGENT_SPECS}

BASE_SYSTEM = (
    "You are one specialist agent inside AutoFleet AI, an autonomous last-mile "
    "disruption resolution system. A disruption was detected by telemetry and the "
    "agent chain woke automatically. There is no human coordinator in this loop: "
    "you decide and act, you never recommend that someone else act, and you never "
    "ask for approval.\n\n"
    "All distances, ETAs, risk scores and driver rankings in your input were "
    "computed by deterministic models from live coordinates. Treat them as ground "
    "truth. Never invent a number that is not in your input.\n\n"
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

_ROLE_PROMPTS: Dict[str, str] = {
    "risk": (
        "YOUR ROLE — Risk Agent. You go first, and your assessment frames every "
        "decision after yours. You are given a failure-risk score and the "
        "per-feature contributions that produced it. Say how severe this is, "
        "whether it is a recoverable delay or a hard failure, and state plainly "
        "what that means for the agents downstream — for example whether a "
        "same-courier retry is still on the table. Name the one or two factors "
        "actually driving the risk. Two sentences."
    ),
    "customer": (
        "YOUR ROLE — Customer Agent. You own what is asked of the recipient. "
        "Decide exactly one course of action: notify of delay, request a new time "
        "slot, authorise a safe drop at the door, or arrange collection. You "
        "decide the commitment, not the wording — the Communication Agent writes "
        "the message. Respect the Risk Agent's assessment: do not offer a "
        "same-courier retry if it has ruled one out. One or two sentences naming "
        "the recipient and the action taken."
    ),
    "communication": (
        "YOUR ROLE — Communication Agent. You own the message that actually goes "
        "out. The Customer Agent has decided the commitment; you decide what the "
        "recipient is told, through which channel, and when the next update "
        "lands. Be concrete about the channel and the timing. Do not re-decide "
        "the commitment. One or two sentences."
    ),
    "resource": (
        "YOUR ROLE — Resource Agent. You own the reassignment. A deterministic "
        "suitability model has already applied the hard constraints and ranked "
        "every eligible driver, and you are given each candidate's score, the "
        "feature contributions behind it, and the route alternates. Pick exactly "
        "one driver — a specific named person, never a category.\n\n"
        "Your first line must be exactly:\nPICK: <driver_id>\n\n"
        "Then, on the next line, one or two sentences naming the driver, their "
        "distance from the pickup point, and the single strongest reason drawn "
        "from the feature contributions. Mention the route only if an alternate "
        "actually changes the outcome. If the incumbent is still the best choice, "
        "pick them and say the assignment is retained."
    ),
    "delivery": (
        "YOUR ROLE — Delivery Agent. You own the original courier's status and "
        "welfare. Set their availability, log the reason, release them from the "
        "assignment, and dispatch whatever field support they are owed. This "
        "courier did not cause the disruption, so their completed-leg earnings "
        "and reliability score are protected — say so explicitly when it applies. "
        "One or two sentences."
    ),
    "coordinator": (
        "YOUR ROLE — Coordinator Agent. You are the final authority and you have "
        "seen every prior decision. Issue the single authoritative resolution in "
        "two or three sentences: the delivery id, who is now carrying it, the "
        "recipient's status, and the updated ETA. Then add one final sentence "
        "stating the avoided-redelivery impact, using only the figures given to "
        "you and describing them as estimates. Do not restate the other agents' "
        "reasoning and do not thank anyone."
    ),
}


def _system_for(spec: Dict, world: World) -> str:
    parts = [BASE_SYSTEM]
    if world.is_humanitarian:
        parts.append(HUMANITARIAN_SYSTEM)
    parts.append("\n\n" + _ROLE_PROMPTS[spec["id"]])
    return "".join(parts)


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
# Deterministic fallbacks — real numbers, no model required
# --------------------------------------------------------------------------

def _fallback_risk(world: World, incident: Dict, dis: Dict, risk: Dict) -> str:
    top = risk["contributions"][0]
    second = risk["contributions"][1]
    hard = dis["disables_driver"]
    if world.is_humanitarian:
        return (
            f"Failure risk on {incident['delivery_id']} is "
            f"{risk['risk']:.0%} ({risk['band']}), driven mainly by "
            f"{top['label'].lower()} compounding with {second['label'].lower()}. "
            f"With {incident.get('cold_chain_minutes_remaining', 0):.0f} minutes of "
            f"integrity window left this is a consignment-integrity failure, not a "
            f"delay — transfer to a cold-chain-capable courier is mandatory."
        )
    return (
        f"Failure risk on {incident['delivery_id']} is {risk['risk']:.0%} "
        f"({risk['band']}), driven mainly by {top['label'].lower()} compounding "
        f"with {second['label'].lower()}. "
        + (
            "This is a hard stop rather than a delay — the courier cannot "
            "continue, so reassignment is mandatory and no same-courier retry "
            "should be offered."
            if hard else
            "The courier can still complete the job, so this is a recoverable "
            "delay and a same-courier resolution remains on the table."
        )
    )


def _fallback_customer(world: World, incident: Dict, dis: Dict) -> str:
    who = incident["recipient"]
    if world.is_humanitarian:
        return (
            f"{who} has been told to hold the receiving cold room open for a "
            f"transferred consignment; no change of destination is required and "
            f"the facility keeps its original slot."
        )
    if dis["needs_replacement_stock"]:
        return (
            f"{who} is being sent a replacement at no charge rather than the "
            f"damaged item, and no action is required from them."
        )
    if dis["label"] == "Recipient Not Home":
        return (
            f"{who} is offered an authorised safe drop at the door as the fastest "
            f"resolution, with a next-day slot as the alternative if they decline."
        )
    if dis["disables_driver"]:
        # A hard failure — do not imply the original window still stands.
        return (
            f"{who} is being notified that the delivery is delayed by a courier "
            f"vehicle failure and that a replacement is already being assigned; "
            f"they keep today's delivery but owe a revised arrival time."
        )
    return (
        f"{who} keeps their existing delivery window and is owed a revised ETA "
        f"once the courier position is confirmed."
    )


def _fallback_communication(world: World, incident: Dict, dis: Dict) -> str:
    who = incident["recipient"]
    if world.is_humanitarian:
        return (
            f"A cold-chain alert has gone to {who} on the facility's duty line "
            f"stating the transfer is under way, with a confirmed arrival time to "
            f"follow the moment the receiving courier is assigned."
        )
    return (
        f"An SMS has gone to {who} naming the {dis['label'].lower()} as the cause "
        f"and setting expectations honestly, with a follow-up carrying the firm "
        f"ETA as soon as the assignment is confirmed."
    )


def _fallback_resource(chosen: Dict, incumbent_id: Optional[str], route: Optional[Dict]) -> str:
    factor = (chosen.get("decisive_factor") or "proximity").lower()
    via = f" via {route['via_name']}" if route else ""
    if chosen["driver_id"] == incumbent_id:
        return (
            f"PICK: {chosen['driver_id']}\n{chosen['name']} remains the best "
            f"available option at {chosen['distance_km']:.1f} km with a "
            f"suitability score of {chosen['suitability']:.2f}, so the assignment "
            f"is retained rather than moved{via}."
        )
    return (
        f"PICK: {chosen['driver_id']}\nDriver {chosen['name']} is "
        f"{chosen['distance_km']:.1f} km from the pickup point with a suitability "
        f"score of {chosen['suitability']:.2f}, led by {factor}, and is taking the "
        f"job{via} with an ETA of {chosen['eta_minutes']:.0f} minutes."
    )


def _fallback_delivery(world: World, incident: Dict, dis: Dict, reassigned: bool) -> str:
    drv = incident.get("current_driver") or {"name": "the assigned courier"}
    if not dis["disables_driver"]:
        if reassigned:
            return (
                f"{drv['name']} stays available and has been released from "
                f"{incident['delivery_id']} with the completed leg credited in full."
            )
        return (
            f"{drv['name']} remains on the assignment with no status change, and "
            f"their reliability score is unaffected by this disruption."
        )
    support = dis["driver_support"] or "no field support"
    return (
        f"{drv['name']} is marked unavailable due to {dis['label'].lower()} and "
        f"released from {incident['delivery_id']}, with {support} dispatched to "
        f"their location; earnings for the completed leg are protected and no "
        f"reliability penalty is logged."
    )


def _fallback_coordinator(world: World, incident: Dict, outcome: Dict, entry: Dict) -> str:
    carrier = world.drivers[outcome["new_driver_id"]]["name"]
    verb = "has been reassigned to" if outcome["reassigned"] else "stays with"
    lead = (
        f"{incident['delivery_id']} {verb} {carrier}. The recipient has been "
        f"notified and the ETA is updated to {outcome['eta_minutes']:.0f} minutes."
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


_FALLBACKS = {
    "risk": lambda w, i, d, ctx: _fallback_risk(w, i, d, ctx["risk"]),
    "customer": lambda w, i, d, ctx: _fallback_customer(w, i, d),
    "communication": lambda w, i, d, ctx: _fallback_communication(w, i, d),
    "resource": lambda w, i, d, ctx: _fallback_resource(
        ctx["chosen"], ctx["incumbent_id"], ctx["route"]
    ),
    "delivery": lambda w, i, d, ctx: _fallback_delivery(w, i, d, ctx["will_reassign"]),
}


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------

_PICK_RE = re.compile(r"PICK\s*:\s*([A-Za-z]{2,3}-\d{1,4})", re.IGNORECASE)


# --------------------------------------------------------------------------
# A7 — the Resource Agent commits via a schema-validated tool call
# --------------------------------------------------------------------------
#
# `strict: True` plus a forced tool_choice means the API guarantees the shape, so
# the driver id arrives as a validated field rather than being scraped out of a
# sentence with a regex. That regex was the most brittle seam in the chain: a
# model that phrased its answer slightly differently silently fell through to the
# top-ranked candidate. It survives only as the offline fallback path.
REASSIGN_TOOL: Dict = {
    "name": "reassign_delivery",
    "description": (
        "Commit this delivery to exactly one driver from the ranked candidates. "
        "Call this once. The driver_id must be copied exactly from a candidate in "
        "your input — never invented, never a driver that was excluded."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "driver_id": {
                "type": "string",
                "description": "driver_id of the chosen candidate, exactly as given.",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "One or two sentences naming the driver, their distance from "
                    "the pickup point, and the single strongest reason drawn from "
                    "the feature contributions. Plain prose, no markdown."
                ),
            },
            "retained": {
                "type": "boolean",
                "description": (
                    "True if this is the courier already assigned, i.e. the "
                    "assignment is retained rather than moved."
                ),
            },
        },
        "required": ["driver_id", "rationale", "retained"],
        "additionalProperties": False,
    },
}


# --------------------------------------------------------------------------
# A8 — Coordinator fact-check
# --------------------------------------------------------------------------

# Models write typographic punctuation, not ASCII. gpt-oss returns "D‑101" with a
# NON-BREAKING HYPHEN (U+2011) and narrow no-break spaces (U+202F) inside numbers.
# An ASCII-only [A-Za-z]-\d pattern silently fails to strip such an id, "101" is
# then read as a claim, and the Coordinator is reported as having fabricated a
# number on every single incident — the fact-checker discrediting itself. So
# normalise the text before any pattern touches it.
_DASHES = dict.fromkeys(
    (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212, 0xFE63, 0xFF0D), "-"
)
_THIN_SPACES = dict.fromkeys((0x00A0, 0x2007, 0x2009, 0x202F), " ")
_PUNCT_NORMALISE = {**_DASHES, **_THIN_SPACES}


def _normalise(text: str) -> str:
    """Fold typographic dashes and no-break spaces down to ASCII."""
    return text.translate(_PUNCT_NORMALISE)


# Identifiers must be stripped before looking for numbers, or "D-102" parses as
# the number -102 and every single incident fails its own fact check.
_ID_RE = re.compile(r"\b[A-Za-z]{1,4}-\d+\b")

# Captures comma-grouped numbers ("1,270") and notes a trailing percent sign, so a
# risk stated as "55%" can be matched against a source stored as 0.55.
_NUM_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(%?)")

# Small integers appear in ordinary prose ("one failed attempt", "a second trip")
# and would produce constant false positives, so they are not treated as claims.
_PROSE_INT_CEILING = 3


def _candidates_for_prompt(candidates: List[Dict]) -> List[Dict]:
    """Trim the ranking payload before it goes into a prompt.

    Each candidate carries a `contributions` array — the per-feature score
    breakdown — at about 1.1k characters apiece. That exists for the UI's
    explainability panel, which receives the FULL ranking over the
    `reassignment.rank` event and is unaffected by this.

    Sending it to the model as well cost ~3,200 tokens on the Resource turn
    alone: its prompt measured 13,170 characters against 1,200-2,500 for every
    other agent. On Groq's 8,000-tokens-per-minute free tier that single call
    was eating a third of the budget, which is what pushed the last two agents
    of a six-agent chain into 429s.

    The agent does not need the breakdown to justify a pick — `suitability`,
    `decisive_factor` and the raw distance/ETA/on-time figures say the same
    thing far more cheaply. The top candidate keeps its full breakdown so the
    winning choice can still be explained in feature terms.
    """
    trimmed = []
    for i, c in enumerate(candidates):
        if i == 0:
            trimmed.append(c)
            continue
        trimmed.append({k: v for k, v in c.items() if k != "contributions"})
    return trimmed


def _numbers_in(text: str) -> List[float]:
    """Numeric values in a string, ignoring identifiers like D-102 or DR-11."""
    return [v for v, _ in _numbers_with_units(text)]


def _numbers_with_units(text: str) -> List[tuple]:
    """(value, is_percent) pairs, with identifiers removed first."""
    cleaned = _ID_RE.sub(" ", _normalise(text))
    out = []
    for raw, pct in _NUM_RE.findall(cleaned):
        try:
            out.append((float(raw.replace(",", "")), pct == "%"))
        except ValueError:
            pass
    return out


def _collect_source_numbers(payload) -> List[float]:
    """Every number the Coordinator was actually given, recursively."""
    found: List[float] = []
    if isinstance(payload, dict):
        for v in payload.values():
            found += _collect_source_numbers(v)
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            found += _collect_source_numbers(v)
    elif isinstance(payload, bool):
        pass
    elif isinstance(payload, (int, float)):
        found.append(float(payload))
    elif isinstance(payload, str):
        found += _numbers_in(payload)
    return found


def verify_numbers(text: str, sources: List[float]) -> Dict:
    """Check every number the Coordinator states against the numbers it was given.

    The Coordinator's whole job is summarising other agents' decisions, which
    makes it the highest hallucination risk in the chain — a fabricated ETA or a
    fabricated CO2e figure would read exactly like a real one. This is cheap to
    check mechanically, so it is checked on every incident.

    A claim passes if it matches a source value exactly, or matches once either
    side is rounded to the same precision (the model says "21 minutes" for 21.0,
    "27.4 km" for 27.44).
    """
    def matches(candidate: float, s: float) -> bool:
        if candidate == s:
            return True
        if round(candidate, 1) == round(s, 1):
            return True
        # Integer rounding must not apply below 1, or any two small fractions
        # match each other (0.03 and 0.14 both round to 0) and a fabricated
        # percentage sails through.
        if abs(candidate) >= 1 and abs(s) >= 1 and round(candidate) == round(s):
            return True
        return s != 0 and abs(candidate - s) / abs(s) < 0.02

    claims, unverified = [], []
    for n, is_pct in _numbers_with_units(text):
        # A bare small integer is usually prose ("a second trip"), but a small
        # *percentage* is always a claim — so the exemption must not apply to it.
        if not is_pct and abs(n) <= _PROSE_INT_CEILING and float(n).is_integer():
            continue
        claims.append(n)
        # A percentage may be stated as "55%" against a source held as 0.55.
        candidates = [n, n / 100.0] if is_pct else [n]
        if not any(matches(c, s) for c in candidates for s in sources):
            unverified.append(n)
    return {
        "claims_checked": len(claims),
        "unverified": unverified,
        "passed": not unverified,
    }

# Hard wall-clock budget for a whole incident. Past it, the chain stops asking the
# model and finishes from deterministic model output instead.
#
# This is what guarantees an incident always terminates. The language layer is NOT
# load-bearing for the resolution — the hard-constraint filter and the ranker
# already produce a complete, actionable answer, and every agent has a
# deterministic fallback derived from it. A stalled model costs the prose, never
# the resolution.
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
    """Resolve one disruption. Routes, runs the chosen agents, commits the result."""
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
        return world.generation != generation or delivery_id not in world.deliveries

    def abort(stage: str) -> Dict:
        emit({
            "type": "aborted", "delivery_id": delivery_id, "stage": stage,
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
        "incident_id": incident_id, "delivery_id": delivery_id,
        "disruption": disruption_key, "disruption_label": dis["label"],
        "disruption_icon": dis["icon"], "severity": dis["severity"],
        "detected_as": dis["detected_as"], "trigger": trigger,
        "risk_before": risk_before, "agents": AGENT_SPECS,
        "mode": world.mode, "llm": llm.status,
    })
    emit({
        "type": "log", "level": "warn",
        "msg": f"{incident_id} · {dis['label']} on {delivery_id} · detected via "
               f"{dis['detected_as'].lower()} · trigger={trigger}",
    })
    world.deliveries[delivery_id]["status"] = "Resolving"
    emit({"type": "state", "state": world.snapshot()})

    # ---- Models run first. All of this is arithmetic, and it is free. --------

    alternates = world.route_alternates(delivery_id, dis["route_penalty_min"])
    emit({
        "type": "tool", "name": "route.alternates",
        "title": "Route alternates computed from live coordinates",
        "detail": f"{len(alternates) - 1} viable detours evaluated against the "
                  f"disrupted direct path",
        "result": alternates,
    })

    detours = [a for a in alternates[1:] if "via" in a]
    chosen_route = None
    if detours:
        best = min(detours, key=lambda o: o["minutes"])
        if best["minutes"] < alternates[0]["direct"]["minutes"]:
            chosen_route = best

    requirement = world.build_requirement(delivery_id, dis)
    pool = world.eligible_drivers(delivery_id, dis)
    ranking = RANKER.rank(pool, requirement)
    emit({
        "type": "tool", "name": "reassignment.rank",
        "title": "Driver suitability ranked",
        "detail": f"{ranking['eligible']} of {ranking['evaluated']} drivers passed "
                  f"hard constraints · model {ranking['model']}",
        "result": {
            "model": ranking["model"], "kind": ranking["kind"],
            "weights": ranking["weights"],
            "pickup_label": requirement["pickup_label"],
            "candidates": ranking["candidates"][:5],
            "rejected": ranking["rejected"][:6],
        },
    })

    # ---- Route the incident. Still no model calls. --------------------------

    # What the resolution would do to the ETA if nobody is reassigned — the router
    # needs it to tell a trivial internal fix from one the recipient must hear about.
    _no_swap_eta = (
        chosen_route["minutes"] if chosen_route else alternates[0]["direct"]["minutes"]
    )
    plan = plan_chain(
        dis, risk_before, ranking,
        incumbent_id=incumbent_id,
        eta_delta_minutes=_no_swap_eta - d["eta_minutes"],
        current_eta_minutes=d["eta_minutes"],
    )
    emit({
        "type": "plan",
        "incident_id": incident_id,
        "path": plan["path"], "reason": plan["reason"],
        "agents": plan["agents"], "skipped": plan["skipped"],
        "saved": plan["saved"], "total": len(ALL_AGENTS),
        "specs": AGENT_SPECS,
    })
    emit({
        "type": "log",
        "level": "ok" if plan["saved"] else "info",
        "msg": f"{incident_id} · routed as '{plan['path']}' · "
               f"{len(plan['agents'])}/{len(ALL_AGENTS)} agents will run · "
               f"{plan['saved']} model call(s) avoided",
    })

    if plan["escalate"]:
        emit({
            "type": "log", "level": "error",
            "msg": f"{incident_id} · no driver passes hard constraints; escalating "
                   f"to a human dispatcher. This is a genuine escalation, not a "
                   f"resolution.",
        })
        world.deliveries[delivery_id]["status"] = "Escalated"
        # A person now has to deal with this, so the dashboard must say so.
        world.ledger.record_escalation(
            incident_id=incident_id, delivery_id=delivery_id,
            reason=plan["reason"],
        )
        emit({"type": "state", "state": world.snapshot()})
        emit({
            "type": "escalated", "incident_id": incident_id,
            "delivery_id": delivery_id, "reason": plan["reason"],
            "rejected": ranking["rejected"],
            "seconds": round(time.perf_counter() - started, 1),
        })
        return {"escalated": True, "incident_id": incident_id}

    # ---- Run the roles the router selected ---------------------------------

    prior: List[Dict] = []
    runs = set(plan["agents"])
    skip_reason = {s["agent"]: s["reason"] for s in plan["skipped"]}
    degraded_announced = False
    # Real model calls attempted. Incremented only when the language layer is
    # actually invoked — a call forced to the deterministic fallback (over
    # budget, or no live provider) does NOT hit an API and must not be counted.
    calls_made = 0

    tool_results: Dict[str, Optional[Dict]] = {}

    def run_agent(
        agent_id: str, *, extra: Optional[Dict], fallback: str,
        tool: Optional[Dict] = None, fallback_tool_input: Optional[Dict] = None,
    ) -> str:
        nonlocal degraded_announced, calls_made
        spec = SPEC_BY_ID[agent_id]

        if agent_id not in runs:
            emit({
                "type": "agent_skipped",
                "agent": agent_id, "label": spec["label"], "icon": spec["icon"],
                "owns": spec["owns"],
                "reason": skip_reason.get(agent_id, "not required for this path"),
            })
            return ""

        over_budget = (time.perf_counter() - started) > CHAIN_BUDGET_SECONDS
        if over_budget and not degraded_announced:
            degraded_announced = True
            emit({
                "type": "degraded", "delivery_id": delivery_id,
                "budget_seconds": CHAIN_BUDGET_SECONDS, "from_agent": agent_id,
            })
            emit({
                "type": "log", "level": "warn",
                "msg": f"{incident_id} · {CHAIN_BUDGET_SECONDS:.0f}s chain budget "
                       f"spent · finishing from deterministic model output · the "
                       f"resolution still completes, without the language layer",
            })

        # The handoff is the whole claim of a "chain", and it is invisible in the
        # UI unless it is published: every agent's prompt literally contains the
        # preceding agents' conclusions (see _user_prompt -> _prior_block). Ship
        # that list so a reader can confirm agent N received agent N-1's words
        # verbatim, rather than taking the arrows in the diagram on faith. This
        # is the same `prior` object handed to the model, not a paraphrase.
        prompt = _user_prompt(incident=incident, prior=prior, extra=extra)
        emit({
            "type": "agent_start", "agent": agent_id, "label": spec["label"],
            "icon": spec["icon"], "owns": spec["owns"],
            "received": [dict(p) for p in prior],
            "prompt_chars": len(prompt),
            "extra_keys": sorted(extra.keys()) if extra else [],
        })
        if llm.live and not over_budget:
            calls_made += 1
        text = ""
        for event in llm.stream(
            system=_system_for(spec, world),
            user=prompt,
            fallback=fallback,
            force_fallback=over_budget,
            tool=tool,
            fallback_tool_input=fallback_tool_input,
        ):
            # Order matters: the terminal event also carries a "text" key, so test
            # for `done` first or the summary is mistaken for a delta.
            if event.get("done"):
                text = event["text"]
                if tool is not None:
                    tool_results[agent_id] = event.get("tool_input")
                    emit({
                        "type": "tool_call",
                        "agent": agent_id,
                        "name": event.get("tool_name") or tool["name"],
                        "input": event.get("tool_input"),
                        "validated": event.get("source") == "live",
                    })
                emit({
                    "type": "agent_done", "agent": agent_id, "label": spec["label"],
                    "text": text, "ms": event.get("ms"),
                    "source": event.get("source"), "note": event.get("note"),
                    "tokens": event.get("tokens"), "model": event.get("model"),
                })
            elif "text" in event:
                emit({"type": "agent_delta", "agent": agent_id, "text": event["text"]})
        return text

    fb_ctx = {
        "risk": risk_before, "route": chosen_route,
        "chosen": ranking["candidates"][0], "incumbent_id": incumbent_id,
        "will_reassign": ranking["candidates"][0]["driver_id"] != incumbent_id,
    }

    def fb(agent_id: str) -> str:
        return _FALLBACKS[agent_id](world, incident, dis, fb_ctx)

    # 1 — Risk
    if stale():
        return abort("risk")
    txt = run_agent("risk", extra={"RISK MODEL OUTPUT": risk_before}, fallback=fb("risk"))
    if txt:
        prior.append({"label": "Risk Agent", "text": txt})

    # 2 — Customer
    if stale():
        return abort("customer")
    txt = run_agent("customer", extra=None, fallback=fb("customer"))
    if txt:
        prior.append({"label": "Customer Agent", "text": txt})

    # 3 — Communication
    if stale():
        return abort("communication")
    txt = run_agent("communication", extra=None, fallback=fb("communication"))
    if txt:
        prior.append({"label": "Communication Agent", "text": txt})

    # 4 — Resource (route alternates + ranked candidates)
    if stale():
        return abort("resource")
    resource_text = run_agent(
        "resource",
        extra={
            "RANKED CANDIDATES (hard constraints already applied)": {
                "pickup_point": requirement["pickup_label"],
                "model": ranking["model"],
                "feature_weights": ranking["weights"],
                "candidates": _candidates_for_prompt(ranking["candidates"][:5]),
                "excluded": ranking["rejected"][:6],
                "incumbent_driver_id": incumbent_id,
            },
            "ROUTE ALTERNATES (minutes are against the disrupted direct path)":
                alternates,
        },
        fallback=fb("resource"),
        tool=REASSIGN_TOOL,
        fallback_tool_input={
            "driver_id": ranking["candidates"][0]["driver_id"],
            "rationale": _strip_pick(fb("resource")),
            "retained": ranking["candidates"][0]["driver_id"] == incumbent_id,
        },
    )

    by_id = {c["driver_id"]: c for c in ranking["candidates"]}
    chosen = None
    if resource_text:
        # Preferred path: a validated tool call carries the id as a field.
        picked_id = (tool_results.get("resource") or {}).get("driver_id")
        chosen = by_id.get(str(picked_id).upper()) if picked_id else None
        if chosen is None:
            # Legacy path, kept for the offline fallback and belt-and-braces: an
            # id scraped out of prose.
            match = _PICK_RE.search(resource_text)
            chosen = by_id.get(match.group(1).upper()) if match else None
        if chosen is None:
            chosen = ranking["candidates"][0]
            emit({
                "type": "log", "level": "warn",
                "msg": f"{incident_id} · resource pick missing or ineligible "
                       f"(got {picked_id!r}); defaulting to top-ranked candidate "
                       f"{chosen['driver_id']}.",
            })
        prior.append({"label": "Resource Agent", "text": _strip_pick(resource_text)})
    else:
        # Resource Agent was routed out — the ranker's top pick stands as-is.
        chosen = ranking["candidates"][0]

    emit({
        "type": "selection", "agent": "resource",
        "driver_id": chosen["driver_id"], "driver_name": chosen["name"],
        "distance_km": chosen["distance_km"], "eta_minutes": chosen["eta_minutes"],
        "suitability": chosen["suitability"], "rank": chosen["rank"],
        "margin_over_next": chosen["margin_over_next"],
        "contributions": chosen["contributions"],
        "decisive_factor": chosen["decisive_factor"],
        "retained": chosen["driver_id"] == incumbent_id,
        "by_model_only": not bool(resource_text),
    })

    will_reassign = chosen["driver_id"] != incumbent_id
    fb_ctx["will_reassign"] = will_reassign

    # 5 — Delivery
    if stale():
        return abort("delivery")
    txt = run_agent("delivery", extra={
        "ORIGINAL COURIER DISPOSITION": {
            "driver": incident.get("current_driver"),
            "disruption_disables_driver": dis["disables_driver"],
            "support_available": dis["driver_support"],
            "job_reassigned_away": will_reassign,
            "welfare_policy": "Completed-leg earnings are protected and no "
                              "reliability penalty is logged when the courier did "
                              "not cause the disruption.",
        }
    }, fallback=fb("delivery"))
    if txt:
        prior.append({"label": "Delivery Agent", "text": txt})

    # ---- Commit -------------------------------------------------------------

    if stale():
        return abort("commit")

    if will_reassign:
        new_eta = chosen["eta_minutes"]
    elif chosen_route:
        new_eta = chosen_route["minutes"]
    else:
        new_eta = alternates[0]["direct"]["minutes"]

    outcome = world.apply_resolution(
        delivery_id=delivery_id, incident_id=incident_id,
        disruption_key=disruption_key, chosen=chosen, reroute=chosen_route,
        new_eta=new_eta, support=dis["driver_support"],
        handover_at=requirement["pickup"] if will_reassign else None,
        handover_label=requirement["pickup_label"] if will_reassign else None,
        # The Resource agent's own sentence, so the courier is told the same
        # reason operations is told — not a separate, blander paraphrase.
        rationale=(tool_results.get("resource") or {}).get("rationale"),
        # len(runs), not calls_made: this ledger line is written before the
        # coordinator runs, so calls_made would undercount the chain by one.
        # The pair is the router's efficiency claim and must sum to ALL_AGENTS.
        llm_calls_used=len(runs), llm_calls_saved=plan["saved"],
    )
    entry = outcome["impact_entry"]
    emit({"type": "state", "state": world.snapshot()})
    emit({
        "type": "impact", "entry": entry, "totals": world.ledger.totals(),
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

    # 6 — Coordinator
    if stale():
        return abort("coordinator")
    coordinator_extra = {
        "COMMITTED RESOLUTION (already applied to fleet state)": {
            "delivery_id": delivery_id,
            "reassigned": outcome["reassigned"],
            "now_carried_by": world.drivers[outcome["new_driver_id"]]["name"],
            "previous_driver": (incident.get("current_driver") or {}).get("name"),
            "new_status": outcome["status"],
            "new_eta_minutes": outcome["eta_minutes"],
            "reroute_via": chosen_route["via_name"] if chosen_route else None,
            "resolution_path": plan["path"],
        },
        "IMPACT (estimates, documented factors)": {
            "failed_attempts_prevented": entry["failed_attempts_prevented"],
            "redelivery_km_avoided": entry["km_avoided"],
            "co2e_kg_avoided": entry["co2e_kg_avoided"],
            "coordinator_minutes_saved": entry["coordinator_minutes_saved"],
            "doses_preserved": entry["doses_preserved"],
        },
    }
    coordinator_text = run_agent(
        "coordinator", extra=coordinator_extra,
        fallback=_fallback_coordinator(world, incident, outcome, entry),
    )

    summary = coordinator_text or _fallback_coordinator(world, incident, outcome, entry)
    if coordinator_text:
        prior.append({"label": "Coordinator Agent", "text": coordinator_text})

    # A8 — the Coordinator summarises, which makes it the highest hallucination
    # risk in the chain. Every number it states must appear in what it was given.
    check = verify_numbers(
        summary,
        _collect_source_numbers(coordinator_extra)
        + _collect_source_numbers(incident)
        + [p for p in (outcome["eta_minutes"], entry["km_avoided"],
                       entry["co2e_kg_avoided"], entry["coordinator_minutes_saved"])],
    )
    emit({
        "type": "verification",
        "agent": "coordinator",
        "claims_checked": check["claims_checked"],
        "unverified": check["unverified"],
        "passed": check["passed"],
    })
    if not check["passed"]:
        emit({
            "type": "log", "level": "error",
            "msg": f"{incident_id} · FACT CHECK FAILED · the Coordinator stated "
                   f"{check['unverified']} which appear nowhere in its input. "
                   f"Treat that summary as unreliable.",
        })

    elapsed = time.perf_counter() - started
    risk_after = world.risk_for(delivery_id)
    emit({
        "type": "resolved",
        "incident_id": incident_id, "delivery_id": delivery_id,
        "seconds": round(elapsed, 1), "human_interventions": 0,
        "summary": summary,
        "risk_before": risk_before["risk"], "risk_after": risk_after["risk"],
        "reassigned": outcome["reassigned"],
        "new_driver": world.drivers[outcome["new_driver_id"]]["name"],
        "eta_minutes": outcome["eta_minutes"],
        "path": plan["path"], "calls_made": calls_made, "calls_saved": plan["saved"],
        "entry": entry, "totals": world.ledger.totals(),
    })
    return {
        "escalated": False, "incident_id": incident_id,
        "seconds": round(elapsed, 1), "outcome": outcome,
        "path": plan["path"], "calls_made": calls_made,
    }
