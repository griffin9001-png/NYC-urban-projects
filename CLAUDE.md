# NYC Urban Projects

A single-page Leaflet map of North Brooklyn development sites, served by GitHub Pages from `main`.

- Site content lives only in `sites.json`. Maintenance procedure: `UPDATING.md`.
- **Any text written for a site (`headline`, `why`, `now`, `history`, `owner`) must follow `STYLE.md`**: plain language for neighbors, no planning jargon, lead with what's happening and what it means for people.
- Before opening a PR that touches `sites.json`, run `python3 scripts/validate_sites.py` (CI runs it too). With network access, also run `python3 scripts/audit_sites.py`, and `python3 scripts/fetch_lots.py` if any `bbls`, `streets` or `osm` changed.
- New sites come from `candidates.html` (built by `scripts/find_candidates.py`) or the owner; a lead is added only after its sources are read in full.
- Only change facts based on articles read in full, and cite them in `sources`.
- **Merge your own PRs without asking** (the owner's standing instruction, Sept 28, 2026), including the weekly site update: once the PR's checks pass and it has no merge conflict, squash-merge it and tell the owner what went live. If a check fails, fix it first; never merge a red PR.
