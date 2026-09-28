#!/usr/bin/env python3
"""Fetch tax-lot outlines and street lines for sites.json and write lots.geojson.

The map shades each lot in its site's pin color. Outlines come from NYC Planning's
MapPLUTO table (the same data ZoLa uses). Street projects list `streets` (exact
Brooklyn street names from the city's street centerline file, CSCL); those
segments are drawn as a line instead. Rerun whenever `bbls` or `streets` change.

Usage: python3 scripts/fetch_lots.py [sites.json] [lots.geojson]
"""
import json
import sys
import urllib.parse
import urllib.request

CARTO = "https://planninglabs.carto.com/api/v2/sql"
CSCL = "https://data.cityofnewyork.us/resource/inkn-q76z.json"


def fetch(bbls):
    ids = ",".join(str(int(b)) for b in bbls)
    sql = (f"SELECT bbl, address, ST_AsGeoJSON(the_geom, 6) AS geom "
           f"FROM dcp_mappluto WHERE bbl IN ({ids})")
    url = CARTO + "?" + urllib.parse.urlencode({"q": sql})
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-urban-projects-lots"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["rows"]


def fetch_street(name):
    """All Brooklyn centerline segments with this exact name, merged into one MultiLineString."""
    q = {"$select": "the_geom", "$limit": "1000",
         "$where": f"full_street_name='{name.upper()}' AND boroughcode='3'"}
    req = urllib.request.Request(CSCL + "?" + urllib.parse.urlencode(q),
                                 headers={"User-Agent": "nyc-urban-projects-lots"})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.load(r)
    lines = [[[round(x, 6), round(y, 6)] for x, y in line]
             for row in rows for line in row["the_geom"]["coordinates"]]
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
        for name in s.get("streets", []):
            geom = fetch_street(name)
            if geom:
                features.append({"type": "Feature", "properties": {"site": s["id"], "street": name}, "geometry": geom})
            else:
                missing_streets.append(name)
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        f.write("\n")
    missing = sorted(set(owner) - found)
    print(f"{len(features)} lots and streets written to {dst}"
          + (f"; not in MapPLUTO: {', '.join(missing)}" if missing else "")
          + (f"; not in CSCL: {', '.join(missing_streets)}" if missing_streets else ""))
    sys.exit(1 if missing or missing_streets else 0)


if __name__ == "__main__":
    main()
