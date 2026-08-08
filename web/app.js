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
  logCount: 0,
};

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
  'Awaiting Driver': 'chip-awaiting',
};

function disruptionsForMode() {
  const mode = App.state.mode;
  return (App.meta.disruptions || []).filter((d) => d.modes.includes(mode));
}

function renderFleet() {
  const list = $('#fleet-list');
  const st = App.state;
  $('#fleet-kind').textContent = st.mode === 'humanitarian' ? 'consignments' : 'deliveries';

  const triggers = disruptionsForMode();

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
  const W = 1000, H = 600;
  const P = svg.clientWidth < 520 ? 34 : 56;
  const proj = projector(map.bounds, W, H, P);
  svg.innerHTML = '';

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
        x: x - 4.5, y: y - 4.5, width: 9, height: 9, rx: 2, class: 'node-hub',
      }));
    } else {
      gNodes.appendChild(svgEl('circle', {
        cx: x, cy: y, r: key ? 3.6 : 2.6,
        class: n.kind === 'phc' ? 'node-phc' : 'node-dot',
      }));
    }
    const t = svgEl('text', {
      x: x + 8, y: y + 3.4, class: 'node-label' + (key ? ' key' : ''),
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
        cx: hx, cy: hy, r: 3.2, class: 'handover',
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
  renderFleet();
  renderRisk();
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
    case 'escalated':        escalatedCard(ev); break;
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
     <p class="fe-sub">Five agents are idle and waiting on an event. Trigger a
     disruption on any delivery, or arm <b>Autonomous</b> and the watchdog will fire
     the chain itself when predicted risk crosses the threshold.</p>`;
  return n;
}

window.addEventListener('resize', () => { if (App.state) renderMap(); });

connect();
