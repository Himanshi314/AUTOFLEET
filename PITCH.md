# AutoFleet AI — Pitch & Q&A Prep

Team 404 · Round 2

**How to use this:** memorise §1 (the 3-minute script). Read §3 (the questions)
until you can answer any of them without looking. §4 is what to say when
something breaks on stage.

---

## 1. The 3-minute script

Timings are deliberate. Practise with a stopwatch — the demo is the pitch, not
the slides.

### 0:00–0:35 · The problem, as a story

> "It's 7pm. Arjun is 3 km from Rohan's flat with a parcel. His bike dies.
>
> Right now, he calls the hub. The coordinator is on another call. Eight minutes
> pass. They start working down a list of riders — there's one 600 metres away,
> but they don't know that. At 7:40 the delivery window closes. The parcel goes
> back to the warehouse and comes out again tomorrow: a second trip, an annoyed
> customer, and Arjun loses the earnings for a delivery he didn't complete.
>
> Fixing that takes about twenty minutes. He had about eight. **That gap is what
> we built for.**"

*Don't say "AI" yet. Make them feel the problem first.*

### 0:35–0:55 · What it is

> "AutoFleet AI is an autonomous layer that sits between a carrier's dispatch
> system and the road. Route optimisers plan the route. Dispatch systems assign
> the job. Neither one *fixes* a delivery once it's already broken — that's still
> a human on a phone. We do that part, and nobody prompts us: the system runs on
> a telemetry event."

### 0:55–2:15 · The demo — the part that matters

**Beat 1 — the board.** *"Four live deliveries. Real Bengaluru coordinates. And a
live failure-risk score on each one, with the line marked where the system decides
to act on its own."*

**Beat 2 — click `🔧 Vehicle Breakdown` on D-102.**

> "First thing that happens isn't an agent. It's the router deciding **how much
> intelligence this problem deserves.** Breakdown means the courier can't
> continue, so it's the full chain — six roles."

Then narrate as the cards arrive — don't read them aloud, point at them:

> "Risk assesses severity and tells the others this is a hard stop, not a delay.
> Customer decides what we ask of Rohan. Communication writes the actual message.
> Resource picks the driver — and notice **it doesn't describe a reassignment, it
> calls a function.** Delivery releases Arjun, dispatches roadside assistance, and
> protects his earnings, because he didn't cause this. Coordinator issues the
> resolution — and every number in that summary is machine-checked against its
> input before you see it.
>
> Four seconds. Zero humans."

**Beat 3 — the one most teams don't have. Click `⚡ Conflicting Assignment` on D-104.**

> "Same system, different answer: **no agents needed.** Two roles greyed out with
> the reason. The models already solved it, so we didn't spend a language model
> narrating it. That counter is AI calls we avoided."

**Beat 4 — arm `Autonomous`, then take your hands off the keyboard.**

> "Now nobody's touching it. The watchdog is watching the risk model. When a
> delivery crosses the threshold, it fires the chain itself and infers what kind
> of problem it is. This is the part that makes it agentic — it isn't waiting for
> me."

### 2:15–2:45 · Why it's a real business

> "One failed delivery costs a carrier ₹60–100. A mid-size carrier has about
> three thousand a day. We charge around ₹10 per exception we resolve — and
> nothing when we have to escalate to a human, because then we didn't do the job.
> It costs us about eighty paise to resolve one. And it gets *cheaper* as the
> router gets smarter."

### 2:45–3:00 · Close

> "The same engine runs cold-chain medical deliveries — vaccines, blood — where a
> late delivery isn't an annoyance, it's spoiled doses. And in the places that
> need that most, rural districts and disaster zones, there is no coordinator to
> escalate to at all. Autonomous coordination isn't a convenience there. It's the
> only coordination that exists."

---

## 2. Numbers you must know cold

If you can't remember a number, **say you'll check it** rather than guessing.

