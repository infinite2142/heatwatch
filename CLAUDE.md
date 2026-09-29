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

The marker's threshold is `window.__navLine`, defaulting to 124 — the two sticky
bars plus a little. **A page with a third sticky element has to raise it**, or the
section a tab jumps to starts below the chrome and never crosses a line drawn above
it, so the marker stays on the previous section. Workability sets it from the filter
bar's measured height.

Overview points at `#map`, not at document top; the brand mark is the link home. A
nav tab that scrolls to y=0 does nothing visible when you are already near the top,
which is most of the time — which is why it read as broken on desktop and not on a
phone, where the taller hero made the same scroll obvious.

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

## Say what a thing is

Write the plain declarative form. Do not define something by what it is not.

```
no:   Grouped by approach, not by vendor — no products, no ranking.
yes:  Solutions are grouped by cooling approach.

no:   Shade is the same model with the direct beam removed, not a fixed offset.
yes:  Shade recomputes the same model with the direct beam removed.
```

The tells are `X, not Y`, `rather than`, `no A, no B`, and the em-dash-then-negation
rhythm. They spend the sentence on a contrast the reader never proposed and bury the
fact. The register to aim for is a scientific presentation: simple and descriptive.
The same rule is in `prompts/daily.md`, so the daily run's own copy follows it.

Two exceptions. A **finding of absence** is a fact and stays one — "India has no
binding national heat limit for outdoor work" is the finding. A **legal disclaimer**
stays literal: "Rule summaries are not legal advice."

This does **not** apply to code comments or to the notes in this file. "Not an
IntersectionObserver, because its callback only carries the sections whose
intersection changed" is the recorded reason a later session must not undo the fix,
and that is the entire value of those comments.

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

## The globe spins on coordinates, not frames

`globe.land_lonlat()` ships the coastline as lon/lat in tenths of a degree, and the
browser projects it each frame. That is the whole reason this is affordable: one
frame of projected geometry is 35KB, so a pre-rendered rotation would be most of a
megabyte, while the source coordinates are 17KB once (7KB gzipped) and the
projection is eight lines of arithmetic.

It is cheap for a second reason. The view is equatorial orthographic, so every
parallel is a horizontal line and the anomaly field is one vertical gradient —
neither changes as it turns. Only the land and the meridians are redrawn.

Land is grouped into latitude bands and drawn as one `<path>` per band. A band's
fill comes from its mean latitude, which rotation does not change, so a frame is
eleven attribute writes rather than 138 rebuilt polygons.

**Meridians are the near half only, one arc per longitude.** Drawn as full
ellipses they showed the far side as well, and at 30° spacing the set of
`|sin(M − lon0)|` values repeats every 30° — so the whole graticule returned to an
identical configuration nine seconds into every rotation. It pulsed in place while
the continents travelled, which reads as a second, static set of meridians. A half
arc belongs to one longitude, enters at one limb and leaves at the other, so it
turns with the land. `rx` collapsing to zero at the centre is correct: that
meridian is edge-on, and SVG draws a zero-radius arc as the straight line it is.

The hero globe is centred at `cx=300` in a 600-wide viewBox. It was 310, which is
invisible on desktop — the art is masked and positioned against the right edge —
and 5px right of centre the moment a phone centres the box instead.

**Three numbers move together when the globe is resized**, and the build only
catches one of them:

- `r` and `cy` — `build()` derives the viewBox height from `cy` and refuses to
  render when `r > cy - 2`, so clipped poles fail loudly rather than shipping.
- `.masthead{min-height}` at `min-width:921px` — the art is absolutely positioned,
  so it contributes nothing to the band's height, and `overflow:hidden` then cuts
  its poles off as soon as it is taller than the text beside it. Nothing checks
  this one. On-screen art height is `min(50%,520px) * vb_h/600`; at r=177.6 that is
  333px, hence a 342px floor.

The width stays 600 whatever the size: the element's on-screen scale is
`width/600`, so holding it fixed makes `r` the only thing that changes how big the
globe renders.

The static SVG stays in the page and is what a reader gets with JavaScript off or
`prefers-reduced-motion: reduce` set — the script replaces the land only once it has
decided to animate. It throttles to 20fps, and pauses when the tab is hidden or the
globe is scrolled out of view.

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

## A country's tooltip may only carry its own headline

Two rules, both enforced by `check_tooltips()` at build time.

**Region phrases are matched in the title and body only, never in `so_what`.** A
country name tags one country; a region phrase tags every member, so it has six
times the blast radius — and the So what line is exactly where a writer reaches for
an analogy. One item read "England's heat-health alert season ends on 30 September"
and closed with "the same instrument design as the Gulf's calendar ban". That
clause put an England headline in the tooltip of all six Gulf states.

**A headline is only shown under a country it names.** An item can legitimately
cover several countries — "Brazil and Indonesia enter their hot season" also carries
projections for Vietnam, Thailand and the Philippines — and hanging its title under
Vietnam reads as a claim about Brazil. Those fall back to the dated label the
archive uses: a signal existed, nothing more is asserted.

`NOT_THE_COUNTRY` rewrites proper nouns that merely contain a country name, so
"New Mexico" is a US state and "New South Wales" is in Australia.

