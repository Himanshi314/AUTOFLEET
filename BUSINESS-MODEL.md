# AutoFleet AI — Business Model

Team 404 · Round 2

> **Every figure here is an assumption unless marked *measured*.** The measured
> ones come from the working system (cost per incident, routing distribution).
> The market and pricing figures are reasoned estimates that need validation with
> one real carrier before anyone should act on them. Say that out loud — a judge
> who knows logistics will respect it more than a confident invented number.

---

## 1. What we sell, in one line

> **Resolved delivery exceptions.** Not software seats, not a dashboard — the
> outcome. A disruption goes in, a completed first-attempt delivery comes out,
> and no coordinator touched it.

---

## 2. Who pays, and out of which budget

We are not sold to an innovation team. We are sold to whoever owns the exception
desk's cost line.

| Buyer | Title | Why they sign |
|---|---|---|
| **Primary** | Head of Last-Mile / VP Operations at a 3PL carrier | Owns exception-desk headcount, redelivery fuel and SLA penalties |
| **Strong second** | COO / Logistics Head at a diagnostic lab chain or pharma distributor | Owns spoiled-sample write-offs — highest cost per exception of any segment |
| **Third** | Head of Field Service (appliance, telecom, utility) | Owns technician no-show and revisit costs on ₹500–5,000 jobs |

**The four budget lines we reduce:**

1. Exception-desk headcount (the largest, and the reason it gets bought)
2. Redelivery fuel and courier-hours
3. SLA penalty payouts to enterprise shippers
4. Written-off spoiled stock (cold chain only — but brutal there)

**Explicitly not our buyer:** quick-commerce (Blinkit / Zepto class). They already
automate rider reassignment in-house and would build, not buy. Saying who you
*don't* sell to makes the rest credible.

---

## 3. Pricing — and why per-seat is structurally wrong

This is the most important decision in the model, so here is the reasoning rather
than just the answer.

**Per-seat pricing is misaligned with what we do.** Standard SaaS charges per
user. AutoFleet *removes* users — its whole value is needing fewer coordinators.
Per-seat pricing would mean the customer pays us more precisely when we are
working worst. The incentives point in opposite directions.

**So we charge per resolved exception.** We charge for work done. Value and price
move together, the buyer's spend scales with their volume rather than their
headcount, and the metric we bill on is the same metric we report success on.

### The price point

| | Per exception |
|---|---|
| **Value delivered** (conservative) | **₹60–100** — redelivery fuel + courier-hours + partial labour recovery |
| **Value delivered** (with full labour + SLA) | ₹120–200 |
| **Our COGS** *(measured)* | **₹0.80** (~$0.009) |
| **Proposed price** | **₹8–15**, tiered down by volume |

At ₹10 we capture roughly **10–17% of the conservative saving** and leave the rest
with the customer. That is an easy conversation: *"we keep a tenth, you keep nine."*

**Structure — three components:**

| Component | Amount | Why it exists |
|---|---|---|
| Platform fee | ₹1.5–4L/month by tier | Integration, support, uptime commitment. Makes revenue predictable and stops tiny accounts being unprofitable. |
| Per resolved exception | ₹8–15, volume-tiered | The real meter. Only charged when the system resolves autonomously. |
| **Escalations: free** | ₹0 | If we hand it to a human, we didn't do the job. **Don't charge for it.** |

That last line is the one to say in the pitch. It is commercially cheap (escalations
should be a small minority) and it makes the incentive unmistakable: we only get
paid when we actually replace the coordinator.

---

## 4. Unit economics

Per resolved exception, at ₹10:

| | ₹ | Note |
|---|---|---|
| Revenue | 10.00 | |
| AI inference *(measured)* | (0.80) | ~$0.009 blended, after routing |
| Infra, comms (SMS), logging | (0.60) | estimate |
| **Gross profit** | **8.60** | |
| **Gross margin** | **~86%** | |

### Account-level, per month

| Customer size | Exceptions/day | Platform fee | Usage | **MRR** | **ARR** |
|---|---|---|---|---|---|
| Large national carrier | 20,000 | ₹4L | ₹60L | **₹64L** | ₹7.7Cr (~$900k) |
| Mid regional carrier | 3,000 | ₹2L | ₹9L | **₹11L** | ₹1.3Cr (~$155k) |
| Diagnostic lab chain | 500 (cold chain) | ₹1.5L | ₹2.3L¹ | **₹3.8L** | ₹46L (~$54k) |

¹ Cold chain prices at a premium (₹15) — a spoiled sample costs far more than a
redelivered parcel, so the value per exception is higher.

### Why the margin *improves* over time — the unusual bit

Most AI products have COGS that scale linearly with usage, which crushes gross
margin as you grow. Ours doesn't, because of the **severity router**.

*Measured:* the router resolves **11% of incidents with zero AI calls** and another
**61% with four instead of six** — cutting blended inference cost from ~$0.068 to
~$0.009 per incident, about **7×**.

Every improvement to the router is a permanent margin gain. And as the resolution-
policy library grows, more cases become mechanical, so more incidents route to zero
AI calls. **The product gets cheaper to run the better it gets.** That is a genuinely
attractive property and most AI startups cannot claim it.

---

## 5. Revenue evolution — three phases

Nobody buys autonomous customer communication on day one. The commercial model has
to mirror the trust ladder.

| Phase | What we deliver | What we charge | What we're really buying |
|---|---|---|---|
| **1 · Shadow** (4–8 weeks) | We watch real exceptions, decide, **act on nothing**. Log our decision beside the coordinator's. | **Free**, or a small fixed pilot fee | The only evidence that matters: *"we matched or beat your coordinator on N real exceptions."* Also: their exception taxonomy, which becomes our policy library. |
| **2 · Assisted → Guarded** (3–6 months) | We propose; the coordinator approves. Then we act alone below a value threshold. | Per-resolution, discounted (₹5–8) | Approval rate as the proof metric. Every override becomes a policy-library entry. |
| **3 · Autonomous** | Full resolution within agreed guardrails | Full price (₹8–15) + platform fee | Expansion: more exception types, more cities, more of their network |

