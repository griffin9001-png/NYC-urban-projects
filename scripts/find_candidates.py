#!/usr/bin/env python3
"""Find possible new sites for the map and write candidates.json.

Pulls leads for Brooklyn Community Districts 1-4 (Greenpoint, Williamsburg, Fort
Greene/Clinton Hill/Brooklyn Heights, Bed-Stuy, Bushwick) from:
  - zoning:   City Planning's Zoning Application Portal (rezonings, waterfront sign-offs)
  - building: Buildings Department new-building filings with MIN_HOMES+ proposed homes
  - park:     Parks Department capital project tracker (projects not yet finished)
  - news:     recent Greenpointers, Streetsblog NYC and Brooklyn Paper headlines that
              name the area and a development topic

Each lead is matched against sites.json: `on_map` when it shares a lot with a site (or,
for news, names one), `near` when a site's pin is within MATCH_M metres or its name is in
the title. Near is a hint to check, not proof it's the same project.
candidates.html shows the list. Nothing here edits sites.json: a lead becomes a site
only after someone reads the sources in full (UPDATING.md, "Adding a site").

Needs network access. Usage: python3 scripts/find_candidates.py [sites.json] [candidates.json]
"""
import datetime
import html
import json
import math
import re
import sys
import urllib.parse
import urllib.request

AREA_CDS = ["301", "302", "303", "304"]
MIN_HOMES = 50
BUILDING_SINCE = "2024-01-01"
ZONING_SINCE = "2024-01-01"
NEWS_DAYS = 45
MATCH_M = 75

SODA = "https://data.cityofnewyork.us/resource/"
UA = {"User-Agent": "Mozilla/5.0 (nyc-urban-projects-candidates)"}
NEWS_SITES = {
    "Greenpointers": "https://greenpointers.com",
    "Streetsblog NYC": "https://nyc.streetsblog.org",
    "Brooklyn Paper": "https://www.brooklynpaper.com",
}
AREA_WORDS = r"greenpoint|williamsburg|bushwick|bed-?stuy|bedford-stuyvesant|fort greene|clinton hill|navy yard|" \
             r"brooklyn heights|dumbo|vinegar hill|boerum hill|downtown brooklyn|east williamsburg|newtown creek|" \
             r"mcguinness|bedford av|kent av|flushing av|myrtle av|broadway triangle|domino|bushwick inlet"
TOPIC_WORDS = r"rezon|develop|tower|apartment|housing|affordable|lottery|park|playground|greenway|bike lane|" \
              r"redesign|road diet|bus lane|plaza|shelter|demoli|construction|community board|landmark|cleanup|" \
              r"superfund|waterfront|bqe"
NOISE_WORDS = r"shot|stabb|arrest|murder|killed|dies|died|enroll|book sale|what.s happening|restaurant|bar\b"


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r), r.headers


def soda(ds, **params):
    return get(SODA + ds + ".json", {"$" + k: v for k, v in params.items()})[0]


def metres(a_lat, a_lng, b_lat, b_lng):
    return math.hypot((a_lng - b_lng) * 111_320 * math.cos(math.radians(a_lat)), (a_lat - b_lat) * 111_320)


def inside(lng, lat, ring):
    hit = False
    for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1]):
        if (ay > lat) != (by > lat) and lng < ax + (lat - ay) * (bx - ax) / (by - ay):
            hit = not hit
    return hit


def area_polygons():
    rows = soda("5crt-au7u", where=f"boro_cd in({','.join(repr(c) for c in AREA_CDS)})", limit=10)
    return [poly[0] for r in rows for poly in r["the_geom"]["coordinates"]]


def pluto_points(bbls):
    """lat/lng and address for each BBL, from PLUTO."""
    out = {}
    bbls = sorted(set(bbls))
    for i in range(0, len(bbls), 100):
        chunk = ",".join(f"'{b}'" for b in bbls[i:i + 100])
        for r in soda("64uk-42ks", select="bbl,address,latitude,longitude", where=f"bbl in({chunk})", limit=1000):
            if r.get("latitude"):
                out[str(r["bbl"]).split(".")[0]] = (float(r["latitude"]), float(r["longitude"]), r.get("address"))
    return out


