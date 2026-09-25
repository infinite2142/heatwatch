#!/usr/bin/env python3
"""HeatWatch public site generator.

    python3 generate_site.py <state.json> <out_dir>

Writes index.html plus one page per sector that the state actually carries.
Scans the directory of <state.json> for sibling state files to build the map's
time windows, so the windows deepen on their own as history accumulates.

Standard library only, by design: this runs unattended on the mini and a
third-party import is how the MarketWatch fetch broke for five days.

The one rule, same as the other trackers: never hand-edit a generated page. They
are build artifacts that happen to be committed. Change this file and regenerate,
or the next daily run silently destroys the edit.

Geometry: world_paths.json (Natural Earth 110m, public domain) via globe.py.
"""
import json
import os
import re
import sys
from collections import OrderedDict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import globe  # noqa: E402  (local module, after sys.path is set)

WORLD = os.path.join(HERE, "world_paths.json")
NUMRE = re.compile(r"-?\d+(?:\.\d+)?")

# ---------------------------------------------------------------------------- #
# Design tokens. h1..h5 is the sequential heat ramp (verified monotonic in OKLab
# lightness). The globe deliberately does NOT use it -- see globe.field() -- so
# the loud colour stays reserved for data.
TOKENS = """
  :root{
    --bg:#f7f4ee; --ink:#16130f; --ink-dim:#4c463d; --muted:#7d766a;
    --line:rgba(22,19,15,0.13); --line-2:rgba(22,19,15,0.26);
    --h1:#f2b134; --h2:#e8912a; --h3:#dd6b20; --h4:#c2410c; --h5:#9a1c13;
    --c3:#4d7387; --c4:#2b5065;
    --good:#0f9d47; --warning:#c08a10; --serious:#d5622a; --critical:#cf3838;
    --gut:48px;
    --land:#e7e0d4; --land-line:rgba(22,19,15,0.20);
  }
  :root[data-theme="dark"]{
    --bg:#0c0a08; --ink:#f4f1ea; --ink-dim:#b9b2a5; --muted:#8a8275;
    --line:rgba(244,241,234,0.14); --line-2:rgba(244,241,234,0.28);
    --h1:#f6c250; --h2:#f0a03c; --h3:#e97b30; --h4:#d9542a; --h5:#c23b2a;
    --c3:#7fa3b8; --c4:#a9c4d4;
    --good:#34c06a; --warning:#e0a92c; --serious:#ef7f45; --critical:#ef5350;
    --land:#221d19; --land-line:rgba(244,241,234,0.16);
  }
"""

# Category -> (label, icon key). "reg" is regulation, drawn separately on the map
# because a rule in force is the mitigation, not the hazard.
CATS = OrderedDict([
    ("heat",    ("Heat & climate", "thermo")),
    ("health",  ("Health", "pulse")),
    ("workers", ("Workers", "hardhat")),
    ("fire",    ("Fire", "flame")),
    ("reg",     ("Heat-at-work rules", "rule")),
])

# state.sections keys -> the category they represent
SECTION_CAT = {"extremes": "heat", "fire": "fire", "workers": "workers", "health": "health"}

# Sector pages, in nav order. Each is (slug, nav label, page title, state key).
SECTORS = [
    ("climate", "Climate", "Climate & records", "extremes"),
    ("health",  "Health",  "Health & mortality", "health"),
    ("workers", "Workers", "Workers & exposure", "workers"),
    ("fire",    "Fire",    "Fire", "fire"),
]

ICONS = {
 "thermo": '<path d="M17 22V8a3 3 0 0 1 6 0v14a6 6 0 1 1-6 0z"/><path d="M20 26v-8"/>',
 "pulse":  '<path d="M5 20h6l3-7 5 14 4-9 3 2h9"/>',
 "hardhat":'<path d="M6 27a14 14 0 0 1 28 0z"/><path d="M15 14a6 6 0 0 1 10 0"/><path d="M4 27h32"/>',
 "flame":  '<path d="M20 5c7 9 10 13 10 18a10 10 0 0 1-20 0c0-5 3-9 10-18z"/>'
           '<path d="M20 30a5 5 0 0 1-3-8"/>',
 "rule":   '<path d="M11 6h13l6 6v22H11z"/><path d="M24 6v6h6"/><path d="M16 21h10M16 26h10"/>',
 "siren":  '<path d="M11 32h18"/><path d="M13 32v-9a7 7 0 0 1 14 0v9"/><path d="M20 10V5"/>'
           '<path d="M30 14l3-3M10 14l-3-3"/>',
 "pylon":  '<path d="M14 34L20 6l6 28"/><path d="M16 22h8M15 27h10"/><path d="M8 34h24"/>',
 "shield": '<path d="M20 5l12 4v11c0 8-6 13-12 15-6-2-12-7-12-15V9z"/>',
 "clock":  '<circle cx="20" cy="20" r="14"/><path d="M20 12v8l6 4"/>',
 "droplet":'<path d="M20 6c6 8 9 12 9 16a9 9 0 0 1-18 0c0-4 3-8 9-16z"/><path d="M15 23a5 5 0 0 0 5 5"/>',
 "chip":   '<rect x="11" y="11" width="18" height="18" rx="2"/><path d="M17 17h6v6h-6z"/>'
           '<path d="M20 5v6M20 29v6M5 20h6M29 20h6"/>',
 "cycle":  '<path d="M11 20a9 9 0 0 1 15-6.7"/><path d="M29 20a9 9 0 0 1-15 6.7"/>'
           '<path d="M26 8v5.5h-5.5M14 32v-5.5h5.5"/>',
 "tube":   '<path d="M8 14h13a6 6 0 0 1 0 12H8"/><path d="M8 20h13"/><circle cx="31" cy="20" r="3"/>',
 "sun":    '<circle cx="20" cy="20" r="7"/><path d="M20 4v5M20 31v5M4 20h5M31 20h5'
           'M9 9l3.5 3.5M27.5 27.5L31 31M31 9l-3.5 3.5M12.5 27.5L9 31"/>',
 "shade":  '<path d="M6 18h28"/><path d="M20 18v16"/><path d="M8 18c0-7 5-12 12-12s12 5 12 12"/>',
 "globe":  '<circle cx="20" cy="20" r="15"/><ellipse cx="20" cy="20" rx="6.5" ry="15"/>'
           '<path d="M5.6 15h28.8M5.6 25h28.8"/>',
}

# Region matching: keyword -> (symbol key, ISO3 set). Most specific first, since
# "UK / N. Europe" contains "europe" and must not fall through to the catch-all.
REGION_DEFS = [
    (("spain", "iberia", "balearic", "aemet"), "iberia", "Spain & Iberia",
     ["ESP", "PRT"]),
    (("uk", "britain", "england", "n. europe", "northern europe", "ukhsa", "met office"),
     "nweur", "UK & Northern Europe",
     ["GBR", "IRL", "FRA", "DEU", "NLD", "BEL", "DNK", "NOR", "SWE"]),
    (("mediterranean", "greece", "italy", "portugal", "turkey"), "med", "Mediterranean",
     ["ESP", "PRT", "FRA", "ITA", "GRC", "TUR", "MAR", "DZA", "TUN", "LBY", "EGY"]),
    (("gulf", "saudi", "emirates", "qatar", "oman", "kuwait", "bahrain"), "gulf", "Gulf",
     ["SAU", "ARE", "QAT", "OMN", "KWT", "IRQ", "IRN", "YEM", "JOR", "SYR"]),
    (("united states", "osha", " us ", "u.s."), "usa", "United States", ["USA"]),
    (("india", "pakistan", "bangladesh", "south asia"), "sasia", "South Asia",
     ["IND", "PAK", "BGD", "NPL", "LKA"]),
    (("australia", "oceania", "new zealand"), "aus", "Australia & Oceania", ["AUS", "NZL"]),
    (("sahel", "africa", "niger", "chad", "sudan"), "africa", "Africa",
     ["NER", "MLI", "TCD", "SDN", "NGA", "ETH", "ZAF", "EGY", "DZA", "LBY", "COD", "AGO"]),
    (("china", "japan", "east asia", "korea"), "easia", "East Asia",
     ["CHN", "JPN", "KOR", "VNM", "THA", "PHL"]),
    (("brazil", "south america", "argentina", "chile"), "samer", "South America",
     ["BRA", "ARG", "CHL", "PER", "COL", "BOL", "PRY"]),
    (("eu ", "european union", "europe"), "eur", "Europe",
     ["ESP", "PRT", "FRA", "DEU", "ITA", "GRC", "POL", "GBR", "IRL",
      "SWE", "NOR", "FIN", "DNK", "ROU", "UKR", "TUR"]),
    (("global", "world", "copernicus", "planet"), "globe", "Global", None),
]

