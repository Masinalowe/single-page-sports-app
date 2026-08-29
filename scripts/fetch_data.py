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
import os
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
    """Real environment first, so CI can inject secrets without a .env file."""
    if os.environ.get(name):
        return os.environ[name]

    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{name}="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val:
                    return val
    sys.exit(f"{name} not set (checked environment and .env)")


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

    score_obj = m.get("score") or {}
    ft = score_obj.get("fullTime") or {}
    score = ({"home": ft["home"], "away": ft["away"]}
             if ft.get("home") is not None and ft.get("away") is not None
             else None)

    # Half-time is the most detail the free tier gives. Goals, bookings and
    # substitutions all come back null, so the expandable result rows show
    # this instead of scorers.
    ht = score_obj.get("halfTime") or {}
    half_time = ({"home": ht["home"], "away": ht["away"]}
                 if ht.get("home") is not None and ht.get("away") is not None
                 else None)

    return {
        "id": m["id"],
        "kickoff_utc": m["utcDate"],
        "status": normalize_status(m["status"]),
        "matchday": m.get("matchday"),
        "half_time": half_time,
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
    # Odds only need capturing once, before the day's first kickoff. Later
    # runs exist to refresh scores, and skip the odds call entirely — both to
    # save quota and because the feed no longer carries started matches.
    scores_only = "--scores-only" in sys.argv

    fd_token = env("FOOTBALL_DATA_TOKEN")
    odds_key = None if scores_only else env("ODDS_API_KEY")
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

    # 1b ---------------------------------------------------------- standings
    # Free tier covers league tables. Fetched on every run, including
    # --scores-only, since the table moves whenever a match finishes.
    table = get(f"{FD_BASE}/competitions/PL/standings",
                {"X-Auth-Token": fd_token}).get("standings", [])
    total = next((t["table"] for t in table if t.get("type") == "TOTAL"), [])
    standings = [{
        "position": r["position"],
        "team": {
            "id": r["team"]["id"],
            "name": r["team"].get("shortName") or r["team"]["name"],
            "crest": r["team"].get("crest"),
        },
        "played": r["playedGames"],
        "won": r["won"],
        "draw": r["draw"],
        "lost": r["lost"],
        "gd": r["goalDifference"],
        "points": r["points"],
    } for r in total]
    print(f"standings: {len(standings)} teams")

    # 2 ------------------------------------------------------------- odds
    if scores_only:
        events = []
        print("odds     : skipped (--scores-only), carrying forward previous")
    else:
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
    previous, old_payload = {}, None
    if OUT.exists():
        try:
            old_payload = json.loads(OUT.read_text())
            for m in old_payload.get("today", []) + old_payload.get("recent", []):
                if m.get("probability"):
                    previous[m["id"]] = m["probability"]
        except (json.JSONDecodeError, KeyError):
            old_payload = None   # a corrupt previous file must not block a fresh one

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
        "standings": standings,
        "today": sorted(today, key=lambda m: m["kickoff_utc"]),
        "recent": sorted(recent, key=lambda m: m["kickoff_utc"], reverse=True),
    }

    # generated_at changes on every run, so comparing whole files would report
    # a change every time and the scheduled job would commit ~13 times a day
    # with nothing but a new timestamp. Compare the actual match data instead
    # and leave the file alone when it is identical.
    if old_payload is not None:
        def content(d):
            return {k: v for k, v in d.items() if k != "generated_at"}
        if content(old_payload) == content(payload):
            print(f"\n{OUT.relative_to(ROOT)} unchanged; left untouched")
            return

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(OUT)        # atomic: a failed run never leaves partial JSON

    print(f"\nwrote {OUT.relative_to(ROOT)}  "
          f"({len(today)} today, {len(recent)} earlier this week)")


if __name__ == "__main__":
    main()
