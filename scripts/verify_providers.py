#!/usr/bin/env python3
"""Phase 0 (second pass) — verify football-data.org + The Odds API.

The question that matters here is not "do the keys work" but "how many
fixtures actually join to odds by team name", since the two providers share
no ids. Everything else is bookkeeping.

Reads FOOTBALL_DATA_TOKEN and ODDS_API_KEY from .env. Never prints them.

    python3 scripts/verify_providers.py
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FD_BASE = "https://api.football-data.org/v4"
ODDS_BASE = "https://api.the-odds-api.com/v4"


def env(name):
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            val = line.split("=", 1)[1].strip().strip("'\"")
            if val:
                return val
    sys.exit(f"{name} not set in .env")


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return {"_error": e.code, "_body": e.read().decode()[:300]}, {}


def show(t):
    print(f"\n{'=' * 66}\n{t}\n{'=' * 66}")


# ---------------------------------------------------------------- matching

SUFFIXES = r"\b(fc|afc|cf|utd)\b"


def norm(name):
    """Fold the two providers' naming conventions onto common ground."""
    n = name.lower().replace("&", "and")
    n = re.sub(r"[.'’\-]", "", n)
    n = re.sub(SUFFIXES, "", n)
    return re.sub(r"\s+", " ", n).strip()


# Cases normalization alone will never bridge.
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


def key(name):
    n = norm(name)
    return ALIASES.get(n, n)


def main():
    fd_token = env("FOOTBALL_DATA_TOKEN")
    odds_key = env("ODDS_API_KEY")
    hdr = {"X-Auth-Token": fd_token}

    # 1 ------------------------------------------------- competition access
    show("1. football-data.org — competition access")
    comp, _ = fetch(f"{FD_BASE}/competitions/PL", hdr)
    if "_error" in comp:
        sys.exit(f"  HTTP {comp['_error']}: {comp['_body']}")
    cs = comp.get("currentSeason", {})
    print(f"  competition   : {comp.get('name')} ({comp.get('code')})")
    print(f"  current season: {cs.get('startDate')} -> {cs.get('endDate')}")
    print(f"  matchday      : {cs.get('currentMatchday')}")

    # 2 ------------------------------------------------------------- teams
    show("2. football-data.org — teams (source for re-keying stadiums.json)")
    teams, _ = fetch(f"{FD_BASE}/competitions/PL/teams", hdr)
    tlist = teams.get("teams", [])
    print(f"  {len(tlist)} teams returned")
    for t in tlist[:4]:
        print(f"    id={t['id']:<5} {t['name']:<26} venue={t.get('venue')}")
    if len(tlist) > 4:
        print(f"    … and {len(tlist) - 4} more")
    has_crest = sum(1 for t in tlist if t.get("crest"))
    print(f"  crest urls present: {has_crest}/{len(tlist)}")

    # save the mapping so Phase 4 can re-key without another call
    if tlist:
        out = ROOT / "data" / "fd_teams.json"
        out.write_text(json.dumps(
            {str(t["id"]): {"name": t["name"], "shortName": t.get("shortName"),
                            "tla": t.get("tla"), "venue": t.get("venue"),
                            "crest": t.get("crest")}
             for t in tlist}, indent=2) + "\n")
        print(f"  wrote {out.relative_to(ROOT)}")

    # 3 ---------------------------------------------------------- fixtures
    show("3. football-data.org — fixtures, today through +10 days")
    today = datetime.now(timezone.utc).date()
    q = urllib.parse.urlencode({
        "dateFrom": today.isoformat(),
        "dateTo": (today + timedelta(days=10)).isoformat(),
    })
    fx, _ = fetch(f"{FD_BASE}/competitions/PL/matches?{q}", hdr)
    matches = fx.get("matches", [])
    print(f"  {len(matches)} match(es) in window; errors={fx.get('message', 'none')}")
    for m in matches[:6]:
        print(f"    {m['utcDate']}  {m['status']:<10} "
              f"{m['homeTeam']['name']} vs {m['awayTeam']['name']}")
    if len(matches) > 6:
        print(f"    … and {len(matches) - 6} more")

    print(f"\n  statuses seen: "
          f"{sorted({m['status'] for m in matches}) or '(none)'}")
    if matches:
        print(f"  match keys    : {sorted(matches[0].keys())}")
        print(f"  venue field   : {matches[0].get('venue', '(absent)')!r}")

    # 4 -------------------------------------------------------------- odds
    show("4. The Odds API — EPL head-to-head prices")
    oq = urllib.parse.urlencode({
        "apiKey": odds_key, "regions": "uk",
        "markets": "h2h", "oddsFormat": "decimal",
    })
    odds, oh = fetch(f"{ODDS_BASE}/sports/soccer_epl/odds?{oq}")
    if isinstance(odds, dict) and "_error" in odds:
        print(f"  HTTP {odds['_error']}: {odds['_body']}")
        odds = []
    print(f"  {len(odds)} event(s) priced")
    print(f"  quota: used={oh.get('x-requests-used')} "
          f"remaining={oh.get('x-requests-remaining')}")
    for e in odds[:4]:
        bk = len(e.get("bookmakers", []))
        print(f"    {e['commence_time']}  {e['home_team']} vs {e['away_team']}"
              f"  ({bk} bookmakers)")

    # 5 --------------------------------------------------------- join test
    show("5. THE REAL TEST — do fixtures join to odds by name?")
    if not matches or not odds:
        print("  cannot test: need both fixtures and odds")
        return

    odds_index = {}
    for e in odds:
        odds_index[(key(e["home_team"]), key(e["away_team"]))] = e

    joined, missed = 0, []
    for m in matches:
        k = (key(m["homeTeam"]["name"]), key(m["awayTeam"]["name"]))
        if k in odds_index:
            joined += 1
        else:
            missed.append((m["homeTeam"]["name"], m["awayTeam"]["name"], k))

    total = len(matches)
    print(f"  joined {joined}/{total} fixtures "
          f"({100 * joined // total if total else 0}%)")

    if missed:
        print("\n  UNMATCHED (each needs an alias, or has no odds posted yet):")
        for h, a, k in missed:
            print(f"    {h} vs {a}")
            print(f"      normalized -> {k}")
        print("\n  names The Odds API actually uses:")
        for n in sorted({e["home_team"] for e in odds} |
                        {e["away_team"] for e in odds}):
            print(f"    {n!r}  -> {key(n)!r}")


if __name__ == "__main__":
    main()
