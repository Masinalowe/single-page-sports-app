# Premier League Match Map

A single-page map of England showing Premier League matches **on the day they're
played**. Live matches pulse. Hovering a pin reveals both crests, win
probability, the venue, and kickoff time in Pacific. Matches concluded earlier
in the week appear in a panel in the upper right.

No build step, no npm, no bundler — open it and it runs.

## Requirements

- Python 3 (only to serve the files and generate data — it's already on macOS)
- A modern browser

## Run it locally

From the project root:

```bash
python3 -m http.server 8000
```

Then open <http://127.0.0.1:8000>.

Opening `index.html` directly by double-clicking will **not** work — the app
fetches `data/matches.json`, and browsers block `fetch` on `file://` URLs. It
has to be served over HTTP.

Stop the server with `Ctrl-C`, or `pkill -f "http.server 8000"` if you
backgrounded it.

## Refresh the data

Real fixtures, scores, and win probabilities:

```bash
python3 scripts/fetch_data.py
```

Needs `FOOTBALL_DATA_TOKEN` and `ODDS_API_KEY` in a local `.env` (gitignored).
Three API requests per run, well inside both free tiers.

**Run it before the day's first kickoff.** The Odds API only prices *upcoming*
matches — once a match starts it leaves the feed and its probabilities are
unrecoverable. The script carries forward any probability it captured on an
earlier run, so a later re-run won't blank the bars, but a match first seen
after kickoff will never have odds.

### Demo data

Most days you can't see every UI state from real fixtures — matches are only
live for two hours. This regenerates fixtures relative to *now*, so there's
always one in play, one still to come, and one with no odds:

```bash
python3 scripts/make_mock.py
```

It **overwrites** `data/matches.json`. Run `fetch_data.py` again to get real
data back.

## Project layout

```
index.html            markup shell
styles.css            theme, pin pulse, hover card, results panel
app.js                loads matches.json → pins, hover cards, results table
data/matches.json     the only file the browser fetches (generated)
data/stadiums.json    team id → stadium coordinates (hand-maintained)
scripts/make_mock.py  generates demo data
PLAN.md               architecture, decisions, and remaining phases
```

`data/matches.json` is the seam between the UI and the data source. Anything
that writes that shape — the current mock script, or the real API fetch in a
later phase — works without the front end changing.

## Status

Phases 1–2 of [PLAN.md](PLAN.md) are done: the map, pins, pulse, hover cards,
and results panel all work against mock data.

Still to come: the live API-Football integration (Phase 4) and the daily refresh
via GitHub Actions (Phase 5). Those need a free api-sports.io key, which goes in
a local `.env` — it is gitignored and must never be committed.
