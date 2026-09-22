#!/usr/bin/env python3
"""HeatWatch public site generator.

    python3 generate_site.py <state.json> <out.html>

Standard library only, by design: this runs unattended on the mini and a
third-party import is how the MarketWatch fetch broke for five days.

The one rule, same as the other trackers: never hand-edit the generated
index.html. It is a build artifact that happens to be committed. Change the
template here and regenerate, or the next daily run silently destroys the edit.
"""
import html
import json
import sys
from datetime import date, datetime

BANDS = {"good": "good", "warning": "warning", "serious": "serious", "critical": "critical"}


def esc(s):
    return html.escape(str(s), quote=True)


def band_of(item):
    return BANDS.get(item.get("band", ""), "warning")


def render_tiles(tiles):
    out = []
    for t in tiles:
        unit = f'<span class="unit">{esc(t["unit"])}</span>' if t.get("unit") else ""
        sub = f'<div class="tile-sub">{esc(t["sub"])}</div>' if t.get("sub") else ""
        out.append(
            f'<div class="tile b-{band_of(t)}">'
            f'<div class="tile-value">{esc(t["value"])}{unit}</div>'
            f'<div class="tile-label">{esc(t["label"])}</div>{sub}</div>'
        )
    return "\n".join(out)


def render_grid(rows):
    out = []
    for r in rows:
        flag = r.get("flag", "—")
        flag_cls = "flag-watch" if flag.upper() == "WATCH" else "flag-none"
        out.append(
            "<tr>"
            f'<td class="g-area">{esc(r["area"])}</td>'
            f'<td class="g-dir"><span class="arrow">{esc(r.get("state", ""))}</span> {esc(r.get("direction", ""))}</td>'
            f'<td class="g-dev">{esc(r["development"])}</td>'
            f'<td class="g-flag"><span class="{flag_cls}">{esc(flag)}</span></td>'
            "</tr>"
        )
    return "\n".join(out)


def render_items(items):
    """Heat-events / fire cards: title, body, 'so what', sources, optional gap note."""
    out = []
    for it in items:
        parts = [f'<h3>{esc(it["title"])}</h3>', f'<p>{esc(it["body"])}</p>']
        if it.get("so_what"):
            parts.append(f'<p class="sowhat"><span>So what</span>{esc(it["so_what"])}</p>')
        if it.get("gap"):
            parts.append(f'<p class="gap">{esc(it["gap"])}</p>')
        if it.get("sources"):
            srcs = " · ".join(esc(s) for s in it["sources"])
            parts.append(f'<p class="srcs">{srcs}</p>')
        out.append('<article class="card">' + "".join(parts) + "</article>")
    return "\n".join(out)


def render_rules(items):
    """Worker-safety regulation tracker: each rule with jurisdiction and status."""
    out = []
    for it in items:
        srcs = ""
        if it.get("sources"):
            srcs = '<p class="srcs">' + " · ".join(esc(s) for s in it["sources"]) + "</p>"
        out.append(
            '<article class="card rule">'
            f'<div class="rule-head"><span class="juris">{esc(it.get("jurisdiction", ""))}</span>'
            f'<span class="rule-status">{esc(it.get("status", ""))}</span></div>'
            f'<h3>{esc(it["title"])}</h3><p>{esc(it["body"])}</p>{srcs}</article>'
        )
    return "\n".join(out)


def render_countdown(cd, report_date):
    if not cd:
        return ""
    ref = datetime.strptime(report_date, "%Y-%m-%d").date()
    out = []
    for label_k, date_k in (("label", "deadline"), ("second_label", "second_deadline")):
        if not cd.get(date_k):
            continue
        d = datetime.strptime(cd[date_k], "%Y-%m-%d").date()
        days = (d - ref).days
        word = "days left" if days > 1 else ("tomorrow" if days == 1 else ("today" if days == 0 else "closed"))
        num = str(days) if days > 0 else ("—" if days < 0 else "0")
        out.append(
            '<div class="cd-row">'
            f'<div class="cd-num">{num}<span>{word}</span></div>'
            f'<div class="cd-label">{esc(cd[label_k])}'
            f'<span class="cd-date">closes {d.strftime("%-d %B %Y")}</span></div></div>'
        )
    note = f'<p class="cd-note">{esc(cd["note"])}</p>' if cd.get("note") else ""
    return '<div class="countdown">' + "".join(out) + note + "</div>"


