# Keeping sites current

All site data lives in `sites.json`. `index.html` (the map) and `audit.html` (the audit table) both read it. Nothing else holds site content.

- Map: https://griffin9001-png.github.io/NYC-urban-projects/
- Audit: https://griffin9001-png.github.io/NYC-urban-projects/audit.html
- Check data locally: `python3 scripts/validate_sites.py`
- Check against city lot records: `python3 scripts/audit_sites.py` (needs internet; writes `audit.json`, which the audit page shows)
- Refresh lot shading: `python3 scripts/fetch_lots.py` (needs internet; writes `lots.geojson` from each site's `bbls`, `streets` and `osm`; rerun whenever any of them changes, before running the validator)
- Find new sites: `python3 scripts/find_candidates.py` (needs internet; writes `candidates.json`, which the candidates page shows: https://griffin9001-png.github.io/NYC-urban-projects/candidates.html)
- Preview locally: `python3 -m http.server` in the repo root, then open http://localhost:8000 (opening `index.html` straight from disk can't load `sites.json`).

## Site fields

| Field | Notes |
|---|---|
| `id` | lowercase-kebab-case, unique, never changes |
| `name`, `headline`, `neighborhood` | shown in popup and list |
| `type` | `park`, `housing`, `road`, `other` (pin shape and color) |
| `category` | `parcel` (a specific development site) or `topic` (a broader fight). Not shown on the page |
| `status` | `contested`, `review` (In review), `active` (Advancing). Process detail, shown small inside the popup |
| `phase` | the resident-facing pill: `decision-coming`, `planned` (approved or cleared, not started), `construction-underway`, `partly-open` (some of it open, the rest still coming), `open-now`, `stalled` |
| `condition` | what physically stands on the site today, shown as a pill: `vacant`, `existing-buildings`, `under-construction`, `partly-built`, `open-space`, `street`, `unverified`. Never set `vacant` without a PLUTO lot showing no buildings |
| `bbls` | the site's NYC tax lots as 10-digit strings (look up at https://zola.planning.nyc.gov). Required in practice for `parcel` sites so the audit can check condition and pin, and for any site whose land should be shaded on the map (streets have none) |
| `streets` | for street projects: exact Brooklyn street names as they appear in the city's street centerline file (CSCL, e.g. `MCGUINNESS BLVD`), or `{"name": "PARK AVE", "along": "BROOKLYN QUEENS EXPY"}` to keep only the segments within 40 m of another street, or `{"name": "BEDFORD AVE", "between": ["FLUSHING AVE", "WILLOUGHBY AVE"]}` for the blocks between two cross streets. Drawn as a line in the pin color |
| `osm` | for anything the city files don't cover (creeks, odd-shaped plazas): OpenStreetMap elements such as `"way/392486579"`. Find the ID by clicking the feature on openstreetmap.org. Closed ways are drawn as areas, other ways and relations as lines |
| `address_notes` | optional; `{"address as written in neighborhood": "why it stands"}` for an address the city's address database doesn't put on the site's lots but that's still right (a planned building's new address, a permit that ties the address to a different lot number). The audit skips these; every other address in `neighborhood` must land on one of the site's `bbls` |
| `lat`, `lng` | geocoded point; say how in `updated`. Must sit on the site's own shape (`bbls`, `streets` or `osm`): `validate_sites.py` prints where every pin lands ("inside lot 3025670001", "4 m from MCGUINNESS BLVD") and fails a pin more than 10 m outside its lots or 30 m off its line. Every site needs at least one of `bbls`, `streets` or `osm` for this check |
| `why` | what the place is and what would change, then the bigger picture, 250 chars max |
| `now` | shown as **Current status**, 250 chars max, lead with the month and year of the latest event |
| `history` | 200 chars max |
| `impact` | what a neighbor will notice, 200 chars max (STYLE.md) |
| `timeline` | `{start, complete, confidence}`: dates as `YYYY`, `YYYY-MM` or `YYYY-MM-DD` or null; `confidence` is `announced` (official date), `estimated` (reported estimate) or `unknown` (then `complete` must be null) |
| `next_step` | `{date, what, where, url}`: the next meeting, vote, lottery or deadline. `what` is required; the rest may be null. Say "No public meeting or deadline scheduled yet." when there is none |
| `units_total`, `units_affordable` | whole numbers from a source, or null. Only derive `units_affordable` from a sourced percentage |
| `park_acres_promised`, `park_acres_delivered` | numbers from a source, or null |
| `owner` | who controls the site, 200 chars max |
| `sources` | list of `{t, u}`; newest first; `u` must be https |
| `image` | `{url, credit, isRendering, page, shows}`, hotlinked. `page` is the https page the image appears on; `shows` is the site name or street address that page uses for it (in the title, caption or alt text), and must also appear in this site's own text. See "Finding an image" below. If missing or broken, the popup shows an "Open in Street View" link instead |
| `updated` | free text shown at the popup foot, e.g. `Updated Sept 25, 2026 · exact match from NYC PAD/GeoSearch` |
| `last_checked` | `YYYY-MM-DD` of the last time someone searched for news on this site, whether or not anything changed |
| `changed_on`, `change_note` | date of the latest material development (not a wording fix) and one plain sentence about it; feeds "What's new" |

Labels must agree with the text. `headline`, `status` and `condition` are what a reader sees first; if `why` or `now` says the plan was dropped, `status` can't be `active`, and if the text mentions existing buildings or tenants, `condition` can't be `vacant`. The validator blocks the obvious contradictions; the weekly review catches the rest.

Writing rules: follow `STYLE.md` (plain language for neighbors, no planning jargon; the validator rejects common jargon). No em dashes, no filler adverbs, no self-referential framing. Every factual claim in `now` must be backed by a source in `sources`.

## Finding an image

Try these in order and stop at the first that shows the site itself (check the caption or alt text, not just the article topic):

1. A photo or rendering in an article already listed in `sources`. Use the article's `og:image` or an in-article image whose caption names the site; credit the outlet (`"Site at Oak and West Sts, via Greenpointers"`).
2. Wikimedia Commons photos taken near the pin: `https://commons.wikimedia.org/w/api.php?action=query&list=geosearch&gscoord=LAT|LNG&gsradius=150&gsnamespace=6&format=json`. Credit the photographer and license.
3. Mapillary street-level imagery (open license, needs a free access token).
4. None of the above: leave `image` out. The popup then links to Google Street View at the pin.

Addresses: take a site's street address from NYC's address database (ZoLa's lot page or GeoSearch), not from PLUTO's address field alone. PLUTO has listed Domino's Kent Avenue lots as "Kent Street", which is in Greenpoint. The audit looks up every address in `neighborhood` and flags one that lands on another lot.

Before keeping an image:

- **Look at it.** Does it match what `why` describes (the number and shape of buildings, a waterfront, the streets named)? A rendering of "twin towers" isn't automatically this site's twin towers.
- **The page must name this site.** Record the page in `image.page` and the words it uses for the site in `image.shows`. If the article is about a different address or project, even a nearby one, don't use its images.
- **Addresses must be on the site's lots.** If `shows` is a street address, it has to geocode to one of the site's `bbls`.
- **Use a page that loads without a bot wall.** New York YIMBY and some others often block automated reads, so the audit can't confirm their images; prefer another outlet's copy of the same rendering.

`validate_sites.py` requires `page` and `shows`. `audit_sites.py` loads the page and flags the image if the page can't be read, doesn't contain the image, doesn't name `shows` in its title or next to the image, or if an address in `shows` isn't on the site's lots.

Don't screenshot Google Street View or Google Maps for the site: Google's terms don't allow hosting those images on a website outside its own embeds and APIs. Avoid images that are mostly a person, a logo or a composite.

## Weekly update procedure

A scheduled Claude Code run does this every Monday morning and opens a PR. Once its checks pass and it has no merge conflict, the run squash-merges it (the standing instruction in `CLAUDE.md`).

1. Start a branch from the latest `main` (the scheduled run reuses its session branch, `claude/friendly-dirac-ydvf3y`).
2. For each site in `sites.json`:
   1. Search the web for news about the site published after its `last_checked` date. Use the site name, street address or neighborhood, and the key actors in `owner` and `now`. Prefer primary sources (NYC agencies, Community Board minutes, City Council, LPC) and local outlets (Greenpointers, Brooklyn Paper, Brooklyn Eagle, Gothamist, Curbed, Patch, Brownstoner, THE CITY).
   2. Only read articles in full; don't update from search snippets. If a page can't be loaded, note it in the PR and leave the site's content unchanged.
   3. If there is a material development (vote, approval, lawsuit, groundbreaking, cancellation, sale, new plan), rewrite `now` within 250 chars, adjust `headline`, `status`, `phase`, `impact`, `timeline`, `next_step` and the unit/acre numbers if they are no longer accurate, set `changed_on` to the development's date and `change_note` to one sentence about it, add the new source(s) to the top of `sources`, and update the date in `updated`. Never fill a number or date from a guess; leave it null.
   4. Set `last_checked` to today for every site that was searched, changed or not.
3. Consistency review, for every site whether or not news changed: read `headline`, `status`, `condition` and `type` against `why`, `now`, `history` and the sources. Fix any label that the text or sources contradict, or list it in the PR if the right value is unclear. Also open the newest listed source and confirm `now` reflects it; a source that is listed but not reflected in the text is a stale entry. Never carry a claim from reader comments, search snippets or paywalled headlines alone into the text.
4. Run `python3 scripts/audit_sites.py`. For each flag, fix the data (set `condition`, add or correct `bbls`, move a pin onto its lot, find or replace an image per "Finding an image") or explain in the PR why it stands. Treat an image flag as a possible wrong image: open the image and its page and confirm it shows this site before doing anything else. Commit the refreshed `audit.json`. If any `bbls`, `streets` or `osm` changed, run `python3 scripts/fetch_lots.py` and commit `lots.geojson`.
5. Run `python3 scripts/validate_sites.py` and fix any errors.
6. Run `python3 scripts/find_candidates.py` and commit the refreshed `candidates.json`. Don't add sites from it in the weekly run; list the ten highest-scoring new leads in the PR so the owner can pick.
7. Open a PR titled `Weekly site update YYYY-MM-DD`. The body has one row per site: id, changed or no change, a one-line summary of what changed, and the source URLs relied on. Add a section listing remaining audit flags and label questions, any pages that couldn't be read, and the top new leads from `candidates.json`.
8. If no site changed, still open the PR (it only bumps `last_checked`) so the audit page shows the check happened.

## Finding new sites

`scripts/find_candidates.py` gathers leads for Brooklyn Community Districts 1 to 4 and writes `candidates.json`:

- **Zoning applications** from City Planning's Zoning Application Portal: rezonings, waterfront sign-offs, anything in public review.
- **New buildings** filed with the Buildings Department since 2024 with 50 or more homes (`MIN_HOMES`), shown as filed, under construction (has a permit) or finished (first certificate of occupancy).
- **Park projects** from the Parks Department's capital project tracker that aren't finished.
- **Bike lanes and street plans** from DOT's "Current Bicycle Route Projects" list (Brooklyn rows placed at their first cross street and kept if inside the area) and DOT's project site, nycdotprojects.info (North Brooklyn place or street names; pages with no dated update in 3 years are skipped). Street projects that DOT handles as sewer or water capital work, like the Commercial St greenway, aren't on either list and still come from news or community board agendas.
- **Community board agendas** from the last 60 days and any upcoming meeting: CB1's Transportation, Land Use and Parks & Waterfront committee notices and full-board agendas, and CB3 and CB4 full-board agendas. Each agenda item becomes a lead; routine items (minutes, reports, liquor and cannabis licenses, outdoor dining, street co-namings) are dropped, and an address in the item is looked up to match it to a lot. CB3's page hasn't posted an agenda since June 2025, and CB2's site blocks automated reads, so those two boards are thin; check their calendars by hand.
- **News** headlines from Greenpointers, Streetsblog NYC and Brooklyn Paper in the last 45 days that name the area and a development topic.

Finished work drops out 3 months after it finishes (`DONE_DAYS`):

- a new building once its first certificate of occupancy (temporary or final) is older than that; a building filing's own date isn't used, since amendments keep arriving long after people move in;
- a park project once construction finished that long ago;
- an approved zoning application only once a new building on its lots has been occupied for 3 months and no building permits have been issued there in 6 months. "Completed" in City Planning's records means the review finished, not that anything was built: Domino Site B was approved in Nov 2025 and is under construction, shown as "Approved 2025-11; 35 building permits issued since". Approvals that bring housing or went through full public review stay up to 3 years (`APPROVED_KEEP_YEARS`); minor sign-offs drop 3 months after they close.

Some large projects never show up as building filings: Domino Site B's new-building job was filed in 2014 in the Buildings Department's older system, which has no unit counts, so it comes through its zoning approval instead.

Each lead gets a score (higher is more worth a look; housing tops out around 16, street plans around 10) and is matched against `sites.json`. Score:

| Points | For |
|---|---|
| 0 to 8 | Size: 1 per 100 proposed homes |
| +3 | A zoning application still filed, noticed or in public review |
| +5 / +4 | A DOT bike lane plan in development / another active DOT street project |
| +2 | A park project under construction |
| +2 / +1 | A community board agenda item at an upcoming / recent meeting; +2 more if it's a rezoning, housing, DOT, park or landmark item |
| +2 / +1 | Latest date within 90 days / within a year |
| up to +3 | One per recent headline naming the lead's street or project |

Matching: "on the map" when it shares a lot with a site, or a headline or DOT plan names one, "near" when a site's pin is close or its name matches, which only means it's worth checking. The area, thresholds and news keywords are constants at the top of the script.

A lead is not a site. To add one, read its sources in full and follow "Adding a site" below; the zoning and building records say what's filed, not what it means for neighbors, so each site still needs news or agency sources that explain it.

## Adding a site

Add an object to `sites.json` with every field above (look up its `bbls` and confirm `condition` in ZoLa or PLUTO), set `last_checked` to today, run `fetch_lots.py`, then the validator and the audit, and open a PR.

Placing the pin: give the site its shape first (`bbls` for land, `streets` for a road project, `osm` for a creek or anything else), then put the pin on that shape where a neighbor would recognize it: the lot's street address, a street corner on the corridor, a bridge over a creek. Never use a nearby address or intersection as a stand-in for a place it isn't on. Run `fetch_lots.py` and check the validator's "Pins" lines before opening the PR. The weekly run picks it up automatically from the next Monday.

Cost scales with the number of sites: each weekly run does a few searches and article reads per site. At tens of sites this is small. Past roughly 50 sites, split the weekly run into batches (for example, half the sites on alternating weeks, or only sites with `status` other than `active` weekly and the rest monthly).
