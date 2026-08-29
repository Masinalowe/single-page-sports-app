/* Premier League Match Map
 *
 * Reads data/matches.json (see PLAN.md §3) and renders:
 *   - a pin per fixture kicking off today, pulsing while in play
 *   - a hover card with crests, win probability, venue, Pacific kickoff
 *   - a weekly results table, upper right
 *
 * Liveness is derived in the browser (PLAN.md §6, option A): the JSON is a
 * once-daily snapshot, so a baked-in status would go stale by kickoff. We
 * compute it from kickoff_utc against the wall clock instead, re-checking on
 * a ticker.
 */

'use strict';

const DATA_URL = 'data/matches.json';
const LIVE_WINDOW_MIN = 115;   // 90 + half-time + typical stoppage
const TICK_MS = 30_000;
const ENGLAND_BOUNDS = L.latLngBounds([49.9, -6.4], [55.9, 1.9]);

/* ------------------------------------------------------------ formatting */

const paTime = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  weekday: 'short', month: 'short', day: 'numeric',
  hour: 'numeric', minute: '2-digit',
  timeZoneName: 'short',           // resolves to PST or PDT on its own
});

const paDay = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles', weekday: 'short',
});

/** scheduled | live | finished — derived from the clock, not from the file. */
function statusOf(match, now = Date.now()) {
  const kickoff = Date.parse(match.kickoff_utc);
  if (now < kickoff) return 'scheduled';
  if (now < kickoff + LIVE_WINDOW_MIN * 60_000) return 'live';
  return 'finished';
}

/** API probabilities don't always total 100; rescale so the bar fills. */
function normalized(prob) {
  const total = prob.home + prob.draw + prob.away;
  if (!total) return { home: 34, draw: 33, away: 33 };
  const home = Math.round((prob.home / total) * 100);
  const draw = Math.round((prob.draw / total) * 100);
  return { home, draw, away: 100 - home - draw };
}

const esc = (s) => String(s).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ------------------------------------------------------------------- map */

const map = L.map('map', {
  zoomControl: false,
  attributionControl: true,
  minZoom: 5,
  maxZoom: 11,
  maxBounds: ENGLAND_BOUNDS.pad(0.35),   // let them roam a little, not to Germany
  maxBoundsViscosity: 0.75,
}).fitBounds(ENGLAND_BOUNDS, { paddingTopRight: [290, 0] });  // clear the results panel

L.control.zoom({ position: 'bottomright' }).addTo(map);

// Esri's Dark Gray Canvas: genuinely dark and keyless, unlike CARTO's dark
// basemap which now requires one. An earlier version inverted light OSM tiles
// in CSS instead, but filtering the tile pane composites every 256px tile
// separately and left visible seams across the map. A natively dark basemap
// needs no filter, so there are no seams to hide.
//
// Base carries no labels — the reference layer draws place names over it.
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas';

L.tileLayer(`${ESRI}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, {
  attribution: 'Esri, HERE, Garmin, &copy; OpenStreetMap contributors',
  maxZoom: 11,
}).addTo(map);

L.tileLayer(`${ESRI}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, {
  maxZoom: 11,
}).addTo(map);

/* ------------------------------------------------------------- hovercard */

const card = document.getElementById('hovercard');