HTML = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HeatWatch</title>
<meta name="description" content="__DESC__">
<meta property="og:type" content="website">
<meta property="og:site_name" content="HeatWatch">
<meta property="og:title" content="HeatWatch — __OG_TITLE__">
<meta property="og:description" content="__DESC__">
<meta name="twitter:card" content="summary_large_image">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>
  :root{
    --bg:#f7f4ee; --ink:#16130f; --ink-dim:#4c463d; --muted:#7d766a;
    --line:rgba(22,19,15,0.13); --line-2:rgba(22,19,15,0.26); --panel:rgba(22,19,15,0.025);
    --card:#ffffff;
    --h1:#f2b134; --h2:#e8912a; --h3:#dd6b20; --h4:#c2410c; --h5:#9a1c13;
    --good:#0f9d47; --warning:#c08a10; --serious:#d5622a; --critical:#cf3838;
    --accent:#c2410c;
  }
  :root[data-theme="dark"]{
    --bg:#0c0a08; --ink:#f4f1ea; --ink-dim:#b9b2a5; --muted:#8a8275;
    --line:rgba(244,241,234,0.14); --line-2:rgba(244,241,234,0.28); --panel:rgba(244,241,234,0.035);
    --card:#141110;
    --h1:#f6c250; --h2:#f0a03c; --h3:#e97b30; --h4:#d9542a; --h5:#c23b2a;
    --good:#34c06a; --warning:#e0a92c; --serious:#ef7f45; --critical:#ef5350;
    --accent:#f0a03c;
  }
  *{box-sizing:border-box}
  html{-webkit-text-size-adjust:100%}
  body{margin:0;background:var(--bg);color:var(--ink);
    font-family:'Space Grotesk',system-ui,-apple-system,sans-serif;
    font-size:16px;line-height:1.55;}
  .wrap{max-width:1020px;margin:0 auto;padding:0 16px}

  /* masthead */
  .masthead{padding:48px 0 30px;border-bottom:1px solid var(--line)}
  .brand{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}
  .brand h1{font-size:30px;margin:0;letter-spacing:-0.02em;font-weight:700}
  .brand .dot{width:11px;height:11px;border-radius:50%;background:var(--h3);
    box-shadow:0 0 0 4px color-mix(in srgb, var(--h3) 22%, transparent);flex:none;align-self:center}
  .brand .tag{font-family:'Space Mono',monospace;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em}
  .standfirst{margin:14px 0 0;max-width:62ch;color:var(--ink-dim);font-size:17px}

  /* headline */
  .headline{margin:30px 0 0;padding:26px 0 0;border-top:1px solid var(--line)}
  .headline-value{font-family:'Space Mono',monospace;font-weight:700;letter-spacing:-0.03em;
    font-size:clamp(56px,13vw,104px);line-height:0.94;color:var(--h5)}
  :root[data-theme="dark"] .headline-value{color:var(--h2)}
  .headline-value .u{font-size:0.42em;margin-left:4px;letter-spacing:0}
  .headline-label{margin:12px 0 0;font-size:19px;max-width:54ch;font-weight:500}
  .headline-detail{margin:10px 0 0;color:var(--ink-dim);max-width:60ch;font-size:15px}
  .headline-src{margin:10px 0 0;font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted)}

  /* tiles */
  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(196px,1fr));gap:12px;margin:28px 0 0}
  .tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 16px 14px;border-top:3px solid var(--warning)}
  .tile.b-critical{border-top-color:var(--critical)} .tile.b-serious{border-top-color:var(--serious)}
  .tile.b-warning{border-top-color:var(--warning)} .tile.b-good{border-top-color:var(--good)}
  .tile-value{font-family:'Space Mono',monospace;font-weight:700;font-size:27px;letter-spacing:-0.02em}
  .tile-value .unit{font-size:14px;color:var(--muted);margin-left:5px;font-weight:400}
  .tile-label{margin-top:5px;font-size:14px;line-height:1.4}
  .tile-sub{margin-top:5px;font-size:12px;color:var(--muted);font-family:'Space Mono',monospace;line-height:1.45}

  /* tabs */
  .topbar{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--bg) 92%,transparent);
    backdrop-filter:saturate(1.4) blur(10px);border-bottom:1px solid var(--line);margin-top:34px}
  .tabs{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none}
  .tabs::-webkit-scrollbar{display:none}
  .tabs a{flex:none;padding:13px 15px;font-size:14px;text-decoration:none;color:var(--muted);
    border-bottom:2px solid transparent;white-space:nowrap;font-weight:500}
  .tabs a:hover{color:var(--ink)}
  .tabs a[aria-current="true"]{color:var(--ink);border-bottom-color:var(--accent)}

  .panel{display:none;padding:30px 0 10px}
  .panel[data-active="true"]{display:block}
  .panel > h2{font-size:13px;font-family:'Space Mono',monospace;text-transform:uppercase;
    letter-spacing:0.1em;color:var(--muted);margin:0 0 16px;font-weight:700}

  /* status grid */
  table.grid{width:100%;border-collapse:collapse;font-size:14.5px}
  table.grid td{border-top:1px solid var(--line);padding:13px 10px 13px 0;vertical-align:top}
  table.grid tr:first-child td{border-top:none}
  .g-area{font-weight:500;width:21%;min-width:150px}
  .g-dir{width:16%;min-width:125px;color:var(--ink-dim);font-size:13px;font-family:'Space Mono',monospace}
  .arrow{color:var(--h3);font-weight:700}
  .g-dev{color:var(--ink-dim)}
  .g-flag{width:70px;text-align:right}
  .flag-watch{font-family:'Space Mono',monospace;font-size:10.5px;font-weight:700;letter-spacing:0.07em;
    color:var(--serious);border:1px solid color-mix(in srgb,var(--serious) 45%,transparent);
    padding:2px 6px;border-radius:4px;white-space:nowrap}
  .flag-none{color:var(--muted)}

  /* cards */
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin:0 0 14px}
  .card h3{margin:0 0 9px;font-size:18px;letter-spacing:-0.01em}
  .card p{margin:0 0 11px;color:var(--ink-dim);font-size:15px}
  .card p:last-child{margin-bottom:0}
  .sowhat{border-left:2px solid var(--h3);padding:2px 0 2px 13px;color:var(--ink) !important;font-size:15px !important}
  .sowhat span{display:block;font-family:'Space Mono',monospace;font-size:10.5px;text-transform:uppercase;
    letter-spacing:0.1em;color:var(--h3);margin-bottom:3px}
  .gap{font-size:13px !important;color:var(--muted) !important;border:1px dashed var(--line-2);
    border-radius:8px;padding:10px 12px}
  .srcs{font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted) !important;margin-top:12px !important}
  .rule-head{display:flex;justify-content:space-between;gap:12px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
  .juris{font-family:'Space Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.09em;color:var(--h3)}
  .rule-status{font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted)}

  /* countdown */
  .countdown{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:0 0 20px}
  .cd-row{display:flex;gap:16px;align-items:baseline;padding:8px 0;border-top:1px solid var(--line)}
  .cd-row:first-child{border-top:none;padding-top:0}
  .cd-num{font-family:'Space Mono',monospace;font-weight:700;font-size:30px;color:var(--serious);
    line-height:1;flex:none;min-width:86px}
  .cd-num span{display:block;font-size:10px;font-weight:400;color:var(--muted);letter-spacing:0.07em;
    text-transform:uppercase;margin-top:4px}
  .cd-label{font-size:14.5px}
  .cd-date{display:block;font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted);margin-top:2px}
  .cd-note{margin:12px 0 0;font-size:13px;color:var(--muted)}

  /* method + footer */
  .method dt{font-family:'Space Mono',monospace;font-size:11px;text-transform:uppercase;
    letter-spacing:0.09em;color:var(--h3);margin-top:18px}
  .method dd{margin:6px 0 0;color:var(--ink-dim);font-size:15px;max-width:68ch}
  footer{border-top:1px solid var(--line);margin-top:44px;padding:22px 0 46px;
    font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted);
    display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap}
  footer a{color:var(--muted)}
  .themer{background:none;border:1px solid var(--line-2);color:var(--muted);border-radius:6px;
    font-family:'Space Mono',monospace;font-size:11px;padding:4px 9px;cursor:pointer}
  .themer:hover{color:var(--ink)}
  @media (max-width:620px){
    .masthead{padding:34px 0 24px}
    .g-area,.g-dir{width:auto}
    table.grid td{display:block;padding:3px 0}
    table.grid tr td:first-child{padding-top:14px;border-top:1px solid var(--line)}
    table.grid td{border-top:none}
    .g-flag{text-align:left;padding-bottom:12px}
  }
