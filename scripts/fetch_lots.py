#!/usr/bin/env python3
"""Fetch each site's shape for the map and write lots.geojson.

- `bbls`: tax-lot outlines from NYC Planning's MapPLUTO table (the data ZoLa uses).
- `streets`: street lines from the city's street centerline file (CSCL). Each entry is
  an exact Brooklyn street name, or {"name": ..., "along": ...} to keep only the
  segments within 40 m of another street (e.g. Park Ave where it runs under the BQE),
  or {"name": ..., "between": [cross1, cross2]} for the blocks between two cross streets. Add
  "borough": "Queens" (or another borough) for a street outside Brooklyn.
- `osm`: OpenStreetMap elements such as "way/392486579" (creeks, plazas, anything
  the city files don't cover). Closed ways become areas, open ways and relations lines.
- `path`: [[lat, lng], ...] points for something proposed that no map has yet (a bridge
  that isn't built). Drawn dashed. Take the points from real street ends and say where in `updated`.

The map draws all of them in the site's pin color, and validate_sites.py checks every
pin sits on its site's shape. Rerun whenever `bbls`, `streets`, `osm` or `path` change.

Also writes viewpoints.json: where the popup's embedded Street View should stand and which
way it should face. Lot sites look from the nearest ordinary street (not a highway or ramp)
toward the pin; street and creek sites stand at the pin and look along the line.

Usage: python3 scripts/fetch_lots.py [sites.json] [lots.geojson]
"""
import json
import math
import re
import sys
import urllib.parse
import urllib.request

CARTO = "https://planninglabs.carto.com/api/v2/sql"
CSCL = "https://data.cityofnewyork.us/resource/inkn-q76z.json"
OSM = "https://api.openstreetmap.org/api/0.6"
ALONG_M = 40


def fetch(bbls):
    ids = ",".join(str(int(b)) for b in bbls)
    sql = (f"SELECT bbl, address, ST_AsGeoJSON(the_geom, 6) AS geom "
           f"FROM dcp_mappluto WHERE bbl IN ({ids})")
    url = CARTO + "?" + urllib.parse.urlencode({"q": sql})
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-urban-projects-lots"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["rows"]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-urban-projects-lots"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


BOROUGH_CODES = {"Manhattan": "1", "Bronx": "2", "Brooklyn": "3", "Queens": "4", "Staten Island": "5"}


def street_lines(name, borough="Brooklyn"):
    q = {"$select": "the_geom", "$limit": "2000",
         "$where": f"full_street_name='{name.upper()}' AND boroughcode='{BOROUGH_CODES[borough]}'"}
    rows = get_json(CSCL + "?" + urllib.parse.urlencode(q))
    return [[[round(x, 6), round(y, 6)] for x, y in line]
            for row in rows for line in row["the_geom"]["coordinates"]]


def meters(a, b):
    return math.hypot((a[0] - b[0]) * 111_320 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111_320)


