#!/usr/bin/env python3
"""Build data/matches.json from football-data.org + The Odds API.

Three requests per run:
  1. football-data.org — fixtures from Monday through end of today
  2. The Odds API      — current EPL head-to-head prices
  3. (nothing else)    — crests and team ids ride along with the fixtures

Fixtures and odds share no id, so they are joined on normalized team names
within a kickoff window (PLAN.md §4b). Odds vanish from the feed at kickoff,
so previously captured probabilities are carried forward (§4c).

Reads FOOTBALL_DATA_TOKEN and ODDS_API_KEY from .env. Never prints them.

    python3 scripts/fetch_data.py
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "matches.json"
FD_BASE = "https://api.football-data.org/v4"
ODDS_BASE = "https://api.the-odds-api.com/v4"
UK = ZoneInfo("Europe/London")

# How far apart a fixture and an odds event may be and still be the same match.
JOIN_WINDOW = timedelta(hours=3)


# ------------------------------------------------------------------- config

def env(name):
    path = ROOT / ".env"
    if not path.exists():
        sys.exit("no .env found")
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            val = line.split("=", 1)[1].strip().strip("'\"")
            if val:
                return val
    sys.exit(f"{name} not set in .env")


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} from {url.split('?')[0]}: "
                 f"{e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        sys.exit(f"network error: {e.reason}")


# ------------------------------------------------------------ name matching

ALIASES = {
    "wolverhampton wanderers": "wolves",
    "brighton and hove albion": "brighton",
    "tottenham hotspur": "tottenham",
    "manchester united": "man united",
    "manchester city": "man city",
    "newcastle united": "newcastle",
    "nottingham forest": "nottm forest",
    "west ham united": "west ham",
    "leicester city": "leicester",
    "leeds united": "leeds",
    "ipswich town": "ipswich",
    "luton town": "luton",
    "sheffield united": "sheffield utd",
    "west bromwich albion": "west brom",
}


def team_key(name):
    """Fold both providers' naming onto common ground. Measured 15/15."""
    n = name.lower().replace("&", "and")
    n = re.sub(r"[.'’\-]", "", n)
    n = re.sub(r"\b(fc|afc|cf|utd)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return ALIASES.get(n, n)


# -------------------------------------------------------------------- odds

def implied_probabilities(event):
    """Average implied probability across bookmakers, with the vig removed.

    A single book's three prices sum to ~105% — that overround is the
    bookmaker's margin, not information about the match. Averaging across
    books first reduces the influence of any one outlier line.
    """
    home_name, away_name = event["home_team"], event["away_team"]
    totals = {"home": 0.0, "draw": 0.0, "away": 0.0}
    counted = 0

    for book in event.get("bookmakers", []):
        market = next((m for m in book.get("markets", [])
                       if m.get("key") == "h2h"), None)
        if not market:
            continue

        raw = {}
        for outcome in market.get("outcomes", []):
            price = outcome.get("price")
            if not price or price <= 1:
                continue
            label = outcome["name"]
            slot = ("home" if label == home_name
                    else "away" if label == away_name
                    else "draw" if label.lower() == "draw"
                    else None)
            if slot:
                raw[slot] = 1.0 / price

        if len(raw) != 3:
            continue                      # incomplete line, skip this book

        overround = sum(raw.values())
        for slot, v in raw.items():
            totals[slot] += v / overround
        counted += 1

    if not counted:
        return None

    pct = {k: (v / counted) * 100 for k, v in totals.items()}

    # integers that still sum to exactly 100, so the bar always fills
    home = round(pct["home"])
    draw = round(pct["draw"])
    return {"home": home, "draw": draw, "away": 100 - home - draw}


# ------------------------------------------------------------------- build

def normalize_status(fd_status):
    if fd_status in ("IN_PLAY", "PAUSED"):
        return "live"
    if fd_status in ("FINISHED", "AWARDED"):
        return "finished"
    return "scheduled"


def build_match(m, stadiums, prob):
    home, away = m["homeTeam"], m["awayTeam"]
    ground = stadiums.get(str(home["id"]))
    if not ground:
        return None, f"no stadium entry for team id {home['id']} ({home['name']})"

    ft = (m.get("score") or {}).get("fullTime") or {}
    score = ({"home": ft["home"], "away": ft["away"]}
             if ft.get("home") is not None and ft.get("away") is not None
             else None)

    return {
        "id": m["id"],
        "kickoff_utc": m["utcDate"],
        "status": normalize_status(m["status"]),
        "venue": {
            "name": ground["venue"],
            "city": ground["city"],
            "lat": ground["lat"],
            "lon": ground["lon"],
        },
        "home": {"id": home["id"], "name": home["name"],
                 "logo": home.get("crest")},
        "away": {"id": away["id"], "name": away["name"],
                 "logo": away.get("crest")},
        "probability": prob,
        "score": score,
    }, None


def main():
    fd_token = env("FOOTBALL_DATA_TOKEN")
    odds_key = env("ODDS_API_KEY")
    stadiums = {k: v for k, v in
                json.loads((ROOT / "data" / "stadiums.json").read_text()).items()
                if not k.startswith("_")}

    now = datetime.now(timezone.utc)
    now_uk = now.astimezone(UK)
    monday = (now_uk - timedelta(days=now_uk.weekday())).date()
    today_uk = now_uk.date()

    # 1 --------------------------------------------------------- fixtures
    q = urllib.parse.urlencode({"dateFrom": monday.isoformat(),
                                "dateTo": today_uk.isoformat()})
    fixtures = get(f"{FD_BASE}/competitions/PL/matches?{q}",
                   {"X-Auth-Token": fd_token}).get("matches", [])
    print(f"fixtures : {len(fixtures)} from {monday} to {today_uk}")

    # 2 ------------------------------------------------------------- odds
    oq = urllib.parse.urlencode({"apiKey": odds_key, "regions": "uk",
                                 "markets": "h2h", "oddsFormat": "decimal"})
    events = get(f"{ODDS_BASE}/sports/soccer_epl/odds?{oq}")
    if not isinstance(events, list):
        events = []
    print(f"odds     : {len(events)} event(s) priced")

    odds_index = []
    for e in events:
        prob = implied_probabilities(e)
        if prob:
            odds_index.append((team_key(e["home_team"]),
                               team_key(e["away_team"]),
                               datetime.fromisoformat(
                                   e["commence_time"].replace("Z", "+00:00")),
                               prob))

    # 3 -------------------------------- probabilities captured on earlier runs
    previous = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
            for m in old.get("today", []) + old.get("recent", []):
                if m.get("probability"):
                    previous[m["id"]] = m["probability"]
        except (json.JSONDecodeError, KeyError):
            pass   # a corrupt previous file must not block a fresh one

    # 4 ------------------------------------------------------------- join
    today, recent, problems = [], [], []
    carried = matched = 0

    for m in fixtures:
        kickoff = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00"))
        hk, ak = team_key(m["homeTeam"]["name"]), team_key(m["awayTeam"]["name"])

        prob = next((p for h, a, t, p in odds_index
                     if h == hk and a == ak and abs(t - kickoff) < JOIN_WINDOW),
                    None)
        if prob:
            matched += 1
        else:
            # §4c: odds leave the feed at kickoff — keep what we already had
            prob = previous.get(m["id"])
            if prob:
                carried += 1

        match, err = build_match(m, stadiums, prob)
        if err:
            problems.append(err)
            continue

        if kickoff.astimezone(UK).date() == today_uk:
            today.append(match)
        elif match["score"]:
            recent.append(match)

    print(f"joined   : {matched} from live odds, {carried} carried forward, "
          f"{len(fixtures) - matched - carried} without probability")

    if problems:
        print("\nPROBLEMS (these fixtures were dropped):")
        for p in problems:
            print(f"  {p}")

    payload = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": monday.year,
        "today": sorted(today, key=lambda m: m["kickoff_utc"]),
        "recent": sorted(recent, key=lambda m: m["kickoff_utc"], reverse=True),
    }

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(OUT)        # atomic: a failed run never leaves partial JSON

    print(f"\nwrote {OUT.relative_to(ROOT)}  "
          f"({len(today)} today, {len(recent)} earlier this week)")


if __name__ == "__main__":
    main()
