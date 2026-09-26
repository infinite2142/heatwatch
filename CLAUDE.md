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

## Conventions

- Standard library only. A third-party import is what broke a sibling project's fetch
  for five days.
- Everything inlined, no external requests except the Google Fonts stylesheet.
- Deploy surface is deny-by-default and always an allowlist: the staging step in
  `.github/workflows/pages.yml`, and `.assetsignore` after the Cloudflare move. The
  mechanism changes, the rule does not.
- Every claim on the page carries its source. Rule summaries are not legal advice.