function cardHTML(match, status) {
  const kickoff = new Date(match.kickoff_utc);

  const label = status === 'live' ? 'Live now'
              : status === 'finished' ? 'Full time'
              : 'Kickoff';

  const middle = match.score
    ? `<div class="hc-vs score">${match.score.home}&ndash;${match.score.away}</div>`
    : `<div class="hc-vs">vs</div>`;

  // The Odds API drops an event at kickoff, so a match we first saw after it
  // started has no prices to show. Omit the bar rather than faking one.
  const p = match.probability ? normalized(match.probability) : null;
  const probBlock = p ? `
    <div class="hc-prob-label">Win probability</div>
    <div class="hc-bar">
      <span class="b-home" style="width:${p.home}%"></span>
      <span class="b-draw" style="width:${p.draw}%"></span>
      <span class="b-away" style="width:${p.away}%"></span>
    </div>
    <div class="hc-pcts">
      <div class="p-home"><b>${p.home}%</b><span class="lbl">HOME</span></div>
      <div class="p-draw"><b>${p.draw}%</b><span class="lbl">DRAW</span></div>
      <div class="p-away"><b>${p.away}%</b><span class="lbl">AWAY</span></div>
    </div>` : `
    <div class="hc-prob-label">Win probability</div>
    <div class="hc-noprob">No odds published for this match</div>`;

  return `
    <div class="hc-status ${status === 'live' ? 'live' : ''}">${label}</div>

    <div class="hc-teams">
      <div class="hc-team">
        <img src="${esc(match.home.logo)}" alt="" loading="lazy">
        <div class="nm">${esc(match.home.name)}</div>
      </div>
      ${middle}
      <div class="hc-team">
        <img src="${esc(match.away.logo)}" alt="" loading="lazy">
        <div class="nm">${esc(match.away.name)}</div>
      </div>
    </div>

    ${probBlock}

    <div class="hc-meta">
      <div class="venue">${esc(match.venue.name)}</div>
      <div class="when">${esc(paTime.format(kickoff))}</div>
    </div>`;
}

/** Place the card near the pin, nudged to stay inside the viewport. */
function positionCard(pt) {
  const GAP = 16, PAD = 10;
  const { offsetWidth: w, offsetHeight: h } = card;

  let left = pt.x - w / 2;
  let top = pt.y - h - GAP;

  left = Math.max(PAD, Math.min(left, window.innerWidth - w - PAD));
  if (top < PAD) top = pt.y + GAP;          // flip below when it would clip the top

  card.style.left = `${left}px`;
  card.style.top = `${top}px`;
}

function showCard(entry) {
  card.innerHTML = cardHTML(entry.match, statusOf(entry.match));
  card.classList.add('is-visible');
  card.setAttribute('aria-hidden', 'false');

  const pt = map.latLngToContainerPoint(entry.marker.getLatLng());
  positionCard({ x: pt.x + entry.offset.x, y: pt.y + entry.offset.y });
}

function hideCard() {
  card.classList.remove('is-visible');
  card.setAttribute('aria-hidden', 'true');
}

/* ------------------------------------------------------------------ pins */

const live = [];   // { match, marker } for everything rendered today

function addPin(match) {
  const status = statusOf(match);
  const mod = status === 'live' ? ' is-live' : status === 'finished' ? ' is-finished' : '';
  const marker = L.marker([match.venue.lat, match.venue.lon], {
    icon: L.divIcon({
      className: '',
      html: `<div class="pin${mod}" tabindex="0" role="button" `
          + `aria-label="${esc(match.home.name)} versus ${esc(match.away.name)}"></div>`,
      iconSize: [18, 18],
      iconAnchor: [9, 9],
    }),
    keyboard: false,
  }).addTo(map);

  const el = marker.getElement().firstElementChild;
  const entry = { match, marker, el, offset: { x: 0, y: 0 } };

  el.addEventListener('mouseenter', () => showCard(entry));
  el.addEventListener('mouseleave', hideCard);
  el.addEventListener('focus', () => showCard(entry));
  el.addEventListener('blur', hideCard);
  // touch: no hover, so tapping opens the card
  el.addEventListener('click', (e) => { e.stopPropagation(); showCard(entry); });

  live.push(entry);
}

/* Seven Premier League clubs play inside London, so at England-wide zoom their
 * pins land on top of each other — Arsenal and Spurs sit ~4px apart, leaving
 * only one of them hoverable. Fan any overlapping cluster out around its
 * centroid so every match stays reachable. Recomputed on zoom, since what
 * overlaps depends entirely on scale.
 *
 * The shift uses margins rather than a transform: `.pin:hover` owns transform
 * for its scale-up, and the two would clobber each other. */
