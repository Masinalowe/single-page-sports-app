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

## The monogram wash

### Changing the artwork

Replace **`assets/monogram.svg`**. That's the whole procedure — no CSS to edit.
`styles.css` tiles that one file twice with a half-tile offset, so the file
only needs to contain a single mark.

The file currently holds a plain "PL" lettermark as a placeholder. For the
Premier League lion, download the official artwork and save it to that path.
Two things make an asset work well here:

- **A silhouette in one flat colour, transparent background.** The page
  multiplies the mark over the map, so a white mark vanishes and a full-colour
  one tints rather than shades. Mid-grey behaves best. A `grayscale()` filter
  in the CSS makes a coloured file usable without editing it.
- **Artwork inside the 100×100 viewBox with a little padding**, so tiling stays
  even.

Note that the Premier League lion is a registered trademark, and this repo is
public. That's a judgement call about your own repo, which is why the
placeholder ships instead.

### How the effect works

The wash is a viewport-fixed layer using `mix-blend-mode: multiply`, not two
layers clipped to the coastline. Multiply darkens whatever sits beneath it, so
grey water darkens to grey and purple land darkens to purple on its own, per
pixel. A mark straddling the coast is genuinely split mid-glyph.

The clipping approach is the obvious one and it doesn't work: Leaflet animates
the coastline path during zoom, so a clip path visibly lags and tears
mid-animation. Blending has nothing to keep in sync and stays correct at any
zoom.

Tuning: `opacity` (`.5`, `.45` on phones) and `background-size` (160px, 120px
on phones) on `#monogram`.

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