**Shadow mode is the entire sales motion, and it is nearly free to deliver.** It
needs read-only access — no approval to *act*, which is the hard approval to get.
That keeps customer acquisition cost low and gives the sales cycle a natural,
data-backed proof point instead of a demo.

---

## 6. Market size — bottom-up, not top-down

We are deliberately not quoting a "$50B logistics market" figure. Bottom-up by
account is more defensible and more useful.

**India, addressable accounts:**

| Segment | Accounts | Realistic ACV | Segment potential |
|---|---|---|---|
| National 3PL / express carriers | ~15 | ₹1.5–7.7Cr | ~₹30–60Cr |
| Regional carriers | ~80 | ₹40L–1.3Cr | ~₹50–80Cr |
| Diagnostic lab / pharma cold chain | ~40 | ₹30L–1Cr | ~₹15–25Cr |
| Enterprise field service | ~150 | ₹20–60L | ~₹40–60Cr |

**Serviceable India opportunity: roughly ₹135–225Cr ARR (~$16–27M).** Beachhead
first: **five mid-size carriers = ~₹6Cr ARR (~$700k)**, which is a real company.

Same playbook extends to South-East Asia, the Middle East and LATAM, where
last-mile density and manual coordination look similar. Do not put that in the
first pitch — beachhead credibility beats a big number.

---

## 7. Costs to run

| | Monthly, early stage |
|---|---|
| AI inference | Scales with usage — ~₹0.80/exception *(measured)* |
| Cloud infra | ₹40–80k (the app itself is light: stdlib Python, no DB, no build step) |
| Integration engineering | 1–2 engineers — **the real cost centre** |
| Sales / customer success | 1 person until ~5 accounts |

**The honest cost warning:** our cost is not compute, it's **integration.** Every
TMS is different. Each new carrier needs connectors to their dispatch system,
driver app and comms provider. That is what will consume the team, and it is also
what compounds into a moat — but budget for it as engineering time, not as licence
cost.

---

## 8. Moat — honest version

**What is not a moat:** the agent chain. An incumbent could rebuild it in a
weekend. Do not claim it as defensibility; a technical judge will call it.

**What actually compounds:**

1. **The resolution-policy library.** Every shadow-mode disagreement teaches the
   system something a competitor starting today doesn't know. This grows with usage
   and cannot be copied from the outside.
2. **Integration surface.** Connectors into a dozen TMS variants are unglamorous,
   slow, and a genuine barrier.
3. **The trust record.** *"We matched human coordinators on 40,000 real exceptions"*
   is the asset no new entrant has, and it is what closes the second customer.
4. **Switching cost.** Once we are in the exception path, removing us means
   rebuilding the exception desk.

---

## 9. Risks, and what would kill this

Naming these makes the model credible rather than weaker.

| Risk | Severity | Response |
|---|---|---|
| **Carriers build it in-house.** The big ones have engineering teams. | **High** | Sell to mid-size carriers who won't build. Be the layer, not the platform. |
| **Rules handle most of it** — *measured:* 66% of exceptions have one obviously best driver, so a rules engine covers the head of the distribution | **High** | We already route those to zero AI calls. Our price reflects resolution, not intelligence — we're paid for the outcome regardless of method. But the value case rests on the tail being large and expensive, and **we have not proven that with real data.** |
| **Trust / adoption is slow.** Ops directors don't hand over customer comms. | Medium | The three-phase ladder is designed for exactly this. Long sales cycle is a fact to plan for, not a bug. |
| **One bad autonomous decision** damages a carrier's key account | Medium | Hard guardrails already built: no payments, no cancellations, value thresholds, and honest escalation. |
| Inference price rises | Low | The router already cut cost 7×; margin has room. |

---

## 10. The 30-second version

> We sell resolved delivery exceptions, not software seats — because our whole
> value is that you need fewer coordinators, so charging per seat would point the
> incentives the wrong way. Roughly ₹10 per exception we resolve autonomously,
> free when we have to escalate to a human. It costs us about eighty paise to
> resolve one, so gross margin is around 86% — and it *improves* as our router
> learns to resolve more cases without waking a language model at all. We land
> through free shadow mode, where we decide but don't act, because the only thing
> that sells this is proof we match a real coordinator on real exceptions. Five
> mid-size carriers is about ₹6 crore of ARR.

---

## Appendix — where each number comes from

| Figure | Source |
|---|---|
| ₹0.80 (~$0.009) COGS per exception | **Measured.** 6,120 input + ~1,500 output tokens at Opus 5 rates, blended across the routing distribution |
| 7× cost reduction from routing | **Measured.** $0.068 → $0.009 blended |
| 29% full / 61% partial / 11% deterministic | **Measured** across all 28 disruption × delivery combinations |
| 66% of exceptions have a decisive winner | **Measured** on the demo fleet (ranker margin ≥ 0.10). *Not* a production distribution |
| 14 coordinator-minutes per incident | Assumption — midpoint of the stated 10–20 min manual window |
| ₹60–200 value per exception, and ₹30–60/parcel carrier margin | **Assumption**, from general commentary on Indian express economics. **Verify both against one real carrier's cost data before quoting either.** |
| ₹8–15 price per exception | **Assumption.** Derived to capture 10–17% of the conservative value estimate |
| Account counts by segment | **Assumption.** Order-of-magnitude reasoning, not a researched census |
