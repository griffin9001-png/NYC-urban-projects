#!/usr/bin/env python3
"""Fetch tax-lot outlines for every BBL in sites.json and write lots.geojson.

The map shades each lot in its site's pin color. Outlines come from NYC Planning's
MapPLUTO table (the same data ZoLa uses). Rerun whenever `bbls` change.

Usage: python3 scripts/fetch_lots.py [sites.json] [lots.geojson]
"""
import json
import sys
import urllib.parse
import urllib.request

CARTO = "https://planninglabs.carto.com/api/v2/sql"


def fetch(bbls):
    ids = ",".join(str(int(b)) for b in bbls)
    sql = (f"SELECT bbl, address, ST_AsGeoJSON(the_geom, 6) AS geom "
           f"FROM dcp_mappluto WHERE bbl IN ({ids})")
    url = CARTO + "?" + urllib.parse.urlencode({"q": sql})
    req = urllib.request.Request(url, headers={"User-Agent": "nyc-urban-projects-lots"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["rows"]


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
    with open(dst, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
        f.write("\n")
    missing = sorted(set(owner) - found)
    print(f"{len(features)} lots written to {dst}" + (f"; not in MapPLUTO: {', '.join(missing)}" if missing else ""))
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    main()
