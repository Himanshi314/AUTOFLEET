# AutoFleet AI

**Autonomous last-mile disruption resolution.** Five specialised agents wake the
moment a disruption is detected and resolve it end to end — reassign the driver,
notify the recipient, update the route, protect the original courier — with no
human coordinator in the loop.

```bash
python server.py
# → http://127.0.0.1:8600
```

Runs on the Python standard library alone. No build step, no `npm install`, no
CDN, no external network requests from the page.

---

## The problem

When a last-mile delivery hits a disruption — courier breakdown, recipient not
home, wrong address, gridlock, damaged payload — a human coordinator has to step
in: make calls, find another driver, notify the customer, update the route. That
takes 10–20 minutes, and it is entirely manual.

Route optimisers plan the route. Dispatch systems assign the job. Neither has a
layer that **detects a problem and fixes it without a human touching it.**

## What this is

An event-driven agent chain. It is not a chatbot: nobody prompts it. Telemetry
raises an event, the chain wakes itself, and it produces a concrete real-world
action — a driver is reassigned, a recipient is notified, an ETA changes, a
courier is marked unavailable and sent help.

### The five agents

Each owns exactly one decision and sees every prior agent's decision.

| # | Agent | Owns |
|---|---|---|
| 1 | 👤 **Customer** | What the recipient is told and asked. Goes first because the commitment made here constrains everything downstream. |
| 2 | 📍 **Route** | Route feasibility and the specific minute impact of the alternate it selects. |
| 3 | 🔄 **Reallocation** | Which named driver takes the job. |
| 4 | 🚚 **Driver** | The original courier's status, field support and earnings protection. |
| 5 | 🧠 **Coordinator** | The final authoritative resolution, having seen all four. |

### The agents never do arithmetic

This is the architectural point. Two deterministic models compute the numbers;
the agents receive the results and make the judgement call.

- **`disruption-risk-v1`** — a logistic model over seven normalised features
  (congestion, address confidence, recipient absence history, vehicle health,
  driver fatigue, weather, schedule pressure). Predicts failure probability so
  the system can act *before* a delivery fails. Every score decomposes into
  per-feature contributions, which the dashboard renders.
- **`reassignment-suitability-v1`** — hard constraints first (cold-chain
  capability, shift time remaining, capacity, payload size, cold-chain
  deadline), then a weighted linear utility over seven features. The
  Reallocation Agent is handed the ranked candidates *with the feature
  contributions that produced each score* and must pick one.

Both are linear and interpretable by design: it means every score is auditable
and every "why this driver" is a real attribution rather than a claim. Both are
hand-calibrated on domain priors, **not fitted to historical data** — the
dashboard says so on the model card.

Distances are real: haversine over actual Bengaluru coordinates, inflated by a
documented circuity factor, with ETAs from a congestion-scaled speed model.

---

## Connecting it to a global cause

The link is narrow and causal, not decorative.

> A disruption resolved while the courier is still in the field completes the
> delivery on the **first attempt**, so the redelivery trip never happens. That
> avoided trip is the vehicle-km, the CO₂e and the congestion.

The mechanism *is* the speed. A human coordinator takes 10–20 minutes; by then
the delivery window has closed and the parcel goes back to the depot. The chain
resolves in seconds, so the second trip is never dispatched. Relevant SDGs:
**13** (climate action), **11.2** (sustainable cities, congestion and urban air
quality), **9.4** (resource-efficient infrastructure), **8.8** (decent work —
see driver welfare below).

### Humanitarian mode

Toggle the header switch. Same five agents, same models, same impact ledger —
the payload and the objective change:

|  | Commercial | Humanitarian |
|---|---|---|
| Payload | Parcels | Vaccine doses, whole blood, insulin, anti-venom |
| Destination | Urban addresses | Primary health centres and district hospitals |
| Binding constraint | Customer convenience | **Cold-chain window** — enforced as a hard constraint, so a driver who cannot arrive in time is not a candidate at any score |
| Coordinator reports | ETA and avoided redelivery | **Doses preserved** |

This maps to SDG **3** (access to medicines) and **12.3** (spoilage). The
argument it makes: in a metro there *is* a coordinator to escalate to. In rural
districts, in disaster zones, in the places where a failed delivery does real
damage, there is no coordinator — the disruption just becomes a failure.
Autonomous coordination isn't a labour-saving convenience there. It's the only
coordination that exists.

### Driver welfare

The Driver Agent doesn't just mark the courier unavailable. It dispatches
roadside assistance, protects completed-leg earnings, and logs no reliability
penalty, because the courier didn't cause the breakdown. On current gig
platforms that loss lands on the driver.

---

## Honesty about the numbers