def zoning():
    cds = ",".join(f"'K{c[1:]}'" for c in AREA_CDS)
    rows = soda("hgx4-8ukb", where=f"borough='Brooklyn' AND community_district in({cds}) AND "
                                   f"(project_status='Active' OR completed_date>'{ZONING_SINCE}')",
                select="project_id,project_name,project_brief,project_status,public_status,ulurp_non,"
                       "completed_date,certified_referred,current_milestone_date", limit=1000)
    ids = ",".join(f"'{r['project_id']}'" for r in rows) or "''"
    lots = {}
    for r in soda("2iga-a6mk", select="project_id,bbl", where=f"project_id in({ids}) AND bbl IS NOT NULL", limit=5000):
        lots.setdefault(r["project_id"], []).append(r["bbl"])
    pts = pluto_points([b for bs in lots.values() for b in bs])
    out = []
    for r in rows:
        brief = r.get("project_brief", "")
        homes = re.search(r"([\d,]+)\s*(?:DUs?|dwelling units|residential units|units)\b", brief, re.I)
        bbls = lots.get(r["project_id"], [])
        pt = next((pts[b] for b in bbls if b in pts), None)
        date = r.get("completed_date") or r.get("current_milestone_date") or r.get("certified_referred") or ""
        out.append({
            "source": "zoning", "key": r["project_id"], "title": r["project_name"],
            "summary": brief[:400], "status": r.get("public_status") or r.get("project_status"),
            "date": date[:10], "homes": int(homes.group(1).replace(",", "")) if homes else None,
            "bbls": bbls, "lat": pt and pt[0], "lng": pt and pt[1], "address": pt and pt[2],
            "link": f"https://zap.planning.nyc.gov/projects/{r['project_id']}",
            "active": r.get("project_status") == "Active",
        })
    return out


def buildings():
    cbs = ",".join(f"'{c}'" for c in AREA_CDS)
    rows = soda("w9ak-ipjd", select="bbl,max(house_no) as house,max(street_name) as street,"
                                    "max(proposed_dwelling_units::number) as homes,max(filing_date) as filed,"
                                    "max(latitude) as lat,max(longitude) as lng",
                where=f"job_type='New Building' AND commmunity_board in({cbs}) AND bbl IS NOT NULL AND "
                      f"proposed_dwelling_units::number>={MIN_HOMES} AND filing_date>'{BUILDING_SINCE}'",
                group="bbl", limit=2000)
    out = []
    for r in rows:
        b = r["bbl"]
        addr = f"{r.get('house', '')} {r.get('street', '')}".strip().title()
        out.append({
            "source": "building", "key": b, "title": f"{addr}: new building, {int(float(r['homes']))} homes",
            "summary": "", "status": "Filed with the Buildings Department", "date": r["filed"][:10],
            "homes": int(float(r["homes"])), "bbls": [b],
            "lat": float(r["lat"]) if r.get("lat") else None, "lng": float(r["lng"]) if r.get("lng") else None,
            "address": addr, "link": f"https://zola.planning.nyc.gov/l/lot/{b[0]}/{int(b[1:6])}/{int(b[6:])}",
            "active": True,
        })
    return out