**Every tooltip line names its category**, and carries one of three kinds, which the
payload ships as `hit[cat] = [kind, text]`:

- `headline` — the item's title, where that title names this country
- `note` — a line the run wrote **for** this country in `state.coverage`, for a
  country the report names without giving it a section item. This is the fix for a
  bare date and the reason `coverage` exists; see `prompts/daily.md`
- `mention` — the first complete sentence of the body that names this country, used
  when the title is about somewhere else. `sentence_about()` matches the country's
  own aliases only (`regions_text=""`), so a sentence about "the Gulf" is never
  offered as a sentence about Saudi Arabia
- `stamp` — a date alone, with a footnote in the tooltip saying what that means

A `stamp` is the last resort, not laziness: those come from
`backfill_from_reports()`, which keeps the date and category and deliberately **no
prose**, because the archived reports also contain desk-only sections and a
mis-parsed heading would walk private text onto a public page. The line that gave
Saudi Arabia its 15 September stamp contains the word "beachhead", which is on the
denylist — that is the rule earning its keep.

## The state file is authoritative for any date it covers

The report backfill fills the **pre-history only** — the weeks before state files
existed. It used to fill every date, and that is why bare dated lines never drained:
on a date the state file already covered, the report added countries the state file
had no item for, and a count with no text is all a report can safely give.

It was also shading countries for nothing happening. One line in the 28 September
report read "Gulf, South Asia, East Asia, sub-Saharan Africa, South America —
quiet. No new observed heat event surfaced in India, Bangladesh, China, Japan …" and
put twenty-five countries on the map on the strength of it. Argentina, Bolivia,
Chile, China, Colombia, Mexico, Peru, Paraguay and South Africa were shaded in the
1M window because the report said they were quiet. "Quiet" is the absence of a
signal, not a signal.

So a country now reaches the map only through something public and written: a
section item, or a `coverage` note. `report_coverage_gaps()` prints the countries
counted from recent reports with neither. **Read that as a list to triage, not a
list to fill** — a country named only to say it was quiet belongs in it.

## A title is read on its own

The map tooltip shows a section item's **title and nothing else**. "The
Mediterranean loaded both hazards this season" landed on seven countries, and
nothing in it says which hazards or what loaded means — the body that explained it
was not on screen. A region word in a title also fans the headline to every member,
so a Spanish flood sequence became Morocco's heat headline. `check_headlines()`
prints a review list of titles carrying three or more countries that way. It warns
rather than fails: an EU consultation legitimately reaches fourteen member states
and names none of them, so this is a judgement the writer has to make.

`check_tooltips()` also asserts the `[kind, text]` shape. A shape change is a blank
tooltip, and a blank tooltip is only visible to someone who hovers.

## Write the character, not the CSS escape

A CSS rule inside a Python string is a **Python string literal first**, and Python
reads `\221` and `\00` as OCTAL. `content:"\2212 "` shipped a minus sign that
rendered as `2`; `content:"\00a0\203a"` shipped a row affordance that rendered as
`Doha�a0 a`. Both were invisible in the source and obvious on the page.

Put the literal character in the source. `check_chars()` fails the build on any C0
or C1 control character in the output, which is what a swallowed escape leaves
behind.

## No one-sided borders

A box gets a border on all four sides or none. The accent-bar-on-the-left pattern is
out — emphasis comes from the heading colour and the surface. Section separators and
table row rules are not box borders and stay.

## The forecast window is fixed, and one day wider than it looks

Every hub renders the same seven dates: the report date plus six. A hub with no
forecast for one of them gets `None`, drawn as a dash, never a zero.

Taking each hub's own first seven days made the table ragged. The fetch runs 05:30
UK, which is the previous evening in Chicago, so Open-Meteo's seven **local** days
for a western hub start a day early and stop a day short of the window — Houston and
Fresno rendered six cells against a seven-column header, shifting every later cell
one column left and leaving the row rule short of the table edge. `FORECAST_DAYS` is
8 for that reason; the eighth day is the offset, not spare data.

## The filter bar's sticky scope and its height

The controls are sticky on desktop only, and their parent is `.filterscope`, which
wraps the key numbers **and** the table. A sticky element only sticks while its own
parent is on screen, so leaving them inside the "This week" section would unstick
them at the moment the table they filter came into view. On a phone they are static:
four control groups wrap to five rows there, which is most of the screen.

Its height is **not a constant** — the control groups wrap as the window narrows, so
it runs from 162px at 1440 to 259px at 780. Two things depend on it and neither can
be a fixed number: `.ctlcard`'s `scroll-margin-top` (a fixed 232px put the By hub
heading 10px behind the bar's own bottom border) and `window.__navLine`. JS measures
the bar into `--ctlbar-h` and sets both.

## Hub detail is a modal

A native `<dialog>`, not a panel under the table. Inline, it opened below eighteen
rows: on a laptop the click produced no visible change, because the thing that
appeared was two screens down. `<dialog>` brings Esc, a focus trap and an inert
background without hand-rolling any of it; the row carries `aria-haspopup="dialog"`
and a `›` so it reads as something that opens.

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