def fetch_street(entry):
    """Centerline segments for a `streets` entry, merged into one MultiLineString."""
    name = entry if isinstance(entry, str) else entry["name"]
    boro = "Brooklyn" if isinstance(entry, str) else entry.get("borough", "Brooklyn")
    lines = street_lines(name, boro)
    if isinstance(entry, dict) and entry.get("along"):
        guide = [(a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10)
                 for line in street_lines(entry["along"], boro) for a, b in zip(line, line[1:]) for k in range(11)]
        lines = [l for l in lines if min(meters(l[len(l) // 2], g) for g in guide) <= ALONG_M]
    if isinstance(entry, dict) and entry.get("between"):
        # Walk the street's own segments from one cross street to the other (shortest path by length),
        # so long or curving streets keep every block in between.
        ends = []
        for cross in entry["between"]:
            nodes = {tuple(p) for l in street_lines(cross, boro) for p in (l[0], l[-1])}
            hits = [tuple(p) for l in lines for p in (l[0], l[-1]) if tuple(p) in nodes]
            if not hits:
                raise SystemExit(f"{name} and {cross} don't meet in CSCL")
            ends.append(hits)
        graph = {}
        for i, l in enumerate(lines):
            a, b, w = tuple(l[0]), tuple(l[-1]), sum(meters(p, q) for p, q in zip(l, l[1:]))
            graph.setdefault(a, []).append((b, w, i))
            graph.setdefault(b, []).append((a, w, i))
        import heapq
        dist, prev, heap = {}, {}, [(0, s) for s in ends[0]]
        for s in ends[0]:
            dist[s] = 0
        goal = None
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue
            if u in ends[1]:
                goal = u
                break
            for v, w, i in graph.get(u, []):
                if d + w < dist.get(v, math.inf):
                    dist[v], prev[v] = d + w, (u, i)
                    heapq.heappush(heap, (d + w, v))
        if goal is None:
            raise SystemExit(f"no path along {name} between {entry['between']}")
        keep = set()
        while goal in prev:
            goal, i = prev[goal]
            keep.add(i)
        lines = [l for i, l in enumerate(lines) if i in keep]
    return {"type": "MultiLineString", "coordinates": lines} if lines else None


SKIP_ROADS = re.compile(r"EXPY|EXPWY|\bEP\b|BRG|BRIDGE|RAMP|ENTRANCE|\bEN\b|EXIT|\bET\b|TUNNEL|PKWY|APPR|SVC", re.I)


def bearing(a, b):
    """Compass heading in degrees from point a to point b, both (lng, lat)."""
    dx = (b[0] - a[0]) * math.cos(math.radians(a[1]))
    dy = b[1] - a[1]
    return round(math.degrees(math.atan2(dx, dy)) % 360)


def nearest_on(p, lines):
    """Closest point to p on any of the polylines, with the segment it's on."""
    best = (math.inf, None, None)
    for line in lines:
        for a, b in zip(line, line[1:]):
            ax, ay = (a[0] - p[0]) * math.cos(math.radians(p[1])), a[1] - p[1]
            bx, by = (b[0] - p[0]) * math.cos(math.radians(p[1])), b[1] - p[1]
            dx, dy = bx - ax, by - ay
            t = 0 if dx == dy == 0 else max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
            q = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])]
            d = meters(p, q)
            if d < best[0]:
                best = (d, q, (a, b))
    return best


SUFFIX_FULL = {"St": "ST", "Street": "ST", "Ave": "AVE", "Avenue": "AVE", "Pl": "PL", "Place": "PL",
               "Blvd": "BLVD", "Boulevard": "BLVD"}


def address_street(site):
    """CSCL name of the street in the site's first address, e.g. "280 Kent Ave" -> "KENT AVE"."""
    m = re.search(r"\b\d+[-\d]*\s+((?:[A-Z][a-z]+\s){1,3})(St|Street|Ave|Avenue|Pl|Place|Blvd|Boulevard)\b",
                  site.get("neighborhood", ""))
    return (m.group(1).strip().upper() + " " + SUFFIX_FULL[m.group(2)]) if m else None


def viewpoint(site, features):
    """Where the popup's Street View stands and faces. A hand-set `streetview` in sites.json wins
    (for spots where the nearest street has no Google imagery)."""
    sv = site.get("streetview") or {}
    if "lat" in sv:
        return {k: sv[k] for k in ("lat", "lng", "heading")}
    pin = [site["lng"], site["lat"]]
    lines = [l for f in features if f["properties"]["site"] == site["id"] and "LineString" in f["geometry"]["type"]
             for l in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "LineString" else f["geometry"]["coordinates"])]
    if lines and not sv.get("street"):  # a street or creek: stand on it at the pin, look along it
        _, q, (a, b) = nearest_on(pin, lines)
        return {"lat": round(q[1], 6), "lng": round(q[0], 6), "heading": bearing(a, b)}
    q = {"$select": "full_street_name,the_geom", "$limit": "200",
         "$where": f"boroughcode='3' AND within_circle(the_geom,{site['lat']},{site['lng']},200)"}
    rows = get_json(CSCL + "?" + urllib.parse.urlencode(q))
    usable = [r for r in rows if not SKIP_ROADS.search(r["full_street_name"])]
    named = sv.get("street") or address_street(site)
    # look from the street in the site's address when it's close by (the front door, not the back lot line)
    if named and any(r["full_street_name"] == named for r in usable):
        usable = [r for r in usable if r["full_street_name"] == named]
    streets = [[[x, y] for x, y in l] for r in usable for l in r["the_geom"]["coordinates"]]
    if not streets:
        return {"lat": site["lat"], "lng": site["lng"], "heading": 0}
    _, q, _ = nearest_on(pin, streets)
    return {"lat": round(q[1], 6), "lng": round(q[0], 6), "heading": bearing(q, pin)}