</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div class="brand">
      <span class="dot"></span>
      <h1>HeatWatch</h1>
      <span class="tag">__DATELINE__</span>
    </div>
    <p class="standfirst">A daily record of heat as a hazard to people at work &mdash; extremes, fire, and the rules that are starting to govern working in it.</p>
    <div class="headline">
      <div class="headline-value">__HL_VALUE__<span class="u">__HL_UNIT__</span></div>
      <p class="headline-label">__HL_LABEL__</p>
      <p class="headline-detail">__HL_DETAIL__</p>
      <p class="headline-src">__HL_SOURCE__</p>
    </div>
    <div class="tiles">__TILES__</div>
  </header>
</div>

<div class="topbar"><div class="wrap"><nav class="tabs">
  <a href="#now" data-tab="now">Now</a>
  <a href="#extremes" data-tab="extremes">Extremes</a>
  <a href="#fire" data-tab="fire">Fire</a>
  <a href="#workers" data-tab="workers">Workers</a>
  <a href="#method" data-tab="method">Method</a>
</nav></div></div>

<div class="wrap">
  <section class="panel" id="p-now" data-panel="now">
    <h2>Status &mdash; __DATELINE__</h2>
    <table class="grid">__GRID__</table>
  </section>

  <section class="panel" id="p-extremes" data-panel="extremes">
    <h2>Heat extremes &amp; records</h2>
    __EXTREMES__
  </section>

  <section class="panel" id="p-fire" data-panel="fire">
    <h2>Fire</h2>
    __FIRE__
  </section>

  <section class="panel" id="p-workers" data-panel="workers">
    <h2>Heat at work &mdash; the rules</h2>
    __COUNTDOWN__
    __WORKERS__
  </section>

  <section class="panel" id="p-method" data-panel="method">
    <h2>Method</h2>
    <div class="card"><dl class="method">
      <dt>Cadence</dt><dd>__M_CADENCE__</dd>
      <dt>Sourcing</dt><dd>__M_SOURCING__</dd>
      <dt>What these numbers are not</dt><dd>__M_LIMITS__</dd>
      <dt>Who publishes this</dt><dd>__M_DISCLOSURE__</dd>
    </dl></div>
  </section>

  <footer>
    <span>HeatWatch &mdash; rebuilt __DATELINE__</span>
    <button class="themer" id="themer">light / dark</button>
  </footer>
