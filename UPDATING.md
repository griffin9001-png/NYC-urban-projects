# Keeping sites current

All site data lives in `sites.json`. `index.html` (the map) and `audit.html` (the audit table) both read it. Nothing else holds site content.

- Map: https://griffin9001-png.github.io/NYC-urban-projects/
- Audit: https://griffin9001-png.github.io/NYC-urban-projects/audit.html
- Check data locally: `python3 scripts/validate_sites.py`
- Check against city lot records: `python3 scripts/audit_sites.py` (needs internet; writes `audit.json`, which the audit page shows)
- Preview locally: `python3 -m http.server` in the repo root, then open http://localhost:8000 (opening `index.html` straight from disk can't load `sites.json`).

## Site fields

| Field | Notes |
|---|---|
| `id` | lowercase-kebab-case, unique, never changes |
| `name`, `headline`, `neighborhood` | shown in popup and list |
| `type` | `park`, `housing`, `road`, `other` (pin shape and color) |
| `category` | `parcel` (a specific development site) or `topic` (a broader fight). Not shown on the page |
| `status` | `contested`, `review` (In review), `active` (Advancing) |
| `condition` | what physically stands on the site today, shown as a pill: `vacant`, `existing-buildings`, `under-construction`, `partly-built`, `open-space`, `street`, `unverified`. Never set `vacant` without a PLUTO lot showing no buildings |
| `bbls` | the site's NYC tax lots as 10-digit strings (look up at https://zola.planning.nyc.gov). Required in practice for `parcel` sites so the audit can check condition and pin |
| `lat`, `lng` | geocoded point; say how in `updated` |
| `why` | one-line framing, 200 chars max |
| `now` | shown as **Current status**, 250 chars max, lead with the month and year of the latest event |
| `history` | 200 chars max |
| `owner` | who controls the site, 200 chars max |
| `sources` | list of `{t, u}`; newest first; `u` must be https |
| `image` | optional `{url, credit, isRendering}`, hotlinked |
| `updated` | free text shown at the popup foot, e.g. `Updated Sept 25, 2026 · exact match from NYC PAD/GeoSearch` |
| `last_checked` | `YYYY-MM-DD` of the last time someone searched for news on this site, whether or not anything changed |

Labels must agree with the text. `headline`, `status` and `condition` are what a reader sees first; if `why` or `now` says the plan was dropped, `status` can't be `active`, and if the text mentions existing buildings or tenants, `condition` can't be `vacant`. The validator blocks the obvious contradictions; the weekly review catches the rest.

Writing rules: plain prose, no em dashes, no filler adverbs, no self-referential framing. Every factual claim in `now` must be backed by a source in `sources`.

## Weekly update procedure

A scheduled Claude Code run does this every Monday morning and opens a PR. It never merges; a person reviews and merges.

1. Start a branch from the latest `main` (the scheduled run reuses its session branch, `claude/friendly-dirac-ydvf3y`).
2. For each site in `sites.json`:
   1. Search the web for news about the site published after its `last_checked` date. Use the site name, street address or neighborhood, and the key actors in `owner` and `now`. Prefer primary sources (NYC agencies, Community Board minutes, City Council, LPC) and local outlets (Greenpointers, Brooklyn Paper, Brooklyn Eagle, Gothamist, Curbed, Patch, Brownstoner, THE CITY).
   2. Only read articles in full; don't update from search snippets. If a page can't be loaded, note it in the PR and leave the site's content unchanged.
   3. If there is a material development (vote, approval, lawsuit, groundbreaking, cancellation, sale, new plan), rewrite `now` within 250 chars, adjust `headline` and `status` if they are no longer accurate, add the new source(s) to the top of `sources`, and update the date in `updated`.
   4. Set `last_checked` to today for every site that was searched, changed or not.
3. Consistency review, for every site whether or not news changed: read `headline`, `status`, `condition` and `type` against `why`, `now`, `history` and the sources. Fix any label that the text or sources contradict, or list it in the PR if the right value is unclear. Also open the newest listed source and confirm `now` reflects it; a source that is listed but not reflected in the text is a stale entry. Never carry a claim from reader comments, search snippets or paywalled headlines alone into the text.
4. Run `python3 scripts/audit_sites.py`. For each flag, fix the data (set `condition`, add or correct `bbls`, move a pin onto its lot) or explain in the PR why it stands. Commit the refreshed `audit.json`.
5. Run `python3 scripts/validate_sites.py` and fix any errors.
6. Open a PR titled `Weekly site update YYYY-MM-DD`. The body has one row per site: id, changed or no change, a one-line summary of what changed, and the source URLs relied on. Add a section listing remaining audit flags and label questions, and any pages that couldn't be read.
7. If no site changed, still open the PR (it only bumps `last_checked`) so the audit page shows the check happened.

## Adding a site

Add an object to `sites.json` with every field above (look up its `bbls` and confirm `condition` in ZoLa or PLUTO), set `last_checked` to today, run the validator and the audit, and open a PR. The weekly run picks it up automatically from the next Monday.

Cost scales with the number of sites: each weekly run does a few searches and article reads per site. At tens of sites this is small. Past roughly 50 sites, split the weekly run into batches (for example, half the sites on alternating weeks, or only sites with `status` other than `active` weekly and the rest monthly).
