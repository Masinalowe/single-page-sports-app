#!/usr/bin/env python3
"""Generate a mock data/matches.json for UI development.

Kickoff times are written relative to the moment you run this, so the demo
always contains one in-play match, one still to come, and one finished today.
Re-run it whenever the fixtures drift out of date.

    python3 scripts/make_mock.py

Phase 4 replaces this with fetch_data.py, which produces the same shape from
the real API. Nothing downstream should be able to tell the difference.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STADIUMS = json.loads((ROOT / "data" / "stadiums.json").read_text())


def team(team_id):
    """Build a team object, borrowing the real crest URL pattern."""
    info = STADIUMS[str(team_id)]
    return {
        "id": team_id,
        "name": info["team"],
        "logo": f"https://crests.football-data.org/{team_id}.png",
    }


def venue_of(team_id):
    info = STADIUMS[str(team_id)]
    return {
        "name": info["venue"],
        "city": info["city"],
        "lat": info["lat"],
        "lon": info["lon"],
    }


def match(fid, home_id, away_id, kickoff, probability, score=None):
    return {
        "id": fid,
        "kickoff_utc": kickoff.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "venue": venue_of(home_id),
        "home": team(home_id),
        "away": team(away_id),
        "probability": probability,
        "score": score,
        # status is advisory only; app.js derives live/finished from the clock
        "status": "finished" if score else "scheduled",
    }


def main():
    now = datetime.now(timezone.utc).replace(microsecond=0)

    today = [
        # in play right now — kicked off 40 minutes ago
        match(9001, 57, 66, now - timedelta(minutes=40),
              {"home": 47, "draw": 28, "away": 25}),
        # also in play, deep into the second half
        match(9002, 64, 65, now - timedelta(minutes=75),
              {"home": 38, "draw": 30, "away": 32}),
        # still to come
        match(9003, 73, 61, now + timedelta(hours=3),
              {"home": 41, "draw": 27, "away": 32}),
        match(9004, 58, 67, now + timedelta(hours=5, minutes=30),
              {"home": 52, "draw": 25, "away": 23}),
        # finished earlier today, but odds were captured before kickoff
        match(9005, 397, 1044, now - timedelta(hours=4),
              {"home": 55, "draw": 24, "away": 21},
              {"home": 2, "away": 0}),
        # finished and never priced — exercises the "no odds" card state
        match(9006, 402, 354, now - timedelta(hours=6),
              None, {"home": 1, "away": 3}),
    ]

    recent = [
        match(8901, 351, 62, now - timedelta(days=2),
              {"home": 44, "draw": 29, "away": 27}, {"home": 1, "away": 1}),
        match(8902, 341, 71, now - timedelta(days=3),
              {"home": 49, "draw": 26, "away": 25}, {"home": 3, "away": 1}),
        match(8903, 63, 349, now - timedelta(days=4),
              {"home": 58, "draw": 23, "away": 19}, {"home": 0, "away": 2}),
        match(8904, 1076, 322, now - timedelta(days=5),
              {"home": 43, "draw": 30, "away": 27}, {"home": 2, "away": 2}),
    ]

    payload = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "season": 2026,
        "mock": True,
        "today": today,
        "recent": recent,
    }

    out = ROOT / "data" / "matches.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(out)
    print(f"wrote {out.relative_to(ROOT)}  "
          f"({len(today)} today, {len(recent)} recent)")


if __name__ == "__main__":
    main()
