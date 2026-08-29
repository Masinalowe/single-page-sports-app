#!/usr/bin/env python3
"""Phase 0 — confirm what the API actually returns before building on it.

Checks, cheapest first, so we learn the account's limits before spending quota:
  1. /status      — key works; plan and remaining requests
  2. /leagues     — which Premier League seasons this plan may query
  3. /fixtures    — real fixture shape, team ids, venue fields
  4. /predictions — whether percent.{home,draw,away} is really the shape

Reads FOOTBALL_IO from .env. Never prints the key.

    python3 scripts/verify_api.py
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://v3.football.api-sports.io"
PREMIER_LEAGUE = 39


def load_key():
    env = ROOT / ".env"
    if not env.exists():
        sys.exit("no .env found — expected FOOTBALL_IO=<key>")
    for line in env.read_text().splitlines():
        line = line.strip()
        if line.startswith("FOOTBALL_IO="):
            key = line.split("=", 1)[1].strip().strip("'\"")
            if key:
                return key
    sys.exit("FOOTBALL_IO not set in .env")


def get(path, key, **params):
    url = f"{BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"_http_error": e.code, "_body": e.read().decode()[:400]}


def show(title):
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def main():
    key = load_key()

    # 1 ------------------------------------------------------------- status
    show("1. /status — is the key live, and what plan is it on?")
    st = get("status", key)
    if "_http_error" in st:
        sys.exit(f"HTTP {st['_http_error']}: {st['_body']}")
    if st.get("errors"):
        sys.exit(f"API returned errors: {st['errors']}")

    resp = st.get("response", {})
    acct, sub, reqs = (resp.get("account", {}),
                       resp.get("subscription", {}),
                       resp.get("requests", {}))
    print(f"  plan      : {sub.get('plan')}   active={sub.get('active')}")
    print(f"  requests  : {reqs.get('current')} used of {reqs.get('limit_day')} today")
    print(f"  account   : {acct.get('firstname') or '(none)'}")

    # 2 ------------------------------------------------------------ seasons
    show("2. /leagues?id=39 — which PL seasons can this plan query?")
    lg = get("leagues", key, id=PREMIER_LEAGUE)
    seasons = []
    if lg.get("response"):
        seasons = lg["response"][0].get("seasons", [])
        current = [s["year"] for s in seasons if s.get("current")]
        covered = [s["year"] for s in seasons if s.get("coverage", {})
                   .get("predictions")]
        print(f"  seasons available : {[s['year'] for s in seasons]}")
        print(f"  marked current    : {current}")
        print(f"  predictions cover : {covered}")
    else:
        print(f"  unexpected: {json.dumps(lg)[:300]}")

    if not seasons:
        sys.exit("\nCannot continue without a season to query.")

    season = ([s["year"] for s in seasons if s.get("current")]
              or [max(s["year"] for s in seasons)])[0]
    if len(sys.argv) > 1:
        season = int(sys.argv[1])

    # 3 ----------------------------------------------------------- fixtures
    show(f"3. /fixtures — season {season}, sample PL fixtures")
    fx = get("fixtures", key, league=PREMIER_LEAGUE, season=season, next=3)
    items = fx.get("response", [])

    # The free plan is locked out of the current season. Fall back to the
    # newest season it will serve so the rest of the checks still run.
    if not items and "plan" in (fx.get("errors") or {}):
        print(f"  BLOCKED on season {season}: {fx['errors']['plan']}")
        season = 2024
        print(f"  retrying with season {season} …")
        fx = get("fixtures", key, league=PREMIER_LEAGUE, season=season,
                 **{"from": "2024-09-01", "to": "2024-09-30"})
        items = fx.get("response", [])[:3]

    print(f"  returned {len(items)} fixture(s); errors={fx.get('errors')}")

    sample = None
    for it in items:
        f, t, v = it["fixture"], it["teams"], it["fixture"]["venue"]
        print(f"\n  fixture {f['id']}  {f['date']}  status={f['status']['short']}")
        print(f"    {t['home']['name']} (id {t['home']['id']})"
              f"  vs  {t['away']['name']} (id {t['away']['id']})")
        print(f"    venue: {v}")
        sample = sample or it

    if sample:
        print("\n  --- venue keys present:",
              list(sample["fixture"]["venue"].keys()))
        has_coords = any(k in sample["fixture"]["venue"]
                         for k in ("lat", "latitude", "lon", "longitude"))
        print(f"  --- venue includes coordinates? {has_coords}"
              "   (we maintain data/stadiums.json because it does not)")

    # 4 -------------------------------------------------------- predictions
    if sample:
        fid = sample["fixture"]["id"]
        show(f"4. /predictions?fixture={fid} — is percent.{{home,draw,away}} real?")
        pr = get("predictions", key, fixture=fid)
        if pr.get("response"):
            preds = pr["response"][0].get("predictions", {})
            print(f"  predictions keys : {list(preds.keys())}")
            print(f"  percent          : {preds.get('percent')}")
            print(f"  winner           : {preds.get('winner')}")
        else:
            print(f"  no response; errors={pr.get('errors')}")
            print(f"  raw: {json.dumps(pr)[:300]}")

    # -------------------------------------------------------- quota + ids
    show("5. Quota after this run")
    st2 = get("status", key)
    r2 = st2.get("response", {}).get("requests", {})
    print(f"  {r2.get('current')} used of {r2.get('limit_day')} today")

    show("6. Cross-check data/stadiums.json team ids")
    tm = get("teams", key, league=PREMIER_LEAGUE, season=season)
    api_teams = {str(t["team"]["id"]): t["team"]["name"]
                 for t in tm.get("response", [])}
    if not api_teams:
        print(f"  could not fetch teams; errors={tm.get('errors')}")
        return

    local = json.loads((ROOT / "data" / "stadiums.json").read_text())
    local = {k: v for k, v in local.items() if not k.startswith("_")}

    missing = [(tid, nm) for tid, nm in api_teams.items() if tid not in local]
    wrong = [(tid, api_teams[tid], local[tid]["team"])
             for tid in api_teams if tid in local
             and api_teams[tid].lower() not in local[tid]["team"].lower()
             and local[tid]["team"].lower() not in api_teams[tid].lower()]

    print(f"  API lists {len(api_teams)} teams in season {season}")
    if missing:
        print("  MISSING from stadiums.json (pins would fail):")
        for tid, nm in missing:
            print(f"    {tid:>6}  {nm}")
    else:
        print("  every team in the league has a stadium entry")
    if wrong:
        print("  NAME MISMATCH (id may be wrong):")
        for tid, api_nm, loc_nm in wrong:
            print(f"    {tid:>6}  api={api_nm!r}  local={loc_nm!r}")


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used by get())
    main()
