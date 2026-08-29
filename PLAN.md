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
| Fixtures | **football-data.org v4** | Free tier covers the Premier League, current season, "free forever", 10 calls/min. Ships team crests. |
| Probability | **The Odds API** | Free tier = 500 req/month; we use ~30. Real bookmaker odds, de-vigged into win/draw/away. |
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

No free football API returns stadium latitude/longitude. **Verified in Phase 0:**
API-Football's venue object is exactly `['id', 'name', 'city']` — no coordinates.
football-data.org is likewise venue-name-only. Pins need coordinates, so we keep
our own `data/stadiums.json`, keyed by **football-data.org team id** (stable
across seasons; venue name strings are not):

```jsonc
{ "57": { "team": "Arsenal", "venue": "Emirates Stadium", "lat": 51.5549, "lon": -0.1084 } }
```

20 entries, entered once. Maintenance: three promoted clubs each summer.
`fetch_data.py` fails loudly on an unknown team id rather than silently dropping
a pin. Cross-check coordinates against Wikipedia when entering.

> **Re-key needed.** The file currently holds API-Football ids, validated in
> Phase 0 before we changed providers. football-data.org uses a different id
> space (Arsenal is 57, not 42), so every key must be remapped. The coordinates
> themselves stay good — only the keys change.

## 4b. Joining two APIs

Fixtures and odds come from different providers with no shared id, so they're
matched on **team names plus kickoff time** — the one genuinely fragile seam in
this design. football-data.org says "Wolverhampton Wanderers FC" where The Odds
API says "Wolves".

Mitigations:
- A normalization pass (drop `FC`/`AFC`, casefold, strip punctuation) plus an
  explicit alias table for the cases normalization won't catch.
- Match only within a ±3h window of kickoff, so same-name fixtures in different
  gameweeks can't cross-match.
- An unmatched fixture still renders its pin — it just shows no probability
  bar, rather than vanishing. `fetch_data.py` reports every miss so the alias
  table can grow.

---

## 5. Build phases

Each phase is independently reviewable. Nothing is committed without your review.

### Phase 0 — Verify the APIs
- [x] api-sports.io key verified via `scripts/verify_api.py`.
- [x] Confirmed `predictions.percent.{home,draw,away}` really is the shape
      (strings like `"45%"`).
- [x] Confirmed venue objects carry **no** coordinates — `stadiums.json` earns
      its place.
- [x] Confirmed all 20 stadium entries resolve against the league team list.
- [x] **Found the blocker:** API-Football's free plan is locked out of the
      current season (*"Free plans do not have access to this season, try from
      2022 to 2024"*), which kills the "matches happening today" premise.
      Provider switched to football-data.org + The Odds API.
- [ ] Register both free keys, add to `.env` (gitignored):
      `FOOTBALL_DATA_TOKEN`, `ODDS_API_KEY`.
- [ ] Re-run verification against the two new APIs: confirm current-season PL
      fixtures return, capture the real crest URLs, and check how many of a
      matchday's fixtures the name-matching actually joins to odds.

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
- [ ] Re-key `data/stadiums.json` to football-data.org team ids (§4).
- [ ] `scripts/fetch_data.py`, stdlib only (`urllib`, `json`, `zoneinfo`):
      one football-data.org call for today's fixtures, one for the week's
      results, one Odds API call for current EPL h2h odds. Three requests per
      run, comfortably inside both free tiers.
- [ ] De-vig the odds: invert each decimal price to an implied probability,
      then divide by their sum to strip the bookmaker margin — otherwise the
      three "probabilities" total ~105%.
- [ ] Join odds to fixtures by normalized name + kickoff window (§4b), joining
      stadium coordinates and normalizing status along the way.
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
