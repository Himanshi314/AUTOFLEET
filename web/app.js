/* ==========================================================================
   AutoFleet AI — dashboard client
   Consumes one SSE channel. Every number rendered here arrives from the server;
   nothing is computed or embellished in the browser.
   ========================================================================== */

'use strict';

const $  = (s) => document.querySelector(s);
const el = (tag, cls, html) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
};
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const SVGNS = 'http://www.w3.org/2000/svg';
const svgEl = (tag, attrs) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
};

const nf = (v, d = 1) => Number(v).toFixed(d);

/* ---------------------------------------------------------------- state --- */

const App = {
  state: null,
  meta: null,
  chain: null,           // { root, spine, fill, cards:{}, order:[] }
  tiles: {},             // rendered impact values, for count-up
  pickedDriver: null,    // highlights the chosen driver on the map
  view: 'ops',           // 'ops' (company) | 'courier' (the rider)
  courierId: null,
  logCount: 0,
  // incident_id last announced to each courier, so a handover alerts once
  // rather than on every state tick.
  seenHandover: {},
  // Map camera. Lives OUTSIDE renderMap because renderMap() wipes and rebuilds
  // the SVG on every state tick — holding zoom in the DOM would reset it to
  // fully-zoomed-out roughly once a second while you were trying to look.
  mapView: { z: 1, cx: 500, cy: 300 },
};

/* ============================================================== MAP CAMERA == */

const MAP_W = 1000, MAP_H = 600;
const MAP_ZOOM_MIN = 1, MAP_ZOOM_MAX = 8;

function clampCamera() {
  const v = App.mapView;
  v.z = Math.min(MAP_ZOOM_MAX, Math.max(MAP_ZOOM_MIN, v.z));
  const w = MAP_W / v.z, h = MAP_H / v.z;
  // Keep the viewport inside the map so you can never pan off into blank space.
  v.cx = Math.min(MAP_W - w / 2, Math.max(w / 2, v.cx));
  v.cy = Math.min(MAP_H - h / 2, Math.max(h / 2, v.cy));
  return v;
}

function applyCamera() {
  const svg = $('#map');
  if (!svg) return;
  const v = clampCamera();
  const w = MAP_W / v.z, h = MAP_H / v.z;
  svg.setAttribute('viewBox', `${v.cx - w / 2} ${v.cy - h / 2} ${w} ${h}`);
  const btn = $('#map-zoom-label');
  if (btn) btn.textContent = v.z.toFixed(1) + '×';
  const reset = $('#map-reset');
  if (reset) reset.disabled = v.z === 1;
}

/** Client pixel -> base map coordinate, so wheel-zoom can hold a point still. */
function mapPointFromEvent(e) {
  const svg = $('#map');
  const r = svg.getBoundingClientRect();
  const v = clampCamera();
  const w = MAP_W / v.z, h = MAP_H / v.z;
  // The SVG uses preserveAspectRatio=xMidYMid meet, so the drawn area is
  // letterboxed inside the element; ignoring that makes the cursor drift.
  const scale = Math.min(r.width / w, r.height / h);
  const drawnW = w * scale, drawnH = h * scale;
  const offX = (r.width - drawnW) / 2, offY = (r.height - drawnH) / 2;
  return [
    (v.cx - w / 2) + (e.clientX - r.left - offX) / scale,
    (v.cy - h / 2) + (e.clientY - r.top - offY) / scale,
  ];
}

function zoomMap(factor, anchor) {
  const v = App.mapView;
  const before = anchor || [v.cx, v.cy];
  const z0 = v.z;
  v.z = Math.min(MAP_ZOOM_MAX, Math.max(MAP_ZOOM_MIN, v.z * factor));
  if (v.z === z0) return;
  if (anchor) {
    // Hold the anchor point under the cursor: shift the centre by the residual.
    const k = 1 - z0 / v.z;
    v.cx += (before[0] - v.cx) * k;
    v.cy += (before[1] - v.cy) * k;
  }
  renderMap();
}

function resetMapCamera() {
  App.mapView = { z: 1, cx: MAP_W / 2, cy: MAP_H / 2 };
  renderMap();
}

function wireMapCamera() {
  const svg = $('#map');
  if (!svg || svg.dataset.camWired) return;
  svg.dataset.camWired = '1';

  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomMap(e.deltaY < 0 ? 1.18 : 1 / 1.18, mapPointFromEvent(e));
  }, { passive: false });

  let drag = null;
  svg.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    drag = { at: mapPointFromEvent(e), cx: App.mapView.cx, cy: App.mapView.cy };
    svg.setPointerCapture(e.pointerId);
    svg.classList.add('grabbing');
  });
  svg.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const now = mapPointFromEvent(e);
    App.mapView.cx = drag.cx - (now[0] - drag.at[0]);
    App.mapView.cy = drag.cy - (now[1] - drag.at[1]);
    applyCamera();
  });
  const endDrag = (e) => {
    if (!drag) return;
    drag = null;
    svg.classList.remove('grabbing');
    try { svg.releasePointerCapture(e.pointerId); } catch (_) {}
    renderMap();   // redraw so label/marker sizes match the final zoom
  };
  svg.addEventListener('pointerup', endDrag);
  svg.addEventListener('pointercancel', endDrag);
  svg.addEventListener('dblclick', (e) => {
    e.preventDefault();
    zoomMap(1.8, mapPointFromEvent(e));
  });
}

/* =========================================================== IMPACT STRIP == */

const TILES = [
  { key: 'incidents_resolved',        label: 'Disruptions resolved', accent: '#5eead4',
    note: 'end-to-end, agent chain only' },
  { key: 'human_interventions',       label: 'Human interventions', accent: '#8b93f8',
    note: 'coordinators involved' },
  { key: 'llm_calls_saved', label: 'AI calls avoided', accent: '#818cf8',
    note: 'router skipped a role that had nothing to decide' },
  { key: 'km_avoided',                label: 'Redelivery km avoided', accent: '#34d399',
    unit: 'km', dec: 1, note: 'estimate · see assumptions' },
  { key: 'co2e_kg_avoided',           label: 'CO₂e avoided', accent: '#34d399',
    unit: 'kg', dec: 2, note: 'estimate · documented factors' },
  { key: 'coordinator_minutes_saved', label: 'Coordinator time saved', accent: '#fbbf24',
    unit: 'min', dec: 0, note: '14 min per incident' },
];

const DOSE_TILE = { key: 'doses_preserved', label: 'Doses preserved', accent: '#5eead4',
                    dec: 0, note: 'delivered inside cold-chain window' };

/* ---- Intent register -------------------------------------------------- */
/* Every stated goal, who holds it, and whether it is currently binding. The
   switch is the point: a judge can withdraw an intent and re-run the same
   incident, and the system commits a different courier. A read-only list would
   prove nothing. */
const HOLDER_ICON = {
  recipient: '\u{1F464}', courier: '\u{1F6B4}',
  operations: '\u{1F3E2}', payload: '\u{1F4E6}',
};

/* ---- Decisions awaiting a person -------------------------------------- */
/* The system has declined to commit and is asking. This panel states what it
   would have done, whose stated goals collided and with what arithmetic, and
   the options genuinely open — derived from state, so "keep the original
   courier" simply is not offered when that courier's bike is broken. */
function renderDecisions(payload) {
  if (!payload) return;
  App.decisions = payload;
  const host = document.getElementById('decisions');
  if (!host) return;
  const pending = payload.pending || [];
  host.hidden = pending.length === 0 && !(payload.history || []).length;
  if (host.hidden) { host.innerHTML = ''; return; }

  const cards = pending.map(d => {
    const why = (d.blocking || []).map(v => {
      const e = v.evidence || {};
      const nums = Object.keys(e)
        .filter(k => k !== 'basis')
        .map(k => `<span class="dc-n"><i>${esc(k.replace(/_/g, ' '))}</i>${esc(String(e[k]))}</span>`)
        .join('');
      return `<div class="dc-conflict">
          <div class="dc-say">${esc(v.holder)} &mdash; &ldquo;${esc(v.statement)}&rdquo;</div>
          <div class="dc-nums">${nums}</div>
        </div>`;
    }).join('');
    const opts = (d.options || []).map(o => `
      <button class="dc-opt${o.destructive ? ' danger' : ''}"
              data-delivery="${esc(d.delivery_id)}"
              data-action="${esc(o.action)}"
              data-intent="${esc(o.intent_id || '')}">
        <span class="dc-o-label">${esc(o.label)}</span>
        <span class="dc-o-detail">${esc(o.detail || '')}</span>
        ${o.cost ? `<span class="dc-o-cost">cost &middot; ${esc(o.cost)}</span>` : ''}
      </button>`).join('');
    const left = Math.max(0, (d.timeout_ticks || 0) - (d.waited_ticks || 0));
    return `<article class="dcard-wait">
        <header class="dw-head">
          <div>
            <span class="dw-tag">needs a decision</span>
            <h3>${esc(d.delivery_id)} &middot; ${esc(d.recipient)}</h3>
            <p class="dw-sub">${esc(d.payload || '')}${d.destination_name
                ? ' &rarr; ' + esc(d.destination_name) : ''}</p>
          </div>
          <div class="dw-meta mono">
            <span>waiting since ${esc(d.since || '--:--')}</span>
            <span class="dw-timeout">${left} ticks before it reverts</span>
          </div>
        </header>
        <p class="dw-reason">${esc(d.reason || '')}</p>
        ${why ? `<div class="dw-why">${why}</div>` : ''}
        <div class="dw-opts">${opts}</div>
      </article>`;
  }).join('');

  const hist = (payload.history || []).slice(0, 6).map(h => `
    <li><span class="mono">${esc(h.clock || '')}</span>
        <b>${esc(h.actor || '')}</b> ${esc(h.outcome || h.action || '')}
        ${h.note ? `<i>&ldquo;${esc(h.note)}&rdquo;</i>` : ''}</li>`).join('');

  host.innerHTML =
    (pending.length
      ? `<div class="dw-list">${cards}</div>`
      : '') +
    (hist
      ? `<div class="dw-trail">
           <h4>Decisions taken</h4>
           <ul>${hist}</ul>
         </div>`
      : '');
}