# ---------------------------------------------------------------------------- #
# Editorial content: slow-changing, reviewed by a human, and deliberately NOT
# regenerated daily. The daily run has no business rewriting what a cooling vest
# is. If the weekly starts maintaining these, move them into the state file.
OCCUPATIONS = {
    "workers": [
        ("Construction", "hardhat", 5,
         "Outdoor, PPE-bound, and the largest exposed population. Schedule shifting is "
         "the main control and it collides with daylight and contract penalties.",
         ["PPE requirements block the obvious adaptation of removing layers",
          "Midday stoppages are the most common regulatory instrument"]),
        ("Emergency services", "siren", 4,
         "Firefighters and paramedics work in heat by definition, in turnout gear, with "
         "no option to defer the task. Exposure is acute rather than cumulative.",
         ["Turnout gear can exceed 25 kg with near-zero breathability",
          "Lengthening wildfire seasons extend the exposure window"]),
        ("Infrastructure & utilities", "pylon", 3,
         "Grid, rail and water crews are dispatched exactly when demand peaks — the "
         "faults they are sent to fix are caused by the same heat.",
         ["Rail buckling and grid faults cluster on the hottest days",
          "Substations and confined spaces concentrate radiant load"]),
        ("Military & defence", "shield", 3,
         "Armoured and dismounted personnel, with an established interest in "
         "micro-climate cooling and the budget to procure it.",
         ["Vehicle crews face cabin loads well above ambient",
          "Training deaths remain the visible tail of the problem"]),
    ],
}

SOLUTIONS = [
    ("clock", "Work scheduling & rest–shade–water", "Organisational", "commercial",
     "Shift the work out of the heat: midday stoppages, rotation, mandated breaks.",
     ["Costs nothing to specify", "Effective in every sector", "Basis of most regulation"],
     ["Collides with deadlines and daylight", "Compliance is hard to verify",
      "No help when the task cannot wait"],
     ["Spain and Greece midday bans", "Gulf states' Jun–Sep bans",
      "OSHA National Emphasis Program inspections"]),
    ("droplet", "Evaporative & phase-change vests", "Personal", "commercial",
     "Water or PCM packs worn on the torso, absorbing heat as they change phase.",
     ["Cheap and widely available", "No power required", "Well understood by buyers"],
     ["Finite capacity, then it is ballast", "Evaporative fails in high humidity",
      "Recharge needs a freezer or cold store"],
     ["Widely issued on European construction sites", "Motorsport pit crews",
      "Warehouse and foundry work"]),
    ("chip", "Thermoelectric (TEC) cooling", "Personal", "pilot",
     "Solid-state Peltier modules moving heat electrically, with no refrigerant loop.",
     ["Solid state, no moving parts", "Small and light", "Continuous while powered"],
     ["Low efficiency at real thermal loads", "Rated cooling rarely published",
      "Rejects heat immediately next to the body"],
     ["Consumer and prosumer vests", "Industrial pilots, few published results"]),
    ("cycle", "Vapour-compression refrigeration (VCR)", "Personal", "pilot",
     "A real refrigeration cycle, miniaturised to be worn — the same physics as a fridge.",
     ["Highest cooling capacity per watt", "Works independent of humidity",
      "Can hold a set temperature"],
     ["Heaviest and most complex", "Needs a battery budget",
      "Refrigerant choice is a regulatory question"],
     ["Early industrial and defence pilots", "No certified operating envelope published yet"]),
    ("tube", "Liquid-cooled garments", "Personal", "commercial",
     "Tubing circulating chilled liquid, fed by a vehicle loop or a carried chiller.",
     ["Very effective where a loop exists", "Long established in defence and motorsport",
      "Comfortable under armour"],
     ["Tethered, or the chiller is carried", "Bulk and connector failure points",
      "Poor fit for roaming work"],
     ["Armoured vehicle crews", "Formula and endurance racing", "EVA suits and hazmat entry"]),
    ("sun", "Passive & radiative fabrics", "Material", "lab",
     "Textiles engineered to emit infrared through the atmospheric window, with no power.",
     ["Zero power and zero maintenance", "Nothing to recharge or refill",
      "Scales as ordinary clothing"],
     ["Single-digit degrees at best", "Needs sky view to work", "Mostly still lab-stage"],
     ["Early architectural and tenting products", "Field trials in agriculture"]),
    ("shade", "Site-level cooling", "Environmental", "commercial",
     "Cool the place, not the person: shade structures, misting, cooled rest areas.",
     ["Helps everyone at once", "No wearer-compliance problem", "Doubles as a rest facility"],
     ["Fixed in place while the work moves", "Water and energy hungry", "Capital cost per site"],
     ["Mandated rest areas on Gulf megaprojects", "Misting in Mediterranean agriculture",
      "Cooling centres in US and Indian cities"]),
]
MATURITY = {"commercial": "Commercial", "pilot": "Pilot", "lab": "Lab"}
# A window is only OFFERED when the archive covers enough of it to mean something.
# 1Y is hidden today because history starts 2026-07-24 -- 64 days, 17% of a year --
# and a "1Y" button showing 64 days of data is a lie told by a label. The gate is
# automatic rather than a hardcoded removal, so 1Y returns on its own at roughly
# 220 days of history (around April 2027) with no code change. Same rule protects
# 3M and 1M in a fresh install.
WINDOWS = [("1W", 7), ("1M", 31), ("3M", 92), ("1Y", 366)]
WINDOW_MIN_COVERAGE = 0.60
COUNTLAB = {1: "1 signal", 2: "2 signals", 3: "3 signals", 4: "4 signals"}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def icon(k, cls="ico"):
    return (f'<svg class="{cls}" viewBox="0 0 40 40" aria-hidden="true" fill="none" '
            f'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS[k]}</svg>')


def region_of(text):
    low = " " + text.lower() + " "
    for keys, key, label, isos in REGION_DEFS:
        if any(k in low for k in keys):
            return key, label, isos
    return "globe", "Global", None


# ---------------------------------------------------------------------------- #
def load_history(state_path):
    """Every sibling state file, newest first, as (date, state)."""
    d = os.path.dirname(os.path.abspath(state_path))
    out = []
    for fn in sorted(os.listdir(d)):
        m = re.match(r"heatwatch_state_(\d{4}-\d{2}-\d{2})\.json$", fn)
        if not m:
            continue
        try:
            out.append((date.fromisoformat(m.group(1)),
                        json.load(open(os.path.join(d, fn)))))
        except Exception:
            continue
    return sorted(out, key=lambda t: t[0], reverse=True)


def items_of(state):
    """Flatten state.sections into (category, item) pairs."""
    out = []
    for key, items in (state.get("sections") or {}).items():
        cat = SECTION_CAT.get(key)
        if not cat:
            continue
        for it in items or []:
            out.append((cat, it))
    return out


