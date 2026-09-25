#!/usr/bin/env python3
"""Check sites.json against NYC PLUTO (tax-lot records) and write audit.json.

For every site it looks up the lot under the pin and each lot listed in `bbls`,
then flags:
  - condition vs PLUTO: e.g. "vacant" while PLUTO records buildings on the lot
  - pin placement: the pin is far from every listed lot
  - missing lots: a development site with no `bbls` to check against
  - unverified condition

Needs network access to geosearch.planninglabs.nyc and data.cityofnewyork.us.
Usage: python3 scripts/audit_sites.py [sites.json] [audit.json]
"""
import datetime
import json
import math
import sys
import urllib.parse
import urllib.request

PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
REVERSE = "https://geosearch.planninglabs.nyc/v2/reverse"
LAND_USE = {
    "1": "1-2 family homes", "2": "Walk-up apartments", "3": "Elevator apartments",
    "4": "Mixed residential/commercial", "5": "Commercial/office", "6": "Industrial/manufacturing",
    "7": "Transportation/utility", "8": "Public facilities", "9": "Open space/recreation",
    "10": "Parking", "11": "Vacant land",
}
# Conditions that describe a specific lot and can be compared with PLUTO.
LOT_CONDITIONS = {"vacant", "existing-buildings", "under-construction", "partly-built"}
PIN_TOLERANCE_M = 80


def get_json(url, params):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                 headers={"User-Agent": "nyc-urban-projects-audit"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pluto_lot(bbl):
    rows = get_json(PLUTO, {"bbl": bbl, "$select": "bbl,address,landuse,bldgclass,numbldgs,"
                            "yearbuilt,bldgarea,lotarea,ownername,latitude,longitude"})
    if not rows:
        return None
    r = rows[0]
    return {
        "bbl": str(r.get("bbl", bbl)).split(".")[0],
        "address": r.get("address"),
        "land_use": LAND_USE.get(str(r.get("landuse")), "Unknown"),
        "buildings": int(float(r.get("numbldgs") or 0)),
        "building_area_sqft": int(float(r.get("bldgarea") or 0)),
        "year_built": int(float(r.get("yearbuilt") or 0)) or None,
        "owner": r.get("ownername"),
        "lot_area_sqft": int(float(r.get("lotarea") or 0)),
        "lat": float(r["latitude"]) if r.get("latitude") else None,
        "lng": float(r["longitude"]) if r.get("longitude") else None,
    }


def pin_bbl(lat, lng):
    feats = get_json(REVERSE, {"point.lat": lat, "point.lon": lng, "size": 1}).get("features", [])
    if not feats:
        return None
    return feats[0]["properties"].get("addendum", {}).get("pad", {}).get("bbl")


def distance_m(a_lat, a_lng, b_lat, b_lng):
    dy = (a_lat - b_lat) * 111_320
    dx = (a_lng - b_lng) * 111_320 * math.cos(math.radians(a_lat))
    return math.hypot(dx, dy)


def observed_condition(lots):
    """What PLUTO says stands on the listed lots."""
    if not lots:
        return None
    built = [l for l in lots if l["building_area_sqft"] > 0 or l["buildings"] > 0]
    if not built:
        return "vacant"
    return "existing-buildings" if len(built) == len(lots) else "partly-built"


def audit_site(site):
    flags = []
    condition = site.get("condition")
    lots = []
    for bbl in site.get("bbls", []):
        lot = pluto_lot(bbl)
        if lot:
            lots.append(lot)
        else:
            flags.append(f"BBL {bbl} not found in PLUTO")

    pin = None
    try:
        bbl = pin_bbl(site["lat"], site["lng"])
        pin = pluto_lot(bbl) if bbl else None
    except Exception as e:  # geosearch hiccups shouldn't sink the whole audit
        flags.append(f"pin lookup failed: {e}")

    if condition == "unverified":
        flags.append("condition unverified: confirm what stands on the site and set condition")
    if site.get("category") == "parcel" and not site.get("bbls"):
        flags.append("no bbls listed: pin and condition can't be checked against PLUTO")

    observed = observed_condition(lots)
    if condition in LOT_CONDITIONS and observed:
        if condition == "vacant" and observed != "vacant":
            flags.append(f"labeled vacant but PLUTO records buildings ({observed})")
        if condition == "existing-buildings" and observed == "vacant":
            flags.append("labeled existing buildings but PLUTO records no buildings")

    if lots:
        dists = [distance_m(site["lat"], site["lng"], l["lat"], l["lng"])
                 for l in lots if l["lat"] is not None]
        on_listed_lot = pin and pin["bbl"] in {l["bbl"] for l in lots}
        if dists and not on_listed_lot:
            # Allow for big lots: tolerance grows with the lot's size.
            tol = max(PIN_TOLERANCE_M, max(math.sqrt(l["lot_area_sqft"]) * 0.3048 for l in lots))
            if min(dists) > tol:
                flags.append(f"pin is {round(min(dists))} m from the nearest listed lot")

    return {"condition": condition, "pluto_condition": observed, "lots": lots,
            "pin_lot": pin, "flags": flags}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "sites.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "audit.json"
    with open(src, encoding="utf-8") as f:
        sites = json.load(f)
    report = {"generated": datetime.date.today().isoformat(), "sites": {}}
    for site in sites:
        result = audit_site(site)
        report["sites"][site["id"]] = result
        status = "OK" if not result["flags"] else "; ".join(result["flags"])
        print(f"{site['id']:28} {status}")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        f.write("\n")
    flagged = sum(1 for r in report["sites"].values() if r["flags"])
    print(f"{len(sites)} sites audited, {flagged} flagged, wrote {dst}")


if __name__ == "__main__":
    main()
