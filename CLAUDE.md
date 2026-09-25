# HeatWatch — public site repo

Published to GitHub Pages from `master`, built on the mini and committed, not
built in CI. The Cloudflare Workers move is deferred until the site has been
evaluated; when it happens, Pages retires rather than running alongside.

Public repo on GitHub: both the *content* and the generator source are public.
`heatwatch-core` is private and stays private.

Pages serves only the generated HTML. `.github/workflows/pages.yml` stages a
named allowlist of pages into an empty directory and uploads that, so the repo
being public does not mean the repo root is *served* — `generate_site.py`,
`globe.py` and `world_paths.json` are build inputs and the workflow fails the
build if any of them reaches the artifact. A new page needs its name added there.

## The one rule

**Never hand-edit a generated page** — `index.html`, `climate.html`,
`health.html`, `workers.html`, `fire.html`, `solutions.html`. It is a build artifact that happens to be
committed. Every design or content change goes into `generate_site.py`, then you
regenerate. A hand-edit is silently destroyed by the next daily run.

## The two repos

| | |
|---|---|
| `~/heatwatch` (this one) | `generate_site.py`, `globe.py`, `world_paths.json`, the generated pages |
| `~/heatwatch-core` (private) | `state/`, `memory/`, `prompts/`, `reports/`, `desk/`, the run script |

## Regenerating

```
python3 generate_site.py ~/heatwatch-core/state/heatwatch_state_<date>.json .
```

Arg order is `<state.json> <out_dir>` — a **directory**, not a filename, because
the generator writes several pages. It also scans the state file's own directory
for siblings to build the map's time windows, so the windows deepen on their own
as history accumulates.

Preview by writing to a scratch directory and serving it — `open file://` works,
but a local `python3 -m http.server` is what a browser on another machine can
reach (bind `0.0.0.0` for that, and send no-cache headers or you will spend an
hour looking at a stale page).

A sector page is only written when the state carries that section, and the nav is
built from the same test — so a tab never leads to an empty page. `health.html`
appears once the run starts producing `sections.health`.

## The map's time windows are gated on real coverage

`WINDOWS` in `generate_site.py` declares 1W / 1M / 3M / 1Y, but a window is only
offered when the archive covers at least `WINDOW_MIN_COVERAGE` (60%) of its span.

**1Y is therefore hidden right now** — history begins 2026-07-24, which is 64 days,
17% of a year, and a button labelled "1Y" showing 64 days of data is a lie told by
a label. It comes back **on its own at roughly 220 days of history, around April
2027**. Nothing to remember and nothing to re-enable: do not hardcode it back.

Window depth comes from two sources. State files (`heatwatch-core/state/`) supply
the items and their real titles. The archived briefings
(`heatwatch-core/reports/*.md`) supply older history, and they contribute **counts
only, never prose** — those reports also contain desk-only Competition and Funding
sections, so the parser uses a strict heading allowlist and the map payload is
checked for desk terms. Do not loosen that to make tooltips richer.

## The map is coupled to the prose

The world map places countries by matching region names in each section item's
`title`, `body` and `so_what` against a keyword table in `generate_site.py`. An
item that never names its country reads correctly on the page and silently
vanishes from the map. `prompts/daily.md` tells the run to name places
explicitly; if you add a region to the keyword table, add its ISO3 set too.

The globe in the hero is real geometry: `world_paths.json` is a Robinson
projection with no lat/lon in it, so `globe.py` inverts Robinson back to
coordinates (parameters fitted and validated to sub-degree longitude accuracy)
and reprojects orthographically. It deliberately uses its own reserved, quieter
palette — mean OKLab chroma 0.06 against the map ramp's 0.16 — so the loud colour
stays reserved for data.

## Public / private split

The daily run produces both surfaces. Only *heat events*, *extremes*, *fire* and
*regulation* go public. Competition, the uniqueness claim, funding, the investor
pipeline and the signal ledger are desk-only and live in `heatwatch-core/desk`,
which deploys to its own Worker behind Cloudflare Access. They are never in this
repo's deploy bundle — that separation is the point, not a convenience.

## Conventions carried from the other trackers

- Standard library only. A third-party import is what broke the MarketWatch
  fetch for five days.
- Everything inlined, no external requests except the Google Fonts stylesheet.
- Deploy surface is deny-by-default and always an allowlist. On Pages that is
  the staging step in `pages.yml`; on Cloudflare it becomes `.assetsignore`.
  The mechanism changes, the rule does not.