def fetch_osm(ref):
    """Geometry of an OpenStreetMap way or relation, e.g. "way/392486579"."""
    kind, _, oid = ref.partition("/")
    els = get_json(f"{OSM}/{kind}/{oid}/full.json")["elements"]
    nodes = {e["id"]: [round(e["lon"], 6), round(e["lat"], 6)] for e in els if e["type"] == "node"}
    ways = {e["id"]: e for e in els if e["type"] == "way"}
    if kind == "way":
        w = ways[int(oid)]
        coords = [nodes[n] for n in w["nodes"]]
        if w["nodes"][0] == w["nodes"][-1] and len(coords) > 3:
            return {"type": "Polygon", "coordinates": [coords]}
        return {"type": "LineString", "coordinates": coords}
    lines = [[nodes[n] for n in w["nodes"]] for w in ways.values()]
    return {"type": "MultiLineString", "coordinates": lines} if lines else None


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "sites.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "lots.geojson"
    with open(src, encoding="utf-8") as f:
        sites = json.load(f)
    owner = {str(b): s["id"] for s in sites for b in s.get("bbls", [])}
    rows = fetch(owner) if owner else []
    found = {str(int(r["bbl"])) for r in rows}
    features = [{
        "type": "Feature",
        "properties": {"site": owner[str(int(r["bbl"]))], "bbl": str(int(r["bbl"])), "address": r["address"]},
        "geometry": json.loads(r["geom"]),
    } for r in sorted(rows, key=lambda r: r["bbl"])]
    missing_streets = []
    for s in sites:
        for entry in s.get("streets", []):
            geom = fetch_street(entry)
            label = entry if isinstance(entry, str) else entry["name"] + (
                f" along {entry['along']}" if entry.get("along") else "") + (
                f" between {' and '.join(entry['between'])}" if entry.get("between") else "")
            if geom:
                features.append({"type": "Feature", "properties": {"site": s["id"], "street": label}, "geometry": geom})
            else:
                missing_streets.append(label)
        for ref in s.get("osm", []):
            geom = fetch_osm(ref)
            if geom:
                features.append({"type": "Feature", "properties": {"site": s["id"], "osm": ref}, "geometry": geom})
            else:
                missing_streets.append(ref)
        if s.get("path"):
            features.append({"type": "Feature", "properties": {"site": s["id"], "path": "proposed"},
                             "geometry": {"type": "LineString", "coordinates": [[lng, lat] for lat, lng in s["path"]]}})
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        f.write("\n")
    views = {s["id"]: viewpoint(s, features) for s in sites}
    with open("viewpoints.json", "w", encoding="utf-8") as f:
        json.dump(views, f, indent=1)
        f.write("\n")
    missing = sorted(set(owner) - found)
    print(f"{len(features)} lots and streets written to {dst}"
          + (f"; not in MapPLUTO: {', '.join(missing)}" if missing else "")
          + (f"; no geometry for: {', '.join(missing_streets)}" if missing_streets else ""))
    sys.exit(1 if missing or missing_streets else 0)


if __name__ == "__main__":
    main()
