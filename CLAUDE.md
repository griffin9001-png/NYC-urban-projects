# NYC Urban Projects

A single-page Leaflet map of North Brooklyn development sites, served by GitHub Pages from `main`.

- Site content lives only in `sites.json`. Maintenance procedure: `UPDATING.md`.
- **Any text written for a site (`headline`, `why`, `now`, `history`, `owner`) must follow `STYLE.md`**: plain language for neighbors, no planning jargon, lead with what's happening and what it means for people.
- Before opening a PR that touches `sites.json`, run `python3 scripts/validate_sites.py` (CI runs it too). With network access, also run `python3 scripts/audit_sites.py`, and `python3 scripts/fetch_lots.py` if any `bbls` changed.
- Only change facts based on articles read in full, and cite them in `sources`.