const OVERLAP_PX = 26;

function deoverlap() {
  const pts = live.map((e) => map.latLngToContainerPoint(e.marker.getLatLng()));
  const claimed = new Array(live.length).fill(false);

  for (const e of live) {
    e.offset = { x: 0, y: 0 };
    e.el.style.margin = '';
  }

  for (let i = 0; i < live.length; i++) {
    if (claimed[i]) continue;
    claimed[i] = true;

    const cluster = [i];
    for (let j = i + 1; j < live.length; j++) {
      if (!claimed[j] && pts[i].distanceTo(pts[j]) < OVERLAP_PX) {
        cluster.push(j);
        claimed[j] = true;
      }
    }
    if (cluster.length < 2) continue;

    const radius = 12 + cluster.length * 2.5;
    cluster.forEach((idx, k) => {
      const angle = (k / cluster.length) * 2 * Math.PI - Math.PI / 2;
      const dx = Math.round(Math.cos(angle) * radius);
      const dy = Math.round(Math.sin(angle) * radius);
      live[idx].offset = { x: dx, y: dy };
      live[idx].el.style.marginLeft = `${dx}px`;
      live[idx].el.style.marginTop = `${dy}px`;
    });
  }
}

/** Re-evaluate live/finished as the afternoon rolls on. */
function refreshStatuses() {
  for (const { match, el } of live) {
    const s = statusOf(match);
    el.classList.toggle('is-live', s === 'live');
    el.classList.toggle('is-finished', s === 'finished');
  }
}

/* --------------------------------------------------------- results panel */

function renderResults(recent) {
  const tbody = document.querySelector('#results-table tbody');

  if (!recent.length) {
    tbody.innerHTML =
      `<tr><td colspan="2" class="rt-empty">No matches concluded yet this week.</td></tr>`;
    return;
  }

  tbody.innerHTML = recent
    .slice()
    .sort((a, b) => Date.parse(b.kickoff_utc) - Date.parse(a.kickoff_utc))
    .map((m) => `
      <tr>
        <td>
          <div class="rt-match">
            <img src="${esc(m.home.logo)}" alt="${esc(m.home.name)}" loading="lazy">
            <span class="rt-score">${m.score.home}&ndash;${m.score.away}</span>
            <img src="${esc(m.away.logo)}" alt="${esc(m.away.name)}" loading="lazy">
          </div>
        </td>
        <td class="rt-day">${esc(paDay.format(new Date(m.kickoff_utc)))}</td>
      </tr>`)
    .join('');
}

document.getElementById('results-toggle').addEventListener('click', () => {
  const panel = document.getElementById('results-panel');
  const collapsed = panel.classList.toggle('collapsed');
  document.getElementById('results-toggle')
          .setAttribute('aria-expanded', String(!collapsed));
});

/* ------------------------------------------------------------------ boot */

async function init() {
  let data;
  try {
    const res = await fetch(DATA_URL, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    data = await res.json();
  } catch (err) {
    document.getElementById('subtitle').textContent =
      'Could not load match data — run scripts/make_mock.py';
    console.error('[match-map] failed to load', DATA_URL, err);
    return;
  }

  const today = data.today ?? [];
  today.forEach(addPin);
  deoverlap();
  map.on('zoomend', deoverlap);
  renderResults(data.recent ?? []);

  document.getElementById('empty-state').hidden = today.length > 0;

  const liveCount = today.filter((m) => statusOf(m) === 'live').length;
  document.getElementById('subtitle').textContent =
    `${today.length} match${today.length === 1 ? '' : 'es'} today` +
    (liveCount ? ` · ${liveCount} live now` : '') +
    (data.mock ? ' · mock data' : '');

  setInterval(refreshStatuses, TICK_MS);
}

// keep the card glued to its pin while panning/zooming
map.on('move zoom', hideCard);
map.on('click', hideCard);
window.addEventListener('resize', hideCard);

init();