</div>

<script>
(function(){
  var tabs = Array.prototype.slice.call(document.querySelectorAll('[data-tab]'));
  var panels = Array.prototype.slice.call(document.querySelectorAll('[data-panel]'));
  function show(name){
    if(!name || !panels.some(function(p){return p.dataset.panel===name;})) name = 'now';
    panels.forEach(function(p){ p.dataset.active = (p.dataset.panel===name) ? 'true' : 'false'; });
    tabs.forEach(function(t){
      if(t.dataset.tab===name){ t.setAttribute('aria-current','true'); }
      else { t.removeAttribute('aria-current'); }
    });
  }
  function fromHash(){ show((location.hash||'#now').slice(1)); }
  window.addEventListener('hashchange', fromHash);
  fromHash();

  var themer = document.getElementById('themer');
  var root = document.documentElement;
  try{ var saved = localStorage.getItem('hw-theme'); if(saved){ root.setAttribute('data-theme', saved); } }catch(e){}
  themer.addEventListener('click', function(){
    var next = root.getAttribute('data-theme')==='dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    try{ localStorage.setItem('hw-theme', next); }catch(e){}
  });
})();
</script>
</body>
</html>
"""


def build(state):
    hl = state["headline"]
    meta = state["meta"]
    rd = meta["report_date"]
    dateline = datetime.strptime(rd, "%Y-%m-%d").strftime("%-d %B %Y")
    m = state["method"]
    desc = ("A daily record of heat as a hazard to people at work — extremes, fire, "
            "and the rules that are starting to govern working in it.")
    subs = {
        "__DESC__": esc(desc),
        "__OG_TITLE__": esc(f'{hl["value"]}{hl["unit"]} above pre-industrial'),
        "__DATELINE__": esc(dateline),
        "__HL_VALUE__": esc(hl["value"]),
        "__HL_UNIT__": esc(hl["unit"]),
        "__HL_LABEL__": esc(hl["label"]),
        "__HL_DETAIL__": esc(hl["detail"]),
        "__HL_SOURCE__": esc(hl["source"]),
        "__TILES__": render_tiles(state.get("tiles", [])),
        "__GRID__": render_grid(state.get("status_grid", [])),
        "__EXTREMES__": render_items(state["sections"].get("extremes", [])),
        "__FIRE__": render_items(state["sections"].get("fire", [])),
        "__WORKERS__": render_rules(state["sections"].get("workers", [])),
        "__COUNTDOWN__": render_countdown(state.get("countdown"), rd),
        "__M_CADENCE__": esc(m["cadence"]),
        "__M_SOURCING__": esc(m["sourcing"]),
        "__M_LIMITS__": esc(m["limits"]),
        "__M_DISCLOSURE__": esc(m["disclosure"]),
    }
    out = HTML
    for k, v in subs.items():
        out = out.replace(k, v)
    if "__" in out.replace("__pycache__", ""):
        leftover = [w for w in out.split() if w.startswith("__") and w.endswith("__")]
        if leftover:
            raise SystemExit(f"unsubstituted placeholders: {leftover[:5]}")
    return out


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    state = json.load(open(sys.argv[1]))
    out = build(state)
    with open(sys.argv[2], "w") as fh:
        fh.write(out)
    print(f"wrote {sys.argv[2]} — {len(out):,} bytes, report_date {state['meta']['report_date']}")


if __name__ == "__main__":
    main()