function refreshDecisions() {
  fetch('/api/decisions')
    .then(r => r.json())
    .then(renderDecisions)
    .catch(() => {});
}

function renderIntents(payload) {
  if (!payload) return;
  App.intentsPayload = payload;
  App.intents = payload.intents || [];
  const host = document.getElementById('intent-list');
  const clock = document.getElementById('intents-clock');
  const count = document.getElementById('intents-count');
  if (!host) return;
  if (clock && payload.clock) clock.textContent = payload.clock;
  const live = App.intents.filter(i => i.active).length;
  if (count) count.textContent = `${live} of ${App.intents.length} binding`;

  const open = App.intentsOpen === true;
  host.classList.toggle('collapsed', !open);
  const summary = document.getElementById('intents-summary');
  if (summary) {
    const by = {};
    App.intents.forEach(i => { by[i.holder_type] = (by[i.holder_type] || 0) + 1; });
    const parts = Object.keys(by).sort().map(k => `${by[k]} ${k}`);
    summary.textContent = parts.join(' \u00b7 ');
  }
  const btn = document.getElementById('intents-expand');
  if (btn) {
    btn.textContent = open ? 'Hide' : 'Show all';
    btn.setAttribute('aria-expanded', String(open));
  }

  host.innerHTML = '';
  App.intents.forEach(i => {
    const row = el('div', 'intent' + (i.active ? '' : ' off'));
    row.innerHTML =
      `<button class="intent-toggle" data-id="${esc(i.id)}"
               data-next="${i.active ? 'false' : 'true'}"
               role="switch" aria-checked="${i.active}"
               title="${i.active ? 'Withdraw this intent' : 'Restore this intent'}">
         <span class="it-knob"></span>
       </button>
       <div class="intent-body">
         <div class="intent-top">
           <span class="i-who">${HOLDER_ICON[i.holder_type] || ''} ${esc(i.holder)}</span>
           <span class="i-hard i-${esc(i.hardness)}">${esc(i.hardness)}</span>
           <span class="i-scope mono">${esc(i.scope === '*' ? 'fleet-wide' : i.scope)}</span>
         </div>
         <div class="intent-say">&ldquo;${esc(i.statement)}&rdquo;</div>
         <div class="intent-meta mono">${esc(i.kind)}${i.declared ? ' &middot; ' + esc(i.declared) : ''}</div>
       </div>`;
    host.appendChild(row);
  });
}

function renderImpact(impact, bump) {
  const strip = $('#impact-strip');
  const humanitarian = App.state && App.state.mode === 'humanitarian';
  // Humanitarian mode swaps "failed attempts" for "doses preserved" — the
  // metric that actually matters when the payload is perishable.
  const tiles = humanitarian
    ? [TILES[0], TILES[1], DOSE_TILE, TILES[3], TILES[4], TILES[5]]
    : TILES;

  // Rebuild when the tile SET changes, not just its length — otherwise a
  // same-length swap reuses stale labels against new values.
  const signature = tiles.map((t) => t.key).join('|');
  if (strip.dataset.sig !== signature) {
    strip.innerHTML = '';
    strip.dataset.sig = signature;
  }

  tiles.forEach((t, i) => {
    const raw = impact[t.key] ?? 0;
    const val = t.dec != null ? Number(raw).toFixed(t.dec) : String(raw);
    let node = strip.children[i];
    if (!node) {
      node = el('div', 'tile');
      node.style.setProperty('--accent', t.accent);
      node.innerHTML =
        `<div class="tile-k">${esc(t.label)}</div>` +
        `<div class="tile-v"><span></span>${t.unit ? `<small>${t.unit}</small>` : ''}</div>` +
        `<div class="tile-n">${esc(t.note)}</div>`;
      strip.appendChild(node);
    }
    const span = node.querySelector('.tile-v span');
    if (span.textContent !== val) {
      span.textContent = val;
      if (bump && Number(raw) > 0) {
        node.classList.remove('bump');
        void node.offsetWidth;
        node.classList.add('bump');
      }
    }
    node.classList.toggle('hot', Number(raw) > 0 && t.key !== 'human_interventions');
  });
}

/* ============================================================ FLEET CARDS == */

const CHIP = {
  'On Route': 'chip-onroute', 'Resolving': 'chip-resolving',
  'Reassigned': 'chip-reassigned', 'Rerouted': 'chip-rerouted',
  'Rescheduled': 'chip-rescheduled', 'Escalated': 'chip-escalated',
  'Awaiting Driver': 'chip-awaiting', 'Delivered': 'chip-delivered',
};

/* A disruption can only be raised where somebody can actually observe it.
   The rider is on the bike and at the door, so breakdowns, no-answers, bad
   addresses and damaged parcels are reported from the courier app. Corridor
   gridlock, double-booked jobs, priority injections and probe telemetry come
   from feeds no rider can see, so those surface on the operations desk.
   Same queue, same agent chain, different origin — which is the point. */
function disruptionsForMode(reporter) {
  const mode = App.state.mode;
  return (App.meta.disruptions || []).filter(
    (d) => d.modes.includes(mode) && (!reporter || d.reported_by === reporter)
  );
}

function renderFleet() {
  const list = $('#fleet-list');
  const st = App.state;
  $('#fleet-kind').textContent = st.mode === 'humanitarian' ? 'consignments' : 'deliveries';

  // Operations only raises what operations can detect. Courier-observed issues
  // arrive from the Courier view instead.
  const triggers = disruptionsForMode('system');

  // Drop cards for deliveries that no longer exist (e.g. after a mode switch).
  const live = new Set(st.deliveries.map((d) => d.id));
  [...list.children].forEach((c) => { if (!live.has(c.dataset.id)) c.remove(); });

  st.deliveries.forEach((d) => {
    let card = list.querySelector(`[data-id="${d.id}"]`);
    const fresh = !card;
    if (fresh) {
      card = el('div', 'dcard');
      card.dataset.id = d.id;
      list.appendChild(card);
    }

    const prevStatus = card.dataset.status;
    const resolving = d.status === 'Resolving';
    const swapped = d.reassigned;

    const edge = resolving ? '#8b93f8'
      : d.status === 'Reassigned' ? '#34d399'
      : d.status === 'Escalated' ? '#fb7185'
      : d.risk_band === 'critical' ? '#fb7185'
      : d.risk_band === 'elevated' ? '#fbbf24' : 'transparent';

    const cold = d.cold_chain ? (() => {
      const tight = d.cold_minutes_remaining < 75;
      return `<div class="cold ${tight ? 'tight' : ''}">
        <span class="cold-k">Cold-chain window</span>
        <span class="cold-v">${d.cold_minutes_remaining} min left</span></div>`;
    })() : '';

    card.style.setProperty('--edge', edge);
    card.innerHTML =
      `<div class="dc-top">
         <div>
           <div class="dc-id">${esc(d.id)}</div>
           <div class="dc-pay">${esc(d.payload)}</div>
         </div>
         <span class="chip ${CHIP[d.status] || 'chip-onroute'}">${esc(d.status)}</span>
         ${d.difficult ? '<span class="chip chip-difficult" title="Low geocode confidence, a recipient often out, or a corridor already bad — this one is likely to conflict">tricky</span>' : ''}
       </div>
       <div class="dc-rows">
         <div class="dc-row"><span class="k">Carrier</span><span class="v">${
           swapped
             ? `<span class="swap">${esc(originalName(d))}</span><b>${esc(d.driver_name)}</b>`
             : `<b>${esc(d.driver_name)}</b>`
         }</span></div>
         <div class="dc-row"><span class="k">${st.mode === 'humanitarian' ? 'Facility' : 'Recipient'}</span><span class="v">${esc(d.recipient)}</span></div>
         <div class="dc-row"><span class="k">Drop</span><span class="v">${esc(d.destination_name)}</span></div>
         <div class="dc-row"><span class="k">ETA</span><span class="v dc-eta">${nf(d.eta_minutes, 0)} min</span></div>
       </div>
       ${cold}
       <div class="dc-meter">
         <div class="dc-meter-top">
           <span>Predicted failure risk</span>
           <b class="t-${d.risk_band}">${(d.risk * 100).toFixed(0)}% · ${esc(d.risk_band)}</b>
         </div>
         <div class="bar b-${d.risk_band}"><i style="width:${(d.risk * 100).toFixed(1)}%"></i></div>
         <div class="dc-why">Dominant factor: <b>${esc(d.risk_top_driver || '—')}</b></div>
       </div>
       <div class="dc-actions">${
         triggers.map((t) =>
           `<button class="trig" data-d="${esc(d.id)}" data-k="${esc(t.key)}" title="${esc(t.detected_as)}"
             ${resolving ? 'disabled' : ''}><span class="ic">${t.icon}</span>${esc(t.label)}</button>`
         ).join('')
       }</div>`;

    card.classList.toggle('resolving', resolving);
    card.classList.toggle('alarm', d.risk_band === 'critical' && !resolving);
    card.dataset.status = d.status;

    if (!fresh && prevStatus && prevStatus !== d.status &&
        (d.status === 'Reassigned' || d.status === 'Rerouted' || d.status === 'Rescheduled')) {
      card.classList.remove('flipped');
      void card.offsetWidth;
      card.classList.add('flipped');
    }
  });
}

