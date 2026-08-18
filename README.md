# AutoFleet AI

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
   NEEDED** — two roles render greyed out with their reason, and `AI calls avoided`
   ticks up. *This is the routing being visible.*
4. **Arm `Autonomous`** and stop touching it. The watchdog fires on its own.
5. **Switch to `Humanitarian`.** Trigger `🌡️ Cold Chain At Risk` and watch drivers
   without a cold box get excluded by hard constraint before any scoring.
6. **Open `Assumptions & models`** when someone asks where the numbers came from.

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

## Docs

| File | What's in it |
|---|---|
| `CLAUDE.md` | Full handover: architecture, every measured number, rules not to break |
| `TEAM-PLAN.md` | The idea, a plain-language tech explainer, per-track tasks |
| `BUSINESS-MODEL.md` | Pricing logic, unit economics, go-to-market |

---

Built by **Team 404**.
