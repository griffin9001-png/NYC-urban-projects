# Writing style for site text

The map is for neighbors, not planners. Write every site so someone who has never heard of the project understands what it is, what would change, and why it matters, from the first sentence.

## Rules

1. **Lead with what's happening in everyday words.** A proposal, a new park, apartments, a highway. Say what the land is now and what would change.
2. **Say what it means for people.** Homes, affordable apartments, a park, a shelter, a beach, a road closed to cars. Put the human outcome ahead of the paperwork.
3. **Round and translate numbers.** "About 1,000 apartments", not "1,025 units". Use apartments, buildings, stories and acres; skip square feet, lot numbers and floor-area figures.
4. **Name the process only if a reader needs it, and say what it does.** "The City Council approved it", "a property-tax break", "a city planning sign-off that doesn't go to the City Council".
5. **Explain names the first time.** Quote a project name and say what it is: the "Greenpoint Landing" plan to add 5,500 homes to the waterfront.
6. **Give the bigger picture in the second sentence**, if there is one: the larger plan, the promise it relates to, the fight around it.
7. **Keep it short and plain.** No em dashes, filler adverbs or self-referential framing ("this site", "as of this writing"). Every fact still needs a source in `sources`.

## Swap list

| Instead of | Write |
|---|---|
| units | apartments, homes |
| income-restricted, AMI bands | affordable, or "for households earning under about $X" |
| mixed-use | apartments with shops |
| ULURP, land use review | the city's public approval process |
| waterfront certification (ZR 62-811) | a city planning sign-off |
| 421a, 485-x | a property-tax break |
| rezoning, upzoning | a zoning change to allow taller or denser buildings |
| remediation | toxic cleanup |
| concession, concessionaire | a business the park lets operate there (café, restroom) |
| RFP, RFEI, disposition | the city will pick a developer |
| HPD, DOT, DHS | the city's housing / transportation / homeless services department |
| parcel, lot, assemblage | land, site, block |
| right-of-way, jurisdiction | street, run by |
| viaduct | elevated highway |
| caissons, bulkhead | old foundations, seawall |

`scripts/validate_sites.py` fails on the jargon in the left column, so the rules above are enforced for the obvious cases.

## Before and after

**Greenpoint Landing, Phase 2**

- Before: "Vacant waterfront lots on Freeman St, Block C of Greenpoint Landing, the 22-acre, 5,500-apartment master plan that grew out of the 2005 rezoning."
- After: "Proposal to fill vacant land along the Greenpoint waterfront with about 1,000 homes across 3 apartment buildings, along with a public park. This is a new piece of the 'Greenpoint Landing' master plan to add 5,500 homes to the waterfront."

**2 Noble Street**

- Before: "Its City Planning waterfront certification was under review as of Sept."
- After: "The city planning department is still reviewing the plan, a sign-off that doesn't go to the City Council."

**River Ring**

- Before: "In May 2026 the state budget extended the old 421a tax break for River Ring past its 2031 deadline."
- After: "In May 2026 the state gave developer Two Trees extra time to keep a large property-tax break it says the project needs."

## Fields

- `headline`: 2 to 5 plain words on where things stand ("Three towers approved", "Promised park still unfinished").
- `why` (250 chars): what the place is and what would change, then the bigger picture.
- `now` (250 chars): the latest development, leading with when it happened.
- `history` (200 chars): what the land was before, in order.
- `owner` (200 chars): who owns or controls it, in plain words.