function originalName(d) {
  const o = App.state.drivers.find((x) => x.id === d.original_driver_id);
  return o ? o.name : d.original_driver_id;
}

$('#fleet-list').addEventListener('click', (e) => {
  const btn = e.target.closest('.trig');
  if (!btn || btn.disabled) return;
  post('/api/disrupt', { delivery_id: btn.dataset.d, disruption: btn.dataset.k });
});

/* ============================================================= RISK LIST == */

function renderRisk() {
  const list = $('#risk-list');
  const thresh = App.meta.autonomous_threshold ?? 0.68;
  list.innerHTML = App.state.deliveries.map((d) => `
    <div class="rrow">
      <span class="rid">${esc(d.id)}</span>
      <div class="rmark">
        <div class="bar b-${d.risk_band}"><i style="width:${(d.risk * 100).toFixed(1)}%"></i></div>
        <span class="thresh" style="left:${(thresh * 100).toFixed(1)}%"></span>
      </div>
      <span class="rmeta t-${d.risk_band}">${(d.risk * 100).toFixed(0)}%<em>${esc(d.risk_band)}</em></span>
    </div>`).join('');
}

/* ============================================== COURIER DASHBOARD ========= */

/* The operations view above is for the company. This is the same live state seen
   by the person on the bike — their job, and when the chain releases them, the
   support dispatched and their earnings protected. That turns the driver-welfare
   claim into something visible rather than a bullet point. */

const SHIFT_FULL_MIN = 240;

/* What the courier who RECEIVES a transferred job is told.
   Previously this was one sentence — "you picked this up after another courier
   could not continue, collect at the handover point marked on your route" —
   which named no place, gave no reason, and pointed at a route marker that does
   not exist in this view. The rider being handed the work is the person who most
   needs the chain's reasoning, so every field below comes from the resolution
   itself: where the payload physically is, who has it and what happened to them,
   why this rider was selected, and what it does to their own ETA. */
function handoverBriefing(job, drv) {
  const h = job.handover;
  if (!h || !job.reassigned || job.driver_id !== drv.id) return '';

  const shift = h.eta_after != null && h.eta_before != null
    ? h.eta_after - h.eta_before : null;
  const shiftLine = shift == null ? '' : `
    <div class="hb-row">
      <i>⏱️</i>
      <div><b>Your ETA for this job is ${nf(h.eta_after, 0)} min.</b>
        ${Math.abs(shift) < 1
          ? `That is effectively unchanged from the original plan.`
          : `That is ${nf(Math.abs(shift), 0)} min ${shift > 0 ? 'later' : 'earlier'} than
             the original courier's ${nf(h.eta_before, 0)} min — the recipient has
             already been told.`}</div>
    </div>`;

  const whyLine = h.why_you ? `
    <div class="hb-row">
      <i>🎯</i>
      <div><b>Why you:</b> ${esc(h.why_you)}${h.suitability != null
        ? ` &middot; suitability ${nf(h.suitability, 2)}` : ''}${h.approach_km != null
        ? ` &middot; you were ${nf(h.approach_km, 1)} km from the collection point` : ''}.
        Every eligible courier was scored; you ranked first.</div>
    </div>` : '';

  // The Resource agent's own sentence — the same rationale operations sees.
  const rationaleLine = h.rationale ? `
    <div class="hb-quote">“${esc(h.rationale)}”
      <span class="hb-attr">— Resource Agent, ${esc(h.incident_id || '')}</span></div>` : '';

  return `
    <div class="cr-handover">
      <div class="hb-head">
        <span class="hb-badge">New job assigned to you</span>
        <span class="hb-inc">${esc(h.reason_icon || '')} ${esc(h.reason || '')}</span>
      </div>
      <div class="hb-rows">
        <div class="hb-row">
          <i>📦</i>
          <div><b>Collect the payload at ${esc(h.collect_at || 'the handover point')}.</b>
            ${h.from_driver_name
              ? `${esc(h.from_driver_name)} is waiting there with it.`
              : ''}</div>
        </div>
        <div class="hb-row">
          <i>${esc(h.reason_icon || '⚠️')}</i>
          <div><b>Why it moved:</b> ${esc(h.from_driver_name || 'The previous courier')}
            had a ${esc((h.reason || 'problem').toLowerCase())} and could not continue.
            ${h.support_for_them
              ? `${esc(h.support_for_them.charAt(0).toUpperCase() + h.support_for_them.slice(1))}
                 has been dispatched to them.` : ''}
            This is not a penalty on them or on you.</div>
        </div>
        ${whyLine}
        ${shiftLine}
      </div>
      ${rationaleLine}
    </div>`;
}

