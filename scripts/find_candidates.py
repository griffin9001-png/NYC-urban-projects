#!/usr/bin/env python3
"""Find possible new sites for the map and write candidates.json.

Pulls leads for Brooklyn Community Districts 1-4 (Greenpoint, Williamsburg, Fort
Greene/Clinton Hill/Brooklyn Heights, Bed-Stuy, Bushwick) from:
  - zoning:   City Planning's Zoning Application Portal (rezonings, waterfront sign-offs)
  - building: Buildings Department new-building filings with MIN_HOMES+ proposed homes
  - park:     Parks Department capital project tracker (projects not yet finished)
  - street:   DOT bike lane and street redesign plans in development, from DOT's
              "Current Bicycle Route Projects" list and its nycdotprojects.info project site
  - agenda:   items on recent and upcoming community board agendas: CB1's Transportation, Land
              Use and Parks committees and full board, CB3 and CB4 full board (CB2's site blocks
              automated reads)
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
STREET_STALE_YEARS = 3   # DOT project pages this long without a dated update are skipped
AGENDA_PAST_DAYS = 60    # agenda items from meetings this recent, plus any upcoming meeting
DONE_DAYS = 90           # drop leads finished longer ago than this (building occupied, approval done, park built)

SODA = "https://data.cityofnewyork.us/resource/"
UA = {"User-Agent": "Mozilla/5.0 (nyc-urban-projects-candidates)"}
CSCL = SODA + "inkn-q76z.json"
DOT_BIKE = "https://www.nyc.gov/html/dot/html/bicyclists/bike-projects.shtml"
DOT_PROJECTS = "https://nycdotprojects.info"
NYC = "https://www.nyc.gov"
GEOSEARCH = "https://geosearch.planninglabs.nyc/v2/search"
REVERSE = "https://geosearch.planninglabs.nyc/v2/reverse"
# (board, page listing agenda PDFs, which link texts to keep)
AGENDA_PAGES = [
    ("CB1", NYC + "/site/brooklyncb1/meetings/notices.page", r"Transportation|Land Use|Parks"),
    ("CB1", NYC + "/site/brooklyncb1/meetings/agendas.page", r"."),
    ("CB3", NYC + "/site/brooklyncb3/meetings/agendas.page", r"."),
    ("CB4", NYC + "/site/brooklyncb4/calendar/agendas.page", r"."),
]
AGENDA_SKIP = r"minutes|old business|new business|adjourn|roll call|chair.?person.s report|district manager|needs statement|" \
              r"co-?naming|sla\b|liquor|cannabis|pending and upcoming|election|budget|public session|announcements|" \
              r"acceptance of|precinct|introduction of|committee reports|^recommendations|elected officials|" \
              r"\bDBA\b|new application|renewal|temporary retail|wine, beer|dispensary|all night permit|dining out|" \
              r"withdrew|regular meeting agenda|^community board no|amended notices"
NEWS_SITES = {
    "Greenpointers": "https://greenpointers.com",
    "Streetsblog NYC": "https://nyc.streetsblog.org",
    "Brooklyn Paper": "https://www.brooklynpaper.com",
}
AREA_WORDS = r"greenpoint|williamsburg|bushwick|bed-?stuy|bedford-stuyvesant|fort greene|clinton hill|navy yard|" \
             r"brooklyn heights|dumbo|vinegar hill|boerum hill|downtown brooklyn|east williamsburg|newtown creek|" \
             r"mcguinness|bedford av|kent av|flushing av|myrtle av|broadway triangle|domino|bushwick inlet|" \
             r"meeker|metropolitan av|grand st|wyckoff|commercial st|nassau av|jay st|ashland|atlantic av"
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
    """lat/lng and PLUTO's address for each BBL. PLUTO's address field can be wrong (it lists Domino's Kent
    Avenue lots as "Kent Street"), so show lot_address() to people, not this."""
    out = {}
    bbls = sorted(set(bbls))
    for i in range(0, len(bbls), 100):
        chunk = ",".join(f"'{b}'" for b in bbls[i:i + 100])
        for r in soda("64uk-42ks", select="bbl,address,latitude,longitude", where=f"bbl in({chunk})", limit=1000):
            if r.get("latitude"):
                out[str(r["bbl"]).split(".")[0]] = (float(r["latitude"]), float(r["longitude"]), r.get("address"))
    return out


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read().decode("utf-8", "ignore")


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
SUFFIX = {"avenue": "AVE", "street": "ST", "place": "PL", "boulevard": "BLVD", "road": "RD", "parkway": "PKWY",
          "drive": "DR", "lane": "LN", "court": "CT", "expressway": "EXPY", "bridge": "BRG"}
_ends = {}


def cscl_name(s):
    words = re.sub(r"[^\w\s]", "", s).split()
    return " ".join(SUFFIX.get(w.lower(), w.upper()) for w in words)


def street_ends(name):
    if name not in _ends:
        try:
            rows = soda("inkn-q76z", select="the_geom", where=f"full_street_name='{name}' AND boroughcode='3'", limit=2000)
        except Exception:
            rows = []
        _ends[name] = {tuple(p) for r in rows for l in r["the_geom"]["coordinates"] for p in (l[0], l[-1])}
    return _ends[name]


def locate(title):
    """Where a DOT project title like "Meeker Avenue, Metropolitan Avenue to Apollo Street" starts: the
    intersection of its first two named streets in Brooklyn, or None."""
    streets = [cscl_name(s) for s in re.split(r",|&| to | and ", title)
               if re.search(r"\b(avenue|street|place|boulevard|road|parkway|drive|lane|court)\b", s, re.I)]
    for i, a in enumerate(streets):
        for b in streets[i + 1:]:
            hit = street_ends(a) & street_ends(b)
            if hit:
                lng, lat = next(iter(hit))
                return lat, lng
    return None


def dot_bike(polys):
    """Brooklyn rows of DOT's current bicycle route projects table, kept if they fall in the area."""
    s = get_text(DOT_BIKE)
    out = []
    for url, name, boro in re.findall(r'<tr>\s*<td>\s*<a\s+href="([^"]+)"[^>]*>(.*?)</a>\s*</td>\s*<td>(.*?)</td>', s, re.S):
        if "Brooklyn" not in boro:
            continue
        title = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", name))).strip()
        pt = locate(title)
        in_area = any(inside(pt[1], pt[0], ring) for ring in polys) if pt else re.search(AREA_WORDS, title, re.I)
        if not in_area:
            continue
        m = re.search(r"-(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*(\d{4})\.pdf$", url, re.I)
        date = f"{m.group(2)}-{MONTHS[m.group(1)[:3].lower()]:02d}-01" if m else ""
        out.append({"source": "street", "key": url, "title": title,
                    "summary": "DOT bike lane plan in development; the link is the plan DOT presented.",
                    "status": "DOT plan in development", "date": date, "homes": None, "bbls": [],
                    "lat": pt and pt[0], "lng": pt and pt[1], "address": None, "link": url, "active": True})
    return out


