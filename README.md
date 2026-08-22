# AutoFleet AI

[![tests](https://github.com/Himanshi314/AUTOFLEET/actions/workflows/tests.yml/badge.svg)](https://github.com/Himanshi314/AUTOFLEET/actions/workflows/tests.yml)

**Autonomous last-mile disruption resolution.** When a delivery breaks — courier
breakdown, nobody home, wrong address, gridlock, cold chain slipping — a chain of
specialised agents wakes on the event and resolves it end to end. Nobody is
prompted. No coordinator is involved.

```bash
python server.py
# → http://127.0.0.1:8600
```

Runs on the Python **standard library alone**. No build step, no `npm install`,
no database, no agent framework, and the page makes **zero external network
requests**.

---

## The problem

> It's 7pm. Arjun is 3 km from Rohan's flat with a parcel. His bike dies.
>
> Today: Arjun calls the hub. The coordinator is on another call. Eight minutes
> pass. They work down a list of riders — there's one 600 m away, but they don't
> know that. At 7:40 the delivery window closes. The parcel goes back to the
> warehouse and comes out again tomorrow: a second trip, an annoyed customer, and
> Arjun loses the earnings for a delivery he didn't complete.
>
> **Time to fix: ~20 minutes. Time available: ~8.** That gap is the product.

Route optimisers plan the route. Dispatch systems assign the job. Neither has a
layer that **detects a problem and fixes it without a human touching it.**

**What this is not:** not route planning, not initial dispatch, not demand
forecasting. Only the 10–20 minutes *after* the plan has already broken.

---

## Architecture

The headline is not the agent chain — it's that **severity decides how much
intelligence the incident gets.**

```
  telemetry event  (or the autonomous watchdog fires on predicted risk)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │  DETERMINISTIC MODELS  — free, instant       │
  │  · disruption risk score + contributions     │
  │  · route alternates from real coordinates    │
  │  · hard constraints + driver ranking         │
  └──────────────────────┬───────────────────────┘
                         ▼
  ┌──────────────────────────────────────────────┐
  │  ROUTER  (autofleet/routing.py) — no AI      │
  │  decides which roles this incident deserves  │
  └──────────────────────┬───────────────────────┘
                         ▼
   🧭 Risk → 👤 Customer → 📣 Communication →
            🔄 Resource → 🚚 Delivery → 🧠 Coordinator
                         │
                         ▼
     fleet state changes: driver reassigned, courier
     released with support, ETA updated, impact logged
```

### The six agents

Each owns exactly one decision and sees every prior decision. Names match the
round-1 pitch deck.

| # | Agent | Owns |
|---|---|---|
| 1 | 🧭 **Risk** | How severe this is, and what kind of problem — its assessment constrains everyone downstream |
| 2 | 👤 **Customer** | What we ask of the recipient (delay, new slot, safe drop, collection) |
| 3 | 📣 **Communication** | The message that actually goes out — channel and timing |
| 4 | 🔄 **Resource** | Which named driver takes the job |
| 5 | 🚚 **Delivery** | Original courier's status, field support and earnings protection |
| 6 | 🧠 **Coordinator** | The final authoritative resolution |

**Order is deliberate.** Risk goes first because you can't decide what to tell
the recipient until you know whether this is a recoverable delay or a hard
failure. Coordinator goes last because it's the only agent that has seen all five.

They are **six roles, not six processes** — stateless, ~290 tokens of system
prompt each, sharing no memory. What carries forward is the previous agents'
conclusions, injected as text.

### The router — "relevant agents activated", literally

Every input the router uses is known **before any model call**, so routing is free:

| Situation | Roles that run | AI calls |
|---|---|---|
| Internal-only fix, ETA barely moves | none — the models resolve it outright | **0** |
| Recipient's expectations change, courier keeps the job | Risk → Customer → Communication → Coordinator | 4 |
| Courier disabled, or a better driver now outranks them | all six | 6 |
| Payload not deliverable — replacement from the depot | all six | 6 |
| No eligible driver at all | none — **escalates to a human** | **0** |

An ETA shift counts as significant above `max(5 min, 20% of current ETA)` — six
minutes on a 70-minute run is noise; six on a 12-minute run is most of the journey.

**Measured across all 28 disruption × delivery combinations: 29% full chain, 61%
partial, 11% resolved with zero AI calls.** That cuts blended inference cost from
~$0.068 to ~$0.009 per incident — about **7×** — and every router improvement is a
permanent gain, so the system gets *cheaper to run the better it gets*.

### The agents never do arithmetic

Two interpretable models do the quantitative work; the agents receive the results
and make the judgement call.

- **`disruption-risk-v1`** — logistic over 7 normalised features (congestion,
  address confidence, recipient absence history, vehicle health, driver fatigue,
  weather, schedule pressure). Predicts failure probability so the system can act
  *before* a delivery fails.
- **`reassignment-suitability-v1`** — **hard constraints first and absolute**
  (cold-chain capability, shift time remaining, capacity, payload size, cold-chain
  deadline), then a weighted ranking. The Resource Agent receives the ranked
  candidates *with the feature contributions that produced each score*.

Both are linear by design: every score decomposes into per-feature contributions
that the dashboard renders, so "why this driver" is a real attribution rather than
a claim. **Both are hand-calibrated on domain priors, not fitted to historical
data** — the UI says so on the model card.

Distances are real: haversine over actual Bengaluru coordinates × a documented
circuity factor, with ETAs from a congestion-scaled speed model.

---

---

## Intent capture and the pre-commit conflict check

*This is the round-2 capability. Everything else in this README is the MVP it
extends.*

The chain has one moment where reality changes: the Resource agent proposes a
reassignment and `world.apply_resolution()` applies it. This sits in front of
that.

### An intent is not a constraint

The suitability ranker already refuses a courier who is off shift, at capacity,
lacks a cold box, or cannot beat the cold window. Those are facts about the
world. An **intent** is a goal a named party *stated*, in their own words, which
they own and can withdraw — and two of them can be irreconcilable in a way no
capability check ever is. The recipient wants it before six; the courier's shift
ends at five forty. Nobody is wrong. Something has to give, and a person should
choose which.

That distinction is load-bearing, and it caught a design error mid-build: the
first `shift_limit` and `cold_window` intents simply duplicated constraints the
ranker already enforced, which would have been a conflict check that could never
find anything. Both are now strictly *stronger* than feasibility:

| intent | the ranker already checks | the intent adds |
|---|---|---|
| `shift_limit` | does the job fit inside the shift at all | the rider asked to keep a **30 min buffer** — 50 min of work in a 70 min shift is feasible and still breaks what they asked for |
| `cold_window` | does it arrive before the window shuts | the facility needs **20 min of handling margin** — arriving with two minutes left is feasible and still not acceptable to the people receiving it |

Seven kinds in total: recipient deadline, no-substitute handoff, shift buffer,
cold handling margin, declared refusal, SLA promise, empty-running ceiling.

### Where the check runs

1. **Before anything is proposed**, every shortlisted courier is screened against
   every applicable intent, and the conflicts go into the Resource agent's prompt
   so it can choose around them and say why.
2. **Immediately before commit**, the chosen action is re-checked — because a
   model given the option to override a stated constraint sometimes takes it.

A **hard** violation blocks. A **soft** one is a cost that gets disclosed, not a
veto; otherwise every preference becomes a hard stop and the system can no longer
act at all.

### What happens on a conflict

Substitute the best remaining option that breaks nothing, walking the ranking in
order. If no option is clean, **commit nothing and escalate** — recorded as a
human intervention, so the autonomy figure on the dashboard stays honest.

A human then gets four actions, derived from the conflict rather than a fixed
menu: override a specific intent, keep the original courier, extend the promised
window, or cancel. Overriding or rescheduling changes the *inputs* and the chain
**re-runs**; a person withdrawing a constraint is not the same as a person
picking the courier. Every decision is recorded with actor, clock and — for an
override — the withdrawn statement by name.

### State exposed, because the brief asked for functional rather than cosmetic

```
GET  /api/intents          the whole register, plus the clock its deadlines read against
POST /api/intents/toggle   withdraw or restore one intent
GET  /api/decisions        pending decisions with their options, plus the decision trail
POST /api/decisions/resolve  apply one, attributed
SSE  intent_check          every option x every intent, INCLUDING what passed
SSE  intent_gate           what was blocked, the arithmetic, and what was done about it
```

Every conflict reports the figures it was derived from — shift remaining against
journey length, projected arrival against the stated cutoff — so a reader can
check the verdict instead of trusting it. A conflict without arithmetic is an
assertion.

**The demonstration is a toggle.** Same incident, one intent withdrawn, different
courier committed:

```
intent binding    -> ranker wanted Meera Joshi, gate fired, committed Suresh Kumar
intent withdrawn  -> ranker wanted Meera Joshi, gate quiet, committed Meera Joshi
```

## Humanitarian mode

Toggle the header switch. Same agents, same models, same ledger — the payload and
the objective change.

| | Commercial | Humanitarian |
|---|---|---|
| Payload | Parcels, e-waste | Vaccine doses, whole blood, insulin, anti-venom |
| Destination | Urban addresses | Real primary health centres and district hospitals |
| Binding constraint | Customer convenience | **Cold-chain window — a hard constraint** |
| Coordinator reports | ETA + avoided redelivery | **Doses preserved** |

Cold chain is enforced absolutely: no cold box → not a candidate; arrives past the
window → not a candidate at any score. Verified — a 12-minute window yields zero
eligible drivers and correctly **escalates**.

The argument it makes: in a metro there *is* a coordinator to escalate to. In rural
districts, disaster zones, and the places where a failed delivery does real damage,
there is no coordinator — the disruption just becomes a failure. Autonomous
coordination isn't a labour-saving convenience there. It's the only coordination
that exists.

**SDGs:** 13 (climate — avoided vehicle-km), 3 (health — cold-chain integrity),
11.2 (urban air quality), 12.3 (spoilage), 8.8 (driver welfare), 9.4 (resource
efficiency).

---

## Autonomous mode

Arm the header toggle and stop touching it. A **server-side** watchdog watches the
risk model; when a delivery crosses the threshold it infers the disruption from the
dominant risk factor and fires the chain itself.

Verified run: fired at 20.3s when D-102 crossed 0.680, dominant factor "schedule
pressure", resolved in 3.6s. The log reads `self-triggering chain, no human input`.

This runs server-side over the shared event stream — not a browser timer. That
distinction is the whole argument for it being agentic.

---

## Honesty about the numbers

Every impact figure is an **estimate built from documented factors**, and the
dashboard ships the derivation. Click **Assumptions & models** to see every
emission factor with its source, the circuity factor, the redelivery-trip fraction,
and both model cards with weights and caveats.

Deliberate choices:

- The redelivery round trip is discounted to **80%** — some retries ride an
  existing route rather than being dispatched fresh.
- **`Human interventions` is a real counter displayed at zero.** If the chain can't
  resolve an incident it **escalates**, says so on screen, and does *not* count it
  as a success.
- **The ETA usually rises slightly on reassignment** (19 → 21 min), because the
  replacement must collect the payload from where the breakdown happened. The map
  draws both legs so the picture and the number always agree. Faking an improvement
  would be easy; the real argument is that the alternative was a *failed* delivery,
  not a 19-minute one.

---

## Running it

```bash
python server.py                 # http://127.0.0.1:8600
python server.py --port 9000
```

Windows: double-click `run.bat`.

| Mode | How | Behaviour |
|---|---|---|
| **Live** | `ANTHROPIC_API_KEY` (env or copy `.env.example` → `.env`) + `pip install anthropic` | Agents stream from **Claude Opus 5**; text types into each card as the model generates. Badge: `LIVE · claude-opus-5` |
| **Simulated** | nothing needed | Same chain, same models, same router — agent text is deterministic prose derived from real computed state. Every card labelled `simulated` |

Simulated mode exists so the demo cannot die on a flaky network — **not** to pass
canned text off as model output. The labelling is unconditional.

### The chain always terminates

Three layers, so an incident can never hang:

| Layer | Guard |
|---|---|
| Per call | 25s timeout, 1 retry |
| Per chain | 45s budget — past it, agents use their deterministic fallback |
| Per incident | worker frees any delivery left mid-resolution |

Worst case **~50s, bounded.** Verified by injecting a model that hangs 20s per
call: the chain finished in 20s instead of 100s, all agents completed, and the
resolution was real. **The language layer is not load-bearing for the resolution** —
a stalled model costs the prose, never the outcome.

---

## Demo script

1. **Open the dashboard.** Four live deliveries, a fleet map from real
   coordinates, a live failure-risk score per delivery with the autonomous trigger
   threshold marked.
2. **Click `🔧 Vehicle Breakdown` on D-102.** The router card appears first showing
   **FULL CHAIN · 6/6 roles** and why. Then six agent cards stream in, with the
   model outputs interleaved where the agents consume them. A green card shows *why*
   Suresh Kumar won, by feature contribution. D-102 flips to **Reassigned**, the map
   draws the handover, Arjun turns red, the counters tick, and a banner reads
   **Resolved autonomously** in ~4–5s.
3. **Click `⚡ Conflicting Assignment` on D-104.** Router says **NO AGENTS
   NEEDED** — `deterministic` path, 0/6 agents, 6 model calls avoided. *This is the
   routing being visible.*
4. **Reset, then click `🔧 Vehicle Breakdown` on D-104.** *The round-2 beat.* The
   intent check runs before anything is proposed and reports `3 stated intents
   checked against 2 options · 0 clear, 2 blocked` — both couriers are 17.68 km from
   the payload against Operations' 8 km ceiling. Nothing is committed. The amber
   **needs a decision** panel appears with the conflict, the arithmetic and the
   options actually open. Click **Override Operations's intent** and the chain
   re-runs with the ceiling withdrawn. `Human interventions` ticks to **1**.
5. **Arm `Autonomous`** and stop touching it. The watchdog fires on its own — on
   real risk, roughly every six or seven minutes, so arm it early and let it land.
6. **Switch to `Humanitarian`.** Trigger `🌡️ Cold Chain At Risk` and watch drivers
   without a cold box get excluded by hard constraint before any scoring.
7. **Open `Assumptions`** when someone asks where the numbers came from.

Every step above was verified against the live build. Steps 2, 3 and 4 are
deterministic after a `Reset`:

| trigger | router | outcome |
|---|---|---|
| D-102 · Vehicle Breakdown | full chain, 6/6 | resolves to Suresh Kumar |
| D-102 · Recipient Not Home | partial chain, 4/6, 2 saved | resolves to Arjun Singh |
| D-104 · Conflicting Assignment | deterministic, 0/6, 6 saved | resolves to Kavya Reddy |
| D-104 · Vehicle Breakdown | full chain | **escalates** on the approach ceiling |

---

## Layout

```
server.py              stdlib HTTP + one SSE broadcast channel + telemetry
                       simulator + autonomous watchdog + incident worker
autofleet/
  routing.py           the severity router — decides which roles run (no AI)
  agents.py            the six-agent chain
  scoring.py           the two interpretable models
  world.py             fleet state, both scenarios, 8 disruption types
  geo.py               real coordinates, haversine, road graph, ETA model
  impact.py            emission factors + named sources, the impact ledger
  llm.py               Claude Opus 5 streaming + deterministic fallback
web/                   dashboard — self-contained, no external requests
```

Worth knowing:

- **One SSE channel** carries everything — which is why the watchdog can push a
  chain the browser never asked for.
- **Incidents are queued and serialised** on one worker thread, so rapid clicks
  don't interleave. A demo choice, not an architectural limit.
- **Chains carry a world generation** — reset or scenario-switch mid-incident
  aborts cleanly with no partial decision applied.
- **The dependency order is a DAG, not a cycle.** Risk → Customer →
  Communication → Resource → Delivery → Coordinator. Each role needs what came
  before and nothing after, which is why this is a pipeline and there is nothing
  to negotiate.

---

## Tests

```bash
python run_tests.py            # all 116
python run_tests.py world      # one suite: routing | intent | world | agents | server
```

No network, no API key, no install step — every suite forces the deterministic
model path, so a full run costs nothing and works offline. That is also why CI
needs no secrets.

| suite | tests | what it guards |
|---|---|---|
| `routing` | 8 | the severity router's decision table |
| `intent` | 42 | conflict evaluators, the pre-commit gate, decisions, register lifecycle |
| `world` | 24 | delivery lifecycle, ETA from geometry, the clock, drift, escalation slots |
| `agents` | 20 | fact-checker (including typographic dashes), prompt budget, routing-efficiency ledger |
| `server` | 22 | the HTTP layer, plus a regression for every defect found by attacking it |

Most of these assert something that was once live and wrong *while looking
right*: a risk score that ratcheted to "critical" on nothing but elapsed time, a
hardcoded `"human_interventions": 0` under a dashboard tile that headlined it, an
ETA parked at 1 min for ever, a JSON array body that killed the request thread.
A green run does not prove the dashboard looks correct — it proves the failures
that were invisible stay fixed.

## Docs

| File | What's in it |
|---|---|
| `CLAUDE.md` | Full handover: architecture, every measured number, rules not to break |
| `TEAM-PLAN.md` | The idea, a plain-language tech explainer, per-track tasks |
| `BUSINESS-MODEL.md` | Pricing logic, unit economics, go-to-market |

---

Built by **Team 404**.