def parks(polys):
    rows = soda("4hcv-tc5r", where="borough='Brooklyn' AND currentphase!='completed'", limit=5000)
    out = []
    for r in rows:
        try:
            lat, lng = float(r["latitude"]), float(r["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if not any(inside(lng, lat, ring) for ring in polys):
            continue
        dates = [("construction starts", r.get("constructionstart")),
                 ("construction ends", r.get("constructionadjustedcompletion") or r.get("constructionprojectedcom"))]
        when = "; ".join(f"{k} {v[:7]}" for k, v in dates if v)
        out.append({
            "source": "park", "key": r["trackerid"], "title": r.get("title", ""),
            "summary": f"{r.get('summary', '')} {r.get('name', '')}. Funding: {r.get('totalfunding', 'n/a')}. {when}".strip(),
            "status": f"Parks: {r.get('currentphase')}", "date": (r.get("lastupdated") or "")[:10], "homes": None,
            "bbls": [], "lat": lat, "lng": lng, "address": r.get("name"),
            "link": f"{SODA}4hcv-tc5r.json?trackerid={r['trackerid']}", "active": True,
        })
    return out


def news():
    since = (datetime.date.today() - datetime.timedelta(days=NEWS_DAYS)).isoformat() + "T00:00:00"
    out = []
    for outlet, base in NEWS_SITES.items():
        for page in range(1, 11):
            try:
                posts, headers = get(base + "/wp-json/wp/v2/posts",
                                     {"after": since, "per_page": 100, "page": page, "_fields": "date,link,title"})
            except Exception as e:
                print(f"  {outlet} page {page}: {e}", file=sys.stderr)
                break
            for p in posts:
                title = html.unescape(re.sub(r"<[^>]+>", "", p["title"]["rendered"]))
                if re.search(AREA_WORDS, title, re.I) and re.search(TOPIC_WORDS, title, re.I) \
                        and not re.search(NOISE_WORDS, title, re.I):
                    out.append({"source": "news", "key": p["link"], "title": title, "summary": outlet,
                                "status": outlet, "date": p["date"][:10], "homes": None, "bbls": [],
                                "lat": None, "lng": None, "address": None, "link": p["link"], "active": True})
            if page >= int(headers.get("X-WP-TotalPages", 1)):
                break
    return out


def name_variants(name):
    base = re.sub(r"\s*\(.*\)", "", name).lower()
    swaps = [("avenue", "ave"), ("street", "st"), ("boulevard", "blvd")]
    out = {base}
    for long, short in swaps:
        out |= {v.replace(long, short) for v in out} | {v.replace(short + " ", long + " ") for v in out}
    return {v for v in out if len(v) >= 6}


def match(c, sites):
    """(on_map, near): the site this lead already is, and a site it may belong to."""
    near = None
    for s in sites:
        if set(c["bbls"]) & set(s.get("bbls", [])):
            return s["id"], None
        named = any(v in c["title"].lower() for v in name_variants(s["name"]))
        if named and c["source"] == "news":
            return s["id"], None
        if near is None and (named or (c["lat"] and metres(c["lat"], c["lng"], s["lat"], s["lng"]) <= MATCH_M)):
            near = s["id"]
    return None, near


def score(c, today):
    pts = min((c["homes"] or 0) / 100, 8)
    if c["source"] == "zoning" and c["status"] in ("Filed", "In Public Review", "Noticed"):
        pts += 3
    if c["source"] == "park" and "construction" in c["status"]:
        pts += 2
    try:
        age = (today - datetime.date.fromisoformat(c["date"])).days
        pts += 2 if age <= 90 else 1 if age <= 365 else 0
    except ValueError:
        pass
    return round(pts, 2)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "sites.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "candidates.json"
    with open(src, encoding="utf-8") as f:
        sites = json.load(f)
    today = datetime.date.today()
    polys = area_polygons()
    found, counts = [], {}
    for name, fn in (("zoning", zoning), ("building", buildings), ("park", lambda: parks(polys)), ("news", news)):
        try:
            rows = fn()
        except Exception as e:  # one source being down shouldn't sink the rest
            print(f"{name}: failed ({e})", file=sys.stderr)
            rows = []
        counts[name] = len(rows)
        found += rows
    for c in found:
        c["on_map"], c["near"] = match(c, sites)
        c["score"] = score(c, today)
    found.sort(key=lambda c: (c["on_map"] is not None, -c["score"], c["title"]))
    report = {"generated": today.isoformat(), "area": f"Brooklyn Community Districts {', '.join(str(int(c[1:])) for c in AREA_CDS)}",
              "min_homes": MIN_HOMES, "counts": counts, "candidates": found}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, ensure_ascii=False)
        f.write("\n")
    new = [c for c in found if not c["on_map"]]
    print(f"{len(found)} leads ({', '.join(f'{k} {v}' for k, v in counts.items())}); "
          f"{len(found) - len(new)} already on the map; wrote {dst}")
    for c in new[:15]:
        print(f"  {c['score']:5.2f}  {c['source']:8} {c['title'][:80]}")


if __name__ == "__main__":
    main()