| Fact | Value |
|---|---|
| Chain resolution time | ~4–5 seconds |
| Worst case, bounded | ~50 seconds |
| Agents | 6 roles, stateless |
| Routing split *(measured, 28 combinations)* | 29% full · 61% partial · 11% zero agents |
| Cost per incident *(measured)* | ~$0.009 ≈ ₹0.80 |
| Routing cost saving *(measured)* | ~7× ($0.068 → $0.009) |
| Risk model | logistic, 7 features, bias −4.60 |
| Ranker | weighted linear, 7 features, weights sum to 1.0 |
| Autonomous trigger threshold | risk ≥ 0.68 |
| Decisive-margin threshold | 0.10 |
| Exceptions with one obviously best driver *(measured)* | 66% |
| Impact for one D-102 incident | 27.4 km, 2.08 kg CO₂e |

**Do not conflate the 66% and the 11%.** The 66% is how often one driver is
obviously best (ranker margin). The 11% is how often *no agent at all* is needed.
Different measurements.

---

## 3. Q&A — twelve questions you will get

### Q1. "Isn't this just a chatbot wrapper / five prompts in a loop?"

> "Mechanically it *is* six prompts — I won't pretend otherwise. Two things make
> it different. First, nobody prompts it: it runs on a telemetry event and writes
> a change back to fleet state, so a driver actually gets reassigned. Second, the
> agents never do arithmetic — two deterministic models compute distance, risk and
> driver ranking, and the agents make the judgement call on top. The value is in
> the decomposition, not the model."

### Q2. "Where's the actual machine learning?"

> "Two interpretable models. `disruption-risk-v1` is a logistic model over seven
> features that predicts whether a delivery will fail, so we can act before it
> does. `reassignment-suitability-v1` applies hard constraints then ranks drivers.
> Both are linear on purpose — every score decomposes into per-feature
> contributions, which is what you see on screen when it explains why it picked a
> driver.
>
> And to be straight with you: **neither is trained yet.** Both are hand-calibrated
> from domain reasoning, and the dashboard says so. The risk model is the easy one
> to fit — the labels are free, you just ask whether the delivery failed on first
> attempt. The ranker is harder because you only observe outcomes for drivers who
> were actually chosen, so it needs exploration or propensity weighting."

*That last paragraph wins more credit than pretending you trained something.*

### Q3. "What's the weakest part of your project?"

Lead with the real one. Do not deflect.

> "Rules could handle most of it. Our own measurement says 66% of exceptions have
> one obviously best driver — a rules engine covers that. The language layer only
> earns its cost on the ambiguous tail: nearest driver is 0.4 km away but their
> shift ends in 20 minutes and the payload needs a cold box and the customer
> already rescheduled twice. That tail is where coordinators actually spend their
> day. But **we haven't proven with real data that the tail is big enough**, and
> that's the honest gap."

### Q4. "What happens when the AI fails or the network drops?"

> "The resolution still happens. Three layers: 25-second timeout per call,
> 45-second budget for the whole incident, and a worker that frees any delivery
> left mid-resolution. Past the budget the agents stop calling the model and use
> their deterministic fallback — because the models already produced a complete
> answer. **The language layer isn't load-bearing for the resolution, only for the
> explanation.** We tested it by injecting a model that hangs 20 seconds per call:
> finished in 20 seconds instead of 100, and the reassignment was real."

### Q5. "Why not a fully autonomous negotiating multi-agent system?"

> "Autonomy is about whether a human is in the loop — not whether the agents chat
> to each other. Ours self-triggers on an event and acts with no human involved.
> And our decisions form a DAG, not a cycle: Risk → Customer → Communication →
> Resource → Delivery → Coordinator. Each role needs what came before and nothing
> that comes after. **There's nothing to negotiate.** Adding negotiation would add
> unbounded latency and a non-termination risk for no gain."

### Q6. "Does this scale? 20,000 exceptions a day is 100,000 model calls."