function renderCourier() {
  const host = $('#courier');
  const st = App.state;
  if (!st) return;

  // Default to whoever is currently carrying something.
  const carrying = st.deliveries.map((d) => d.driver_id);
  if (!App.courierId || !st.drivers.some((d) => d.id === App.courierId)) {
    App.courierId = carrying[0] || st.drivers[0].id;
  }
  const drv = st.drivers.find((d) => d.id === App.courierId);
  const job = st.deliveries.find((d) => d.driver_id === drv.id);

  const statusChip = {
    on_route: ['chip-onroute', 'On route'],
    available: ['chip-reassigned', 'Available'],
    unavailable: ['chip-escalated', 'Unavailable'],
    off_shift: ['chip-awaiting', 'Shift ended · resting'],
  }[drv.status] || ['chip-onroute', drv.status];

  const roster = st.drivers.map((d) => {
    const badge = d.status === 'unavailable' ? 'down'
      : carrying.includes(d.id) ? 'busy' : 'free';
    return `<button class="cr-pick ${d.id === drv.id ? 'on' : ''} ${badge}"
              data-driver="${esc(d.id)}">
              <b>${esc(d.name.split(' ')[0])}</b>
              <span>${esc(d.id)}</span>
            </button>`;
  }).join('');

  // Welfare panel — only meaningful once the chain has actually released them.
  const welfare = drv.status === 'unavailable' ? `
    <div class="cr-welfare">
      <div class="cr-welfare-h">You were released from this job — here's what happened</div>
      <div class="cr-wrow"><i>⚠️</i><div><b>Reason logged:</b> ${esc(drv.unavailable_reason || '—')}</div></div>
      <div class="cr-wrow"><i>🛠️</i><div><b>Support dispatched:</b> ${esc(drv.support_dispatched || 'none required')}</div></div>
      <div class="cr-wrow ok"><i>✅</i><div><b>Earnings for the completed leg are protected.</b>
        You are paid for the distance you covered.</div></div>
      <div class="cr-wrow ok"><i>✅</i><div><b>No reliability penalty logged.</b>
        This disruption was not your fault, so your on-time score is untouched.</div></div>
    </div>` : '';

  const jobCard = job ? `
    <div class="cr-job">
      <div class="cr-job-h">
        <span class="cr-job-id">${esc(job.id)}</span>
        <span class="chip ${CHIP[job.status] || 'chip-onroute'}">${esc(job.status)}</span>
      </div>
      <div class="cr-job-rows">
        <div><span>Deliver to</span><b>${esc(job.recipient)}</b></div>
        <div><span>Drop point</span><b>${esc(job.destination_name)}</b></div>
        <div><span>Payload</span><b>${esc(job.payload)}</b></div>
        <div><span>Arrive in</span><b class="cr-eta">${nf(job.eta_minutes, 0)} min</b></div>
      </div>
      ${job.cold_chain ? `<div class="cold ${job.cold_minutes_remaining < 75 ? 'tight' : ''}">
        <span class="cold-k">Cold-chain window</span>
        <span class="cold-v">${job.cold_minutes_remaining} min left</span></div>` : ''}
      ${handoverBriefing(job, drv)}
    </div>`
    : `<div class="cr-job empty">
         <div class="cr-job-h"><span class="cr-job-id">No active job</span></div>
         <p>You are ${drv.status === 'unavailable'
            ? 'off the road. Dispatch has been notified and support is on the way.'
            : 'available. The system will assign you the next job that fits your vehicle, load and shift.'}</p>
       </div>`;

  const shiftPct = Math.max(0, Math.min(100,
    (drv.shift_remaining_minutes / SHIFT_FULL_MIN) * 100));

  /* Where a disruption actually starts. In the field the rider is the sensor:
     they know the bike died or nobody answered before any system does. Raising
     it here rather than on the operations desk is the honest flow, and it makes
     the demo tell the truth — the rider reports, the chain resolves, ops watches
     it happen. Disabled with a reason when there is nothing to report against. */
  const reportable = disruptionsForMode('courier');
  const canReport = !!job && drv.status !== 'unavailable'
    && job.status !== 'Delivered' && job.status !== 'Resolving';
  const reportPanel = `
    <div class="cr-report">
      <div class="cr-report-h">
        <div>
          <h3>Report a problem</h3>
          <p>${canReport
            ? `Tap what you're seeing. It goes straight to the agent chain — no phone call, no waiting for dispatch.`
            : (drv.status === 'unavailable'
              ? `You've already been released from this job. Support is on the way.`
              : `Nothing to report — you have no active job right now.`)}</p>
        </div>
      </div>
      <div class="cr-report-grid">
        ${reportable.map((d) => `
          <button class="cr-rbtn" data-disruption="${esc(d.key)}"
                  data-job="${esc(job ? job.id : '')}"
                  title="${esc(d.reported_why || '')}"
                  ${canReport ? '' : 'disabled'}>
            <i>${d.icon}</i><span>${esc(d.label)}</span>
          </button>`).join('')}
      </div>
      <div class="cr-report-foot">
        Corridor gridlock, double-booked jobs and priority overrides aren't here —
        you can't see those from the saddle. The operations desk raises them.
      </div>
    </div>`;

  host.innerHTML = `
    <div class="cr-roster">
      <div class="cr-roster-k">Signed in as</div>
      <div class="cr-roster-list">${roster}</div>
    </div>

    <div class="cr-main">
      <div class="cr-id">
        <div class="cr-avatar">${esc(drv.name.split(' ').map((w) => w[0]).join('').slice(0, 2))}</div>
        <div class="cr-id-text">
          <h2>${esc(drv.name)}</h2>
          <p>${esc(drv.vehicle_label)} · ${esc(drv.id)}</p>
        </div>
        <span class="chip ${statusChip[0]}">${esc(statusChip[1])}</span>
      </div>

      <div class="cr-stats">
        <div class="cr-stat"><div class="cv">${(drv.on_time_rate * 100).toFixed(0)}%</div>
          <div class="ck">On-time record</div></div>
        <div class="cr-stat"><div class="cv">${drv.active_load}/${drv.capacity}</div>
          <div class="ck">Load</div></div>
        <div class="cr-stat"><div class="cv">${nf(drv.shift_remaining_minutes, 0)}<small>min</small></div>
          <div class="ck">Shift left</div>
          <div class="bar b-nominal"><i style="width:${shiftPct.toFixed(0)}%"></i></div></div>
        <div class="cr-stat"><div class="cv">${drv.cold_chain_capable ? 'Yes' : 'No'}</div>
          <div class="ck">Cold-chain box</div></div>
      </div>

      ${welfare}
      ${jobCard}
      ${courierRoute(job, drv)}
      ${reportPanel}
    </div>`;

  // Being handed a job is a push notification in the real product, not something
  // you discover by re-reading your own screen. Fire it once per incident, per
  // courier, so a state tick every second does not re-alert forever.
  const h = job && job.reassigned && job.driver_id === drv.id ? job.handover : null;
  if (h && h.incident_id && App.seenHandover[drv.id] !== h.incident_id) {
    App.seenHandover[drv.id] = h.incident_id;
    courierToast(
      `${h.reason_icon || '📦'} New job: ${job.id}`,
      `Collect at ${h.collect_at || 'the handover point'} · ETA ${nf(job.eta_minutes, 0)} min`
    );
  }
}

/* The rider's own route. The operations map shows the whole city, which is not
   what the person on the bike needs: they need their next two moves. This fits
   the view to just their leg(s) — current position, the collection point if the
   job was transferred to them, and the drop — so the geometry is legible at
   phone size. Same coordinates and same projector as the fleet map, so the two
   views can never disagree about where anything is. */
function courierRoute(job, drv) {
  const st = App.state;
  if (!st || !job || !drv || !job.destination_at) return '';

  const from = drv.at;
  const collect = job.reassigned && job.driver_id === drv.id ? job.handover_at : null;
  const drop = job.destination_at;
  const legPts = [from, collect, drop].filter(Boolean);
  if (legPts.length < 2) return '';

  // Fit to the rider's own leg rather than the city, with a margin so the
  // markers and their labels are never clipped at the edge.
  const lats = legPts.map((p) => p[0]);
  const lons = legPts.map((p) => p[1]);
  const padLat = Math.max((Math.max(...lats) - Math.min(...lats)) * 0.42, 0.008);
  const padLon = Math.max((Math.max(...lons) - Math.min(...lons)) * 0.42, 0.008);
  const b = {
    min_lat: Math.min(...lats) - padLat, max_lat: Math.max(...lats) + padLat,
    min_lon: Math.min(...lons) - padLon, max_lon: Math.max(...lons) + padLon,
  };
  const W = 640, H = 230, P = 24;
  const proj = projector(b, W, H, P);
  const inView = (p) =>
    p[0] >= b.min_lat && p[0] <= b.max_lat && p[1] >= b.min_lon && p[1] <= b.max_lon;

  const nodeById = {};
  (st.map.nodes || []).forEach((n) => { nodeById[n.id] = n; });

  // Context: the surrounding road graph, kept deliberately faint.
  const roads = (st.map.roads || []).map((r) => {
    const a = nodeById[r.from], c = nodeById[r.to];
    if (!a || !c) return '';
    const [x1, y1] = proj(a.at[0], a.at[1]);
    const [x2, y2] = proj(c.at[0], c.at[1]);
    return `<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}"
                  x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}" class="crt-road"/>`;
  }).join('');

  const places = (st.map.nodes || []).filter((n) => inView(n.at)).map((n) => {
    const [x, y] = proj(n.at[0], n.at[1]);
    return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="2.2" class="crt-node"/>
            <text x="${(x + 6).toFixed(1)}" y="${(y + 3).toFixed(1)}"
                  class="crt-place">${esc(n.name)}</text>`;
  }).join('');

  const pt = (p) => proj(p[0], p[1]);
  const [fx, fy] = pt(from);
  const [dx, dy] = pt(drop);

  let legs = '', marks = '';
  if (collect) {
    const [cx, cy] = pt(collect);
    // Two legs, drawn differently because they mean different things: ride to
    // the payload, then carry it to the recipient.
    legs = `
      <line x1="${fx.toFixed(1)}" y1="${fy.toFixed(1)}"
            x2="${cx.toFixed(1)}" y2="${cy.toFixed(1)}" class="crt-leg collect"/>
      <line x1="${cx.toFixed(1)}" y1="${cy.toFixed(1)}"
            x2="${dx.toFixed(1)}" y2="${dy.toFixed(1)}" class="crt-leg deliver"/>`;
    marks = `
      <g class="crt-mk collect">
        <circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="6"/>
        <text x="${(cx + 10).toFixed(1)}" y="${(cy - 7).toFixed(1)}">1 · Collect payload</text>
      </g>`;
  } else {
    legs = `<line x1="${fx.toFixed(1)}" y1="${fy.toFixed(1)}"
                  x2="${dx.toFixed(1)}" y2="${dy.toFixed(1)}" class="crt-leg deliver"/>`;
  }

  const n1 = collect ? '2' : '1';
  marks = `
    <g class="crt-mk you">
      <circle cx="${fx.toFixed(1)}" cy="${fy.toFixed(1)}" r="7"/>
      <text x="${(fx + 11).toFixed(1)}" y="${(fy + 4).toFixed(1)}">You</text>
    </g>` + marks + `
    <g class="crt-mk drop">
      <circle cx="${dx.toFixed(1)}" cy="${dy.toFixed(1)}" r="6"/>
      <text x="${(dx + 10).toFixed(1)}" y="${(dy + 4).toFixed(1)}">${n1} · ${esc(job.destination_name)}</text>
    </g>`;

  const legend = collect
    ? `<span><i class="crt-sw collect"></i>ride to the payload</span>
       <span><i class="crt-sw deliver"></i>carry it to ${esc(job.recipient)}</span>`
    : `<span><i class="crt-sw deliver"></i>to ${esc(job.recipient)} at ${esc(job.destination_name)}</span>`;

  return `
    <div class="cr-route">
      <div class="cr-route-h">
        <h3>Your route</h3>
        <span class="mono">${collect ? 'two legs · collect, then deliver' : 'direct'}</span>
      </div>
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"
           role="img" aria-label="Your route">
        <g>${roads}</g><g>${places}</g><g>${legs}</g><g>${marks}</g>
      </svg>
      <div class="cr-route-legend">${legend}</div>
    </div>`;
}

function courierToast(title, body) {
  // Append to body, NOT to #courier: renderCourier() replaces that element's
  // innerHTML on every state tick, which destroyed the toast about once a
  // second and made it effectively invisible. It is position:fixed anyway.
  const t = el('div', 'cr-toast');
  t.innerHTML = `<b>${esc(title)}</b><span>${esc(body)}</span>`;
  document.body.appendChild(t);
  // Leave long enough to read, then remove so it cannot stack up over a demo.
  setTimeout(() => { t.classList.add('out'); }, 6000);
  setTimeout(() => { t.remove(); }, 6600);
}

$('#courier').addEventListener('click', (e) => {
  const pick = e.target.closest('.cr-pick');
  if (pick) {
    App.courierId = pick.dataset.driver;
    renderCourier();
    return;
  }
  // A rider raising a problem from the field. trigger='courier' so the log and
  // the incident card show where it came from — a report, not a console click.
  const report = e.target.closest('.cr-rbtn');
  if (report && !report.disabled && report.dataset.job) {
    report.classList.add('sent');
    post('/api/disrupt', {
      delivery_id: report.dataset.job,
      disruption: report.dataset.disruption,
      trigger: 'courier',
    });
  }
});

$('#view-toggle').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-view]');
  if (!b) return;
  App.view = b.dataset.view;
  document.querySelectorAll('#view-toggle button').forEach((x) =>
    x.classList.toggle('on', x.dataset.view === App.view));
  document.querySelector('.app').classList.toggle('view-courier', App.view === 'courier');
  if (App.view === 'courier') renderCourier(); else renderMap();
});

/* ================================================================== MAP === */

function projector(bounds, w, h, pad) {
  const { min_lat, max_lat, min_lon, max_lon } = bounds;
  const dLat = (max_lat - min_lat) || 1e-6;
  const dLon = (max_lon - min_lon) || 1e-6;
  return (lat, lon) => [
    pad + ((lon - min_lon) / dLon) * (w - pad * 2),
    pad + (1 - (lat - min_lat) / dLat) * (h - pad * 2),
  ];
}

function renderMap() {
  const svg = $('#map');
  const st = App.state;
  const map = st.map;
  const W = MAP_W, H = MAP_H;
  const P = svg.clientWidth < 520 ? 34 : 56;
  const proj = projector(map.bounds, W, H, P);
  svg.innerHTML = '';

  // Zooming the viewBox magnifies everything, including 9px labels and 4px dots,
  // which turns a zoomed-in map into a screen of giant text. Counter-scale every
  // size by the zoom so glyphs and markers keep their on-screen size and only
  // the geography spreads out. Stroke widths are handled in CSS by
  // vector-effect: non-scaling-stroke.
  const k = 1 / clampCamera().z;

  const gRoads = svgEl('g'), gNodes = svgEl('g'),
        gRoutes = svgEl('g'), gMarks = svgEl('g');

  // --- roads ---
  const nodeById = {};
  map.nodes.forEach((n) => { nodeById[n.id] = n; });
  map.roads.forEach((r) => {
    const a = nodeById[r.from], b = nodeById[r.to];
    if (!a || !b) return;
    const [x1, y1] = proj(a.at[0], a.at[1]);
    const [x2, y2] = proj(b.at[0], b.at[1]);
    gRoads.appendChild(svgEl('line', { x1, y1, x2, y2, class: 'road' }));
  });

  // --- nodes ---
  map.nodes.forEach((n) => {
    const [x, y] = proj(n.at[0], n.at[1]);
    const key = n.kind === 'hub' || n.kind === 'phc';
    if (n.kind === 'hub') {
      gNodes.appendChild(svgEl('rect', {
        x: x - 4.5 * k, y: y - 4.5 * k, width: 9 * k, height: 9 * k,
        rx: 2 * k, class: 'node-hub',
      }));
    } else {
      gNodes.appendChild(svgEl('circle', {
        cx: x, cy: y, r: (key ? 3.6 : 2.6) * k,
        class: n.kind === 'phc' ? 'node-phc' : 'node-dot',
      }));
    }
    const t = svgEl('text', {
      x: x + 8 * k, y: y + 3.4 * k, class: 'node-label' + (key ? ' key' : ''),
      style: `font-size:${(key ? 9.5 : 8.5) * k}px`,
    });
    t.textContent = n.name;
    gNodes.appendChild(t);
  });

  // --- routes ---
  st.deliveries.forEach((d) => {
    if (!d.driver_at) return;
    const [dx, dy] = proj(d.driver_at[0], d.driver_at[1]);
    const [ex, ey] = proj(d.destination_at[0], d.destination_at[1]);

    // Build the path the ETA was actually computed from: a reassigned driver
    // collects the payload at the handover point first, then delivers. Drawing a
    // straight line to the destination would contradict the stated ETA.
    const legs = [[dx, dy]];
    if (d.handover_at) {
      const [hx, hy] = proj(d.handover_at[0], d.handover_at[1]);
      legs.push([hx, hy]);
      gRoutes.appendChild(svgEl('circle', {
        cx: hx, cy: hy, r: 3.2 * k, class: 'handover',
      }));
    }
    if (d.reroute) {
      const via = nodeById[d.reroute.via];
      if (via) legs.push(proj(via.at[0], via.at[1]));
    }
    legs.push([ex, ey]);
    const path = 'M ' + legs.map(([x, y]) => `${x} ${y}`).join(' L ');

    const cls = d.status === 'Reassigned' || d.status === 'Rerouted'
      ? 'route route-new'
      : d.risk_band === 'critical' || d.risk_band === 'elevated'
        ? 'route route-risk' : 'route route-live';

    const p = svgEl('path', { d: path, class: cls });
    if (cls.includes('route-new')) {
      gRoutes.appendChild(p);
      const len = p.getTotalLength ? p.getTotalLength() : 400;
      p.setAttribute('stroke-dasharray', len);
      p.style.setProperty('--len', len);
      p.classList.add('route-draw');
    } else {
      gRoutes.appendChild(p);
    }
  });

  // --- driver markers ---
  const carrying = new Set(st.deliveries.map((d) => d.driver_id));
  st.drivers.forEach((drv) => {
    const [x, y] = proj(drv.at[0], drv.at[1]);
    const kind = drv.status === 'unavailable' ? 'down'
      : App.pickedDriver === drv.id ? 'picked'
      : carrying.has(drv.id) ? 'assigned' : 'standby';
    const g = svgEl('g', { class: 'mk mk-' + kind });
    if (kind !== 'standby') g.appendChild(svgEl('circle', { cx: x, cy: y, r: 7, class: 'mk-halo' }));
    g.appendChild(svgEl('circle', { cx: x, cy: y, r: kind === 'standby' ? 3.4 : 4.6, class: 'mk-body' }));
    if (kind !== 'standby') {
      const t = svgEl('text', { x: x + 8, y: y - 5, class: 'mk-name' });
      t.textContent = drv.name.split(' ')[0];
      g.appendChild(t);
    }
    gMarks.appendChild(g);
  });

  svg.append(gRoads, gNodes, gRoutes, gMarks);
  applyCamera();
  wireMapCamera();

  const down = st.drivers.filter((d) => d.status === 'unavailable').length;
  $('#map-foot').textContent =
    `${map.nodes.length} nodes · ${map.roads.length} corridors · ` +
    `${st.drivers.length} drivers (${carrying.size} carrying, ${down} unavailable) · ` +
    `positions from real coordinates, distances via haversine × circuity`;
}

/* ================================================================= FEED === */

function feedEl() { return $('#feed'); }

function startChain(ev) {
  const feed = feedEl();
  const empty = $('#feed-empty');
  if (empty) empty.remove();

  // Collapse whatever chain was on screen into a one-line summary.
  if (App.chain) collapseChain();

  const root = el('div', 'chain');
  const auto = ev.trigger !== 'manual';
  root.innerHTML =
    `<div class="inc-head ${auto ? 'auto' : ''}">
       <div class="inc-top">
         <span class="inc-ic">${ev.disruption_icon}</span>
         <span class="inc-t">${esc(ev.disruption_label)} · ${esc(ev.delivery_id)}</span>
         <span class="inc-id">${esc(ev.incident_id)}</span>
       </div>
       <div class="inc-detect">Detected by ${esc(ev.detected_as)}. Predicted failure risk
         at detection: <b>${(ev.risk_before.risk * 100).toFixed(0)}%</b>
         (${esc(ev.risk_before.band)}).</div>
       ${auto ? `<div class="inc-trigger">◈ self-triggered · ${esc(ev.trigger)} · no human input</div>` : ''}
     </div>
     <div class="spine"><div class="spine-fill"></div></div>`;

  feed.prepend(root);
  App.chain = {
    root,
    spine: root.querySelector('.spine'),
    fill: root.querySelector('.spine-fill'),
    cards: {},
    summary: { icon: ev.disruption_icon, label: ev.disruption_label, id: ev.delivery_id },
  };
  setFeedStatus('running', 'chain running');
}

function collapseChain() {
  const c = App.chain;
  if (!c) return;
  const s = c.summary;
  const row = el('div', 'past-row');
  row.innerHTML =
    `<span class="pi">${s.icon}</span>
     <span class="pt">${esc(s.label)} · ${esc(s.id)}</span>
     <span class="ps">${s.seconds != null ? s.seconds + 's' : 'incomplete'}</span>`;
  c.root.replaceWith(row);
  App.chain = null;
}

const PATH_STYLE = {
  'full chain':    { cls: 'p-full', label: 'FULL CHAIN' },
  'partial chain': { cls: 'p-part', label: 'PARTIAL CHAIN' },
  'deterministic': { cls: 'p-det',  label: 'NO AGENTS NEEDED' },
  'escalate':      { cls: 'p-esc',  label: 'ESCALATE' },
};

/* The routing decision — which roles this incident actually deserves. Rendered
   before any agent runs, so the judge sees the choice being made. */
function planCard(ev) {
  const c = App.chain; if (!c) return;
  const style = PATH_STYLE[ev.path] || PATH_STYLE['partial chain'];
  const runs = new Set(ev.agents);
  const reasonBy = {};
  (ev.skipped || []).forEach((s) => { reasonBy[s.agent] = s.reason; });

  const chips = ev.specs.map((s) => {
    const on = runs.has(s.id);
    return `<span class="rchip ${on ? 'on' : 'off'}"
              title="${esc(on ? s.owns : reasonBy[s.id] || 'skipped')}">
              <i>${s.icon}</i>${esc(s.label.replace(' Agent', ''))}
            </span>`;
  }).join('');

  const card = el('div', 'pcard ' + style.cls);
  card.innerHTML =
    `<div class="pc-head">
       <span class="pc-tag">router</span>
       <span class="pc-path">${style.label}</span>
       <span class="pc-count">${ev.agents.length}/${ev.total} roles
         ${ev.saved ? `· <b>${ev.saved} AI call${ev.saved === 1 ? '' : 's'} avoided</b>` : ''}</span>
     </div>
     <div class="pc-chips">${chips}</div>
     <div class="pc-reason">${esc(ev.reason)}</div>`;
  c.spine.appendChild(card);
  feedEl().scrollTop = 0;
}

/* A role the router decided had nothing to decide. Shown, not hidden — otherwise
   the smartest part of the system is invisible. */
function skippedCard(ev) {
  const c = App.chain; if (!c) return;
  const card = el('div', 'acard skipped');
  card.innerHTML =
    `<div class="ac-head">
       <span class="ac-ic">${ev.icon}</span>
       <div>
         <div class="ac-name">${esc(ev.label)}</div>
         <div class="ac-owns">skipped — ${esc(ev.reason)}</div>
       </div>
       <span class="ac-time">0.0s</span>
     </div>`;
  c.spine.appendChild(card);
}

/* The Resource Agent doesn't describe a reassignment — it invokes one. Showing
   the actual call is the clearest answer to "your agents just write sentences". */
function toolCallCard(ev) {
  const c = App.chain; if (!c) return;
  const args = Object.entries(ev.input || {})
    .filter(([k]) => k !== 'rationale')
    .map(([k, v]) => `<span class="tk-k">${esc(k)}</span>=<span class="tk-v">${esc(JSON.stringify(v))}</span>`)
    .join('<span class="tk-c">, </span>');
  const card = el('div', 'kcard');
  card.innerHTML =
    `<div class="kc-head">
       <span class="kc-tag">${ev.validated ? 'schema-validated tool call' : 'tool call · deterministic'}</span>
     </div>
     <div class="kc-sig"><b>${esc(ev.name)}</b>(${args})</div>`;
  c.spine.appendChild(card);
}

/* Every number the Coordinator states is checked against the numbers it was
   given. It summarises, so it is the highest hallucination risk in the chain. */
/* The pre-commit conflict check, as a card in the feed. Shows every option and
   every intent evaluated — including the ones that passed — because a judge
   asking "did that actually run?" needs to see the whole matrix, not just the
   failures. */
function intentCheckCard(ev) {
  const c = App.chain;
  if (!c) return;
  const card = el('div', 'icard');
  const rows = (ev.options || []).map(o => {
    const hard = (o.results || []).filter(r => r.verdict === 'violated' && r.hardness === 'hard');
    const soft = (o.results || []).filter(r => r.verdict === 'violated' && r.hardness === 'soft');
    const risk = (o.results || []).filter(r => r.verdict === 'at_risk');
    const tags = [
      ...hard.map(r => `<span class="ic-t hard">${esc(r.holder)}: ${esc(r.kind)}</span>`),
      ...soft.map(r => `<span class="ic-t soft">${esc(r.holder)}: ${esc(r.kind)}</span>`),
      ...risk.map(r => `<span class="ic-t risk">${esc(r.holder)}: tight</span>`),
    ].join('');
    return `<div class="ic-row ${o.clear ? 'ok' : 'blocked'}">
      <span class="ic-verdict">${o.clear ? 'CLEAR' : 'BLOCKED'}</span>
      <span class="ic-who">#${o.rank} ${esc(o.name)}</span>
      <span class="ic-eta mono">${nf(o.eta_minutes, 0)} min</span>
      <span class="ic-tags">${tags || '<span class="ic-t none">no conflict</span>'}</span>
    </div>`;
  }).join('');
  card.innerHTML =
    `<div class="ic-top">
       <span class="ic-mark">&#9878;</span>
       <span class="ic-title">Intent conflict check</span>
       <span class="ic-clock mono">${esc(ev.clock || '')}</span>
     </div>
     <div class="ic-sub">${ev.intents_active} stated intent(s) checked against
       ${(ev.options || []).length} option(s) before proposing anything &middot;
       <b>${ev.clear_count} clear</b>, ${ev.blocked_count} blocked</div>
     <div class="ic-rows">${rows}</div>`;
  c.root.appendChild(card);
  feedEl().scrollTop = 0;
}

/* The gate. This is the moment the system declines to do the thing it would
   otherwise have done. */
function intentGateCard(ev) {
  const c = App.chain;
  if (!c) return;
  const escalated = ev.resolution === 'escalated';
  const card = el('div', 'gcard' + (escalated ? ' esc' : ''));
  const why = (ev.blocking || []).map(v => {
    const e = v.evidence || {};
    const nums = Object.keys(e)
      .filter(k => k !== 'basis')
      .map(k => `<span class="gc-n"><i>${esc(k.replace(/_/g, ' '))}</i>${esc(String(e[k]))}</span>`)
      .join('');
    return `<div class="gc-v">
        <div class="gc-say">${esc(v.holder)} &mdash; &ldquo;${esc(v.statement)}&rdquo;</div>
        <div class="gc-nums">${nums}</div>
        <div class="gc-hint">${esc(v.hint || '')}</div>
      </div>`;
  }).join('');
  card.innerHTML =
    `<div class="gc-top">
       <span class="gc-mark">${escalated ? '&#9888;' : '&#8631;'}</span>
       <span class="gc-title">${escalated
          ? 'Blocked before commit &mdash; handed to a person'
          : 'Blocked before commit &mdash; re-selected'}</span>
     </div>
     <div class="gc-body">
       <div class="gc-line">Would have committed
         <b>${esc(ev.blocked_driver_name)}</b>. Stopped because:</div>
       ${why}
       <div class="gc-out">${escalated
          ? 'No available option satisfies every stated intent. Nothing was committed &mdash; a human decides which goal gives way.'
          : `Committed <b>${esc(ev.substitute_driver_name || '')}</b> instead &mdash; the best option that breaks no stated intent.`}</div>
     </div>`;
  c.root.appendChild(card);
  feedEl().scrollTop = 0;
}

function verificationBadge(ev) {
  const c = App.chain; if (!c) return;
  const card = el('div', 'vcard ' + (ev.passed ? 'ok' : 'bad'));
  card.innerHTML = ev.passed
    ? `<span class="vc-tick">✓</span><span>Facts verified — all
         <b>${ev.claims_checked}</b> figures in the summary trace to its input</span>`
    : `<span class="vc-tick">!</span><span>Fact check <b>failed</b> —
         ${esc(JSON.stringify(ev.unverified))} appear nowhere in the input.
         Treat this summary as unreliable.</span>`;
  c.spine.appendChild(card);
  feedEl().scrollTop = 0;
}

/* The handoff, shown as evidence rather than asserted. Each agent's prompt
   contains the previous agents' conclusions verbatim; this renders exactly that
   list, so "the agents communicated" is something a reader can check instead of
   believe. Collapsed by default via <details> — native, no icon font needed. */
function handoffBlock(ev) {
  const got = ev.received || [];
  const extras = (ev.extra_keys || []).length
    ? `<div class="hx-extra">plus computed input: ${(ev.extra_keys || [])
         .map((k) => `<code>${esc(k)}</code>`).join(', ')}</div>`
    : '';
  if (!got.length) {
    return `<details class="handoff">
      <summary>Input &middot; first in the chain &middot; ${ev.prompt_chars || 0} chars</summary>
      <div class="hx-body">
        <div class="hx-none">No prior agent output — this agent starts the chain and
        works only from the incident telemetry and model output.</div>
        ${extras}
      </div></details>`;
  }
  const rows = got.map((p) => `
    <div class="hx-row">
      <div class="hx-from">${esc(p.label)}</div>
      <div class="hx-text">${esc(p.text)}</div>
    </div>`).join('');
  return `<details class="handoff">
    <summary>Input &middot; received ${got.length} prior
      ${got.length === 1 ? 'decision' : 'decisions'} &middot; ${ev.prompt_chars || 0} chars</summary>
    <div class="hx-body">
      <div class="hx-lead">Passed into this agent's prompt verbatim:</div>
      ${rows}
      ${extras}
    </div></details>`;
}

function agentStart(ev) {
  const c = App.chain; if (!c) return;
  const card = el('div', 'acard active');
  card.innerHTML =
    `<div class="ac-head">
       <span class="ac-ic">${ev.icon}</span>
       <div>
         <div class="ac-name">${esc(ev.label)}</div>
         <div class="ac-owns">${esc(ev.owns)}</div>
       </div>
       <span class="ac-time"></span>
     </div>
     ${handoffBlock(ev)}
     <div class="acard-body"></div>`;
  c.spine.appendChild(card);
  c.cards[ev.agent] = card;
  card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function agentDelta(ev) {
  const c = App.chain; if (!c) return;
  const card = c.cards[ev.agent]; if (!card) return;
  const body = card.querySelector('.acard-body');
  // Strip the machine-readable PICK directive from the visible text.
  body.textContent = (body.textContent + ev.text).replace(/PICK\s*:\s*[A-Za-z]{2,3}-\d{1,4}\s*/i, '');
  feedEl().scrollTop = 0;
}

function agentDone(ev) {
  const c = App.chain; if (!c) return;
  const card = c.cards[ev.agent]; if (!card) return;
  card.classList.remove('active');
  card.classList.add('settled');
  card.querySelector('.acard-body').textContent =
    String(ev.text).replace(/PICK\s*:\s*[A-Za-z]{2,3}-\d{1,4}\s*/i, '').trim();

  const t = card.querySelector('.ac-time');
  const tok = ev.tokens && ev.tokens.output ? `<em>${ev.tokens.output} tok</em>` : '';
  t.innerHTML = `${ev.ms != null ? (ev.ms / 1000).toFixed(1) + 's' : ''}${tok}`;

  if (ev.source && ev.source !== 'live') {
    const s = el('div', 'src fb', `simulated · ${esc(ev.note || 'deterministic fallback')}`);
    card.appendChild(s);
  } else if (ev.model) {
    card.appendChild(el('div', 'src', `live · ${esc(ev.model)}`));
  }

  // Advance the spine to this node.
  App.chain.fill.style.height = (card.offsetTop + 19) + 'px';
}

function toolCard(ev) {
  const c = App.chain; if (!c) return;
  const card = el('div', 'tcard');
  let inner = '';

  if (ev.name === 'route.alternates') {
    const arr = ev.result;
    const direct = arr[0].direct;
    const alts = arr.slice(1);
    inner =
      `<div class="tc-list">
         <div class="tc-item"><span class="rk">—</span>
           <span class="nm">Direct path <span>${nf(direct.distance_km, 1)} km${
             direct.penalty_minutes ? ` · +${nf(direct.penalty_minutes, 0)} min disruption penalty` : ''
           }</span></span>
           <span class="sc">${nf(direct.minutes, 0)} min</span></div>
         ${alts.map((a, i) => `
           <div class="tc-item ${a.added_minutes <= 0 ? 'top' : ''}"><span class="rk">${i + 1}</span>
             <span class="nm">via ${esc(a.via_name)} <span>${nf(a.distance_km, 1)} km</span></span>
             <span class="sc">${a.added_minutes <= 0 ? '' : '+'}${nf(a.added_minutes, 0)} min</span></div>`).join('')}
       </div>`;
  } else if (ev.name === 'reassignment.rank') {
    const r = ev.result;
    inner =
      `<div class="tc-list">
         ${r.candidates.map((cd) => `
           <div class="tc-item ${cd.rank === 1 ? 'top' : ''}"><span class="rk">${cd.rank}</span>
             <span class="nm">${esc(cd.name)} <span>${nf(cd.distance_km, 1)} km · ETA ${nf(cd.eta_minutes, 0)} min</span></span>
             <span class="sc">${nf(cd.suitability, 3)}</span></div>`).join('')}
       </div>
       ${r.rejected && r.rejected.length ? `<div class="tc-rej"><b>Excluded by hard constraints:</b> ${
         r.rejected.map((x) => `${esc(x.name)} (${esc(x.reason)})`).join('; ')
       }</div>` : ''}
       <div class="tc-rej">Pickup point: <b>${esc(r.pickup_label)}</b></div>`;
  } else {
    inner = `<pre class="tc-rej">${esc(JSON.stringify(ev.result).slice(0, 400))}</pre>`;
  }

  card.innerHTML =
    `<div class="tc-head"><span class="tc-tag">model</span><span>${esc(ev.name)}</span></div>
     <div class="tc-title">${esc(ev.title)}</div>
     <div class="tc-detail">${esc(ev.detail)}</div>${inner}`;
  c.spine.appendChild(card);
  feedEl().scrollTop = 0;
}

function selectionCard(ev) {
  const c = App.chain; if (!c) return;
  App.pickedDriver = ev.driver_id;
  const top = ev.contributions.slice(0, 5);
  const max = Math.max(...top.map((x) => x.contribution), 1e-6);
  const card = el('div', 'scard');
  const how = ev.by_model_only
    ? 'selected by the ranker · no agent needed'
    : (ev.retained ? 'assignment retained' : 'driver selected');
  card.innerHTML =
    `<div class="sc-k">${how} · rank ${ev.rank}${
       ev.margin_over_next != null ? ` · +${nf(ev.margin_over_next, 3)} over next` : ''}</div>
     <div class="sc-name">${esc(ev.driver_name)}</div>
     <div class="sc-sub">${nf(ev.distance_km, 1)} km from pickup · ETA ${nf(ev.eta_minutes, 0)} min ·
       suitability ${nf(ev.suitability, 3)}</div>
     <div class="sc-attr">
       <div class="sc-attr-k">Why this driver — feature contributions</div>
       ${top.map((x) => `
         <div class="attr">
           <span class="al">${esc(x.label)}</span>
           <span class="ab"><i style="width:${((x.contribution / max) * 100).toFixed(1)}%"></i></span>
           <span class="av">${nf(x.contribution, 3)}</span>
         </div>`).join('')}
     </div>`;
  c.spine.appendChild(card);
  renderMap();
}

function impactCard(ev) {
  const c = App.chain; if (!c) return;
  const e = ev.entry;
  const cells = [
    { v: nf(e.km_avoided, 1), k: 'km redelivery avoided' },
    { v: nf(e.co2e_kg_avoided, 2), k: 'kg CO₂e avoided' },
  ];
  if (e.doses_preserved) cells.push({ v: e.doses_preserved, k: 'doses preserved' });
  cells.push({ v: nf(e.coordinator_minutes_saved, 0), k: 'coordinator min saved' });

  const card = el('div', 'icard');
  card.innerHTML =
    `<div class="ic-k">impact ledger · estimate</div>
     <div class="ic-grid">${cells.map((x) =>
       `<div class="ic-cell"><div class="cv">${x.v}</div><div class="ck">${esc(x.k)}</div></div>`).join('')}
     </div>
     <div class="ic-deriv">${esc(ev.derivation)}</div>`;
  c.spine.appendChild(card);
}

function resolvedCard(ev) {
  const c = App.chain; if (!c) return;
  c.summary.seconds = ev.seconds;
  const facts = [
    `<b>0</b> human interventions`,
    `risk <b>${(ev.risk_before * 100).toFixed(0)}% → ${(ev.risk_after * 100).toFixed(0)}%</b>`,
    `ETA <b>${nf(ev.eta_minutes, 0)} min</b>`,
    ev.reassigned ? `now with <b>${esc(ev.new_driver)}</b>` : `retained <b>${esc(ev.new_driver)}</b>`,
    `<b>${ev.calls_made}</b> AI call${ev.calls_made === 1 ? '' : 's'}${
      ev.calls_saved ? `, <b>${ev.calls_saved}</b> avoided` : ''}`,
  ];
  const card = el('div', 'rescard');
  card.innerHTML =
    `<div class="rc-top">
       <span class="rc-tick"><svg viewBox="0 0 24 24"><path d="M5 13l4 4L19 7"/></svg></span>
       <span class="rc-t">Resolved autonomously</span>
       <span class="rc-time">${nf(ev.seconds, 1)}s</span>
     </div>
     <div class="rc-body">${esc(ev.summary)}</div>
     <div class="rc-facts">${facts.map((f) => `<span class="fact">${f}</span>`).join('')}</div>`;
  c.root.appendChild(card);
  setFeedStatus('done', `resolved in ${nf(ev.seconds, 1)}s`);
  App.pickedDriver = null;
}

function escalatedCard(ev) {
  const c = App.chain; if (!c) return;
  c.summary.seconds = ev.seconds;
  const card = el('div', 'esccard');
  card.innerHTML =
    `<div class="rc-top">
       <span class="rc-tick"><svg viewBox="0 0 24 24"><path d="M12 8v5M12 16.5v.5"/></svg></span>
       <span class="rc-t">Escalated to a human</span>
       <span class="rc-time">${nf(ev.seconds, 1)}s</span>
     </div>
     <div class="rc-body">${esc(ev.reason)} The system did not resolve this and says so
       rather than reporting a false success.</div>`;
  c.root.appendChild(card);
  setFeedStatus('', 'escalated');
}

function abortedCard(ev) {
  const c = App.chain;
  App.pickedDriver = null;
  if (!c) return;
  c.summary.seconds = ev.seconds;
  const card = el('div', 'esccard');
  card.innerHTML =
    `<div class="rc-top">
       <span class="rc-tick"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></span>
       <span class="rc-t">Incident abandoned</span>
       <span class="rc-time">${nf(ev.seconds, 1)}s</span>
     </div>
     <div class="rc-body">Aborted at the <b>${esc(ev.stage)}</b> stage — ${esc(ev.reason)}.
       No partial decision was applied and nothing was counted.</div>`;
  c.root.appendChild(card);
  setFeedStatus('', 'abandoned');
}

function setFeedStatus(cls, text) {
  const n = $('#feed-status');
  n.className = 'feed-status ' + (cls || '');
  $('#feed-status-text').textContent = text;
}

/* ================================================================== LOG === */

function logRow(level, msg) {
  const log = $('#log');
  const now = new Date();
  const ts = [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map((n) => String(n).padStart(2, '0')).join(':');
  const row = el('div', 'lrow ' + (level || ''));
  row.innerHTML = `<span class="lt">${ts}</span><span class="lm">${esc(msg)}</span>`;
  log.prepend(row);
  while (log.childElementCount > 220) log.lastElementChild.remove();
  App.logCount += 1;
  $('#log-sub').textContent = `${App.logCount} event${App.logCount === 1 ? '' : 's'}`;
}

/* =============================================================== DRAWER === */

function renderDrawer() {
  const m = App.meta;
  const body = $('#drawer-body');
  body.innerHTML =
    `<div class="dsec">
       <h3>What is actually being claimed</h3>
       <div class="callout">A disruption resolved while the courier is still in the
       field completes the delivery on the <b>first attempt</b>, so the redelivery
       trip never happens. That avoided trip is the km and the CO₂e counted here.
       Nothing else is claimed. Every factor below is an <b>estimate</b> — re-derive
       each one against its source for your own fleet, region and grid mix before
       publishing any of these numbers.</div>
     </div>

     <div class="dsec">
       <h3>Agent engine</h3>
       <div class="arow">
         <div class="ak"><span class="an">${m.llm.live ? 'Live agents' : 'Simulated agents'}</span>
           <span class="av">${esc(m.llm.model)}</span></div>
         <div class="anote">${esc(m.llm.note)}</div>
       </div>
     </div>

     <div class="dsec">
       <h3>Models</h3>
       <p class="lead">The language agents never do arithmetic. These deterministic
       models compute distance, ETA, risk and driver suitability; the agents receive
       the results and make the judgement call.</p>
       ${m.models.map((mc) => {
         const weights = Object.entries(mc.weights);
         const max = Math.max(...weights.map(([, v]) => Math.abs(v)));
         return `<div class="mcard">
           <div class="mn">${esc(mc.name)}</div>
           <div class="mk">${esc(mc.kind)}</div>
           <div class="mp">${esc(mc.purpose)}</div>
           <div class="mw">${weights.map(([k, v]) => `
             <div class="mwrow">
               <span class="wl">${esc(k)}</span>
               <span class="wb"><i style="width:${((Math.abs(v) / max) * 100).toFixed(0)}%"></i></span>
               <span class="wv">${nf(v, 2)}</span>
             </div>`).join('')}</div>
           <div class="mcav">Caveat: ${esc(mc.caveat)}</div>
         </div>`;
       }).join('')}
     </div>

     <div class="dsec">
       <h3>Assumptions</h3>
       ${m.assumptions.map((a) => `
         <div class="arow">
           <div class="ak"><span class="an">${esc(a.key)}</span><span class="av">${esc(a.value)}</span></div>
           <div class="anote">${esc(a.note)}</div>
           <div class="asrc">${esc(a.source)}</div>
         </div>`).join('')}
     </div>

     <div class="dsec">
       <h3>Emission factors</h3>
       ${m.emission_factors.map((f) => `
         <div class="arow">
           <div class="ak"><span class="an">${esc(f.vehicle)}</span>
             <span class="av">${nf(f.kg_co2e_per_km, 4)} kg/km</span></div>
           <div class="asrc">${esc(f.source)}</div>
         </div>`).join('')}
     </div>

     <div class="dsec">
       <h3>Disruption catalogue</h3>
       ${m.disruptions.map((d) => `
         <div class="arow">
           <div class="ak"><span class="an">${d.icon} ${esc(d.label)}</span>
             <span class="av">${esc(d.severity)}</span></div>
           <div class="anote">Detected by: ${esc(d.detected_as)}</div>
         </div>`).join('')}
     </div>`;
}

function openDrawer(on) {
  $('#drawer').classList.toggle('on', on);
  $('#drawer').setAttribute('aria-hidden', String(!on));
  $('#scrim').classList.toggle('on', on);
}
$('#assumptions-btn').addEventListener('click', () => { renderDrawer(); openDrawer(true); });
$('#drawer-close').addEventListener('click', () => openDrawer(false));
$('#scrim').addEventListener('click', () => openDrawer(false));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') openDrawer(false); });

/* ============================================================= CONTROLS === */

async function post(path, body) {
  try {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const j = await r.json();
    if (!j.ok && j.error) logRow('warn', j.error);
    return j;
  } catch (err) {
    logRow('error', 'request failed: ' + err.message);
  }
}

$('#mode-toggle').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-mode]');
  if (!b || b.classList.contains('on')) return;
  post('/api/mode', { mode: b.dataset.mode });
});

$('#autonomous-btn').addEventListener('click', () => {
  post('/api/autonomous', { enabled: !App.meta.autonomous });
});

$('#reset-btn').addEventListener('click', () => post('/api/reset'));

$('#map-in').addEventListener('click', () => zoomMap(1.5));
$('#map-out').addEventListener('click', () => zoomMap(1 / 1.5));
$('#map-reset').addEventListener('click', resetMapCamera);

function renderControls() {
  const m = App.meta;
  document.querySelectorAll('#mode-toggle button').forEach((b) => {
    b.classList.toggle('on', b.dataset.mode === App.state.mode);
  });
  const ab = $('#autonomous-btn');
  ab.classList.toggle('armed', !!m.autonomous);
  ab.setAttribute('aria-pressed', String(!!m.autonomous));
  $('#autonomous-state').textContent = m.autonomous ? 'ARMED' : 'OFF';

  const badge = $('#engine-badge');
  badge.className = 'engine-badge ' + (m.llm.live ? 'live' : 'sim');
  badge.title = m.llm.note;
  $('#engine-label').textContent = m.llm.live
    ? `LIVE · ${m.llm.model}` : 'SIMULATED AGENTS';
}

/* ================================================================ RENDER == */

let mapDirty = 0;
function renderAll(bumpImpact) {
  renderControls();
  renderImpact(App.state.impact, bumpImpact);
  refreshIntents();
  refreshDecisions();
  renderFleet();
  renderRisk();
  if (App.view === 'courier') {
    renderCourier();
    return;   // the map and fleet list are hidden in this view
  }
  // Redraw the map on a light throttle — telemetry ticks every ~2s.
  const now = Date.now();
  if (now - mapDirty > 400) { mapDirty = now; renderMap(); }
}

/* =================================================================== SSE == */

function connect() {
  const es = new EventSource('/api/stream');

  es.onopen = () => logRow('ok', 'event stream connected');
  es.onerror = () => {
    setFeedStatus('', 'stream lost — retrying');
    $('#engine-label').textContent = 'RECONNECTING…';
  };

  es.onmessage = (msg) => {
    let ev;
    try { ev = JSON.parse(msg.data); } catch { return; }
    handle(ev);
  };
}

function handle(ev) {
  switch (ev.type) {
    case 'hello':
      App.state = ev.state; App.meta = ev.meta;
      renderAll(false);
      logRow('', `AutoFleet AI online · ${ev.state.mode} scenario · ` +
        `${ev.state.deliveries.length} active · agents ${ev.meta.llm.live ? 'LIVE' : 'SIMULATED'}`);
      break;

    case 'mode':
      App.state = ev.state; App.meta = ev.meta;
      if (App.chain) collapseChain();
      feedEl().innerHTML = '';
      feedEl().appendChild(emptyFeedNode());
      setFeedStatus('', 'idle');
      renderAll(false);
      break;

    case 'reset':
      App.state = ev.state;
      if (App.chain) collapseChain();
      feedEl().innerHTML = '';
      feedEl().appendChild(emptyFeedNode());
      setFeedStatus('', 'idle');
      App.pickedDriver = null;
      renderAll(false);
      break;

    case 'autonomous':
      App.meta.autonomous = ev.enabled;
      renderControls();
      break;

    case 'telemetry':
    case 'state':
      App.state = ev.state;
      renderAll(false);
      break;

    case 'chain_start':
      App.meta.llm = ev.llm;
      startChain(ev);
      break;

    case 'plan':             planCard(ev); break;
    case 'tool_call':        toolCallCard(ev); break;
    case 'verification':     verificationBadge(ev); break;
    case 'intent_check':     intentCheckCard(ev); break;
    case 'intent_gate':      intentGateCard(ev); break;
    case 'intents':          renderIntents(ev); break;
    case 'decisions':        renderDecisions(ev); break;
    case 'decision':         refreshDecisions(); break;
    case 'agent_start':      agentStart(ev); break;
    case 'agent_delta':      agentDelta(ev); break;
    case 'agent_done':       agentDone(ev); break;
    case 'agent_skipped':    skippedCard(ev); break;
    case 'tool':             toolCard(ev); break;
    case 'selection':        selectionCard(ev); break;

    case 'impact':
      impactCard(ev);
      App.state.impact = ev.totals;
      renderImpact(ev.totals, true);
      break;

    case 'resolved':         resolvedCard(ev); break;
    case 'escalated':        escalatedCard(ev); refreshDecisions(); break;
    case 'aborted':          abortedCard(ev); break;

    case 'degraded':
      setFeedStatus('running', 'budget spent — finishing deterministically');
      if (App.chain) {
        const n = el('div', 'tcard');
        n.innerHTML =
          `<div class="tc-head"><span class="tc-tag">guard</span><span>chain budget</span></div>
           <div class="tc-title">${ev.budget_seconds}s budget spent — language layer dropped</div>
           <div class="tc-detail">Remaining agents finish from deterministic model
             output. The resolution still completes: the ranker and hard constraints
             already produced the answer.</div>`;
        App.chain.spine.appendChild(n);
      }
      break;

    case 'risk_alert':
      logRow('warn', `RISK ALERT · ${ev.delivery_id} at ${(ev.risk * 100).toFixed(0)}% ` +
        `(threshold ${(ev.threshold * 100).toFixed(0)}%) · inferring ${ev.label}`);
      break;

    case 'log':              logRow(ev.level, ev.msg); break;
  }
}

function emptyFeedNode() {
  const n = el('div', 'feed-empty');
  n.id = 'feed-empty';
  n.innerHTML =
    `<div class="fe-mark"><svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="21"/><path d="M24 13v11l8 5"/></svg></div>
     <p class="fe-title">No active incident</p>
     <p class="fe-sub">Six agents are idle and waiting on an event. Trigger a
     disruption on any delivery, or arm <b>Autonomous</b> and the watchdog will fire
     the chain itself when predicted risk crosses the threshold.</p>`;
  return n;
}

window.addEventListener('resize', () => { if (App.state) renderMap(); });

connect();

/* The register is fetched rather than pushed on boot, then kept current by the
   `intents` event whenever one is switched. */
function refreshIntents() {
  fetch('/api/intents')
    .then(r => r.json())
    .then(renderIntents)
    .catch(() => {});
}

document.getElementById('intents').addEventListener('click', (e) => {
  const btn = e.target.closest('.intent-toggle');
  if (!btn) return;
  const id = btn.dataset.id;
  const active = btn.dataset.next === 'true';
  btn.disabled = true;
  fetch('/api/intents/toggle', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, active }),
  })
    .then(r => r.json())
    .then(() => refreshIntents())
    .catch(() => { btn.disabled = false; });
});

/* Applying a decision. The button carries the action and, for an override, the
   specific intent being withdrawn — so the request says exactly which stated
   goal a person chose to set aside, and the audit trail can name it. */
document.getElementById('decisions').addEventListener('click', (e) => {
  const btn = e.target.closest('.dc-opt');
  if (!btn) return;
  const payload = {
    delivery_id: btn.dataset.delivery,
    action: btn.dataset.action,
    intent_id: btn.dataset.intent || '',
    actor: 'operations desk',
  };
  if (btn.classList.contains('danger') &&
      !window.confirm('Cancel ' + payload.delivery_id +
                      '? Nothing will be delivered today.')) {
    return;
  }
  [...document.querySelectorAll('.dc-opt')].forEach(b => { b.disabled = true; });
  fetch('/api/decisions/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
    .then(r => r.json())
    .then(() => { refreshDecisions(); refreshIntents(); })
    .catch(() => {
      [...document.querySelectorAll('.dc-opt')].forEach(b => { b.disabled = false; });
    });
});

/* The register is reference material, so it stays out of the way until asked
   for. Collapsed it is one line; the deliveries, map and agent feed get the
   vertical space instead. */
document.getElementById('intents-expand').addEventListener('click', () => {
  App.intentsOpen = !App.intentsOpen;
  renderIntents(App.intentsPayload || { intents: App.intents || [] });
});
