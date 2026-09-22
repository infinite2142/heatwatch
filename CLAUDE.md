# HeatWatch — public site repo

Deployed to Cloudflare Workers static assets from the mini, not from CI.
Private repo on GitHub; the *content* is public, the repo is not.

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
- Deploy surface controlled by `.assetsignore`, deny-by-default.