def dot_projects():
    """North Brooklyn projects on DOT's project site, with the latest date each page mentions."""
    home = get_text(DOT_PROJECTS + "/")
    seen, out = {}, []
    for path, name in re.findall(r'<a[^>]+href="(/(?:project/)?[a-z0-9-]+)"[^>]*>(.*?)</a>', home, re.S):
        title = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", name))).strip()
        if title and path not in seen and "citywide" not in title.lower():
            seen[path] = title
    cutoff = datetime.date.today().year - STREET_STALE_YEARS
    for path, title in seen.items():
        try:
            page = get_text(DOT_PROJECTS + path)
        except Exception:
            continue
        desc = re.search(r'name="description"\s+content="([^"]*)"', page)
        desc = html.unescape(desc.group(1)) if desc else ""
        if not re.search(AREA_WORDS, title + " " + desc, re.I):
            continue
        dates = []
        for mon, day, year in re.findall(r"\b(January|February|March|April|May|June|July|August|September|October|"
                                         r"November|December) (\d{1,2}), (20\d\d)", page):
            try:
                dates.append(datetime.date(int(year), MONTHS[mon[:3].lower()], int(day)))
            except ValueError:
                pass
        last = max(dates) if dates else None
        if last and last.year < cutoff:
            continue
        out.append({"source": "street", "key": DOT_PROJECTS + path, "title": title, "summary": desc,
                    "status": "DOT project", "date": last.isoformat() if last else "", "homes": None, "bbls": [],
                    "lat": None, "lng": None, "address": None, "link": DOT_PROJECTS + path, "active": True})
    return out