Every impact figure is an **estimate built from documented factors**, and the
dashboard ships the whole derivation. Click **Assumptions & models** in the
header to see: every emission factor with its source, the circuity factor, the
redelivery-trip fraction, the coordinator-minutes figure, and both model cards
with weights and caveats. The impact card in the feed prints the arithmetic
inline, e.g.:

> Depot to destination 17.15 km on-road; a failed attempt costs a round trip,
> discounted to 27.44 km at the redelivery-trip fraction; × 2w_petrol emission
> factor = 2.077 kg CO₂e. All factors are estimates.

Deliberate choices:

- The redelivery round trip is discounted to **80%**, because some retries ride
  along an existing route rather than being dispatched fresh.
- **Human interventions is a real counter, displayed at zero.** If the chain
  can't resolve an incident — no driver passes the hard constraints — it emits
  an **escalation**, says so on screen, and does *not* count it as a success.
- `re-derive each factor against its source for your own fleet, region and grid
  mix before publishing any of these numbers` is printed in the drawer, because
  a factor lifted from a UK dataset is not a Bengaluru measurement.

### The ETA usually goes *up* slightly, and that's the honest result

On a breakdown reassignment D-102's ETA moves from ~19 min to ~21 min, because
the replacement courier has to collect the payload from wherever the bike failed
before delivering it. The map draws both legs, so the path and the number always
agree.

It would be easy to fake an ETA improvement here. The reason the resolution is
valuable is not that it beats the original ETA — the original driver cannot
continue at all. **The alternative was a failed delivery, not a 19-minute one.**
Every ETA on screen is derived from remaining road distance and the live
congestion index, never seeded, so the card and the map cannot disagree.

---

## Running it

```bash
python server.py                 # http://127.0.0.1:8600
python server.py --port 9000     # different port
```

Windows: double-click `run.bat`.

### Live vs simulated agents

| | |
|---|---|
| **Live** | Set `ANTHROPIC_API_KEY` (env var, or copy `.env.example` → `.env`) and `pip install anthropic`. The five agents stream from **Claude Opus 5**; text types into each card token by token as the model generates. Header badge reads `LIVE · claude-opus-5`. |
| **Simulated** | No key needed. The same chain runs, the same models compute, but agent text is deterministic prose derived from the real computed state. Every card is labelled `simulated` and the header badge reads `SIMULATED AGENTS`. |

Simulated mode exists so the demo cannot die on a flaky network — not to pass
canned text off as model output. The labelling is unconditional.

---

## Demo script

1. **Open the dashboard.** Four live deliveries, a fleet map built from real
   coordinates, and a live failure-risk score per delivery with a marker showing
   the autonomous trigger threshold.
2. **Click `🔧 Vehicle Breakdown` on D-102.** The right panel comes alive: five
   agent cards slide in along a chain spine, each streaming its decision, with
   the two model outputs (route alternates, ranked drivers) interleaved where the
   agents consume them. A green attribution card shows *why* Suresh Kumar won.
   The D-102 card flips to **Reassigned**, the map redraws the handover, Arjun
   Singh turns red as unavailable, the impact counters tick up, and a banner
   reads **Resolved autonomously** in about 4–5 seconds.
3. **Arm `Autonomous`.** Now stop touching it. Telemetry drifts; when a
   delivery's predicted risk crosses the threshold the watchdog fires the chain
   itself, infers the disruption from the dominant risk factor, and resolves it.
   The log line reads `self-triggering chain, no human input`.
4. **Switch to `Humanitarian`.** Same engine, cold-chain consignments. Trigger
   `🌡️ Cold Chain At Risk` on V-202 and watch drivers without a cold box get
   excluded by hard constraint before any scoring happens.
5. **Open `Assumptions & models`** when someone asks where the numbers came from.

---

## Layout

```
server.py              stdlib HTTP + one SSE broadcast channel + telemetry
                       simulator + the autonomous watchdog
autofleet/
  geo.py               real coordinates, haversine, road graph, ETA model
  impact.py            emission factors + sources, the impact ledger
  scoring.py           the two interpretable models
  world.py             fleet state, both scenarios, disruption effects
  llm.py               Claude Opus 5 streaming + deterministic fallback
  agents.py            the five-agent chain
web/
  index.html           dashboard shell
  styles.css           self-contained (no external fonts or CDN)
  app.js               SSE client, SVG map, agent feed
```

Architecture notes worth knowing:

- **One SSE channel** carries everything. The watchdog can therefore push a
  chain the browser never asked for, which is what makes the autonomy real
  rather than a client-side timer.
- **Incidents are queued and serialised** on a worker thread, so rapid clicks
  don't interleave two chains.
- The Reallocation Agent's pick is parsed from a `PICK: <driver_id>` first line
  and validated against the eligible set; an unparsable or ineligible pick falls
  back to the top-ranked candidate and **logs that it did so**.
