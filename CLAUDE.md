# AutoFleet AI — project context

> Handover document. If you are an AI assistant picking up this project, read this
> file first. It contains the idea, the honest positioning, the architecture, every
> measured number, and the rules not to break. Last verified 2026-08-07.

**One sentence:** When a delivery goes wrong, a human has to fix it, and while
they're fixing it the delivery fails — AutoFleet AI fixes it immediately instead.

**Status:** Working, verified end to end. Built for a hackathon by a 4-person
team. Runs on the Python standard library alone (`python server.py` →
http://127.0.0.1:8600). The `anthropic` package is needed only for live agents;
without a key it runs a labelled deterministic fallback.

---

## 1. The story to tell (memorise this, it is the pitch)

> It's 7pm. Arjun is 3 km from Rohan's flat with a parcel. His bike dies.
>
> Today: Arjun calls the hub. The coordinator is on another call. Eight minutes
> pass. They start working down a list of riders — there's one 600 m away but they
> don't know that. They call a rider who's mid-delivery. They call another.
> Rohan has been told nothing.
>
> At 7:40 the window closes. The parcel goes back to the warehouse and comes out
> again tomorrow — a second trip, a second attempt, an annoyed customer, and Arjun
> loses the earnings for a delivery he didn't complete, through no fault of his own.
>
> **Time to fix: ~20 minutes. Time available: ~8.** That gap is the product.

---

## 2. The eight questions, answered

### 1. What goes wrong, in one sentence?
A delivery already in progress hits a problem — courier's vehicle fails, nobody
home, wrong address, road blocked, payload damaged, cold chain breaking — and it
can no longer complete as planned.

### 2. Who fixes it today, and how long do they take?
A human exception coordinator at the hub, reached by phone. They call around to
find a replacement rider, notify the customer, and update the route. **10–20
minutes minimum per incident**; one coordinator handles roughly 30–50 exceptions
a shift. The delivery window is frequently shorter than the fix takes.

### 3. What does it cost when nobody fixes it in time?
Four costs, by who feels them:
- **Carrier** — a second delivery attempt: another trip, another courier-hour.
  At ₹30–60 revenue per parcel, one failed attempt can wipe out that parcel's
  margin and several others'.
- **Environment** — the redelivery is additional vehicle-km, fuel and congestion.
  Measured in this system for one Bengaluru parcel: **~27 km and ~2.08 kg CO₂e**.
- **Driver** — the completed leg goes unpaid and their reliability score drops,
  for a breakdown they did not cause.
- **Customer** — no delivery, and no information.

In cold chain (vaccines, whole blood, lab samples) the cost is not a retry —
**the payload spoils.** Doses nobody receives.

### 4. What does our system do instead?
Detects the disruption from telemetry (nobody reports it), wakes a chain of up to six
specialist agents (the router decides how many), and resolves it end to end in **~4–5 seconds**: recipient
notified, route assessed, a specific named replacement driver assigned, original
driver marked unavailable with roadside assistance dispatched and earnings
protected, and one authoritative resolution issued. The decision is written back
to fleet state. No human touches it.

### 5. Why can't you just write rules for this?
Because the decisions **constrain each other in a loop**:
- whether you need a new driver depends on whether the customer accepted a safe drop
- which driver you pick depends on how long the detour is
- what you tell the customer depends on which driver you got
- whether the original driver gets support depends on *why* they failed

**Honest limit — state this, don't hide it:** for common cases rules *do* work.
Measured on this fleet, **66% of incidents have one decisively best driver**
(suitability margin ≥ 0.10 over the runner-up). The interdependency only bites in
the tail. So the defensible claim is: **rules handle the head of the
distribution; the agents cover the tail without anyone writing 400 rules.**

### 6. Who would pay for it, and what line on their budget does it reduce?
**Buyer:** Head of Last-Mile / Ops at a 3PL carrier (Delhivery, Ecom Express,
Shadowfax class). Also strong: **diagnostic labs and pharma cold chain** (hard
time-and-temperature limits, high cost per exception), and **enterprise field
service** (appliance repair, telecom installs — ₹500–5,000 jobs, coordination
still done by phone).

**Budget lines reduced:** exception-desk headcount; redelivery fuel and
courier-hours; SLA penalty payouts; written-off spoiled stock in cold chain.

**Weak fit:** quick-commerce (Blinkit/Zepto class) — they already automate rider
reassignment in-house and would build, not buy.

### 7. What does our system refuse to do on its own?
- Any payment action — refunds, credits, compensation
- Cancelling a delivery outright
- Promising the customer something the fleet cannot deliver
- Rerouting regulated payloads (controlled substances, hazmat)
- Anything above a value threshold the operator sets

**Already built:** when no driver passes the hard constraints the system
**escalates to a human and says so on screen**, rather than reporting a false
success. `Human interventions` is a real counter displayed at zero, not decoration.

### 8. What's the weakest part of our idea?
Ranked honestly. Knowing this list is the strongest signal the team understands
the project.

1. **Rules could handle most of it.** Our own measurement says 66% of exceptions
   have an obvious answer. The LLM layer is only justified on the ambiguous tail —
   so the value depends on that tail being large and expensive enough, and we have
   not proven that with real data.
2. **Nothing is trained.** Both models are hand-calibrated, not fitted. The
   dashboard says so. It means the risk scores are not calibrated probabilities.
3. **We have never seen the real problem.** No team member has watched a real
   coordinator work. The exception taxonomy and the 10–20 minute figure come from
   the brief, not from observation. *Fixing this is the highest-value action
   available: talk to one delivery rider for ten minutes.*
4. **Trust is the real barrier, not technology.** No ops director hands over
   customer comms on day one. Real adoption needs shadow → assisted → guarded →
   autonomous, and we have only built the last stage.
5. **The agent chain is not defensible.** An incumbent could rebuild it in a
   weekend. What would actually compound is the resolution-policy library, the
   TMS integrations, and a shadow-mode record proving the decisions hold up —
   none of which we have.

---

## 3. What this is NOT solving

Boundaries are a strength here. Do not let the scope drift.

- ❌ Not route planning — Google Maps and every TMS already do that
- ❌ Not initial dispatch or assignment — dispatch systems do that
- ❌ Not demand forecasting or fleet optimisation
- ✅ **Only** the 10–20 minutes *after* the plan has already broken

---

## 4. How to run

```bash
python server.py            # http://127.0.0.1:8600
python server.py --port 9000
```

Windows: `run.bat`. Stdlib only — no build step, no npm, no CDN, and the page
makes **zero external network requests** (verified).

| Mode | How | Behaviour |
|---|---|---|
| **Live** | `ANTHROPIC_API_KEY` in env or `.env` (copy `.env.example`), plus `pip install anthropic` | Agents stream from **Claude Opus 5**. Header reads `LIVE · claude-opus-5`. |
| **Simulated** | No key needed | Same chain, same models, but agent text is deterministic prose derived from real computed state. Every card labelled `simulated`; header reads `SIMULATED AGENTS`. |

Simulated mode exists so a demo cannot die on a flaky network — **not** to pass
canned text off as model output. The labelling is unconditional and must stay that way.

⚠️ **The live path is written but UNVERIFIED** — it was built to the current Opus 5
contract (streaming, `effort` in `output_config`, no `temperature`/`top_p`,
`refusal` stop-reason handling) but no API key was available during development.
Test it before relying on it.

---

## 5. Architecture

```
server.py              stdlib HTTP + ONE SSE broadcast channel + telemetry
                       simulator thread + autonomous watchdog + incident worker
autofleet/
  geo.py               real Bengaluru coords, haversine, road graph, ETA model
  impact.py            emission factors + named sources, the impact ledger
  scoring.py           the two interpretable models
  world.py             fleet state, both scenarios, disruption catalogue + effects
  llm.py               Claude Opus 5 streaming + deterministic fallback
  agents.py            the five-agent chain
web/
  index.html           dashboard shell
  styles.css           self-contained (no external fonts / CDN)
  app.js               SSE client, SVG map, agent feed
```

Design decisions that matter:

- **One SSE channel** carries everything. This is why the autonomous watchdog can
  push a chain the browser never asked for — that's what makes the autonomy real
  rather than a client-side timer.
- **Incidents are queued and serialised** on one worker thread. Rapid clicks don't
  interleave two chains. *This is a demo choice, not an architectural limit* —
  production swaps the thread for a pool.
- **Chains carry a world generation.** If the world is reset or the scenario
  switched mid-incident, the chain aborts cleanly at the next stage boundary and
  applies no partial decision.

---

## 6. The severity router (`autofleet/routing.py`)

Decides which roles an incident deserves, **before any model call**. No AI in this
module — if/else over numbers already computed.

| Condition | Path | Roles |
|---|---|---|
| No eligible driver | escalate | 0 — handed to a human |
| Courier disabled, or replacement stock needed | full chain | 6 |
| A better driver now outranks the incumbent | full chain | 6 |
| Internal-only fix, ETA shift insignificant, risk calm | deterministic | **0** |
| Otherwise (recipient's expectations change) | partial chain | 4 |

An ETA shift is significant above `max(5 min, 20% of current ETA)` — six minutes on
a 70-minute run is noise, six on a 12-minute run is most of the journey. Both
figures are assumptions.

**Measured distribution** across all 28 disruption × delivery combinations:
**29% full · 61% partial · 11% deterministic.** Do not confuse this with the 66%
ranker-margin figure in section 2 — different measurement, different meaning.

## 6b. The six agents

Six **roles**, not six processes. Stateless. Each is ~290 tokens of system
prompt plus a structured input. Nothing is instantiated or persisted per incident.

| # | Agent | Owns |
|---|---|---|
| 1 | 🧭 Risk | How severe this is, and what kind of problem |
| 2 | 👤 Customer | What we ask of the recipient |
| 3 | 📣 Communication | The message that actually goes out |
| 4 | 🔄 Resource | Which named driver takes the job |
| 5 | 🚚 Delivery | Original courier's status, support, earnings |
| 6 | 🧠 Coordinator | The final authoritative resolution |

Names match the round-1 pitch deck. The Reallocation Agent's `PICK:` parsing and
fallback-to-top-ranked behaviour is unchanged, now on the Resource Agent.

**Order is deliberate.** Customer goes first because its commitment constrains
everything downstream (a safe-drop authorisation changes what a reassignment must
achieve). Coordinator goes last because it is the only agent that has seen all four.

**The agents never do arithmetic.** Deterministic models compute the numbers and
are injected as tool results immediately before the agent that consumes them:

```
1. Customer Agent
   ├─ [model] route.alternates ....... real distances, added minutes
2. Route Agent
   ├─ [model] reassignment.rank ...... hard constraints + ranked drivers
3. Reallocation Agent
   ├─ [attribution] why this driver won
4. Driver Agent
   ├─ [ledger] impact of this resolution
5. Coordinator Agent
```

The Reallocation Agent must emit `PICK: <driver_id>` as its first line. This is
parsed and **validated against the eligible set**; an unparsable or ineligible
pick falls back to the top-ranked candidate and logs that it did so.

---

## 7. The two models (this is the ML story)

Both live in `autofleet/scoring.py`. Both are **linear and interpretable by
design** — every score decomposes into per-feature contributions, which the UI
renders. That decomposition is load-bearing for operator trust; do not trade it
away for a couple of points of AUC.

### `disruption-risk-v1` — logistic, 7 features
Predicts probability an in-flight delivery fails, so the system can act *before*
it does. `BIAS = -4.60`.

| Feature | Weight |
|---|---|
| recipient_absence_rate | 2.60 |
| address_uncertainty | 2.35 |
| vehicle_health_risk | 2.10 |
| traffic_index | 1.95 |
| schedule_pressure | 1.70 |
| driver_fatigue | 1.45 |
| weather_risk | 1.15 |

Bands: `critical ≥ 0.68` (aligned with the autonomous trigger, so the band a
viewer sees is the line the system acts on), `elevated ≥ 0.42`, `watch ≥ 0.15`.

### `reassignment-suitability-v1` — weighted linear utility, 7 features
**Hard constraints run first and are absolute** (status, cold-chain capability,
capacity, payload size, shift time remaining, cold-chain deadline). Only survivors
get scored. Weights sum to 1.0:

| Feature | Weight |
|---|---|
| proximity | 0.34 |
| eta_fit | 0.20 |
| reliability | 0.15 |
| load_headroom | 0.11 |
| shift_headroom | 0.09 |
| capability_margin | 0.07 |
| zone_familiarity | 0.04 |

### Nothing here is trained
Both weight sets are **hand-calibrated on domain priors, not fitted to historical
data.** The model cards in the UI say this. Do not claim otherwise.

**What would be trained, in order:**
1. **Risk model** — supervised binary classification, labels are free (did the
   delivery fail on first attempt?). ~10k–50k historical deliveries. Gives
   calibrated probabilities, so the threshold can be set on expected cost instead
   of an arbitrary 0.68.
2. **Eval harness** — build before anything else. Per-role metrics differ. The
   **Coordinator hallucination check is the highest-value piece and is
   automatable**: assert every number in its summary appears in its input.
3. **Ranker** — learning-to-rank, with a selection-bias trap: you only observe
   outcomes for drivers actually chosen. Needs inverse propensity weighting or
   randomised exploration.
4. **Fine-tuning / distillation** — skip. Premature, and the cheaper wins
   (triage, payload trimming, model tiering) are already measured.

The roles improve via **shadow mode**: system decides, acts on nothing, logs its
decision beside the human's. Each disagreement either exposes a missing
consideration in a role prompt or produces evidence for the sales conversation.

---

## 8. Impact accounting — every number is an estimate with a source

The causal claim is narrow and must stay narrow:

> A disruption resolved while the courier is still in the field completes the
> delivery on the **first attempt**, so the redelivery trip never happens. That
> avoided trip is the km and the CO₂e. Nothing else is claimed.

Constants in `autofleet/impact.py`, all surfaced in the UI's Assumptions drawer:

| Constant | Value | Note |
|---|---|---|
| Circuity factor | 1.35× | straight-line → on-road, dense metro. Assumption. |
| Redelivery trip fraction | 80% | deliberately conservative — some retries ride an existing route |
| Coordinator time per incident | 14 min | midpoint of the stated 10–20 min window |
| 2-wheeler petrol | 0.0757 kg CO₂e/km | DEFRA/BEIS range. **Verify against source.** |
| Refrigerated van | 0.2645 kg CO₂e/km | diesel van + ~25% cold-chain uplift (the uplift is an assumption) |
| Free-flow speed | 22 km/h urban / 38 km/h corridor | scaled down up to 45% by congestion index |
| Service time | 6 min | doorstep/handover, added to every ETA |

**The ETA usually goes *up* slightly on reassignment** (D-102: 19 → 21 min)
because the replacement must collect the payload from where the bike failed. The
map draws both legs so path and number always agree. **Do not fake an
improvement.** The value isn't beating the original ETA — the original driver
cannot continue at all. The alternative was a *failed* delivery, not a 19-minute one.

---

## 9. Two scenarios, one engine

Same agents, same models, same ledger. Only payload and objective change — that
shared-engine property is the point.

| | Commercial | Humanitarian |
|---|---|---|
| Payload | Parcels, e-waste | Vaccine doses, whole blood, insulin, anti-venom |
| Destination | Urban Bengaluru addresses | Real PHCs / district hospitals |
| Binding constraint | Customer convenience | **Cold-chain window — a hard constraint** |
| Coordinator reports | ETA + avoided redelivery | **Doses preserved** |
| Impact tile swap | Failed attempts prevented | Doses preserved |

Cold chain is enforced as a *hard constraint*: no cold box → not a candidate;
arrives past the window → not a candidate at any score. **Verified:** a 12-minute
window yields zero eligible drivers and correctly escalates.

Disruption catalogue (`world.py → DISRUPTIONS`): `bike_breakdown`,
`customer_not_home`, `wrong_address`, `traffic_gridlock`, `package_damaged`,
`cold_chain_breach` (humanitarian only).

---

## 10. Autonomous mode — the genuine agentic proof

Arm the header toggle and stop touching it. A **server-side** watchdog on the
simulator thread watches the risk model; when a delivery crosses
`AUTONOMOUS_THRESHOLD = 0.68` it infers the disruption from the dominant risk
factor and fires the chain itself.

**Verified run:** fired at 20.3s when D-102 crossed 0.680, dominant factor
"Schedule pressure" → inferred `traffic_gridlock`, resolved in 3.6s. Log reads
`self-triggering chain, no human input`.

This runs server-side over the shared SSE channel, not as a browser timer. That
distinction is the whole argument for it being agentic.

---

## 10b. Why the chain always terminates

A common question: *what if the agents never reach a conclusion?*

**Structurally it cannot happen.** The chain is five sequential calls, not a loop.
No negotiation, no consensus mechanism, no voting, no agent speaking twice. There
is nothing to deadlock on.

The practical risk is a hung or failing model call, which is bounded in three layers:

| Layer | Mechanism | Guarantee |
|---|---|---|
| Per call | `timeout=25s`, `max_retries=1` on the Anthropic client | one call can't stall for the SDK's 10-minute default |
| Per chain | `CHAIN_BUDGET_SECONDS = 45`, checked before each agent | past budget, agents stop calling the model and use their deterministic fallback |
| Per incident | worker `finally` forces any delivery left in `Resolving` back to `On Route` | controls can never be permanently disabled |

Worst case per incident: **~50 seconds, bounded.** Verified by injecting a model
that hangs 20s per call — the chain finished in 20s instead of 100s, all five
agents completed, and the resolution was real (reassigned, ETA updated, impact
recorded).

**The key architectural property:** the language layer is **not load-bearing for
the resolution.** Hard constraints plus the ranker already produce a complete,
actionable answer, and every agent has a deterministic fallback derived from it.
A stalled or failing model costs the prose and the nuance — never the resolution.

Three distinct terminal outcomes, all visible on screen and all honest:
- **Resolved** — normal path
- **Degraded** — budget spent, resolved from model output without the language layer
- **Escalated** — no driver passes the hard constraints; handed to a human, **not**
  counted as a success

## 11. Global-cause framing (SDGs)

Lead with **13** and **3**. Six SDGs on a slide reads as padding.

- **13** Climate Action — avoided vehicle-km from prevented redeliveries
- **11.2** Sustainable Cities — congestion and urban air quality
- **3** Good Health — cold-chain integrity, rural medicine access (humanitarian mode)
- **12.3** Responsible Consumption — spoilage prevented
- **8.8** Decent Work — driver safety and income protection
- **9.4** Resource-efficient infrastructure

**The strongest line:** in a metro there *is* a coordinator to escalate to. In
rural districts, disaster zones, and the places where a failed delivery does real
damage, there is no coordinator — the disruption just becomes a failure.
Autonomous coordination isn't a labour-saving convenience there. It's the only
coordination that exists.

**Driver welfare (SDG 8.8):** the Driver Agent doesn't just mark the courier
unavailable — it dispatches roadside assistance, protects completed-leg earnings,
and logs no reliability penalty, because the courier didn't cause the breakdown.
On current gig platforms that loss lands on the driver.

---

## 12. Measured numbers (do not re-derive; these are verified)

**Cost / scale**
- Full chain input: **6,120 tokens**. Reallocation agent alone: **3,514 (57%)** —
  it dumps 5 candidates with full feature contributions. **Highest-leverage
  optimisation: trim to top-3 × top-3.**
- ~1,500 output tokens per chain → **~$0.068/incident** at Opus 5 ($5/$25 per MTok)
- 20,000 exceptions/day → **~$1,360/day ≈ $41k/month**. Too expensive untiered.
- With triage (66% deterministic / 26% partial / 8% full) → **~$0.009/incident
  ≈ $180/day.** ~7× cheaper.
- System prompts are ~293 tokens each — **below Opus 5's 512-token minimum
  cacheable prefix**, so prompt caching does not fire. Trim payloads instead.
- Throughput is a non-issue: 20k/day = 0.23/s average, ~1.2/s at evening peak,
  ~4.5s chains → ~6 concurrent chains.

**Triage measurement** (44 incident combinations, seeded fleet — indicative only,
not a production distribution)
- 66% decisive winner (margin ≥ 0.10) → no judgement needed
- 34% thin margin → agents earn their cost
- median margin 0.129

**Demo baseline (commercial, at load)**
| Delivery | ETA | Risk | Band |
|---|---|---|---|
| D-101 | 16 min | 0.15 | watch |
| D-102 | 19 min | 0.55 | elevated |
| D-103 | 46 min | 0.56 | elevated |
| D-104 | 68 min | 0.13 | nominal |

**D-102 vehicle-breakdown reference run:** Suresh Kumar (0.63 km behind Arjun)
selected, suitability 0.758, decisive factor proximity. ETA 19 → 21 min. Risk
0.55 → 0.14. Resolved 4.0–5.0s. Impact: 27.4 km, 2.08 kg CO₂e, 14 coordinator-min.

---

## 13. Hard rules — do not violate

- **Never fabricate or inflate an impact number.** Every factor needs a named
  source in `impact.py` and must appear in the Assumptions drawer.
- **Never remove or weaken the `simulated` labelling.** Fallback text must never
  be presentable as live model output.
- **Never let the map contradict a stated number.** ETAs are derived from
  remaining road distance; the drawn path must be the path the ETA was computed from.
- **`Human interventions` stays a real counter.** If the chain can't resolve
  something it escalates and says so. No false successes.
- **Keep the page self-contained.** No external fonts, CDNs, map tiles, or any
  network request from the browser. (Also: Google Fonts is blocked on the team's
  network.)
- **Keep both models interpretable.** The per-feature contribution breakdown is
  what the UI renders and what earns trust.
- **Don't claim anything is trained.** It isn't.

---

## 14. Gotchas found the hard way

- The LLM stream's terminal event **also carries a `text` key** — test
  `event.get("done")` *before* `"text" in event`, or the summary is mistaken for a
  delta and every agent card renders blank.
- On-route drivers must be positioned **partway along their corridor** (lerp from
  origin to destination by `progress`), not on the destination node — otherwise
  remaining distance reads as zero and the Route Agent reports "0.0 km".
- ETAs must be **derived from geometry at load**, never seeded. A seeded 12-min ETA
  once contradicted a 7 km remaining distance.
- `renderImpact` must rebuild when the tile **key set** changes, not just its
  length — a same-length swap (commercial ↔ humanitarian) otherwise reuses stale
  labels against new values.
- `renderFleet` must **prune cards** for deliveries that no longer exist, or a
  mode switch leaves all 8 on screen.
- Suppress `ConnectionAbortedError`/`ConnectionResetError` at the *server* level
  (`QuietServer.handle_error`) — an SSE client disconnects on every page reload and
  otherwise dumps a traceback wall.
- Windows console: use `python -X utf8` when printing ₹ or emoji.

---

## 15. Known gaps / next work, in priority order

1. **Verify the live Claude path.** Written to spec, never run with a real key.
2. **Triage gate** — route incidents deterministic/partial/full on
   `margin_over_next`; add an "LLM calls saved" tile. Makes the scale story visible.
3. **Coordinator hallucination check** — assert every number in its output appears
   in its input; surface a per-incident "facts verified ✓" badge.
4. **Trim the Reallocation payload** — top-3 candidates × top-3 contributions.
   Cuts chain input ~40%.
5. **Look at the UI with human eyes.** Built and verified structurally (layout
   fits, no overflow, zero external requests) but never screenshotted. Check it on
   the actual presentation projector — dark themes wash out.
6. **Talk to one real delivery rider.** The team has never observed the problem.
7. Model tiering (Haiku on Customer + Driver roles), eval harness, shadow mode.

---

## 16. Team notes

Four people, ~10 days. Tracks are deliberately **file-disjoint** to avoid merge
pain between contributors of similar experience level:

| Track | Files | Must be able to answer |
|---|---|---|
| A · Agents & Pitch | `agents.py`, `llm.py` | "How is this not a chatbot wrapper?" |
| B · Models & Impact | `scoring.py`, `impact.py`, `geo.py` | "Where's the ML? Where do these numbers come from?" |
| C · Frontend & Demo | `web/*` | owns the first 10 seconds + the backup video |
| D · Backend & Reliability | `server.py`, `world.py` | "What happens when it breaks?" |

Whoever owns a track must be able to explain **every line** in it. A judge asking
"why 0.68?" and getting silence ends the demo regardless of how well the code runs.

Integrate on day 6, not day 9. Freeze code on day 9 and rehearse. Record a backup
video of a perfect run — if the network dies on stage, play it and keep talking.

## Tests

    python run_tests.py            # all 116
    python run_tests.py world      # one suite: routing | intent | world | agents | server

No network and no API calls — every suite forces the deterministic model, so a
run costs nothing and works offline. Run it before a demo.

| suite   | what it guards |
|---------|----------------|
| routing | the severity router's decision table |
| intent  | conflict evaluators, the pre-commit gate, decisions, register lifecycle |
| world   | delivery lifecycle, ETA from geometry, the clock, drift, escalation slots |
| agents  | fact-checker (incl. typographic dashes), prompt budget, routing-efficiency ledger |
| server  | HTTP layer, plus a regression for every defect found by attacking it |

Most of these assert something that was once live and wrong *while looking
right* — a risk score that ratcheted to critical on idle time, a hardcoded
"0 human interventions", an ETA parked at 1 min for ever. A green run does not
prove the dashboard looks correct; it proves the quiet failures stay fixed.
