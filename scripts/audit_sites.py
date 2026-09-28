#!/usr/bin/env python3
"""Check sites.json against NYC PLUTO (tax-lot records) and write audit.json.

For every site it looks up the lot under the pin and each lot listed in `bbls`,
then flags:
  - condition vs PLUTO: e.g. "vacant" while PLUTO records buildings on the lot
  - pin placement: the pin is far from every listed lot
  - missing lots: a development site with no `bbls` to check against
  - unverified condition
  - missing or broken image (images are hotlinked, so source sites can move them)
  - street addresses in `neighborhood` that NYC's address database (PAD, via GeoSearch) doesn't put
    on the site's own lots, unless `address_notes` explains why the address stands
  - image that can't be tied to this site: its `image.page` must load, contain the
    image, and name the site (`image.shows`) in the page title or next to the image;
    if `shows` is an address it must fall on one of the site's `bbls`

Needs network access to geosearch.planninglabs.nyc and data.cityofnewyork.us.
Usage: python3 scripts/audit_sites.py [sites.json] [audit.json]
"""
import datetime
import html
import json
import math
import re
import sys
import urllib.parse
import urllib.request

PLUTO = "https://data.cityofnewyork.us/resource/64uk-42ks.json"
REVERSE = "https://geosearch.planninglabs.nyc/v2/reverse"
SEARCH = "https://geosearch.planninglabs.nyc/v2/search"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
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


def image_ok(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (nyc-urban-projects-audit)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200 and r.headers.get("Content-Type", "").startswith("image")
    except Exception:
        return False


def image_tokens(url):
    """Pieces of an image URL that should appear in the HTML of the page it came from."""
    path = urllib.parse.urlparse(url).path
    tokens = {path.rsplit("/", 1)[-1]} - {""}
    for seg in path.split("/"):
        stem = re.sub(r"\.(jpe?g|png|webp|gif)$", "", seg, flags=re.I)
        while True:  # WordPress adds -scaled, -1024x570 and -e1234567890 to resized copies
            shorter = re.sub(r"-(scaled|\d+x\d+|e\d{9,})$", "", stem)
            if shorter == stem:
                break
            stem = shorter
        if stem in {"wp-content", "uploads", "app", "images", "assets"} or re.fullmatch(r"\d{1,4}", stem):
            continue
        if len(stem) >= 6 or re.search(r"\d", stem):
            tokens.add(stem)
    return tokens


def check_image_page(site, img):
    """Flags for an image that can't be shown to belong to this site."""
    page, shows = img.get("page"), img.get("shows")
    if not page or not shows:
        return ["image has no page/shows: record where it came from and what names the site (UPDATING.md)"]
    req = urllib.request.Request(page, headers={"User-Agent": BROWSER_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            doc = r.read().decode("utf-8", "ignore")
    except Exception as e:
        return [f"image page could not be read ({e}): cannot confirm the image shows this site; pick one from a readable page"]
    if "<title>Just a moment" in doc[:5000]:
        return ["image page is behind a bot wall: cannot confirm the image shows this site; pick one from a readable page"]
    want = shows.lower()
    heads = " ".join(a or b for a, b in re.findall(
        r'<title[^>]*>(.*?)</title>|(?:og:title|og:image:alt)"\s+content="([^"]*)"', doc, re.S | re.I))
    spots = [m.start() for tok in image_tokens(img["url"]) for m in re.finditer(re.escape(tok), doc)]
    if not spots:
        return ["image does not appear on its page: it may be from a different article"]
    near = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", doc[max(0, i - 1500):i + 1500]))
                    + " " + " ".join(re.findall(r'alt="([^"]*)"', doc[max(0, i - 1500):i + 1500])) for i in spots)
    flags = []
    if want not in html.unescape(heads).lower() and want not in near.lower():
        flags.append(f'image page does not name "{shows}" in its title or next to the image: check it shows this site')
    if re.match(r"\d", shows):  # an address: it must be on one of the site's lots
        try:
            feats = get_json(SEARCH, {"text": shows + ", Brooklyn", "size": 1}).get("features", [])
            bbl = feats[0]["properties"]["addendum"]["pad"]["bbl"] if feats else None
            if bbl not in site.get("bbls", []):
                flags.append(f'image address "{shows}" is lot {bbl}, not one of this site\'s bbls')
        except Exception as e:
            flags.append(f"image address lookup failed: {e}")
    return flags


ADDRESS_RE = re.compile(r"\b\d+[-\d]*\s+(?:[A-Z][a-z]+\s){1,3}(?:St|Ave|Street|Avenue|Pl|Place|Blvd|Boulevard)\b")
SUFFIX_FULL = {"St": "Street", "Ave": "Avenue", "Pl": "Place", "Blvd": "Boulevard"}


def check_addresses(site):
    """Flags for addresses in `neighborhood` that land on another lot (or none). Ranges like 79-97 pass
    if either end is on the site. Only sites with `bbls` are checked."""
    if not site.get("bbls"):
        return []
    noted = set((site.get("address_notes") or {}).keys())
    flags = []
    for addr in ADDRESS_RE.findall(site.get("neighborhood", "")):
        if addr in noted:
            continue
        words = addr.split()
        words[-1] = SUFFIX_FULL.get(words[-1], words[-1])
        found = []
        for num in dict.fromkeys(words[0].split("-")):
            try:
                feats = get_json(SEARCH, {"text": " ".join([num] + words[1:]) + ", Brooklyn, NY", "size": 5}).get("features", [])
            except Exception as e:
                return [f"address lookup failed: {e}"]
            found += [(f["properties"]["label"].split(",")[0], f["properties"].get("addendum", {}).get("pad", {}).get("bbl"))
                      for f in feats if "Brooklyn" in f["properties"]["label"] and f["properties"]["label"].split()[0] == num]
        if not any(b in site["bbls"] for _, b in found):
            where = f"lot {found[0][1]} ({found[0][0].title()})" if found else "no lot in the city's address database"
            flags.append(f'address "{addr}" is on {where}, not this site\'s lots: fix it, or explain in address_notes')
    return flags


def distance_m(a_lat, a_lng, b_lat, b_lng):
    dy = (a_lat - b_lat) * 111_320
    dx = (a_lng - b_lng) * 111_320 * math.cos(math.radians(a_lat))
    return math.hypot(dx, dy)


def observed_condition(lots):
    """What PLUTO says stands on the listed lots."""
    if not lots:
        return None
    # PLUTO counts booths and sheds on parking lots as buildings with zero floor area,
    # so only recorded floor area counts as "built".
    built = [l for l in lots if l["building_area_sqft"] > 0]
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

    img = site.get("image")
    if not img:
        flags.append("no image: popup falls back to a Street View link (see UPDATING.md for how to find one)")
    elif not image_ok(img["url"]):
        flags.append("image URL no longer loads: replace it")
    else:
        flags += check_image_page(site, img)

    flags += check_addresses(site)

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
