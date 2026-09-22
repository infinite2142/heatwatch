# HeatWatch — public site repo

Published to GitHub Pages from `master`, built on the mini and committed, not
built in CI. The Cloudflare Workers move is deferred until the site has been
evaluated; when it happens, Pages retires rather than running alongside.

Public repo on GitHub: both the *content* and the generator source are public.
`heatwatch-core` is private and stays private.

Pages serves exactly one file. `.github/workflows/pages.yml` stages `index.html`
into an empty directory and uploads only that, so the repo being public does not
mean the repo root is *served*. A new runtime asset needs a `cp` line there.

## The one rule

**Never hand-edit `index.html`.** It is a build artifact that happens to be
committed. Every design or content change goes into `generate_site.py`, then you
regenerate. A hand-edit is silently destroyed by the next daily run.

## The two repos

| | |
|---|---|
| `~/heatwatch` (this one) | `generate_site.py`, `index.html` |
| `~/heatwatch-core` (private) | `state/`, `memory/`, `prompts/`, `reports/`, `desk/`, the run script |

## Regenerating

```
python3 generate_site.py ~/heatwatch-core/state/heatwatch_state_<date>.json index.html
```

Arg order is `<state.json> <out.html>`. Preview by writing to a scratch path and
serving it — `open file://` works, but a local `python3 -m http.server` is what
the browser pane can reach.

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
