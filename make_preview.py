#!/usr/bin/env python3
"""Render the link-preview card (the Open Graph image) as HTML.

    python3 make_preview.py <state.json> <out.html>

Then screenshot it at 1200x630 to preview.png -- daily-update.sh does that with
headless Chrome.

Kept out of generate_site.py on purpose: turning this into a PNG needs a browser,
and the build must never depend on one being present. A day Chrome is missing
keeps the previous card rather than failing the run.

Nothing here is a second copy of the site. The strapline is generate_site.DESC,
the globe is the same globe.build() the masthead draws, and the number is the
state file's headline -- so the card cannot drift from the page it advertises.
It is coloured with the dark token set, --h4 on the number exactly as .metric .mv
does, because a dark card reads as deliberate in a timeline and the ramp colour
means the same thing in both places.
"""
import json, os, sys, html
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import globe
import generate_site as gs

state_path = sys.argv[1] if len(sys.argv) > 1 else "heatwatch_state.json"
out_path = sys.argv[2] if len(sys.argv) > 2 else "preview.html"

with open(state_path) as f:
    S = json.load(f)

hl = S.get("headline") or {}
meta = S.get("meta") or {}
try:
    when = date.fromisoformat(meta.get("report_date", "")).strftime("%-d %B %Y")
except ValueError:
    sys.exit("FATAL: state meta.report_date is not an ISO date")

# r=250 against cy=256 gives a 600x512 viewBox; build() refuses anything that
# would clip the poles. Rendered at width 700 that is 597px tall, which clears
# the 630px card with a margin either side.
art = globe.build(lon0=20.0, r=250.0, cx=300.0, cy=256.0)

# Braces are left alone: the CSS is a plain string and the one dynamic value the
# card needs is a custom property set on <body>. Escaped sequences are a trap
# here -- see "Write the character, not the CSS escape" in CLAUDE.md -- so the
# characters go in literally.
CSS = """
  *{box-sizing:border-box;margin:0}
  html,body{width:1200px;height:630px;overflow:hidden}
  body{background:#0c0a08;color:#f4f1ea;position:relative;
    font-family:'Space Grotesk',system-ui,sans-serif;-webkit-font-smoothing:antialiased}

  /* globe.build() ships class="hero-art" and the page positions it; the card
     positions it its own way, bleeding off the right edge behind the same mask
     the masthead uses. */
  .hero-art{position:absolute;right:-116px;top:50%;transform:translateY(-50%);width:700px;
    -webkit-mask-image:linear-gradient(90deg,transparent 2%,#000 44%);
    mask-image:linear-gradient(90deg,transparent 2%,#000 44%)}
  /* The page animates .cyc from 0; a still has to pick one point in that cycle. */
  .cyc{opacity:.15}
  .grat line,.grat ellipse,.grat path{stroke:#fff}

  .in{position:relative;z-index:2;padding:60px 70px;height:100%;
    display:flex;flex-direction:column}
  .eb{font-family:'Space Mono',monospace;font-size:18px;font-weight:700;
    letter-spacing:.2em;text-transform:uppercase;color:#f0a03c}
  .eb .sep{color:#4c463d;margin:0 15px}
  .eb .upd{color:#8a8275;letter-spacing:.13em}
  h1{font-family:'Fraunces',Georgia,serif;font-size:106px;font-weight:700;
    letter-spacing:-.025em;line-height:.95;margin:22px 0 24px}
  p.sub{font-size:24px;line-height:1.42;color:#b9b2a5;max-width:620px}

  /* No rule between the number and its line: a box gets four borders or none. */
  .row{margin-top:auto;display:flex;align-items:flex-end;gap:38px;max-width:800px}
  .num{font-size:84px;font-weight:700;letter-spacing:-.035em;line-height:.86;
    color:#d9542a;white-space:nowrap}
  .num span{font-size:37px;color:#8a8275;margin-left:5px}
  .hl{font-size:21.5px;line-height:1.34;color:#f4f1ea;padding-bottom:5px}
"""

num = ""
if hl.get("value"):
    unit = f'<span>{html.escape(hl["unit"])}</span>' if hl.get("unit") else ""
    num = f'<div class="num">{html.escape(hl["value"])}{unit}</div>'

CARD = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,700&family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>
{art}
<div class="in">
  <div class="eb">Global heat intelligence<span class="sep">/</span><span class="upd">Updated {html.escape(when)}</span></div>
  <h1>HeatWatch</h1>
  <p class="sub">{html.escape(gs.DESC)}</p>
  <div class="row">
    {num}
    <div class="hl">{html.escape(hl.get("label", ""))}</div>
  </div>
</div></body></html>"""

with open(out_path, "w") as f:
    f.write(CARD)
print(f"wrote {out_path} - screenshot at 1200x630 to make preview.png")
