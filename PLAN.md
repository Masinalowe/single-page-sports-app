# Premier League Match Map — Plan

A single-page web app showing a map of England with pins for Premier League
matches happening **today**. Live matches pulse. Hovering a pin reveals team
crests, win probability bars, venue, and kickoff time in Pacific. A panel in the
upper right lists matches already concluded this week, with scores.

---

## 1. Locked decisions

| Area | Choice | Why |
|---|---|---|
| Toolchain | **Zero-build vanilla JS** | No Node/npm/brew on this machine. `python3` is present. A single-page map app doesn't need a bundler. |
| Map | **Leaflet 1.9 + OpenStreetMap tiles**, via CDN | No API key, no build step, good hover/marker primitives. |
| Data | **API-Football v3** (api-sports.io) | One API covers fixtures, live status, venue, crests, and win predictions. Free tier = 100 req/day. |
| Refresh | **GitHub Action cron** commits `data/matches.json` | API key stays in GitHub Secrets, never in the browser. App remains fully static. |
| Serving | `python3 -m http.server 8000` | Stdlib. No install. |

---

## 2. File layout

```
single-page-sports-app/
├── index.html              # markup shell: #map, #results-panel
├── styles.css              # layout, pin pulse keyframes, hover card, table
├── app.js                  # load JSON → render pins, hover cards, table
├── data/
│   ├── matches.json        # generated daily; the only thing the browser fetches
│   └── stadiums.json       # hand-maintained team_id → {lat, lon} (see §4)
├── scripts/
│   └── fetch_data.py       # stdlib-only; API-Football → data/matches.json
└── .github/workflows/
    └── refresh-data.yml    # daily cron
```

No `package.json`. No build step. `index.html` opens and runs.

---

## 3. Data contract

`app.js` reads exactly one file. This is the seam — the UI can be built and
reviewed against a mock version of this file before the API is wired up.

```jsonc
{
  "generated_at": "2026-08-29T09:00:00Z",
  "season": 2026,
  "today": [
    {
      "id": 1035123,
      "kickoff_utc": "2026-08-29T14:00:00Z",
      "status": "scheduled",              // scheduled | live | finished
      "venue": {
        "name": "Emirates Stadium",
        "city": "London",
        "lat": 51.5549,
        "lon": -0.1084
      },
      "home": { "id": 42, "name": "Arsenal",           "logo": "https://…" },
      "away": { "id": 33, "name": "Manchester United", "logo": "https://…" },
      "probability": { "home": 45, "draw": 30, "away": 25 },   // ints, sum 100
      "score": null                        // { "home": 2, "away": 1 } once played
    }
  ],
  "recent": [ /* same shape, status "finished", score populated */ ]
}
```

`fetch_data.py` normalizes API-Football's ~20 status codes down to the three
values above so the browser never carries that table.

---

## 4. Stadium coordinates (the one unavoidable manual bit)

API-Football's venue object has name, address, city, capacity, surface, and an
image — **but no latitude/longitude**. Pins need coordinates, so we keep our own
`data/stadiums.json`, keyed by API-Football **team id** (stable across seasons;
venue name strings are not):

```jsonc
{ "42": { "venue": "Emirates Stadium", "lat": 51.5549, "lon": -0.1084 } }
```

20 entries, entered once. Maintenance: three promoted clubs each summer.
`fetch_data.py` fails loudly on an unknown team id rather than silently dropping
a pin. Cross-check coordinates against Wikipedia when entering.

---

## 5. Build phases

Each phase is independently reviewable. Nothing is committed without your review.

### Phase 0 — Verify the API *(needs your key)*
- [ ] You create a free api-sports.io account; key goes in `.env` (gitignored),
      never in a committed file.
- [ ] Throwaway script hits `/fixtures` and `/predictions` for one real fixture.
- [ ] **Confirm the predictions response shape.** Expected is
      `predictions.percent.{home,draw,away}` as strings like `"45%"`, but the
      docs site blocks automated reads, so we verify against a live response
      before building on it.

### Phase 1 — Static shell
- [ ] `index.html` + `styles.css`: full-viewport map, England-fitted bounds,
      results panel docked top-right.
- [ ] `data/stadiums.json` with all 20 clubs.
- [ ] Hand-written mock `data/matches.json` covering every state: a scheduled
      match, a live one, and finished ones — so the UI can be judged before any
      network call exists.

### Phase 2 — Pins, hover card, pulse
- [ ] Render one marker per `today[]` entry.
- [ ] Hover card: crests side by side, a stacked probability bar
      (home / draw / away) with percentages beneath, venue name, and kickoff
      rendered in Pacific.
- [ ] Pulse animation on live markers (CSS `@keyframes`, `prefers-reduced-motion`
      respected).
- [ ] Card also opens on click/focus, so it works on touch and by keyboard.

### Phase 3 — Results panel
- [ ] Top-right table of matches concluded **this week**, defined as Monday
      00:00 UK time → now. Columns: crests, `home 2–1 away`, day.
- [ ] Collapsible, and scrollable past ~6 rows so it never overruns the viewport.

### Phase 4 — Real data
- [ ] `scripts/fetch_data.py`, stdlib only (`urllib`, `json`, `zoneinfo`):
      one `/fixtures` call for today, one for the week's results, then one
      `/predictions` call per today-fixture. Worst case ≈ 12 requests/day
      against a 100/day budget.
- [ ] Joins stadium coordinates, normalizes status, writes `data/matches.json`.
- [ ] Writes to a temp file and renames, so a failed run never leaves a
      truncated JSON the page would choke on.

### Phase 5 — Automation
- [ ] `.github/workflows/refresh-data.yml` — daily cron, key from GitHub
      Secrets, commits `data/matches.json` only when it actually changed.

---

## 6. Resolved: how "live" is determined — **Option A**

The data refreshes each morning, but "is this match live *right now*?" changes
through the afternoon. We resolve this **client-side**: a match is live from
`kickoff_utc` to `kickoff_utc + 115 minutes`, recomputed on a ticker in the
browser.

Zero extra requests, keeps the app a pure static site, and honors the
once-a-day fetch constraint. Accepted tradeoff: it can't know about a delayed
kickoff or unusually long stoppage time, so the pulse may be off by a few
minutes at the edges. `LIVE_WINDOW_MIN` in `app.js` is a single constant if that
needs tuning.

---

## 7. Notes

- **Times.** Stored as UTC in JSON, rendered with
  `Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', timeZoneName: 'short' })`.
  That yields "PST" in winter and "PDT" in summer automatically, rather than
  mislabeling half the season.
- **Probabilities.** API-Football's percentages don't always sum to exactly 100;
  `fetch_data.py` normalizes them so the bar always fills.
- **Crests** are hotlinked from `media.api-sports.io`. If they prove flaky we
  cache them into `assets/` in a later pass.
- **Empty state.** Most days have no Premier League fixtures. The map needs a
  deliberate "no matches today" state, not a blank screen.
- **Git identity is not configured** on this machine — `user.name` and
  `user.email` are both unset, so the first commit will fail until they're set.

---

## 8. Running it

```bash
python3 -m http.server 8000     # then open http://localhost:8000
python3 scripts/fetch_data.py   # refresh data/matches.json (needs API key)
```
