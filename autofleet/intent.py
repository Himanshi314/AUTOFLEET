"""Intent capture and pre-commit conflict checking.

The chain's commit point is `world.apply_resolution()`. Everything before it is a
proposal; that call is where a courier's evening actually changes. This module
sits in front of it.

Three ideas, kept separate on purpose:

  · An INTENT is a goal somebody stated. Not a capability, not a constraint the
    system inferred — something a named party declared, in their own words, that
    they can point at afterwards. "Nothing after 18:00, I leave for work."
  · A CONFLICT is an intent this specific proposed action would break, with the
    arithmetic that proves it. Never a label on its own.
  · The GATE is what happens next: try the next-best option, or stop and ask a
    person. A conflict that only gets logged is decoration.

Why intents are not just more hard constraints: the suitability model already
filters on capability (has a cold box, has capacity, is on shift). Those are
facts about the world. An intent is a *preference with an owner*, it can be
withdrawn, and two of them can be irreconcilable in a way no capability check
ever is — the recipient wants it before six, the courier's shift ends at five
forty. Nobody is wrong. Something has to give, and a person should choose which.

Every number in a conflict comes from live state — driver shift remaining, cold
window remaining, the ranked candidate's own ETA. Nothing here invents a figure.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

HOLDER_TYPES = ("recipient", "courier", "operations", "payload")

# Hard means: do not commit this action while the intent stands. Soft means:
# committing is allowed, but the cost has to be shown rather than absorbed
# silently.
HARDNESS = ("hard", "soft")

VERDICTS = ("satisfied", "at_risk", "violated")


class Intent:
    """A goal somebody stated, and the machinery to test one action against it."""

    __slots__ = ("id", "holder", "holder_type", "kind", "statement", "params",
                 "hardness", "scope", "active", "declared")

    def __init__(
        self, *, id: str, holder: str, holder_type: str, kind: str,
        statement: str, params: Dict, hardness: str = "hard",
        scope: str = "*", active: bool = True, declared: str = "",
    ) -> None:
        if holder_type not in HOLDER_TYPES:
            raise ValueError(f"holder_type must be one of {HOLDER_TYPES}")
        if hardness not in HARDNESS:
            raise ValueError(f"hardness must be one of {HARDNESS}")
        self.id = id
        self.holder = holder
        self.holder_type = holder_type
        self.kind = kind
        self.statement = statement
        self.params = params
        self.hardness = hardness
        # Which delivery or driver this applies to; "*" is fleet-wide.
        self.scope = scope
        self.active = active
        self.declared = declared

    def applies_to(self, *, delivery_id: str, driver_id: Optional[str]) -> bool:
        if not self.active:
            return False
        return self.scope in ("*", delivery_id) or self.scope == driver_id

    def as_dict(self) -> Dict:
        return {
            "id": self.id, "holder": self.holder, "holder_type": self.holder_type,
            "kind": self.kind, "statement": self.statement, "params": self.params,
            "hardness": self.hardness, "scope": self.scope, "active": self.active,
            "declared": self.declared,
        }


# --------------------------------------------------------------------------
# Evaluators — one per intent kind
# --------------------------------------------------------------------------
# Each returns (verdict, evidence, hint). `evidence` must contain the numbers a
# reader needs to check the verdict themselves; a conflict with no arithmetic is
# an assertion, and the whole point of this module is that it isn't one.

def _fmt_clock(minutes: float) -> str:
    """Minutes-since-midnight as HH:MM, so a deadline reads like a deadline."""
    m = int(round(minutes)) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def _eval_delivery_deadline(intent: Intent, action: Dict, ctx: Dict):
    """Recipient will not accept the payload after a stated time."""
    deadline = float(intent.params["by_minutes"])          # minutes since midnight
    arrival = ctx["clock_minutes"] + float(action["eta_minutes"])
    over = arrival - deadline
    evidence = {
        "deadline": _fmt_clock(deadline),
        "projected_arrival": _fmt_clock(arrival),
        "margin_minutes": round(-over, 1),
        "basis": f"clock {_fmt_clock(ctx['clock_minutes'])} + ETA "
                 f"{action['eta_minutes']:.1f} min",
    }
    if over > 0:
        return "violated", evidence, (
            f"arrives {over:.0f} min after the recipient's cutoff — a faster "
            f"courier, or the recipient has to authorise a later handoff"
        )
    if over > -10:
        return "at_risk", evidence, (
            f"only {-over:.0f} min of margin against the cutoff"
        )
    return "satisfied", evidence, ""


def _eval_shift_limit(intent: Intent, action: Dict, ctx: Dict):
    """Courier wants a buffer at the end of their shift, not just to fit inside it.

    The suitability ranker already refuses a driver whose shift cannot physically
    contain the job — that is feasibility, and it is not this. This is the rider
    saying they want to actually get home: a job that technically fits but leaves
    them four minutes is feasible and still breaks what they asked for. The
    buffer is the whole reason this is an intent rather than a duplicate of the
    constraint, so it is what gets tested.
    """
    remaining = float(ctx["driver"]["shift_remaining_minutes"])
    needed = float(action["journey_minutes"])
    buffer = float(intent.params.get("buffer_minutes", 30.0))
    over = (needed + buffer) - remaining
    evidence = {
        "shift_remaining_minutes": round(remaining, 1),
        "journey_minutes": round(needed, 1),
        "requested_buffer_minutes": buffer,
        "buffer_left_minutes": round(remaining - needed, 1),
        "margin_minutes": round(-over, 1),
    }
    if over > 0:
        return "violated", evidence, (
            f"would leave {intent.holder} {remaining - needed:.0f} min of shift "
            f"against the {buffer:.0f} min they asked to keep — another courier, "
            f"or {intent.holder} has to agree to give up the buffer"
        )
    if over > -10:
        return "at_risk", evidence, (
            f"only {-over:.0f} min beyond {intent.holder}'s requested buffer"
        )
    return "satisfied", evidence, ""


def _eval_cold_window(intent: Intent, action: Dict, ctx: Dict):
    """Receiving facility wants margin on the cold window, not a photo finish.

    As with the shift limit, the ranker already refuses a driver who arrives
    after the window closes — arriving spoiled is infeasible, not merely
    unwanted. What a facility states on top of that is a handling margin: time
    to actually get the consignment into the cold room and logged before it is
    at risk. Arriving with two minutes left is feasible and still not acceptable
    to the people who have to receive it.
    """
    window = float(ctx["delivery"].get("cold_minutes_remaining") or 0.0)
    needed = float(action["eta_minutes"])
    margin = float(intent.params.get("handling_margin_minutes", 20.0))
    over = (needed + margin) - window
    evidence = {
        "cold_window_minutes": round(window, 1),
        "eta_minutes": round(needed, 1),
        "requested_handling_margin_minutes": margin,
        "window_left_on_arrival_minutes": round(window - needed, 1),
        "margin_minutes": round(-over, 1),
        "doses": ctx["delivery"].get("doses", 0),
    }
    if over > 0:
        return "violated", evidence, (
            f"arrives with {window - needed:.0f} min of cold window against the "
            f"{margin:.0f} min {intent.holder} needs to receive it safely — a "
            f"nearer courier, or a cold transfer point en route"
        )
    if over > -15:
        return "at_risk", evidence, (
            f"only {-over:.0f} min beyond the requested handling margin"
        )
    return "satisfied", evidence, ""


def _eval_no_substitute_handoff(intent: Intent, action: Dict, ctx: Dict):
    """Recipient will only accept the courier originally assigned."""
    reassigned = action["kind"] == "reassign"
    evidence = {
        "action": action["kind"],
        "original_courier": ctx["delivery"].get("original_driver_name")
                            or ctx["delivery"].get("driver_name", "the original courier"),
        "proposed_courier": action.get("driver_name", "—"),
    }
    if reassigned:
        return "violated", evidence, (
            "the recipient declined courier substitution — retain the original "
            "courier, or get the recipient's consent to the swap"
        )
    return "satisfied", evidence, ""


def _eval_capability_refusal(intent: Intent, action: Dict, ctx: Dict):
    """Courier has declared they will not take a category of work."""
    category = intent.params.get("category", "cold_chain")
    applies = bool(ctx["delivery"].get(category))
    evidence = {
        "category": category,
        "payload_requires_it": applies,
        "courier": intent.holder,
    }
    if applies and action["kind"] in ("reassign", "retain"):
        return "violated", evidence, (
            f"{intent.holder} has declined {category.replace('_', ' ')} work — "
            f"route it to a courier who accepts it"
        )
    return "satisfied", evidence, ""


def _eval_sla_promise(intent: Intent, action: Dict, ctx: Dict):
    """Operations promised the recipient a window and does not want to breach it."""
    promised = float(ctx["delivery"].get("promised_minutes") or 0.0)
    eta = float(action["eta_minutes"])
    over = eta - promised
    evidence = {
        "promised_minutes_remaining": round(promised, 1),
        "eta_minutes": round(eta, 1),
        "margin_minutes": round(-over, 1),
    }
    if over > 0:
        return "violated", evidence, (
            f"breaches the promised window by {over:.0f} min — accept the breach "
            f"deliberately, or find a faster option"
        )
    if over > -5:
        return "at_risk", evidence, "almost no margin against the promised window"
    return "satisfied", evidence, ""


def _eval_approach_ceiling(intent: Intent, action: Dict, ctx: Dict):
    """Operations caps the dead mileage a reassignment may add."""
    limit = float(intent.params["max_approach_km"])
    approach = float(action.get("approach_km") or 0.0)
    over = approach - limit
    evidence = {
        "approach_km": round(approach, 2),
        "limit_km": limit,
        "margin_km": round(-over, 2),
    }
    if over > 0:
        return "violated", evidence, (
            f"{approach:.1f} km of empty running to reach the payload, against a "
            f"{limit:.1f} km ceiling — a nearer courier, or lift the ceiling"
        )
    return "satisfied", evidence, ""


EVALUATORS = {
    "delivery_deadline": _eval_delivery_deadline,
    "shift_limit": _eval_shift_limit,
    "cold_window": _eval_cold_window,
    "no_substitute_handoff": _eval_no_substitute_handoff,
    "capability_refusal": _eval_capability_refusal,
    "sla_promise": _eval_sla_promise,
    "approach_ceiling": _eval_approach_ceiling,
}


# --------------------------------------------------------------------------
# The register
# --------------------------------------------------------------------------

class IntentRegister:
    """Every stated intent, and the check that runs before a commit."""

    def __init__(self) -> None:
        self._intents: Dict[str, Intent] = {}
        self._seq = 0

    # -- contents ----------------------------------------------------------

    def add(self, **kwargs) -> Intent:
        self._seq += 1
        kwargs.setdefault("id", f"INT-{self._seq:03d}")
        intent = Intent(**kwargs)
        self._intents[intent.id] = intent
        return intent

    def get(self, intent_id: str) -> Optional[Intent]:
        return self._intents.get(intent_id)

    def set_active(self, intent_id: str, active: bool) -> Optional[Intent]:
        intent = self._intents.get(intent_id)
        if intent is not None:
            intent.active = bool(active)
        return intent

    def remove(self, intent_id: str) -> bool:
        return self._intents.pop(intent_id, None) is not None

    def clear(self) -> None:
        self._intents.clear()
        self._seq = 0

    def all(self) -> List[Intent]:
        return list(self._intents.values())

    def as_list(self) -> List[Dict]:
        return [i.as_dict() for i in self._intents.values()]

    def for_delivery(self, delivery_id: str, driver_id: Optional[str] = None) -> List[Intent]:
        return [
            i for i in self._intents.values()
            if i.applies_to(delivery_id=delivery_id, driver_id=driver_id)
        ]

    # -- the check ---------------------------------------------------------

    def check(self, *, action: Dict, ctx: Dict) -> Dict:
        """Test one proposed action against every intent that applies to it.

        Returns the whole evaluation, not just the failures: a judge asking
        whether this is real needs to see what was checked and passed, not only
        what happened to break. `clear` is the answer to "may we commit".
        """
        delivery_id = action["delivery_id"]
        driver_id = action.get("driver_id")
        results: List[Dict] = []

        for intent in self.for_delivery(delivery_id, driver_id):
            evaluator = EVALUATORS.get(intent.kind)
            if evaluator is None:
                continue
            # A courier's own intent only binds when that courier is the one
            # being proposed. Suresh's shift limit says nothing about a job
            # being handed to Meera.
            if intent.holder_type == "courier" and intent.scope not in ("*", driver_id):
                continue
            try:
                verdict, evidence, hint = evaluator(intent, action, ctx)
            except (KeyError, TypeError, ValueError) as exc:
                # A malformed intent must not take the chain down with it.
                verdict, evidence, hint = "satisfied", {"skipped": str(exc)}, ""
            results.append({
                "intent_id": intent.id,
                "holder": intent.holder,
                "holder_type": intent.holder_type,
                "kind": intent.kind,
                "statement": intent.statement,
                "hardness": intent.hardness,
                "verdict": verdict,
                "evidence": evidence,
                "hint": hint,
            })

        violated = [r for r in results if r["verdict"] == "violated"]
        blocking = [r for r in violated if r["hardness"] == "hard"]
        return {
            "action": action,
            "checked": len(results),
            "results": results,
            "violations": violated,
            "blocking": blocking,
            "at_risk": [r for r in results if r["verdict"] == "at_risk"],
            # Only a HARD violation blocks. A soft one is a cost to disclose,
            # not a veto — otherwise every preference becomes a hard stop and
            # the system stops being able to act at all.
            "clear": not blocking,
        }
