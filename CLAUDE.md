# HeatWatch — public site repo

Published to GitHub Pages from `master`, built on this machine and committed, not
built in CI. A move to Cloudflare Workers is planned; when it happens, Pages
retires rather than running alongside.

## The one rule

**Never hand-edit `index.html`.** It is a build artifact that happens to be
committed. Every design or content change goes into `generate_site.py`, then you
regenerate. A hand-edit is silently destroyed by the next run.

## Regenerating

```
python3 generate_site.py <state.json> <out_dir> [denylist.txt]
```

`<out_dir>` is a **directory**, not a filename. The generator also scans the state
file's own directory for sibling state files to build the map's time windows, so the
windows deepen on their own as history accumulates.

Preview by writing to a scratch directory and serving it — `open file://` works, but
a local `python3 -m http.server` is what a browser on another machine can reach (bind
`0.0.0.0` for that, and send no-cache headers or you will spend an hour looking at a
stale page).

## One page

Topic sections live on `index.html`, with the nav as anchor links and a scroll
position test marking the current section. A topic with no items gets no tab and no
section. `section_block()` is per-topic, so splitting into separate pages later is a
change to `main()` rather than a rewrite.

Anchors need `scroll-margin-top:118px` to clear the two sticky bars. If either bar's
height changes, that number has to change with it.

Do not use an IntersectionObserver for the current-section marker. Its callback only
carries the sections whose intersection changed, so neighbouring sections flicker
while scrolling one direction. The position test is deterministic.

## The map's time windows are gated on real coverage

`WINDOWS` declares 1W / 1M / 3M / 1Y, but a window is only offered when history
covers at least `WINDOW_MIN_COVERAGE` (60%) of its span. **1Y is hidden** until
roughly 220 days of history exist, around April 2027. It returns on its own: do not
hardcode it back.

## The map is coupled to the prose

Countries are placed by matching country names in each item's `title`, `body` and
`so_what`. An item that never names a country reads correctly on the page and
silently fails to appear on the map.

A named country tags **only that country**. Only phrases that genuinely cover several
— "the Gulf", "the Sahel", "South Asia" — tag their members. An earlier version fanned
a region out to every member, so one item about Brazil tagged the whole of South
America with Brazil's text.

`check_names()` fails the build if any ISO3 the map can show has no entry in `NAMES`;
a missing one printed a bare country code on the page.

## Nothing internal in published strings

The site is public. `check_terms()` fails the build on a denylist of internal terms,
checked against the whole rendered page **including HTML and CSS comments**, which
ship in the page source. The list is passed in by path and is deliberately not held in
this file — a denylist inside a public file publishes the terms it exists to suppress.

Dates in generated labels take a human form ("Recorded 19 September 2026"), never a
reference to an internal artifact.

## Text length

`short()` returns complete sentences and **never an ellipsis**. A clipped clause with
no way to read the rest is worse than a slightly long card. Keeping bodies short is
the writer's job, not the renderer's.

## The globe

`world_paths.json` is a Robinson projection with no lat/lon in it, so `globe.py`
inverts Robinson back to coordinates (parameters fitted and validated to sub-degree
longitude accuracy) and reprojects orthographically. It uses its own reserved,
quieter palette — mean OKLab chroma 0.06 against the map ramp's 0.16 — so the loud
colour stays reserved for data.

## SVG `<use>` and `<symbol>`

Styles do **not** reliably reach inside a `<use>` shadow tree: a descendant selector
such as `.rg polygon` does not match content defined in `<defs><symbol>`, and
`currentColor` resolves against the definition site rather than the use site. Paint
those shapes with presentation attributes pointing at custom properties, which do
inherit across the boundary. Two rendering bugs came from ignoring this.

## Two pages, one site

`index.html` is Updates. `workability.html` is Workability: a seven-day forecast of
working hours too hot for outdoor work at 18 hubs, against the rule that applies
there. The `Updates | Workability` switch lives in the **first** sticky bar, next to
the brand.

The switch appears on both pages, so its CSS belongs to the shared stylesheet in
`head()` — not to `workability.CSS`, which is only injected into the one page. Put
it in the wrong place and the Updates page renders two bare blue links.

`generate_site.py` writes the Workability page only when a stored forecast exists
for the date. No forecast, no page, and the view switch is not drawn at all rather
than pointing at a 404.

## Workable hours

