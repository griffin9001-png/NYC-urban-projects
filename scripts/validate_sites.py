#!/usr/bin/env python3
"""Validate sites.json. Exits non-zero on any error so CI blocks a bad data PR.

Usage: python3 scripts/validate_sites.py [path/to/sites.json]
"""
import datetime
import json
import re
import sys

TYPES = {"park", "housing", "road", "other"}
CATEGORIES = {"parcel", "topic"}
STATUSES = {"contested", "review", "active"}
CONDITIONS = {"vacant", "existing-buildings", "under-construction", "partly-built",
              "open-space", "street", "unverified"}
REQUIRED = ["id", "name", "headline", "type", "category", "status", "neighborhood",
            "condition", "lat", "lng", "why", "history", "now", "owner", "sources", "updated", "last_checked"]
# Popup caps: why and Current status (now) 250, history and owner 200.
LIMITS = {"why": 250, "history": 200, "now": 250, "owner": 200}
# Rough NYC bounding box, catches swapped or mistyped coordinates.
LAT_RANGE, LNG_RANGE = (40.49, 40.92), (-74.27, -73.68)
# Planning jargon readers won't know (see STYLE.md for the plain-language swap).
JARGON = {
    r"\bulurp\b": "the city's public approval process",
    r"\bbbls?\b|\bpluto\b": "leave lot IDs out of reader text",
    r"\bami\b|income-restricted": "affordable",
    r"\b421-?a\b|\b485-?x\b": "a property-tax break",
    r"\bupzon": "a zoning change allowing taller buildings",
    r"mixed-use": "apartments with shops",
    r"certification": "a city planning sign-off",
    r"concession": "a business the park lets operate there",
    r"\brfp\b|\brfei\b|\bdisposition\b": "the city will pick a developer",
    r"remediation": "toxic cleanup",
    r"\bassemblage\b|\bparcels?\b": "land, site or block",
    r"right-of-way|jurisdiction": "street, run by",
    r"\bviaduct\b": "elevated highway",
    r"caissons?|bulkhead": "old foundations, seawall",
    r"\bhpd\b": "the city's housing department",
    r"\bdhs\b": "the city's homeless services department",
    r"\bunits?\b": "apartments or homes",
}
JARGON_FIELDS = ("headline", "why", "now", "history", "owner")

# Label-vs-text contradictions: (field, value, pattern in why/now/history, message).
# Cheap deterministic backstop; the weekly review catches subtler mismatches.
CONTRADICTIONS = [
    ("condition", "vacant", r"existing building|demoli|torn down|tear(ing)? down|tenants?|evict|occupied",
     "condition is vacant but text describes buildings or tenants"),
    ("condition", "open-space", r"demoli|torn down|tear(ing)? down|evict",
     "condition is open-space but text describes demolition"),
    ("status", "active", r"scrapped|dropped|killed|cancell?ed|rejected|withdrawn|voted down",
     "status is Advancing but text says the plan was stopped"),
]


def validate(sites):
    errors = []
    today = datetime.date.today()
    seen = set()
    if not isinstance(sites, list) or not sites:
        return ["sites.json must be a non-empty list"]
    for i, s in enumerate(sites):
        where = s.get("id", f"#{i}")
        err = lambda msg: errors.append(f"{where}: {msg}")
        for key in REQUIRED:
            if key not in s or s[key] in ("", None, []):
                err(f"missing {key}")
        sid = s.get("id", "")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", str(sid)):
            err("id must be lowercase-kebab-case")
        if sid in seen:
            err("duplicate id")
        seen.add(sid)
        if s.get("type") not in TYPES:
            err(f"type must be one of {sorted(TYPES)}")
        if s.get("category") not in CATEGORIES:
            err(f"category must be one of {sorted(CATEGORIES)}")
        if s.get("status") not in STATUSES:
            err(f"status must be one of {sorted(STATUSES)}")
        if s.get("condition") not in CONDITIONS:
            err(f"condition must be one of {sorted(CONDITIONS)}")
        bbls = s.get("bbls", [])
        if not isinstance(bbls, list) or not all(re.fullmatch(r"[1-5]\d{9}", str(b)) for b in bbls):
            err("bbls must be a list of 10-digit BBL strings")
        for key in JARGON_FIELDS:
            for pattern, plain in JARGON.items():
                m = re.search(pattern, str(s.get(key) or ""), re.I)
                if m:
                    err(f"{key} uses jargon '{m.group(0)}': write '{plain}' instead (STYLE.md)")
        text = " ".join(str(s.get(k) or "") for k in ("why", "now", "history")).lower()
        for field, value, pattern, message in CONTRADICTIONS:
            if s.get(field) == value and re.search(pattern, text):
                err(message)
        lat, lng = s.get("lat"), s.get("lng")
        if not isinstance(lat, (int, float)) or not LAT_RANGE[0] <= lat <= LAT_RANGE[1]:
            err(f"lat {lat} outside NYC")
        if not isinstance(lng, (int, float)) or not LNG_RANGE[0] <= lng <= LNG_RANGE[1]:
            err(f"lng {lng} outside NYC")
        for key, limit in LIMITS.items():
            text = s.get(key) or ""
            if len(text) > limit:
                err(f"{key} is {len(text)} chars, limit {limit}")
            if "—" in text:
                err(f"{key} contains an em dash")
        for j, src in enumerate(s.get("sources") or []):
            if not src.get("t") or not str(src.get("u", "")).startswith("https://"):
                err(f"source {j + 1} needs a title and an https:// url")
        img = s.get("image")
        if img is not None and not str(img.get("url", "")).startswith("https://"):
            err("image.url must be https://")
        try:
            checked = datetime.date.fromisoformat(str(s.get("last_checked")))
            if checked > today:
                err("last_checked is in the future")
        except ValueError:
            err("last_checked must be YYYY-MM-DD")
    return errors


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "sites.json"
    with open(path, encoding="utf-8") as f:
        sites = json.load(f)
    errors = validate(sites)
    for e in errors:
        print(f"ERROR {e}")
    print(f"{len(sites)} sites checked, {len(errors)} error(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