# Only these report sections may inform the public map. The daily reports also
# carry "Competition & technology" and "Funding & investor climate", which are
# desk-only -- parsing the whole file would walk that straight onto a public page.
# Belt and braces: history contributes COUNTS ONLY, never prose, so even a
# mis-parsed heading cannot surface desk text in a tooltip.
PUBLIC_REPORT_SECTIONS = {
    "heat events & records": "heat",
    "heat events": "heat",
    "extremes": "heat",
    "regulation & policy": "reg",
    "regulation": "reg",
    "fire": "fire",
    "fire weather": "fire",
    "health": "health",
    "health & mortality": "health",
}
DESK_ONLY_HEADINGS = ("competition", "funding", "investor", "memory update",
                      "ledger", "uniqueness", "threat board", "pipeline")


def backfill_from_reports(core_dir):
    """Per-date (category, ISO3) signals read out of the archived briefings, so
    the map's longer windows are real on day one instead of months from now.

    Returns {date: {iso: set(categories)}} -- deliberately no text. The reports
    are the only place two months of history exists, and they also contain
    desk-only sections, so the safe contract is that history can say a signal
    existed and nothing more."""
    rdir = os.path.join(core_dir, "reports")
    if not os.path.isdir(rdir):
        return {}
    out = {}
    for fn in sorted(os.listdir(rdir)):
        if not fn.endswith(".md"):
            continue
        m = re.search(r"(\d{4}-\d{2}-\d{2})", fn)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
            text = open(os.path.join(rdir, fn), encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        cur = None
        per = out.setdefault(d, {})
        for line in text.splitlines():
            if line.startswith("#"):
                head = line.lstrip("#").strip().lower()
                head = re.sub(r"[·—-].*$", "", head).strip()
                if any(k in head for k in DESK_ONLY_HEADINGS):
                    cur = None
                else:
                    cur = PUBLIC_REPORT_SECTIONS.get(head)
                continue
            if not cur or not line.strip():
                continue
            _k, _l, isos = region_of(line)
            if not isos:
                continue
            for iso in isos:
                per.setdefault(iso, set()).add(cur)
    return out


def derive_signals(history, today, backfill=None):
    """Per-window, per-country signal counts, derived from the real reports.

    A country carries a signal in a category when a section item for that
    category names its region inside the window. Unweighted: the count is how
    many categories are live, nothing more. No weighting means no implicit claim
    that a death is worth n degrees.

    Coverage follows the reports, so while the briefing is Europe-weighted the
    map is too. That is a true picture of what is being watched, which is the
    honest failure mode -- the alternative is inventing values for countries
    nobody looked at."""
    backfill = backfill or {}
    out, depth = {}, {}
    for label, days in WINDOWS:
        cutoff = today - timedelta(days=days)
        per = {}
        oldest = today
        # State files first: they carry real titles, which the tooltip shows.
        for d, st in history:
            if d < cutoff:
                continue
            oldest = min(oldest, d)
            for cat, it in items_of(st):
                text = f"{it.get('title','')} {it.get('body','')} {it.get('so_what','')}"
                _key, _label, isos = region_of(text)
                if not isos:
                    continue
                for iso in isos:
                    per.setdefault(iso, {}).setdefault(cat, it.get("title", ""))
        # Then the archive, which only ever adds a category that has no entry
        # yet, and labels it generically -- history contributes counts, not prose.
        for d, isomap in backfill.items():
            if d < cutoff or d > today:
                continue
            oldest = min(oldest, d)
            for iso, cats in isomap.items():
                for cat in cats:
                    per.setdefault(iso, {}).setdefault(
                        cat, f"Reported in earlier briefings ({d.isoformat()})")
        out[label] = {iso: {"n": min(len(c), 4), "hit": c} for iso, c in per.items()}
        depth[label] = (today - oldest).days + 1
    return out, depth


def derive_rules(history):
    """Heat-at-work rules, read out of the workers sections. 2 = in force,
    1 = draft or consultation live. Anything the reports have not established is
    left unmarked rather than guessed."""
    out = {}
    for _d, st in history:
        for it in (st.get("sections") or {}).get("workers", []) or []:
            text = f"{it.get('title','')} {it.get('body','')} {it.get('status','')}"
            low = text.lower()
            _k, _l, isos = region_of(text)
            if not isos:
                continue
            lvl = 0
            if any(w in low for w in ("in force", "binding", "enforced", "ban ", "bans ",
                                      "halted", "stoppage", "limit")):
                lvl = 2
            if any(w in low for w in ("consultation", "draft", "proposed", "nprm",
                                      "under revision", "pending", "planned")):
                lvl = max(lvl, 1)
            if not lvl:
                continue
            for iso in isos:
                prev = out.get(iso)
                if not prev or lvl > prev[0]:
                    out[iso] = (lvl, it.get("title", ""))
    return out


# ---------------------------------------------------------------------------- #
def head(title,desc):
    return f"""<!doctype html><html lang="en" data-theme="light"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
<style>{TOKENS}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);
  font-family:'Space Grotesk',system-ui,sans-serif;line-height:1.55;-webkit-font-smoothing:antialiased}}
.wrap{{width:100%;max-width:1180px;margin:0 auto;padding:0 clamp(14px,3.2vw,40px) 90px}}

/* RESTYLE: accent is for DATA. Structure is ink and hairlines, so a kicker is
   muted type rather than orange -- the colour then means something when it does
   appear (a chip, a map fill, a metric). */
.card{{border-top:1px solid var(--line);padding:54px 0 0;margin-top:52px}}
.card:first-of-type{{border-top:0;margin-top:0;padding-top:36px}}
.card h2{{font-size:clamp(28px,3.3vw,40px);line-height:1.02;font-weight:700;
  letter-spacing:-.032em;margin:0 0 10px}}
.kicker{{display:block;font-family:'Space Mono',monospace;font-size:11px;font-weight:700;
  color:var(--muted);letter-spacing:.19em;text-transform:uppercase;margin-bottom:12px}}
.lede{{font-size:16px;color:var(--ink-dim);max-width:68ch;margin:0}}
h3{{letter-spacing:-.015em}}
.ico{{width:20px;height:20px;flex:none;color:var(--muted)}}
.ico-lg{{width:30px;height:30px;flex:none;color:var(--h4)}}

.chip{{display:inline-flex;align-items:center;gap:6px;font-family:'Space Mono',monospace;
  font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.09em;
  color:var(--muted);white-space:nowrap}}
.chip::before{{content:"";width:8px;height:8px;border-radius:2px;background:currentColor;flex:none}}
.chip.critical{{color:var(--critical)}} .chip.serious{{color:var(--serious)}}
.chip.warning{{color:var(--warning)}} .chip.good{{color:var(--good)}}
/* a status with no asserted band gets no colour -- the dot becomes a hairline
   marker rather than implying a severity the run never stated */
.chip:not(.critical):not(.serious):not(.warning):not(.good)::before{{
  background:none;border:1.5px solid currentColor}}

/* ---- hero, and the compressed band it becomes ---- */
.masthead{{position:relative;overflow:hidden;padding:52px 0 38px}}
.hero-txt{{position:relative;z-index:2;max-width:620px}}
.eyebrow{{font-family:'Space Mono',monospace;font-size:11px;letter-spacing:.22em;
  text-transform:uppercase;color:var(--muted);font-weight:700}}
.hero-title{{font-size:clamp(44px,6.8vw,78px);font-weight:700;letter-spacing:-.038em;
  line-height:.9;margin:13px 0 15px}}
.hero-sub{{font-size:16.5px;color:var(--ink-dim);max-width:600px;margin:0}}
.hero-meta{{font-family:'Space Mono',monospace;font-size:11.5px;color:var(--muted);margin-top:17px}}
.hero-art{{position:absolute;right:-20px;top:50%;transform:translateY(-50%);width:min(50%,520px);
  pointer-events:none;z-index:1;
  -webkit-mask-image:linear-gradient(90deg,transparent 1%,#000 38%);
  mask-image:linear-gradient(90deg,transparent 1%,#000 38%)}}
@media(max-width:920px){{.hero-art{{display:none}}}}
.cyc{{animation:cyc 14s ease-in-out infinite;opacity:0}}
@keyframes cyc{{0%,100%{{opacity:0}}50%{{opacity:.5}}}}
@media(prefers-reduced-motion:reduce){{.cyc{{animation:none;opacity:.22}}}}
:root[data-theme="dark"] .grat line,:root[data-theme="dark"] .grat ellipse{{stroke:#fff}}

/* region thumbnails: the actual coastline, so the eye finds the place before it
   reads the words. Defined once as <symbol>s and referenced, not repeated. */
.rg{{width:42px;height:31px;display:block;color:var(--h4)}}
.rg path{{fill:currentColor;fill-opacity:.62;stroke:currentColor;stroke-opacity:.62;
  stroke-linejoin:round;stroke-linecap:round}}
.rgrim{{fill:none;stroke:var(--ink);stroke-opacity:.55;stroke-width:1.1;
  vector-effect:non-scaling-stroke}}
.rgland polygon{{fill:var(--ink);fill-opacity:.42;stroke:var(--ink);stroke-opacity:.6;
  stroke-width:.6;vector-effect:non-scaling-stroke}}

/* every section ends in the same right-hand status cell, so exposure, confidence,
   maturity and flags all land on one line down the page */
.statcell{{justify-self:end;text-align:right;display:flex;flex-direction:column;
  align-items:flex-end;gap:5px;white-space:nowrap}}

/* The compressed hero: the mark, the page title and the date stay with you.
   Not just a nav bar -- the hero's identity survives the scroll. */
.topbar{{position:sticky;top:0;z-index:40;background:var(--bg);border-top:1px solid var(--line);
  border-bottom:1px solid var(--line);padding:0}}
.topinner{{width:100%;max-width:1180px;margin:0 auto;padding:0 clamp(14px,3.2vw,40px);
  display:flex;align-items:center;gap:16px;flex-wrap:wrap;min-height:56px}}
.mini{{display:flex;align-items:center;gap:9px;flex:none;white-space:nowrap}}
.brandmark{{width:22px;height:22px;flex:none}}
.mininame{{font-size:15px;font-weight:700;letter-spacing:-.022em}}

.minidate{{font-family:'Space Mono',monospace;font-size:10.5px;color:var(--muted)}}
.tabs{{display:flex;flex-wrap:wrap}}
.tab{{font-family:'Space Mono',monospace;font-size:14px;font-weight:700;text-transform:uppercase;
  letter-spacing:.07em;color:var(--ink-dim);background:none;border:0;
  border-bottom:2px solid transparent;padding:9px 3px;margin-right:20px;cursor:pointer;
  text-decoration:none;transition:color .14s;display:inline-flex;align-items:center;gap:7px}}
.tab .ico{{width:17px;height:17px;color:var(--muted);transition:color .14s}}
.tab:hover .ico,.tab[aria-current="true"] .ico{{color:var(--h4)}}
.tab:hover{{color:var(--ink)}}
.tab[aria-current="true"]{{color:var(--ink);border-bottom-color:var(--h4)}}

.spacer{{flex:1}}
.ghost{{font-family:'Space Mono',monospace;font-size:11px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);background:none;border:0;cursor:pointer;padding:6px 2px}}
.ghost:hover{{color:var(--ink)}}

/* ---- map: wider than the text column, because a 936x426 graphic needs it ---- */
.bleed{{margin-left:calc(50% - 50vw);margin-right:calc(50% - 50vw);
  padding:0 clamp(14px,3.2vw,40px)}}
.mapwrap{{margin-top:6px}}
.mapwrap svg{{width:100%;height:auto;display:block}}
.cty{{fill:var(--land);stroke:var(--land-line);stroke-width:.4;vector-effect:non-scaling-stroke;
  transition:fill .2s}}
.cty.n1{{fill:var(--h2)}} .cty.n2{{fill:var(--h3)}} .cty.n3{{fill:var(--h4)}} .cty.n4{{fill:var(--h5)}}
.cty:hover{{stroke:var(--ink);stroke-width:1.3}}
.reg{{fill:none;stroke:var(--c4);vector-effect:non-scaling-stroke;pointer-events:none}}
.reg.r2{{stroke-width:1.9}}
.reg.r1{{stroke-width:1.6;stroke-dasharray:3 2.5}}
:root[data-theme="dark"] .reg{{stroke:var(--c4)}}
.ctrlrow{{display:flex;flex-wrap:wrap;gap:16px;align-items:baseline;margin:24px 0 8px}}
.ctrllab{{font-family:'Space Mono',monospace;font-size:10px;text-transform:uppercase;
  letter-spacing:.11em;color:var(--muted)}}
.opts{{display:flex;gap:2px}}
.opt{{font-family:'Space Mono',monospace;font-size:12px;font-weight:700;letter-spacing:.05em;
  padding:6px 12px;border:0;background:none;color:var(--muted);cursor:pointer;
  border-bottom:2px solid transparent}}
.opt:hover{{color:var(--ink)}}
.opt[aria-pressed="true"]{{color:var(--ink);border-bottom-color:var(--h4)}}
/* one legend, one row, wraps instead of overflowing */
.legend{{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin:14px 0 0;
  font-family:'Space Mono',monospace;font-size:10.5px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em}}
.lg{{display:inline-flex;align-items:center;gap:6px;color:var(--ink-dim)}}
.lgd{{width:14px;height:14px;border-radius:2px;flex:none}}
.lgo{{width:16px;height:0;border-top:2px solid var(--c4);flex:none}}
.lgo.dash{{border-top-style:dashed}}
#tip{{position:fixed;z-index:70;pointer-events:none;opacity:0;transition:opacity .1s;
  background:var(--bg);border:1px solid var(--line-2);border-radius:6px;padding:10px 12px;
  font-size:12.5px;max-width:290px;box-shadow:0 6px 20px rgba(0,0,0,.13)}}
#tip b{{display:block;font-size:13.5px;margin-bottom:6px}}
#tip .sig{{display:flex;gap:7px;align-items:flex-start;padding:3px 0;font-size:12px;
  color:var(--ink-dim)}}
#tip .sig svg{{width:15px;height:15px;flex:none;margin-top:2px;color:var(--muted)}}
#tip .rul{{margin-top:7px;padding-top:7px;border-top:1px solid var(--line);font-size:11.5px;
  color:var(--c3)}}
#tip .none{{color:var(--muted);font-size:12px}}
table.tv{{width:100%;border-collapse:collapse;font-size:13px;margin-top:12px}}
table.tv th,table.tv td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line)}}
table.tv th{{font-family:'Space Mono',monospace;font-size:10px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted)}}
table.tv td.n{{font-family:'Space Mono',monospace}}
summary{{cursor:pointer}}

/* ---- headlines ---- */
.geo{{font-family:'Space Mono',monospace;font-size:11px;text-transform:uppercase;
  letter-spacing:.14em;color:var(--ink);font-weight:700;margin:34px 0 0;
  padding-bottom:7px;border-bottom:1px solid var(--line-2)}}
.hl{{display:grid;grid-template-columns:var(--gut) 1fr auto;gap:16px;border-top:1px solid var(--line);
  padding:16px 0}}
.hl:first-of-type{{border-top:0}}
.geo + .hl{{border-top:0}}
.hlico{{color:var(--h4);margin-top:2px}}
.hlhead{{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap}}
.hlhead h3{{font-size:17px;margin:0;font-weight:600;flex:1;min-width:230px}}
.hl p{{margin:6px 0 0;font-size:14px;color:var(--ink-dim);max-width:78ch}}
.tlab{{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);display:inline-flex;align-items:center;gap:5px}}
.tlab .ico{{width:14px;height:14px}}
/* a source on every entry, not only every section: a headline with no
   attribution is just an assertion, and this page is meant to be checkable */
/* '.hl p' is (0,1,1) and '.hlsrc' was (0,1,0), so the source line inherited the
   14px body size -- and mono at 14px looks larger than sans at 14px. Qualified
   so it wins. */
.hl p.hlsrc,.srcline{{font-family:'Space Mono',monospace;font-size:9px;
  color:var(--muted);margin:6px 0 0;letter-spacing:.04em;line-height:1.5}}

/* ---- detail page: content + metadata rail ---- */
/* sources sit with the section they belong to; method and disclosure go to the
   foot of the page. A panel of metadata pinned beside the reading column was not
   earning its place on screen. */
.srcline{{margin-top:16px;padding-top:11px;border-top:1px solid var(--line)}}
.pagefoot{{border-top:1px solid var(--line-2);margin-top:56px;padding-top:26px;
  display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:30px}}
.pagefoot h4{{font-family:'Space Mono',monospace;font-size:10px;letter-spacing:.13em;
  text-transform:uppercase;color:var(--muted);margin:0 0 8px;font-weight:700}}
/* Footer copy is apparatus -- method, cadence, limits, disclosure -- not body
   text. Setting it in the muted tone alongside the source lines means a reader
   can tell at a glance what is reporting and what is small print. */
.pagefoot p{{margin:0;font-size:12.5px;color:var(--muted);line-height:1.7}}

/* ---- metrics ---- */
.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));
  gap:1px;background:var(--line);margin-top:24px}}
.metric{{background:var(--bg);padding:17px 19px 16px}}
.metric .mv{{font-size:38px;font-weight:700;letter-spacing:-.035em;line-height:1;color:var(--h4)}}
.metric .mk{{font-size:13.5px;color:var(--ink-dim);margin-top:6px}}
.metric .ms{{font-family:'Space Mono',monospace;font-size:9.5px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.07em;margin-top:9px}}

/* ---- forecast ---- */
.fr{{display:grid;grid-template-columns:var(--gut) 1fr auto;gap:16px;align-items:start;
  border-top:1px solid var(--line);padding:15px 0}}
@media(max-width:640px){{.fr{{grid-template-columns:1fr}}}}
.fw{{font-family:'Space Mono',monospace;font-size:10.5px;text-transform:uppercase;
  letter-spacing:.1em;color:var(--muted);font-weight:700;margin-bottom:3px}}
.fr h4{{margin:0 0 4px;font-size:16.5px;font-weight:600}}
.fr p{{margin:0;font-size:13.5px;color:var(--ink-dim)}}

/* ---- subsegments ---- */
.sub{{display:grid;grid-template-columns:var(--gut) 1fr auto;gap:16px;border-top:1px solid var(--line);
  padding:21px 0}}
.subhead{{display:flex;align-items:baseline;gap:13px;flex-wrap:wrap}}
.subhead h3{{font-size:19px;margin:0;font-weight:600}}
.expo{{display:inline-flex;gap:3px;align-items:center}}
.expo i{{width:9px;height:9px;border-radius:2px;background:var(--line-2);display:block}}
.expo i.on{{background:var(--h4)}}
.sub p{{font-size:14.5px;color:var(--ink-dim);margin:9px 0 0;max-width:80ch}}
.sub ul{{margin:9px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-dim)}}

/* ---- solutions ---- */
.soln{{display:grid;grid-template-columns:var(--gut) 1fr auto;gap:16px;border-top:1px solid var(--line);
  padding:23px 0}}
@media(max-width:700px){{.soln,.sub,.hl,.fr{{grid-template-columns:var(--gut) 1fr}}
  .statcell{{grid-column:2;align-items:flex-start;text-align:left;margin-top:8px}}}}
.solnhead{{display:flex;align-items:baseline;gap:11px;flex-wrap:wrap;margin-bottom:3px}}
.solnhead h3{{margin:0;font-size:18.5px;font-weight:600}}
.mat{{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted)}}
.mat.commercial{{color:var(--good)}} .mat.pilot{{color:var(--warning)}}
.pc{{display:grid;grid-template-columns:repeat(3,1fr);gap:24px;margin-top:14px}}
@media(max-width:820px){{.pc{{grid-template-columns:1fr}}}}
.pc h5{{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.1em;margin:0 0 6px;color:var(--muted);font-weight:700}}
.pc ul{{margin:0;padding-left:15px;font-size:13.5px;color:var(--ink-dim)}}
.pc li{{margin:3px 0}}
.pc .pro h5{{color:var(--good)}} .pc .con h5{{color:var(--serious)}} .pc .app h5{{color:var(--c3)}}
.note{{font-family:'Space Mono',monospace;font-size:11px;color:var(--muted);margin-top:24px;
  border-top:1px solid var(--line);padding-top:14px;line-height:1.75}}
</style></head><body>
"""




def brandmark():
    return globe.icon(22)


NAV_ICON = {"index": "globe", "climate": "thermo", "health": "pulse",
            "workers": "hardhat", "fire": "flame", "solutions": "shade"}


def nav_items(state):
    """Only pages the state can actually fill. A tab leading to an empty page is
    worse than a missing tab."""
    secs = (state.get("sections") or {})
    out = [("index", "Overview")]
    for slug, label, _title, key in SECTORS:
        if secs.get(key):
            out.append((slug, label))
    out.append(("solutions", "Solutions"))
    return out


def topbar(active, page_title, nav):
    tabs = "".join(
        f'<a class="tab" href="{"index.html" if slug == "index" else slug + ".html"}"'
        + (' aria-current="true"' if slug == active else '')
        + f'>{icon(NAV_ICON.get(slug, "thermo"), "ico")}{esc(label)}</a>'
        for slug, label in nav)
    # No page title in the bar, on purpose. It varied in length per page, which put
    # the tabs at a different x on every page -- and the active tab already says
    # where you are, in bold with an underline. page_title is still an argument
    # because <title> and the hero use it.
    # Deliberately NOT inside .wrap: a sticky element can only stick within its
    # parent's box, and .wrap is the bar's height plus 90px of padding -- so it
    # unstuck two scroll-lines in.
    return (f'<nav class="topbar" id="topbar"><div class="topinner">'
            f'<span class="mini">{brandmark()}<span class="mininame">HeatWatch</span></span>'
            f'<span class="tabs">{tabs}</span><span class="spacer"></span>'
            f'<button class="ghost" onclick="tog()">Theme</button></div></nav>')


def hero(title, sub, kicker, dl):
    return f"""<div class="wrap"><header class="masthead">{globe.build(lon0=20.0, r=148.0, cx=310.0, cy=160.0)}
<div class="hero-txt"><div class="eyebrow">{esc(kicker)}</div>
<h1 class="hero-title">{esc(title)}</h1>
<p class="hero-sub">{esc(sub)}</p>
<div class="hero-meta">Updated {esc(dl)} · rebuilt daily from primary sources</div>
</div></header></div>"""


def region_symbols(used):
    """One <symbol> per region referenced. Each is padded to the thumbnail's own
    aspect before fitting, so a compact region and a wide one occupy the same
    area -- without it, preserveAspectRatio letterboxed Europe down to a sliver
    while Gulf filled its box."""
    W = json.load(open(WORLD))["countries"]
    out = []
    for keys, key, label, isos in REGION_DEFS:
        if key not in used:
            continue
        if isos is None:
            land = globe.land_paths(lon0=20.0, r=17.0, cx=27.2, cy=20.0)
            out.append(f'<symbol id="rg-{key}" viewBox="0 0 54.3 40">'
                       f'<circle class="rgrim" cx="27.2" cy="20" r="17"/>'
                       f'<g class="rgland">{land}</g></symbol>')
            continue
        ds, xs, ys = [], [], []
        for iso in isos:
            rec = W.get(iso)
            if not rec:
                continue
            d = rec.get("d") if isinstance(rec, dict) else rec
            ds.append(d)
            nums = [float(v) for v in NUMRE.findall(d)]
            xs += nums[0::2]; ys += nums[1::2]
        if not ds:
            continue
        ASPECT = 42 / 31
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
        if w / h < ASPECT:
            need = h * ASPECT; c = (x0 + x1) / 2; x0, x1 = c - need / 2, c + need / 2; w = need
        else:
            need = w / ASPECT; c = (y0 + y1) / 2; y0, y1 = c - need / 2, c + need / 2; h = need
        m = 0.06 * max(w, h)
        # Fitting alone was not the fix. Every symbol already filled its box --
        # measured: all aspects 1.306-1.307 -- but Europe is 16 fragments at 61%
        # ink coverage while Gulf is a handful of fat blobs at 121%, so Europe
        # read as confetti and Gulf as a landmass. A stroke in USER units (so it
        # scales with the viewBox) dilates each country until neighbours fuse
        # into one silhouette, which is what makes a region recognisable at 42px.
        sw = 0.024 * max(w, h)
        out.append(f'<symbol id="rg-{key}" viewBox="{x0-m:.1f} {y0-m:.1f} {w+2*m:.1f} {h+2*m:.1f}">'
                   + "".join(f'<path d="{d}" stroke-width="{sw:.2f}"/>' for d in ds)
                   + "</symbol>")
    return ('<svg width="0" height="0" aria-hidden="true" style="position:absolute">'
            f'<defs>{"".join(out)}</defs></svg>')


def region_thumb(key):
    return f'<svg class="rg" aria-hidden="true"><use href="#rg-{key}"/></svg>'


def build_map_paths():
    W = json.load(open(WORLD))["countries"]
    paths = []
    for iso, rec in W.items():
        d = rec.get("d") if isinstance(rec, dict) else rec
        if d:
            paths.append(f'<path class="cty" data-iso="{iso}" d="{d}"/>')
    return json.load(open(WORLD))["viewBox"], "".join(paths)


def rule_overlay(rules):
    W = json.load(open(WORLD))["countries"]
    out = []
    for iso, (lvl, _note) in rules.items():
        rec = W.get(iso)
        if not rec:
            continue
        d = rec.get("d") if isinstance(rec, dict) else rec
        out.append(f'<path class="reg r{lvl}" d="{d}"/>')
    return "".join(out)


def legend_html():
    fills = "".join(f'<span class="lg"><span class="lgd" style="background:var(--h{i+1})"></span>'
                    f'{esc(COUNTLAB[i])}</span>' for i in range(1, 5))
    return (f'<div class="legend"><span>Signals in window</span>{fills}'
            f'<span class="lg"><span class="lgd" style="background:var(--land)"></span>None</span>'
            f'<span class="lg"><span class="lgo"></span>Heat-at-work rules in force</span>'
            f'<span class="lg"><span class="lgo dash"></span>Draft / consultation</span></div>')


def table_view(sig, rules, names):
    rows = sorted(sig.get("1M", {}).items(), key=lambda kv: (-kv[1]["n"], kv[0]))[:14]
    tr = ""
    for iso, rec in rows:
        cats = ", ".join(CATS[c][0] for c in CATS if c in rec["hit"])
        r = rules.get(iso)
        tr += (f'<tr><td class="n">{esc(names.get(iso, iso))}</td><td class="n">{rec["n"]}</td>'
               f'<td>{esc(cats)}</td>'
               f'<td>{esc("In force" if r and r[0] == 2 else "Draft" if r else "—")}</td></tr>')
    if not tr:
        return ""
    return (f'<details><summary class="ctrllab" style="margin-top:14px">Table view — '
            f'top {len(rows)} by signal count, 1M window (the non-colour route to the same '
            f'data)</summary><table class="tv"><thead><tr><th>Country</th><th>Signals</th>'
            f'<th>Categories</th><th>Rules</th></tr></thead><tbody>{tr}</tbody></table></details>')


def src_line(it):
    srcs = it.get("sources") or []
    if not srcs:
        return ""
    return f'<p class="hlsrc">Sources — {esc(" · ".join(str(s) for s in srcs))}</p>'


def band_of(it):
    """No band means no severity claim. Defaulting to "warning" painted a colour
    the run never asserted -- this state has band=null on every section item."""
    b = (it.get("band") or "").lower()
    return b if b in ("critical", "serious", "warning", "good") else ""


def entry(it, cat, thumb_key=None):
    label, ik = CATS[cat]
    lead = region_thumb(thumb_key) if thumb_key else f'<span class="hlico">{icon(ik, "ico ico-lg")}</span>'
    body = it.get("body") or ""
    so = it.get("so_what")
    # The right-hand cell carries STATUS, never the category. It used to fall back
    # to the category label, which is already the topic label two columns left --
    # so every item without a status printed "Heat & climate" twice on one row.
    status = it.get("status") or it.get("flag") or ""
    band = band_of(it)
    chip = (f'<span class="chip{" " + band if band else ""}">{esc(status)}</span>'
            if status else (f'<span class="chip {band}">{esc(band)}</span>' if band else ""))
    gap = it.get("gap")
    extra = f'<p class="hlsrc">Gap — {esc(gap)}</p>' if gap else ""
    return (f'<div class="hl">{lead}<div>'
            f'<div class="hlhead"><h3>{esc(it.get("title", "Untitled"))}</h3>'
            f'<span class="tlab">{icon(ik, "ico")}{esc(label)}</span></div>'
            f'<p>{esc(body)}</p>'
            + (f'<p><b>So what:</b> {esc(so)}</p>' if so else "")
            + src_line(it) + extra
            + f'</div><span class="statcell">{chip}</span></div>')


def home_headlines(state):
    """Grouped by region, in the long form, from the sections -- which carry real
    `sources`. status_grid has no sources field, so building this from the grid
    would mean inventing attributions, and an invented source is worse than none."""
    groups, used = OrderedDict(), set()
    for cat, it in items_of(state):
        text = f"{it.get('title','')} {it.get('body','')} {it.get('so_what','')}"
        key, label, _isos = region_of(text)
        used.add(key)
        groups.setdefault((key, label), []).append((cat, it))
    out = []
    for (key, label), rows in groups.items():
        out.append(f'<div class="geo">{esc(label)}</div>')
        for cat, it in rows:
            out.append(entry(it, cat, thumb_key=key))
    return region_symbols(used) + "".join(out)


def metrics_html(state):
    hl = state.get("headline") or {}
    cells = []
    if hl.get("value"):
        cells.append(f'<div class="metric"><div class="mv">{esc(hl["value"])}'
                     f'{(" " + esc(hl["unit"])) if hl.get("unit") else ""}</div>'
                     f'<div class="mk">{esc(hl.get("label", ""))}</div>'
                     f'<div class="ms">{esc(hl.get("source", ""))}</div></div>')
    for t in state.get("tiles") or []:
        cells.append(f'<div class="metric"><div class="mv">{esc(t.get("value", ""))}'
                     f'{(" " + esc(t["unit"])) if t.get("unit") else ""}</div>'
                     f'<div class="mk">{esc(t.get("label", ""))}</div>'
                     f'<div class="ms">{esc(t.get("sub", ""))}</div></div>')
    return f'<div class="metrics">{"".join(cells)}</div>' if cells else ""


def forecast_html(state):
    cd = state.get("countdown") or {}
    rows = []
    for lab, dl in (("label", "deadline"), ("second_label", "second_deadline")):
        if cd.get(lab) and cd.get(dl):
            try:
                when = date.fromisoformat(cd[dl]).strftime("%-d %b %Y")
            except Exception:
                when = cd[dl]
            rows.append(f'<div class="fr">{icon("clock", "ico ico-lg")}'
                        f'<div><div class="fw">{esc(when)}</div>'
                        f'<h4>{esc(cd[lab])}</h4>'
                        f'<p>{esc(cd.get("note", ""))}</p></div>'
                        f'<span class="statcell"><span class="chip serious">dated</span>'
                        f'</span></div>')
    return f'<div class="fc">{"".join(rows)}</div>' if rows else ""


def occupations_html(key):
    rows = OCCUPATIONS.get(key)
    if not rows:
        return ""
    return "".join(
        f'<div class="sub"><span class="hlico">{icon(ik, "ico ico-lg")}</span><div>'
        f'<div class="subhead"><h3>{esc(nm)}</h3></div><p>{esc(body)}</p><ul>'
        + "".join(f"<li>{esc(x)}</li>" for x in bl)
        + f'</ul></div><span class="statcell"><span class="expo">'
        + "".join(f'<i class="{"on" if i < e else ""}"></i>' for i in range(5))
        + f'</span><span class="tlab">Exposure {e}/5</span></span></div>'
        for nm, ik, e, body, bl in rows)


def footer(state):
    m = state.get("method") or {}
    parts = []
    for h, k in (("Method", "sourcing"), ("Cadence", "cadence"),
                 ("Limits", "limits"), ("Disclosure", "disclosure")):
        if m.get(k):
            parts.append(f'<div><h4>{h}</h4><p>{esc(m[k])}</p></div>')
    return f'<footer class="pagefoot">{"".join(parts)}</footer>' if parts else ""


JS_COMMON = """
function tog(){var r=document.documentElement;
 r.dataset.theme=r.dataset.theme==='dark'?'light':'dark';}
(function(){var b=document.getElementById('topbar');if(!b)return;
 var t=b.offsetTop;
 function f(){b.classList.toggle('compact',window.scrollY>t-1);}
 addEventListener('scroll',f,{passive:true});f();})();
"""

JS_MAP = """
var SIG=__SIG__,RULES=__RULES__,NAMES=__NAMES__,CATS=__CATS__,ICONS=__ICONS__,DEPTH=__DEPTH__;
var TF=__DEFAULT_TF__;
function paint(){
 var m=SIG[TF]||{};
 document.querySelectorAll('.cty').forEach(function(p){
  p.className.baseVal='cty';
  var r=m[p.dataset.iso];
  if(r)p.classList.add('n'+r.n);});
 document.querySelectorAll('[data-tf]').forEach(function(b){
  b.setAttribute('aria-pressed',b.dataset.tf===TF?'true':'false');});
 var n=document.getElementById('tfnote');
 if(n){var k=Object.keys(m).length,tot=0;
  for(var i in m)tot+=m[i].n;
  n.textContent=k+' countries · '+tot+' signals · '+(DEPTH[TF]||0)+' days of reports in this window';}
}
function setTF(t){TF=t;paint();}
var tip=document.getElementById('tip');
function svgFor(k){return '<svg viewBox="0 0 40 40" fill="none" stroke="currentColor" '+
 'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+ICONS[k]+'</svg>';}
function show(e,iso){if(!tip)return;
 var r=(SIG[TF]||{})[iso],h='<b>'+(NAMES[iso]||iso)+'</b>';
 if(r){for(var c in CATS){ if(r.hit[c])
   h+='<div class="sig">'+svgFor(CATS[c][1])+'<span>'+r.hit[c]+'</span></div>';}
 } else { h+='<div class="none">No signal in this window</div>'; }
 var g=RULES[iso];
 if(g)h+='<div class="rul">'+(g[0]===2?'Rules in force: ':'Draft: ')+g[1]+'</div>';
 tip.innerHTML=h;tip.style.opacity=1;
 var x=e.clientX+14,y=e.clientY+14;
 if(x+300>innerWidth)x=e.clientX-300;
 if(y+170>innerHeight)y=Math.max(8,e.clientY-170);
 tip.style.left=x+'px';tip.style.top=y+'px';}
document.addEventListener('mouseover',function(e){
 var p=e.target.closest('.cty');if(p)show(e,p.dataset.iso);});
document.addEventListener('mousemove',function(e){
 var p=e.target.closest('.cty');if(p)show(e,p.dataset.iso);});
document.addEventListener('mouseout',function(e){
 if(e.target.closest('.cty')&&tip)tip.style.opacity=0;});
paint();
"""

NAMES = {
 "AUS": "Australia", "BRA": "Brazil", "ARG": "Argentina", "ZAF": "South Africa",
 "IND": "India", "PAK": "Pakistan", "SAU": "Saudi Arabia", "ARE": "UAE", "OMN": "Oman",
 "QAT": "Qatar", "ESP": "Spain", "PRT": "Portugal", "GBR": "United Kingdom",
 "FRA": "France", "ITA": "Italy", "GRC": "Greece", "MAR": "Morocco", "DZA": "Algeria",
 "TUN": "Tunisia", "USA": "United States", "MEX": "Mexico", "NER": "Niger", "MLI": "Mali",
 "TCD": "Chad", "SDN": "Sudan", "IRQ": "Iraq", "IRN": "Iran", "KWT": "Kuwait",
 "CHN": "China", "JPN": "Japan", "KOR": "South Korea", "DEU": "Germany", "POL": "Poland",
 "HUN": "Hungary", "ROU": "Romania", "TUR": "Türkiye", "EGY": "Egypt", "LBY": "Libya",
 "NGA": "Nigeria", "ETH": "Ethiopia", "SOM": "Somalia", "KEN": "Kenya", "VNM": "Vietnam",
 "THA": "Thailand", "PHL": "Philippines", "IDN": "Indonesia", "NPL": "Nepal",
 "BGD": "Bangladesh", "LKA": "Sri Lanka", "CAN": "Canada", "RUS": "Russia",
 "KAZ": "Kazakhstan", "COL": "Colombia", "PER": "Peru", "CHL": "Chile", "PRY": "Paraguay",
 "BOL": "Bolivia", "NAM": "Namibia", "BWA": "Botswana", "ZWE": "Zimbabwe",
 "MOZ": "Mozambique", "CYP": "Cyprus", "BEL": "Belgium", "NLD": "Netherlands",
 "IRL": "Ireland", "UKR": "Ukraine", "FIN": "Finland", "NOR": "Norway", "SWE": "Sweden",
 "DNK": "Denmark", "SYR": "Syria", "JOR": "Jordan", "YEM": "Yemen", "AGO": "Angola",
 "COD": "DR Congo", "NZL": "New Zealand",
}

DESC = ("Where heat is breaking records, who it is reaching, what the rules are about "
        "to require, and what can be done about it. Rebuilt daily from primary sources.")


def page_home(state, sig, depth, rules, nav, dl):
    vb, paths = build_map_paths()
    offered = [w for w, days in WINDOWS
               if depth.get(w, 0) >= days * WINDOW_MIN_COVERAGE]
    if not offered:
        offered = [WINDOWS[0][0]]
    default = "1M" if "1M" in offered else offered[-1]
    wins = "".join(
        f'<button class="opt" data-tf="{w}" onclick="setTF(\'{w}\')"'
        + (' aria-pressed="true"' if w == default else '') + f'>{w}</button>'
        for w in offered)
    js = (JS_MAP.replace("__SIG__", json.dumps(sig))
                .replace("__RULES__", json.dumps(rules))
                .replace("__NAMES__", json.dumps(NAMES))
                .replace("__CATS__", json.dumps({k: list(v) for k, v in CATS.items()}))
                .replace("__ICONS__", json.dumps(ICONS))
                .replace("__DEPTH__", json.dumps(depth))
                .replace("__DEFAULT_TF__", json.dumps(default)))
    return head("HeatWatch — global heat intelligence", DESC) + f"""
{hero("HeatWatch", DESC, "Global heat intelligence", dl)}
{topbar("index", "", nav)}
<div class="wrap">
<section class="card">
  <span class="kicker">Signal density by country</span>
  <h2>Global heat signals</h2>
  <p class="lede">Shading is how many signals a country carries in the window — heat,
  health, workers, fire — counted flat, with no weighting. Outlined countries have
  heat-at-work rules, which is the mitigation rather than the hazard, so it is drawn
  separately. Hover any country for the detail.</p>
  <div class="ctrlrow">
    <span class="ctrllab">Window</span>
    <div class="opts">{wins}</div>
    <span class="ctrllab" id="tfnote"></span>
  </div>
  <div class="bleed"><div class="mapwrap"><svg viewBox="{vb}" role="img"
    aria-label="World map shaded by the number of heat-related signals per country">
    <g>{paths}</g><g>{rule_overlay(rules)}</g></svg></div>{legend_html()}</div>
  {table_view(sig, rules, NAMES)}
  <p class="srcline">Derived from the dated briefings behind this site, so coverage
  follows what has been reported rather than the whole world. Every underlying claim
  is sourced in the entry below it.</p>
</section>

<section class="card">
  <span class="kicker">Key numbers</span>
  <h2>Today</h2>
  {metrics_html(state)}
</section>

<section class="card">
  <span class="kicker">In full</span>
  <h2>Headlines by region</h2>
  <p class="lede">The long-form read of the map, grouped by geography and marked by topic.</p>
  {home_headlines(state)}
</section>
{('<section class="card"><span class="kicker">Dated, from primary sources</span>'
  '<h2>Upcoming deadlines</h2>' + forecast_html(state) + '</section>') if forecast_html(state) else ''}
{footer(state)}
</div>
<div id="tip"></div>
<script>{JS_COMMON}{js}</script></body></html>"""


def page_sector(state, slug, title, key, nav, dl):
    items = (state.get("sections") or {}).get(key) or []
    hls = "".join(entry(it, SECTION_CAT[key]) for it in items)
    occ = occupations_html(key)
    fc = forecast_html(state) if key == "workers" else ""
    lede = {
        "extremes": "Records, anomalies and the operational read on each one.",
        "workers":  "Who is exposed, where, and what the rules are about to require. Heat "
                    "is an occupational hazard before it is a climate statistic.",
        "fire":     "Fire weather and burned area, and what it means for the people sent "
                    "to work in it.",
        "health":   "Excess mortality and heat-attributable illness, with the surveillance "
                    "gaps stated rather than smoothed over.",
    }.get(key, "")
    return head(f"HeatWatch — {title}", DESC) + f"""
{hero(title, lede, "Sector detail", dl)}
{topbar(slug, title, nav)}
<div class="wrap">
{('<section class="card"><span class="kicker">Key numbers</span><h2>The numbers</h2>'
  + metrics_html(state) + '</section>') if metrics_html(state) else ''}
<section class="card">
  <span class="kicker">Current</span>
  <h2>Headlines — {esc(title.split(" ")[0].lower())}</h2>
  <p class="lede">Only this topic. The other sectors carry their own.</p>
  {hls}
</section>
{('<section class="card"><span class="kicker">Dated, from primary sources</span>'
  '<h2>Upcoming deadlines</h2>'
  '<p class="lede">Each one dated, so a slipped deadline stays visible rather than '
  'quietly forgotten.</p>' + fc + '</section>') if fc else ''}
{('<section class="card"><span class="kicker">Where the exposure sits</span>'
  '<h2>By occupation</h2><p class="lede">Each group faces a different version of the '
  'same hazard, so each needs a different control. Exposure is a judgement, not a '
  'measurement.</p>' + occ + '</section>') if occ else ''}
{footer(state)}
</div>
<div id="tip"></div>
<script>{JS_COMMON}</script></body></html>"""


def page_solutions(state, nav, dl):
    sol = "".join(
        f'<div class="soln">{icon(g, "ico ico-lg")}<div>'
        f'<div class="solnhead"><h3>{esc(t)}</h3><span class="tlab">{esc(k)}</span></div>'
        f'<p class="lede" style="font-size:14.5px">{esc(d)}</p><div class="pc">'
        f'<div class="pro"><h5>Works because</h5><ul>'
        + "".join(f"<li>{esc(x)}</li>" for x in pr)
        + f'</ul></div><div class="con"><h5>Limits</h5><ul>'
        + "".join(f"<li>{esc(x)}</li>" for x in li)
        + f'</ul></div><div class="app"><h5>Current applications</h5><ul>'
        + "".join(f"<li>{esc(x)}</li>" for x in ap)
        + f'</ul></div></div></div>'
          f'<span class="statcell"><span class="mat {m}">{MATURITY[m]}</span></span></div>'
        for g, t, k, m, d, pr, li, ap in SOLUTIONS)
    disc = ((state.get("method") or {}).get("disclosure") or "")
    return head("HeatWatch — industry solutions", DESC) + f"""
{hero("Industry solutions",
      "What already exists to keep people working safely in heat, where each approach "
      "stops working, and where it is in use today.", "What can be done", dl)}
{topbar("solutions", "Industry solutions", nav)}
<div class="wrap">
<section class="card">
  <span class="kicker">By approach</span>
  <h2>Ways to stay cool at work</h2>
  <p class="lede">Grouped by approach, not by vendor — no products, no ranking, no
  league table. Maturity is lab → pilot → commercial.</p>
  {sol}
  <p class="note">Every approach here has a real limit and it is stated, including the
  category HeatWatch's publisher sells into.<br>{esc(disc)}</p>
</section>
{footer(state)}
</div>
<div id="tip"></div>
<script>{JS_COMMON}</script></body></html>"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    state_path, out_dir = sys.argv[1], sys.argv[2]
    state = json.load(open(state_path))
    os.makedirs(out_dir, exist_ok=True)

    today = date.fromisoformat(state["meta"]["report_date"])
    dl = today.strftime("%-d %B %Y")
    history = load_history(state_path)
    core_dir = os.path.dirname(os.path.dirname(os.path.abspath(state_path)))
    backfill = backfill_from_reports(core_dir)
    sig, depth = derive_signals(history, today, backfill)
    rules = derive_rules(history)
    nav = nav_items(state)

    pages = {"index.html": page_home(state, sig, depth, rules, nav, dl)}
    for slug, _label, title, key in SECTORS:
        if (state.get("sections") or {}).get(key):
            pages[f"{slug}.html"] = page_sector(state, slug, title, key, nav, dl)
    pages["solutions.html"] = page_solutions(state, nav, dl)

    for fn, html in pages.items():
        leftover = [w for w in html.split() if w.startswith("__") and w.endswith("__")]
        if leftover:
            raise SystemExit(f"{fn}: unsubstituted placeholders: {leftover[:5]}")
        with open(os.path.join(out_dir, fn), "w") as fh:
            fh.write(html)
        print(f"wrote {fn} — {len(html):,} bytes")
    print(f"report_date {state['meta']['report_date']} · {len(history)} state files · "
          f"{len(sig.get('1M', {}))} countries in the 1M window")


if __name__ == "__main__":
    main()
