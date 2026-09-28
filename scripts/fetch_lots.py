#!/usr/bin/env python3
"""Fetch each site's shape for the map and write lots.geojson.

- `bbls`: tax-lot outlines from NYC Planning's MapPLUTO table (the data ZoLa uses).
- `streets`: street lines from the city's street centerline file (CSCL). Each entry is
  an exact Brooklyn street name, or {"name": ..., "along": ...} to keep only the
  segments within 40 m of another street (e.g. Park Ave where it runs under the BQE).
- `osm`: OpenStreetMap elements such as "way/392486579" (creeks, plazas, anything
  the city files don't cover). Closed ways become areas, open ways and relations lines.

The map draws all of them in the site's pin color, and validate_sites.py checks every
pin sits on its site's shape. Rerun whenever `bbls`, `streets` or `osm` change.

Usage: python3 scripts/fetch_lots.py [sites.json] [lots.geojson]
"""
import json
import math
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


def street_lines(name):
    q = {"$select": "the_geom", "$limit": "2000",
         "$where": f"full_street_name='{name.upper()}' AND boroughcode='3'"}
    rows = get_json(CSCL + "?" + urllib.parse.urlencode(q))
    return [[[round(x, 6), round(y, 6)] for x, y in line]
            for row in rows for line in row["the_geom"]["coordinates"]]


def meters(a, b):
    return math.hypot((a[0] - b[0]) * 111_320 * math.cos(math.radians(a[1])), (a[1] - b[1]) * 111_320)


def fetch_street(entry):
    """Centerline segments for a `streets` entry, merged into one MultiLineString."""
    name = entry if isinstance(entry, str) else entry["name"]
    lines = street_lines(name)
    if isinstance(entry, dict) and entry.get("along"):
        guide = [(a[0] + (b[0] - a[0]) * k / 10, a[1] + (b[1] - a[1]) * k / 10)
                 for line in street_lines(entry["along"]) for a, b in zip(line, line[1:]) for k in range(11)]
        lines = [l for l in lines if min(meters(l[len(l) // 2], g) for g in guide) <= ALONG_M]
    return {"type": "MultiLineString", "coordinates": lines} if lines else None


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
            label = entry if isinstance(entry, str) else f"{entry['name']} along {entry.get('along')}"
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
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        f.write("\n")
    missing = sorted(set(owner) - found)
    print(f"{len(features)} lots and streets written to {dst}"
          + (f"; not in MapPLUTO: {', '.join(missing)}" if missing else "")
          + (f"; no geometry for: {', '.join(missing_streets)}" if missing_streets else ""))
    sys.exit(1 if missing or missing_streets else 0)


if __name__ == "__main__":
    main()
