#!/usr/bin/env python3
"""Build data/england.geojson — the map's only landmass.

Natural Earth's map_subunits file splits the UK into England, Scotland, Wales
and Northern Ireland, which is what makes an England-only map possible; the
plain countries file has the UK as one shape.

The source is 13MB, far too heavy to ship to a browser, so this extracts just
England, drops islets too small to read at England-wide zoom, and simplifies
the outline with Douglas-Peucker. Run it only when the outline needs
regenerating — data/england.geojson is committed.

    python3 scripts/build_england_geojson.py

Source: Natural Earth, public domain.
"""

import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "england.geojson"
SRC = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
       "master/geojson/ne_10m_admin_0_map_subunits.geojson")

# Degrees. ~0.005 keeps the coastline recognisable (Cornwall, The Wash, the
# Thames estuary) while shedding most of the points.
TOLERANCE = 0.005

# Drop islands whose bounding box is smaller than this, in square degrees.
# Keeps the mainland and the Isle of Wight; drops Scilly, Lundy and the rest,
# which render as unreadable specks at this zoom.
MIN_AREA = 0.02


def perpendicular_distance(pt, start, end):
    (x, y), (x1, y1), (x2, y2) = pt, start, end
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    t = ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    px, py = x1 + t * dx, y1 + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def simplify(points, tol):
    """Douglas-Peucker, iterative so a long coastline can't blow the stack."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        worst, index = 0.0, None
        for i in range(first + 1, last):
            d = perpendicular_distance(points[i], points[first], points[last])
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tol:
            keep[index] = True
            stack.append((first, index))
            stack.append((index, last))

    return [p for p, k in zip(points, keep) if k]


def bbox_area(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def main():
    print(f"downloading {SRC.rsplit('/', 1)[-1]} …")
    with urllib.request.urlopen(SRC, timeout=120) as r:
        data = json.loads(r.read())

    england = next(f for f in data["features"]
                   if f["properties"].get("SUBUNIT") == "England")

    geom = england["geometry"]
    polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
             else [geom["coordinates"]])

    before = sum(len(ring) for poly in polys for ring in poly)

    kept = []
    for poly in polys:
        outer = poly[0]
        if bbox_area(outer) < MIN_AREA:
            continue
        # outer ring only; England's holes are lakes, invisible at this zoom
        simplified = simplify([tuple(p) for p in outer], TOLERANCE)
        if len(simplified) >= 4:
            kept.append([[list(p) for p in simplified]])

    kept.sort(key=lambda p: -bbox_area(p[0]))
    after = sum(len(ring) for poly in kept for ring in poly)

    out = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "England"},
            "geometry": {"type": "MultiPolygon", "coordinates": kept},
        }],
    }

    OUT.write_text(json.dumps(out, separators=(",", ":")))
    size_kb = OUT.stat().st_size / 1024

    print(f"polygons : {len(polys)} -> {len(kept)} "
          f"(dropped islets under {MIN_AREA} sq deg)")
    print(f"points   : {before} -> {after}")
    print(f"wrote {OUT.relative_to(ROOT)}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