def meeting_date(text, url):
    m = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)"
                  r"\s+(\d{1,2}),?\s+(20\d\d)", text)
    if m:
        return datetime.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
    m = re.search(r"(\d{2})-(\d{2})-(\d{2,4})\.pdf$", url) or re.search(r"(\d{2})(\d{2})(20\d\d)\.pdf$", url)
    if m:
        y = int(m.group(3))
        return datetime.date(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
    m = re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*-(20\d\d)", url, re.I)
    if m:
        return datetime.date(int(m.group(2)), MONTHS[m.group(1).lower()], 1)
    return None


def pdf_text(url):
    import subprocess
    import tempfile
    import time
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(data)
        f.flush()
        # reading order, not -layout: some boards print the agenda beside a sidebar of officers
        return subprocess.run(["pdftotext", f.name, "-"], capture_output=True, text=True).stdout


def agenda_items(text):
    """Items in an agenda: numbered ("1." or "1)") where the board numbers them, otherwise one per
    paragraph, read from the first AGENDA / Public Hearing heading to the notice's footer."""
    start = re.search(r"^\s*(AGENDA|Public Hearing Items|PUBLIC HEARING)\s*$", text, re.M | re.I)
    body = text[start.end():] if start else text
    body = re.split(r"\n\s*cc:|Board Meeting notices can be found|\(Note: For further information", body)[0]
    chunks = re.split(r"\n\s*\d{1,2}[.)]\s+", "\n" + body)
    # text before the first number (e.g. a list of public hearing items) is split by paragraph
    items = re.split(r"(?<=\.)\s*\n(?=[A-Z][a-z])", chunks[0]) + chunks[1:]
    return [re.sub(r"\s+", " ", i).strip() for i in items if i.strip()]


def item_title(item):
    """A short name for an agenda item: what's proposed, not who's presenting it."""
    m = re.search(r"\s[–-]\s(seeking|providing|presenting|requesting|proposing|applying)\b(.*)", item[:300])
    head = (m.group(1) + m.group(2)) if m else item
    head = re.split(r"(?<!\bMr)(?<!\bMs)(?<!\bDr)(?<!\bSt)(?<!Ave)(?<!Esq)[.:](?=\s|$)", head)[0]
    head = re.sub(r"^(PRESENTATION|DISCUSSION)( PROJECT)?( ON)?\s*", "", head, flags=re.I)
    return head[:120].strip(" ,;–-")


def geocode(address):
    try:
        feats = get(GEOSEARCH, {"text": address + ", Brooklyn", "size": 1})[0].get("features", [])
    except Exception:
        return None
    if not feats:
        return None
    p = feats[0]["properties"]
    lng, lat = feats[0]["geometry"]["coordinates"]
    return lat, lng, p.get("addendum", {}).get("pad", {}).get("bbl")


def agendas(polys):
    today = datetime.date.today()
    oldest = today - datetime.timedelta(days=AGENDA_PAST_DAYS)
    out, seen = [], set()
    for board, page, keep in AGENDA_PAGES:
        try:
            s = get_text(page)
        except Exception as e:
            print(f"  {board} agendas: {e}", file=sys.stderr)
            continue
        for href, label in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', s, re.S | re.I):
            label = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label))).strip()
            url = href if href.startswith("http") else NYC + href
            when = meeting_date(label, url)
            if url in seen or not when or when < oldest or not re.search(keep, label, re.I):
                continue
            seen.add(url)
            try:
                text = pdf_text(url)
            except Exception as e:
                print(f"  {url}: {e}", file=sys.stderr)
                continue
            if not re.search(r"\d{1,2},?\s+20\d\d", label):  # link gave only a month: use the notice's own date
                exact = re.search(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+([A-Z][a-z]+\s+\d{1,2},?\s+20\d\d)", text)
                when = meeting_date(exact.group(1), "") if exact else when
            meeting = re.sub(r"\s*(Meeting )?Notice.*$", "", label, flags=re.I) or f"{board} meeting"
            for item in agenda_items(text):
                head = item_title(item)
                if len(head) < 12 or re.search(AGENDA_SKIP, head, re.I):
                    continue
                homes = re.search(r"(\d[\d,]*)\s+(?:residential\s+)?(?:dwelling\s+)?units", item, re.I)
                addr = re.search(r"\b\d+[-\d]*\s+(?:[A-Z][a-z]+\s){1,3}(?:Street|Avenue|Place|Boulevard|Road|Drive|St|Ave|Blvd)\b",
                                 item)
                pt = geocode(addr.group(0)) if addr else None
                if pt and not any(inside(pt[1], pt[0], ring) for ring in polys):
                    pt = None
                out.append({"source": "agenda", "key": url + "#" + head[:40], "title": head,
                            "summary": item[:500], "status": f"{board}: {meeting}", "date": when.isoformat(),
                            "homes": int(homes.group(1).replace(",", "")) if homes else None,
                            "bbls": [pt[2]] if pt and pt[2] else [], "lat": pt and pt[0], "lng": pt and pt[1],
                            "address": addr.group(0) if addr else None, "link": url, "active": True,
                            "upcoming": when >= today})
    return out


_addr = {}


def lot_address(bbl, lat, lng, given=None):
    """A lot's address as NYC's official address database (PAD, via GeoSearch) has it. `given` (the address a
    filing or lot record uses) is kept if PAD puts it on this same lot, since it's the one people know;
    otherwise PAD's address for the lot's location is used. Neither confirming it, `given` is shown marked
    unconfirmed: PLUTO's address field has been wrong (Domino's Kent Avenue lots listed as "Kent Street")."""
    key = (bbl, given)
    if key not in _addr:
        label = None
        tries = []
        if given:
            tries.append((GEOSEARCH, {"text": given + ", Brooklyn", "size": 3}))
        if lat is not None:
            tries.append((REVERSE, {"point.lat": lat, "point.lon": lng, "size": 5}))
        for url, params in tries:
            try:
                feats = get(url, params)[0].get("features", [])
            except Exception:
                continue
            same = [f for f in feats if f["properties"].get("addendum", {}).get("pad", {}).get("bbl") == bbl]
            if same:
                label = same[0]["properties"]["label"].replace(", Brooklyn, NY, USA", "").title()
                break
        _addr[key] = label
    if _addr[key]:
        return _addr[key]
    return f"{given.title()} (lot record, unconfirmed)" if given else None


def zoning():
    cds = ",".join(f"'K{c[1:]}'" for c in AREA_CDS)
    rows = soda("hgx4-8ukb", where=f"borough='Brooklyn' AND community_district in({cds}) AND "
                                   f"(project_status='Active' OR completed_date>'{ZONING_SINCE}')",
                select="project_id,project_name,project_brief,project_status,public_status,ulurp_non,"
                       "completed_date,certified_referred,current_milestone_date", limit=1000)
    cutoff = (datetime.date.today() - datetime.timedelta(days=DONE_DAYS)).isoformat()
    # a finished review (approved, withdrawn or otherwise closed) drops out DONE_DAYS after its last date
    rows = [r for r in rows if r.get("project_status") == "Active" and r.get("public_status") != "Completed"
            or (r.get("completed_date") or r.get("current_milestone_date") or "")[:10] >= cutoff]
    ids = ",".join(f"'{r['project_id']}'" for r in rows) or "''"
    lots = {}
    for r in soda("2iga-a6mk", select="project_id,bbl", where=f"project_id in({ids}) AND bbl IS NOT NULL", limit=5000):
        lots.setdefault(r["project_id"], []).append(r["bbl"])
    pts = pluto_points([b for bs in lots.values() for b in bs])
    out = []
    for r in rows:
        brief = r.get("project_brief", "")
        homes = re.search(r"([\d,]+)\s*(?:DUs?|dwelling units|residential units|units)\b", brief, re.I)
        bbls = list(dict.fromkeys(lots.get(r["project_id"], [])))
        located = [b for b in bbls if b in pts]
        pt = pts[located[0]] if located else None
        # A project can cover many lots; name up to three rather than pass one off as "the" address.
        names = list(dict.fromkeys(filter(None, (lot_address(b, pts[b][0], pts[b][1], pts[b][2]) for b in located[:3]))))
        address = "; ".join(names) + (f" (+{len(bbls) - 3} more lots)" if len(bbls) > 3 else "") if names else None
        date = r.get("completed_date") or r.get("current_milestone_date") or r.get("certified_referred") or ""
        out.append({
            "source": "zoning", "key": r["project_id"], "title": r["project_name"],
            "summary": brief[:400], "status": r.get("public_status") or r.get("project_status"),
            "date": date[:10], "homes": int(homes.group(1).replace(",", "")) if homes else None,
            "bbls": bbls, "lat": pt and pt[0], "lng": pt and pt[1], "address": address,
            "link": f"https://zap.planning.nyc.gov/projects/{r['project_id']}",
            "active": r.get("project_status") == "Active",
        })
    return out


def first_occupancy(bbls):
    """Earliest new-building certificate of occupancy (temporary or final) per lot, from DOB NOW. That's
    when people could move in, so the building counts as finished from then."""
    out = {}
    bbls = sorted(set(bbls))
    for i in range(0, len(bbls), 100):
        chunk = ",".join(f"'{b}'" for b in bbls[i:i + 100])
        for r in soda("pkdm-hqz6", select="bbl,c_of_o_issuance_date",
                      where=f"bbl in({chunk}) AND job_type='New Building' AND c_of_o_status='CO Issued'", limit=5000):
            try:
                d = datetime.datetime.strptime(r["c_of_o_issuance_date"].split()[0], "%m/%d/%y").date()
            except (KeyError, ValueError):
                continue
            if d.year >= 2015 and (r["bbl"] not in out or d < out[r["bbl"]]):
                out[r["bbl"]] = d
    return out


def buildings():
    cbs = ",".join(f"'{c}'" for c in AREA_CDS)
    rows = soda("w9ak-ipjd", select="bbl,max(house_no) as house,max(street_name) as street,"
                                    "max(proposed_dwelling_units::number) as homes,min(filing_date) as first_filed,"
                                    "min(first_permit_date) as permit,max(latitude) as lat,max(longitude) as lng",
                where=f"job_type='New Building' AND commmunity_board in({cbs}) AND bbl IS NOT NULL AND "
                      f"proposed_dwelling_units::number>={MIN_HOMES} AND filing_date>'{BUILDING_SINCE}'",
                group="bbl", limit=2000)
    occupied = first_occupancy([r["bbl"] for r in rows])
    cutoff = datetime.date.today() - datetime.timedelta(days=DONE_DAYS)
    out = []
    for r in rows:
        b = r["bbl"]
        done = occupied.get(b)
        if done and done < cutoff:
            continue  # people have lived there for months: finished, not news
        first = r["first_filed"][:10]
        permit = (r.get("permit") or "")[:10]
        if done:
            status, date = f"Finished: first certificate of occupancy {done.isoformat()}", done.isoformat()
        elif permit:
            status, date = f"Under construction: permit {permit[:7]}, filed {first[:7]}", permit
        else:
            status, date = f"Filed {first[:7]}, no building permit yet", first
        lat = float(r["lat"]) if r.get("lat") else None
        lng = float(r["lng"]) if r.get("lng") else None
        filed = f"{r.get('house', '')} {r.get('street', '')}".strip()
        addr = lot_address(b, lat, lng, filed) or filed.title()
        out.append({
            "source": "building", "key": b, "title": f"{addr.replace(' (lot record, unconfirmed)', '')}: new building, {int(float(r['homes']))} homes",
            "summary": "", "status": status, "date": date,
            "homes": int(float(r["homes"])), "bbls": [b],
            "lat": lat, "lng": lng, "address": addr, "link": f"https://zola.planning.nyc.gov/l/lot/{b[0]}/{int(b[1:6])}/{int(b[6:])}",
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
        built = (r.get("constructionactualcompletion") or "")[:10]
        if built and built < (datetime.date.today() - datetime.timedelta(days=DONE_DAYS)).isoformat():
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
        if named and c["source"] in ("news", "street", "agenda"):
            return s["id"], None
        if near is None and (named or (c["lat"] and metres(c["lat"], c["lng"], s["lat"], s["lng"]) <= MATCH_M)):
            near = s["id"]
    return None, near


def mentions(c, news):
    """How many recent headlines name this lead's main street or project name."""
    key = re.split(r",| - |:|\(", c["title"])[0].strip().lower()
    key = re.sub(r"^\d+[-\d]*\s+", "", key) if c["source"] == "building" else key
    if len(key) < 6 or c["source"] == "news":
        return 0
    return sum(1 for n in news if key in n["title"].lower())


def score(c, today, news):
    """Housing leads score on size; street leads on being a live DOT plan. Both add points for
    being open to public input, for recent activity and for news coverage."""
    pts = min((c["homes"] or 0) / 100, 8)
    if c["source"] == "zoning" and c["status"] in ("Filed", "In Public Review", "Noticed"):
        pts += 3
    if c["source"] == "park" and "construction" in c["status"]:
        pts += 2
    if c["source"] == "agenda":
        pts += 2 if c.get("upcoming") else 1
        if re.search(r"rezon|zoning map|dwelling|residential units|DOT\b|bike|redesign|greenway|plaza|park\b|landmark",
                     c["summary"], re.I):
            pts += 2
    if c["source"] == "street":
        pts += 5 if c["status"] == "DOT plan in development" else 4
    try:
        age = (today - datetime.date.fromisoformat(c["date"])).days
        pts += 2 if age <= 90 else 1 if age <= 365 else 0
    except ValueError:
        pass
    pts += min(mentions(c, news), 3)
    return round(pts, 2)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "sites.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "candidates.json"
    with open(src, encoding="utf-8") as f:
        sites = json.load(f)
    today = datetime.date.today()
    polys = area_polygons()
    found, counts = [], {}
    sources = (("zoning", zoning), ("building", buildings), ("park", lambda: parks(polys)),
               ("street", lambda: dot_bike(polys) + dot_projects()), ("agenda", lambda: agendas(polys)), ("news", news))
    for name, fn in sources:
        try:
            rows = fn()
        except Exception as e:  # one source being down shouldn't sink the rest
            print(f"{name}: failed ({e})", file=sys.stderr)
            rows = []
        counts[name] = len(rows)
        found += rows
    for c in found:
        c["on_map"], c["near"] = match(c, sites)
    headlines = [c for c in found if c["source"] == "news"]
    for c in found:
        c["score"] = score(c, today, headlines)
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