```
python3 fetch_forecast.py <core_dir>      # in heatwatch-core, writes state/forecast/
python3 generate_site.py <state.json> <out_dir> [denylist.txt]
```

The fetch is a separate step on purpose: the build never reaches the network, so a
page can be rebuilt from a stored forecast and reproduce exactly.

`wbgt.py` solves outdoor WBGT hour by hour after Liljegren et al. (2008) — the globe
and the wetted wick each get their own energy balance, because sun and wind are what
decide whether a shift is workable and the simple regressions ignore both. Pure
standard library. `test_wbgt.py` runs 756 fixed hours of physical invariants on every
build and **fails the run**.

**The ±0.5 °C acceptance check is not met yet.** It needs a Liljegren-to-Liljegren
comparison against the NOAA port (`pywbgt`), which requires Python 3.10; this machine
has 3.9.6. `--compare` against ECMWF's thermofeel runs today and is a magnitude check
only: that difference tracks the sun almost exactly (+0.8 °C at night, +3.3 °C in
strong sun) because thermofeel uses a thermodynamic wet bulb with no radiative term.
Do not read agreement there as validation, and do not tighten `TOL` until the
reference is like-for-like.

Hours are counted from the **hourly** series between 06:00 and 20:00 local, never
derived from a daily peak: a day that touches the limit for an hour and a day that
sits above it from ten until six can share a peak. Shade is the model recomputed with
the direct beam removed, not a fixed offset.

## Rule status comes from records, never from prose

`rules_from_db()` replaced `derive_rules()`, which read status out of the reports and
guessed. It marked a country "In force" when a workers item named it near a word like
"limit" or "ban", so an EU-level consultation tagged member states — Finland, Denmark,
Sweden, Poland, Romania, Ireland and Norway all showed a rule in force, and Norway is
not in the EU — while the four Gulf states running midday bans showed nothing.

The records live in `heatwatch-core/rules/`, one JSON file per instrument, shared by
the map and the Workability page so the two cannot disagree.

**A record may only read "In force" when `confidence` is `sourced` AND at least one
source is `type: primary`.** Anything else reads "Reported, not confirmed" and counts
as an *unprotected* hour. Erring toward "nobody is covering this" is the safe
direction for a page an HSE manager might act on. `check_rules()` fails the build on a
hub with no record or a record with no source, and prints the rest as a review queue.

A `supranational` record shades nothing on the map. That is the whole of the old bug.

## Theme starts light, and that is a decision

Spec A12 asks for `prefers-color-scheme` as the default. **The owner asked for
"always start light" and confirmed it again on 26 September 2026.** The instruction
wins over the spec. The page starts light when nothing is stored, and the stored
choice persists.

Do not "fix" this against A12. If it ever changes, it changes because the owner says
so, not because a later session read the spec and thought the code had drifted.

## The archive is immutable

Each build writes `archive/forecast/<date>/<hub>.json` and a manifest of SHA-256
hashes at `archive/manifest/<date>.json`. **An existing file for a date is left
alone.** The archive says what was known that morning; a rebuild in the evening must
not quietly improve it. Do not backfill dates before the module shipped.

The rule is immutable once **published**. Today's archive was rewritten once before
the first publish, because rule records were corrected in the same session and
shipping a snapshot we already knew was wrong would have been worse than rewriting
one nobody had seen. That is the only case: once a date has gone out, the manifest is
the promise that it has not moved, and deleting to rebuild breaks it.

## Sticky inside a scroll container

The hub table sits in `.wkwrap`, which is `overflow-x:auto`. A `position:sticky`
descendant resolves against *that* box, not the viewport — `top:106px` on the table
header pinned it 106px below the table's own top edge and painted it over the first
row of data. The header is not sticky. If you want it back, the scroll container has
to go first.

## Conventions

- Standard library only. A third-party import is what broke a sibling project's fetch
  for five days.
- Everything inlined, no external requests except the Google Fonts stylesheet.
- Deploy surface is deny-by-default and always an allowlist: the staging step in
  `.github/workflows/pages.yml`, and `.assetsignore` after the Cloudflare move. The
  mechanism changes, the rule does not. It now stages `index.html`,
  `workability.html`, `workability-week.csv` and the `archive/` tree; a new runtime
  asset needs a line there or it silently 404s.
- Every claim on the page carries its source. Rule summaries are not legal advice.