> "Six roles, not six processes — stateless, one worker pool. And we don't run all
> six on everything: measured, 11% of incidents need zero agents and 61% need four
> instead of six. That's a 7× cost reduction, about a cent an incident. Throughput
> isn't the constraint — 20,000 a day is 0.23 per second."

### Q7. "How do we know it isn't making the numbers up?"

> "For the Coordinator, we check mechanically. Every number in its summary is
> extracted and matched against the numbers it was given; if anything doesn't
> trace, the incident is flagged on screen. And the Resource Agent doesn't write a
> driver name in prose — it makes a schema-validated tool call, so the driver id
> is a validated field, and we check it against the eligible set before committing."

### Q8. "Where do the CO₂ figures come from?"

> "They're estimates from documented factors, and the dashboard ships the whole
> derivation — click Assumptions. The distance is computed from real coordinates;
> the emission factor is a published range for a petrol two-wheeler. We
> deliberately discount the redelivery to 80% of a round trip, because some retries
> ride an existing route. **The factors need re-deriving for a specific fleet and
> grid mix before anyone publishes them, and we say that on screen.**"

### Q9. "Who pays for this, and why would they?"

> "Head of Last-Mile at a 3PL carrier. It reduces four budget lines:
> exception-desk headcount, redelivery fuel, SLA penalties, and spoiled stock in
> cold chain. We charge per exception resolved, not per seat — because our whole
> value is that they need fewer coordinators, so per-seat pricing would point the
> incentives the wrong way. And escalations are free: if we hand it to a human, we
> didn't do the job."

### Q10. "What stops a big carrier building this themselves?"

> "Nothing, and the big ones probably will. The agent chain is a weekend of work —
> we don't claim it as a moat. What compounds is the resolution-policy library
> from every case where a human overrode us, the integration surface into a dozen
> different dispatch systems, and a track record showing our decisions matched
> real coordinators. We sell to mid-size carriers who won't build."

### Q11. "Is it live right now, or simulated?"

Answer honestly whichever is true. If simulated:

> "Right now the language layer is running our deterministic fallback, and every
> card on screen is labelled `simulated` — we never hide that. The architecture,
> the router, the models and the actions are all identical; what changes is
> whether the sentences come from Claude or from a template built off the same
> computed state. We built it that way deliberately so a network problem can't
> kill a demo."

### Q12. "What would you do next with three more months?"

> "Shadow mode with one real carrier — the system decides but acts on nothing,
> and we log our decision beside the coordinator's. That gives us the only thing
> that actually sells this: proof we match a human on real exceptions. It also
> gives us the labelled data to fit the risk model properly, and every
> disagreement becomes a policy-library entry."

---

## 4. When something breaks on stage

| What breaks | What you do |
|---|---|
| Network / API dies | Keep going. It falls back automatically and the cards say `simulated`. **Say so out loud** — "that's the fallback path I mentioned, the resolution still completed." It's a feature, demonstrated live. |
| App won't start | Play the backup video. Narrate over it as if live. Never debug on stage. |
| A delivery is stuck | Hit **Reset**. Board returns to a clean state. |
| Projector washes out the dark theme | Say the numbers out loud instead of pointing at them. Have one bright slide with the six agents as a backup. |
| You blank on a number | *"I'd have to check that one."* Never invent a figure — one made-up number costs you the whole credibility of the honest ones. |
| A judge finds a real flaw | *"That's fair, and it's on our list."* Then say which weakness of ours it maps to. Agreeing costs nothing; defending a real flaw costs everything. |

---

## 5. Rules for the four of us

1. **One person drives the demo, one person narrates.** Never both on the keyboard.
2. **Whoever owns a track answers questions about that track.** Don't rescue each
   other mid-answer — it reads as uncertainty.
3. **Never say "I think" about a measured number.** Either know it or say you'll check.
4. **Never oversell.** Every honest limit in this doc is there because the honest
   version is more persuasive than the inflated one, and it survives follow-ups.
5. **If asked something nobody knows:** *"We don't know yet — here's how we'd find
   out."* That's a good answer, not a bad one.
