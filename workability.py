#!/usr/bin/env python3
"""The Workability page: working hours too hot for outdoor work, against the rule
that applies there.

Three things the page puts together, which is the only reason it is worth
building: occupational heat stress computed properly (wbgt.py, ISO 7243), a
structured rules database with dated sources, and an archive of each day as it
was known that morning.

Everything is computed at build time. The only client-side work is switching
between precomputed states, filtering rows and selecting a hub -- no framework,
no fetch, same as the map on the Updates page.

The hard rule this file exists to enforce: a computed WBGT is never presented as
an official status. The hours come from the forecast; the rule status comes from a
rule record with a source and a date, and the two are printed in separate columns
because they answer different questions. A record that has not been confirmed
against a primary source cannot read "In force" -- it reads as unconfirmed and it
counts as an unprotected hour, which is the side to err on.
"""
import hashlib
import json
import os
import re
from datetime import date, datetime, timedelta

import wbgt

HERE = os.path.dirname(os.path.abspath(__file__))

REGIONS = [("all", "All"), ("italy", "Italy"), ("europe", "Europe"), ("gulf", "Gulf"),
           ("americas", "Americas"), ("apac", "Asia-Pacific")]

# Heat ramp bands for the day cells, in hours above the limit. Six bands over a
# 14-hour working day, matching the site's five-step ramp plus "none".
BANDS = [(0, 0, "b0", "0"), (1, 2, "b1", "1-2"), (3, 4, "b2", "3-4"),
         (5, 6, "b3", "5-6"), (7, 8, "b4", "7-8"), (9, 99, "b5", "9+")]

COVER_LABEL = {"covered": "Covered", "partial": "Partial", "gap": "No rule in force"}
COVER_BAND = {"covered": "good", "partial": "warning", "gap": "critical"}

# What the status line says when no rule record volunteered a reason. "gap" with
# no reason used to print "A rule in force covers these hours." next to a chip
# reading "No rule in force", which is the one thing the page must never do.
DEFAULT_REASON = {"covered": "A rule in force covers these hours.",
                  "partial": "Cover is partial.",
                  "gap": "No binding rule covers these hours."}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def band_for(hours):
    for lo, hi, cls, lab in BANDS:
        if lo <= hours <= hi:
            return cls
    return "b5"


def combo_key(workload, setting, acclimatised):
    return f"{workload}-{setting}-{'acc' if acclimatised else 'new'}"


COMBOS = [(w, s, a) for w, _ in wbgt.WORKLOADS for s, _ in wbgt.SETTINGS for a, _ in wbgt.ACCLIM]


# ---------------------------------------------------------------------------- #
# Loading

def load_hubs(core_dir):
    path = os.path.join(core_dir, "hubs.json")
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8"))["hubs"]


def load_rules(core_dir):
    """Every rule record, by id. The directory is the source of truth: adding a
    record is adding a file, which is what makes the review step in B9 a diff."""
    rdir = os.path.join(core_dir, "rules")
    out = {}
    if not os.path.isdir(rdir):
        return out
    for fn in sorted(os.listdir(rdir)):
        if not fn.endswith(".json"):
            continue
        r = json.load(open(os.path.join(rdir, fn), encoding="utf-8"))
        out[r["id"]] = r
    return out


def load_forecast(core_dir, when):
    """The stored forecast for a date, or None. The build must not fetch: a page
    that silently reaches the network cannot be rebuilt from the archive."""
    path = os.path.join(core_dir, "state", "forecast", f"heatwatch_forecast_{when}.json")
    if not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8"))


# ---------------------------------------------------------------------------- #
# Rule reasoning

def is_confirmed(rule):
    """A record may only assert a rule is in force when it is sourced AND at
    least one of its sources is primary. Both halves matter: "sourced" without a
    primary source is a summary of somebody else's summary, which is how the
    wrong ban hours end up on a public page."""
    return (rule.get("confidence") == "sourced"
            and any((s or {}).get("type") == "primary" for s in rule.get("sources") or []))


def season_active(rule, today):
    """Is the rule's season open on this date? A recurring season is compared on
    month-day so it survives the year rolling over."""
    season = rule.get("season")
    if not season:
        return True
    start, end = season.get("start"), season.get("end")
    if not start or not end:
        return True
    md = (today.month, today.day)
    s = tuple(int(x) for x in start.split("-")[-2:])
    e = tuple(int(x) for x in end.split("-")[-2:])
    if s <= e:
        return s <= md <= e
    return md >= s or md <= e            # a season that crosses the new year


def season_label(rule):
    season = rule.get("season") or {}
    if not season.get("start"):
        return ""
    months = ["", "January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]

    def fmt(md):
        m, d = (int(x) for x in md.split("-")[-2:])
        return f"{d} {months[m]}"
    return f"{fmt(season['start'])} to {fmt(season['end'])}"


def wbgt_trigger(rule):
    """The lowest WBGT value the rule triggers on, or None."""
    vals = [t.get("value") for t in rule.get("thresholds") or []
            if t.get("metric") == "wbgt" and isinstance(t.get("value"), (int, float))]
    return min(vals) if vals else None


def coverage(hub, rules, today, limit):
    """Does a rule cover the hours this forecast says are too hot?

    Deliberately not stored: coverage is a function of the rule, the date and the
    selected workload, so storing it would mean storing 12 answers per hub per day
    and keeping them in step with the records. Computed, it cannot drift.

    Precedence is worst-case: a hub is only "covered" when something actually
    bites on these conditions today. Everything softer lands in partial, and the
    reason is carried through to the page so the chip is never the whole story."""
    best, reasons = "gap", []
    for rid in hub.get("rule_ids") or []:
        rule = rules.get(rid)
        if not rule:
            continue
        status = rule.get("status")
        trigger = rule.get("trigger_type")
        confirmed = is_confirmed(rule)
        title = rule.get("title", rid)

        # Nothing in force: a consultation or a draft never covers an hour. This
        # is the A2 bug in one line -- an EU-level consultation item used to tag
        # member states as having a rule in force.
        if status in ("draft", "consultation", "none", "expired"):
            if status == "expired":
                reasons.append(f"Season closed {season_label(rule).split(' to ')[-1]}"
                               if rule.get("season") else f"{title} has expired")
            elif status in ("draft", "consultation"):
                reasons.append(f"{title} is not in force")
            else:
                reasons.append(f"{title}: no binding rule")
            continue

        if status == "in_force_seasonal_inactive" or (
                status == "in_force" and rule.get("season") and not season_active(rule, today)):
            end = season_label(rule).split(" to ")[-1]
            reasons.append(f"Season closed {end}" if end else "Out of season")
            best = best if best == "covered" else "partial"
            continue

        if status != "in_force":
            continue

        # In force, in season. Does its trigger reach these hours?
        if trigger == "general_duty":
            reasons.append("General duty only, no temperature trigger")
            best = best if best == "covered" else "partial"
        elif trigger == "advisory":
            reasons.append("Advisory only")
            best = best if best == "covered" else "partial"
        elif trigger == "wbgt":
            thr = wbgt_trigger(rule)
            if thr is not None and thr > limit:
                reasons.append(f"Trigger is WBGT {thr:g} C, above the ISO limit of {limit:g} C")
                best = best if best == "covered" else "partial"
            elif confirmed:
                best = "covered"
            else:
                reasons.append(f"{title} not confirmed against a primary source")
                best = best if best == "covered" else "partial"
        elif trigger in ("weather_alert", "forecast_index"):
            reasons.append("Applies only on days the authority declares")
            best = best if best == "covered" else "partial"
        elif trigger in ("calendar", "air_temperature", "heat_index"):
            if confirmed:
                best = "covered"
            else:
                reasons.append(f"{title} not confirmed against a primary source")
                best = best if best == "covered" else "partial"
    # de-duplicate but keep order
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return best, out


# ---------------------------------------------------------------------------- #
# Computation

def compute_hub(hub, fc_hub, today):
    """Hourly WBGT in sun and shade, then the hour counts for all 12 control
    combinations and the daily peaks the hub chart draws.

    Hours are counted from the HOURLY series, not derived from a daily peak. The
    difference is not cosmetic: a day that touches the limit for one hour and a
    day that sits above it from ten until six can share a peak."""
    h = fc_hub["hourly"]
    off = fc_hub.get("utc_offset_seconds") or 0
    per_day = {}
    for i, ts in enumerate(h["time"]):
        try:
            local = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if not (wbgt.WORK_START <= local.hour < wbgt.WORK_END):
            continue
        utc = local - timedelta(seconds=off)
        cza = wbgt.cos_zenith(hub["lat"], hub["lon"], utc)
        sw = h["shortwave_radiation"][i] or 0.0
        dr = min(h["direct_radiation"][i] or 0.0, sw)
        slot = per_day.setdefault(local.date(), {"sun": [], "shade": []})
        for setting in ("sun", "shade"):
            # Shade is the diffuse component with the beam removed, recomputed
            # through the model -- not the mock's flat -3 C.
            solar = sw if setting == "sun" else max(sw - dr, 0.0)
            direct = dr if setting == "sun" else 0.0
            w = wbgt.wbgt(h["temperature_2m"][i], h["relative_humidity_2m"][i],
                          h["surface_pressure"][i], h["wind_speed_10m"][i],
                          solar, direct, cza)
            slot[setting].append(w)

    # The window is FIXED at the report date plus six, the same seven dates for
    # every hub, and a day a hub has no forecast for is None rather than absent.
    #
    # Taking each hub's own first seven days made the table ragged: the fetch runs
    # 05:30 UK, which is the previous evening in Chicago, so Open-Meteo's seven
    # local days for a western hub start a day earlier and end a day short of the
    # window. Houston and Fresno rendered six cells against a seven-column header,
    # which shifted every later cell in the row one column left and left the row
    # rule hanging short of the table edge.
    window = [today + timedelta(days=i) for i in range(7)]
    peaks = {s: [round(max(per_day[d][s]), 1) if per_day.get(d, {}).get(s) else None
                 for d in window] for s in ("sun", "shade")}
    hours = {}
    for workload, setting, acc in COMBOS:
        limit = wbgt.limit_for(workload, acc)
        hours[combo_key(workload, setting, acc)] = [
            (sum(1 for w in per_day[d][setting] if w is not None and w > limit)
             if d in per_day else None) for d in window]
    return {"days": [d.isoformat() for d in window], "hours": hours, "peaks": peaks,
            "missing": [d.isoformat() for d in window if d not in per_day],
            "hourly": {s: {d.isoformat(): [None if w is None else round(w, 2)
                                           for w in per_day[d][s]]
                           for d in window if d in per_day} for s in ("sun", "shade")}}


def so_what(hub, computed, rules, today):
    """One line per hub, written only from the computed numbers and the rule
    record. It may not state a rule, date or threshold that is not in a record --
    which is why this is a function and not a prompt."""
    key = combo_key("heavy", "sun", True)
    hrs = [h for h in computed["hours"][key] if h is not None]
    total = sum(hrs)
    limit = wbgt.limit_for("heavy", True)
    if total == 0:
        return (f"No hour this week is forecast above WBGT {limit:g} C for heavy work at "
                f"{hub['name']}.")
    full = computed["hours"][key]
    worst = max((i for i, h in enumerate(full) if h is not None),
                key=lambda i: full[i])
    d = date.fromisoformat(computed["days"][worst])
    cov, reasons = coverage(hub, rules, today, limit)
    why = (reasons[0] if reasons else DEFAULT_REASON[cov]).rstrip(".")
    tail = {"covered": "A rule in force covers those hours.",
            "partial": f"Cover is partial \u2014 {why}.",
            "gap": f"No binding rule covers those hours \u2014 {why}."}[cov]
    return (f"{total} working hour{'s' if total != 1 else ''} this week are forecast above "
            f"WBGT {limit:g} C for heavy work in the sun at {hub['name']}, the worst on "
            f"{d.strftime('%A %-d %B')} with {hrs[worst]}. {tail}")


# ---------------------------------------------------------------------------- #
# Archive (B6)

def write_archive(out_dir, when, hubs, computed, rules, today, issued):
    """The forecast as issued, plus the rule status it was read against, one file
    per hub, and a manifest of hashes for the day.

    Immutable: an existing file for a date is left alone. The point of the archive
    is that it says what was known that morning, and a build re-run in the evening
    must not quietly improve it."""
    fdir = os.path.join(out_dir, "archive", "forecast", when)
    mdir = os.path.join(out_dir, "archive", "manifest")
    os.makedirs(fdir, exist_ok=True)
    os.makedirs(mdir, exist_ok=True)
    manifest, written = {}, 0
    for hub in hubs:
        c = computed.get(hub["id"])
        if not c:
            continue
        path = os.path.join(fdir, f"{hub['id']}.json")
        if not os.path.exists(path):
            snapshot = []
            for rid in hub.get("rule_ids") or []:
                r = rules.get(rid)
                if not r:
                    continue
                snapshot.append({"id": rid, "status": r.get("status"),
                                 "confidence": r.get("confidence"),
                                 "last_checked": r.get("last_checked"),
                                 "in_season": season_active(r, today)})
            rec = {
                "hub": hub["id"], "name": hub["name"], "admin": hub["admin"],
                "lat": hub["lat"], "lon": hub["lon"], "tz": hub["tz"],
                "issued_utc": issued, "forecast_date": when,
                "working_day": f"{wbgt.WORK_START:02d}:00-{wbgt.WORK_END:02d}:00 local",
                "method": "WBGT after Liljegren et al. (2008); limits from ISO 7243:2017",
                "source": "Open-Meteo API (CC BY 4.0)",
                "days": c["days"], "wbgt_hourly_c": c["hourly"],
                "daily_peak_wbgt_c": c["peaks"], "hours_above_limit": c["hours"],
                "iso7243_limits_c": {f"{w}-{'acc' if a else 'new'}": wbgt.limit_for(w, a)
                                     for w, _ in wbgt.WORKLOADS for a, _ in wbgt.ACCLIM},
                "rule_status_snapshot": snapshot,
            }
            with open(path, "w") as fh:
                json.dump(rec, fh, separators=(",", ":"), sort_keys=True)
            written += 1
        with open(path, "rb") as fh:
            manifest[f"archive/forecast/{when}/{hub['id']}.json"] = hashlib.sha256(
                fh.read()).hexdigest()

    mpath = os.path.join(mdir, f"{when}.json")
    if not os.path.exists(mpath):
        with open(mpath, "w") as fh:
            json.dump({"date": when, "issued_utc": issued, "algorithm": "sha256",
                       "files": manifest}, fh, indent=1, sort_keys=True)
    return written, len(manifest)


def write_csv(out_dir, hubs, computed):
    """One file covering every hub, day and control combination, so a download
    exists for whatever filter the reader had on screen."""
    rows = ["hub,name,admin,date,workload,setting,acclimatisation,limit_wbgt_c,"
            "hours_above_limit,daily_peak_wbgt_c"]
    for hub in hubs:
        c = computed.get(hub["id"])
        if not c:
            continue
        for workload, setting, acc in COMBOS:
            key = combo_key(workload, setting, acc)
            limit = wbgt.limit_for(workload, acc)
            for i, day in enumerate(c["days"]):
                peak = c["peaks"][setting][i]
                hrs = c["hours"][key][i]
                rows.append(f'{hub["id"]},"{hub["name"]}",{hub["admin"]},{day},{workload},'
                            f'{setting},{"acclimatised" if acc else "new-to-heat"},'
                            f'{limit:g},{"" if hrs is None else hrs},'
                            f'{"" if peak is None else peak}')
    path = os.path.join(out_dir, "workability-week.csv")
    with open(path, "w") as fh:
        fh.write("\n".join(rows) + "\n")
    return len(rows) - 1


# ---------------------------------------------------------------------------- #
# Presentation

CSS = """
/* ---- the WBGT explainer ---------------------------------------------------
   Two carrying hues plus the page's neutral, validated with the dataviz
   validator against both surfaces: light #0f7fa8/#dd6b20 and dark
   #1a89ae/#d97328. The dark pair is CHOSEN for the dark lightness band
   (L 0.48-0.67), not lightened from the light pair -- the obvious flip lands
   both hues outside the band. Blue for the wet bulb is a deliberate addition to
   the palette: the site keeps loud colour for data, and this is data. Grey for
   air temperature is the point being made, not a shortage of hues. */
:root{--wx-wet:#0f7fa8; --wx-globe:#dd6b20}
:root[data-theme="dark"]{--wx-wet:#1a89ae; --wx-globe:#d97328}
.wbgtx{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}
.wbgtx > summary{font-family:'Space Mono',monospace;font-size:11.5px;font-weight:700;
  letter-spacing:.06em;color:var(--c3);list-style:none}
.wbgtx > summary::-webkit-details-marker{display:none}
.wbgtx > summary::before{content:"+ ";font-weight:700}
.wbgtx[open] > summary::before{content:"− "}
.wbgtx > summary:hover{color:var(--ink)}
.wbgtx > summary:focus-visible{outline:2px solid var(--h4);outline-offset:3px}
.wxbody{padding-top:14px}
.wxbody p{font-size:14px;color:var(--ink-dim);margin:0 0 11px}
.wxbar{display:flex;gap:2px;height:30px;margin:18px 0 12px;max-width:560px}
.wxseg{display:block;height:100%}
.wxseg:first-child{border-radius:4px 0 0 4px}
.wxseg:last-child{border-radius:0 4px 4px 0}
.wx1{background:var(--wx-wet)} .wx2{background:var(--wx-globe)} .wx3{background:var(--muted)}
.wxkey{margin:0;padding:0;list-style:none;max-width:560px}
/* Two columns at every width, and the name and its share are ONE cell. Splitting
   them into separate grid items dropped the "70%" onto its own line on a phone,
   which read as a stray number under the label it belongs to. */
.wxkey li{display:grid;grid-template-columns:14px 1fr;gap:3px 9px;
  padding:8px 0;border-top:1px solid var(--line);font-size:13.5px;color:var(--ink-dim)}
.wxkey .sw{width:14px;height:14px;border-radius:3px;margin-top:3px}
.wxkey .hd{display:flex;align-items:baseline;gap:9px;flex-wrap:wrap}
.wxkey b{font-weight:600;color:var(--ink)}
.wxkey .pc{font-family:'Space Mono',monospace;font-size:12px;color:var(--ink);
  font-weight:700}
.wxkey .ds{grid-column:2}
/* forced-colors strips the fills; the shares are written out in the key below,
   so the bar becomes an outline rather than disappearing into one block */
@media(forced-colors:active){
  .wxseg{border:1px solid CanvasText}
  .wxkey .sw{border:1px solid CanvasText}
}

/* ---- controls ---- */
.wkctl{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));gap:14px 26px;
  margin-top:24px;border-top:1px solid var(--line);padding-top:18px}
.wkgrp{min-width:0}
.wkgrp .ctrllab{display:block;margin-bottom:5px}
.wkopts{display:flex;flex-wrap:wrap;gap:5px}
.wkopt{font-family:'Space Mono',monospace;font-size:11.5px;font-weight:700;letter-spacing:.04em;
  padding:5px 11px;border:1px solid var(--line-2);border-radius:20px;background:none;
  color:var(--muted);cursor:pointer}
.wkopt:hover{color:var(--ink);border-color:var(--ink-dim)}
.wkopt[aria-pressed="true"]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.wkopt:focus-visible{outline:2px solid var(--h4);outline-offset:2px}
.limitline{font-family:'Space Mono',monospace;font-size:11.5px;color:var(--ink-dim);
  margin-top:16px;padding-top:13px;border-top:1px solid var(--line)}
.limitline b{color:var(--h4)}

/* ---- the filter bar --------------------------------------------------------
   Sticky on desktop only. Its scope is .filterscope, which wraps the tiles AND
   the table: a sticky element only sticks while its own parent is on screen, so
   leaving the controls inside the "This week" section would have unstuck them at
   the exact moment the table they filter came into view.
   Not sticky on a phone -- four control groups wrap to five rows there, which is
   most of the screen, and the table is one card per hub anyway. */
.ctlbar{padding:4px 0 0}
.ctlinner{padding-bottom:10px}
@media(min-width:761px){
  .ctlbar{position:sticky;top:106px;z-index:30;background:var(--bg);
    border-bottom:1px solid var(--line-2);margin-bottom:8px}
  .ctlbar .wkctl{margin-top:14px;padding-top:0;border-top:0}
  .ctlbar .limitline{margin-top:10px;padding-top:9px}
  /* The heading below must clear both sticky bars AND this one when jumped to.
     The bar's height is not a constant: the four control groups wrap as the
     window narrows, so it runs from 162px at 1440 to 259px at 780, and any fixed
     number here is wrong at most widths -- 232px put the heading 10px behind the
     bar's own bottom border. JS measures it into --ctlbar-h; the fallback is the
     widest case, which errs toward too much clearance rather than too little. */
  .ctlcard{scroll-margin-top:calc(106px + var(--ctlbar-h, 259px) + 16px)}
}
.ctlcard{border-top:0;margin-top:0;padding-top:26px}
@media(min-width:761px){
}

/* ---- the hub table ---- */
.wkwrap{margin-top:8px;overflow-x:auto}
table.wk{width:100%;border-collapse:collapse;font-size:13.5px;min-width:840px}
table.wk th,table.wk td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--line);
  vertical-align:top}
/* NOT position:sticky. .wkwrap is overflow-x:auto, which makes it the scroll
   container a sticky descendant resolves against -- so top:106px pinned the
   header 106px below the TABLE's top edge and painted it over the first row,
   rather than under the two sticky bars. The table is 18 rows; a header that
   scrolls away costs less than one that lands in the middle of the data, and the
   phone layout repeats the day initials on every card anyway. */
table.wk thead th{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted);font-weight:700;border-bottom:1px solid var(--line-2);
  background:var(--bg)}
table.wk tbody tr{cursor:pointer}
table.wk tbody tr:hover,table.wk tbody tr:focus-visible{background:rgba(194,65,12,.055)}
table.wk tbody tr:focus-visible{outline:2px solid var(--h4);outline-offset:-2px}
/* an affordance that the row opens something, rather than a row that happens to
   be clickable and gives no sign of it */
.hubname::after{content:" ›";color:var(--h4);font-weight:700}
table.wk tbody tr:hover .hubname::after{opacity:1}
.hubname{display:block;font-weight:600;font-size:14.5px}
.hubsec{display:block;font-family:'Space Mono',monospace;font-size:9.5px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.06em;margin-top:2px}
.dayc{width:38px;text-align:center!important;padding:6px 3px!important}
.cellv{display:block;font-family:'Space Mono',monospace;font-size:13px;font-weight:700;
  border-radius:4px;padding:7px 0;color:var(--ink)}
.b0{background:var(--land);color:var(--muted)}
/* a day the forecast does not cover: visibly nothing, not a zero */
.nod{background:none;color:var(--muted);opacity:.5}
.b1{background:var(--h1)} .b2{background:var(--h2)} .b3{background:var(--h3)}
.b4{background:var(--h4);color:#fff} .b5{background:var(--h5);color:#fff}
:root[data-theme="dark"] .b1,:root[data-theme="dark"] .b2,:root[data-theme="dark"] .b3{color:#16130f}
.tot{font-family:'Space Mono',monospace;font-size:16px;font-weight:700;color:var(--h4)}
.rulecell{max-width:250px;font-size:12.5px;color:var(--ink-dim)}
.rulecell .rt{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.07em;color:var(--muted);display:block;margin-bottom:3px}
.covcell{max-width:190px}
.covst{display:block;font-size:11.5px;color:var(--muted);margin-top:5px;line-height:1.45}

/* Phone: one card per hub, the week as seven small cells with day initials.
   The table stays a real table -- only its boxes change -- so the header
   association and keyboard order survive the reflow. */
@media(max-width:760px){
  .wkwrap{overflow-x:visible}
  table.wk{min-width:0;display:block}
  table.wk thead{display:none}
  table.wk tbody,table.wk tr{display:block}
  table.wk tr{border-top:1px solid var(--line);padding:14px 0}
  table.wk td{display:block;border:0;padding:0}
  table.wk td.dayc{display:none}
  table.wk td.week{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin:10px 0 2px}
  table.wk td.week .d{text-align:center}
  table.wk td.week .dl{font-family:'Space Mono',monospace;font-size:9px;color:var(--muted);
    display:block;margin-bottom:3px}
  table.wk td.totc{margin-top:8px}
  .rulecell,.covcell{max-width:none;margin-top:9px}
}
@media(min-width:761px){table.wk td.week{display:none}}

.wklegend{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-top:16px;
  font-family:'Space Mono',monospace;font-size:10.5px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.05em}
.wklegend .lgd{width:14px;height:14px;border-radius:3px;flex:none;display:inline-block}
.dls{margin-top:14px;font-family:'Space Mono',monospace;font-size:11px}
.dls a{color:var(--c3)}

/* ---- selected hub, as a modal ---- */
.hubdlg{border:1px solid var(--line-2);border-radius:10px;padding:0;
  width:min(760px,calc(100vw - 32px));max-height:min(86vh,900px);
  background:var(--bg);color:var(--ink);overflow:hidden}
.hubdlg::backdrop{background:rgba(22,19,15,.44)}
:root[data-theme="dark"] .hubdlg::backdrop{background:rgba(0,0,0,.62)}
.hubdlgbody{padding:24px 26px 28px;overflow-y:auto;max-height:inherit}
.hubclose{position:sticky;top:0;z-index:2;display:flex;justify-content:flex-end;
  padding:10px 12px 0;margin:0;background:var(--bg)}
.hubclose button{font-family:'Space Mono',monospace;font-size:11px;font-weight:700;
  letter-spacing:.07em;text-transform:uppercase;color:var(--muted);background:none;
  border:1px solid var(--line-2);border-radius:20px;padding:5px 12px;cursor:pointer}
.hubclose button:hover{color:var(--ink);border-color:var(--ink-dim)}
.hubclose button:focus-visible{outline:2px solid var(--h4);outline-offset:2px}
@media(max-width:620px){
  .hubdlg{width:100vw;max-width:100vw;max-height:100vh;height:100vh;border-radius:0;border:0}
  .hubdlgbody{padding:18px 16px 28px}
}
.hubdlg h3{margin:0 0 4px;font-size:21px;font-weight:600}
.hubmeta{font-family:'Space Mono',monospace;font-size:10px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted)}
.sowhat{font-size:14.5px;color:var(--ink-dim);margin:14px 0 0}
.barwrap{margin:18px 0 6px}
.barwrap svg{width:100%;height:auto;display:block;max-width:560px}
.rulebox{border-top:1px solid var(--line);margin-top:18px;padding-top:16px}
.rulebox h4{font-family:'Space Mono',monospace;font-size:9.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);margin:0 0 7px;font-weight:700}
.rulebox p{margin:0 0 10px;font-size:13.5px;color:var(--ink-dim)}
.rulebox ul{margin:0 0 10px;padding-left:17px;font-size:13.5px;color:var(--ink-dim)}
.rulebox li{margin:3px 0}
.rulegrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;
  margin-top:12px}
/* No one-sided borders. A box gets a border on all four sides or none; the
   accent-bar-on-the-left pattern is out everywhere in this project. Emphasis
   comes from the heading colour and the surface instead. */
.recbox{border:1px solid var(--line-2);border-radius:7px;
  padding:14px 16px;margin-top:16px}
.recbox h4{color:var(--h4)}
.unconf{border:1px solid var(--warning);border-radius:7px;padding:11px 14px;margin-top:12px}
.unconf p{font-size:12.5px;color:var(--muted);margin:0}
.unconf h4{font-family:'Space Mono',monospace;font-size:9.5px;letter-spacing:.12em;
  text-transform:uppercase;color:var(--warning);margin:0 0 5px;font-weight:700}
.srcs{font-family:'Space Mono',monospace;font-size:9.5px;color:var(--muted);line-height:1.65}
.srcs a{color:var(--c3)}

/* ---- season record ---- */
table.season{width:100%;border-collapse:collapse;font-size:13px;margin-top:14px}
table.season th,table.season td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
table.season th{font-family:'Space Mono',monospace;font-size:9.5px;text-transform:uppercase;
  letter-spacing:.08em;color:var(--muted)}
table.season td.n{font-family:'Space Mono',monospace}
.emptyrow{text-align:center;color:var(--muted);font-size:13px;padding:22px 0}
"""


def trigger_label(rule):
    return {"calendar": "Calendar ban", "weather_alert": "Weather alert",
            "forecast_index": "Forecast risk map", "wbgt": "WBGT measured",
            "air_temperature": "Air temperature", "heat_index": "Heat index",
            "advisory": "Advisory", "general_duty": "General duty",
            "none": "None"}.get(rule.get("trigger_type"), "—")


def primary_rule(hub, rules):
    """The record the table's rule column shows.

    Most local instrument first, which is the order that matches how the duty
    actually reaches a site: a regional ordinance governs the working day at
    Palermo, and Italy's national wage-support scheme does not, however much
    sharper its trigger looks. Ranking on the trigger first put the INPS scheme in
    the rule column for every Italian hub and a draft federal rule in Houston's.

    Within a level: something in force beats something that is not, and a real
    trigger beats a general duty."""
    level = {"municipal": 0, "regional": 1, "national": 2, "supranational": 3}
    rank = {"wbgt": 0, "calendar": 1, "air_temperature": 1, "heat_index": 1,
            "weather_alert": 2, "forecast_index": 2, "general_duty": 3,
            "advisory": 4, "none": 5}
    best, best_key = None, None
    for rid in hub.get("rule_ids") or []:
        r = rules.get(rid)
        if not r:
            continue
        live = 0 if r.get("status") in ("in_force", "in_force_seasonal_inactive") else 1
        key = (level.get(r.get("level"), 9), live, rank.get(r.get("trigger_type"), 9))
        if best is None or key < best_key:
            best, best_key = r, key
    return best


def first_sentence(text, limit=150):
    """Whole sentences, never an ellipsis -- the same rule the Updates page's
    short() follows. A clause cut mid-word ("...Ministry\u2026") is worse than a
    slightly long cell, and the full text is one click away in the panel below."""
    t = " ".join(str(text or "").split())
    if not t:
        return ""
    if len(t) <= limit:
        return t
    out = ""
    for part in re.findall(r"[^.!?]+[.!?]*", t):
        cand = (out + part).strip()
        if out and len(cand) > limit:
            break
        out = cand
    return out or t


def rule_detail_html(rule, today):
    """The full rule record, as the selected-hub panel shows it: what triggers it,
    what it obliges, what the employer must keep, where it came from and when it
    was last looked at."""
    status_txt = {
        "in_force": "In force",
        "in_force_seasonal_inactive": "In force, season closed",
        "expired": "Expired",
        "draft": "Draft",
        "consultation": "At consultation",
        "none": "No rule",
    }.get(rule.get("status"), rule.get("status") or "—")
    if not is_confirmed(rule) and rule.get("status") in ("in_force", "in_force_seasonal_inactive"):
        status_txt = "Reported, not confirmed"

    parts = [f'<div class="rulebox"><h4>The rule</h4>',
             f'<p><b>{esc(rule.get("title",""))}</b>']
    if rule.get("title_local"):
        parts.append(f'<br><span class="hubmeta">{esc(rule["title_local"])}</span>')
    parts.append("</p>")
    if rule.get("summary_en"):
        parts.append(f'<p>{esc(rule["summary_en"])}</p>')

    grid = [("Status", status_txt), ("Trigger", trigger_label(rule))]
    if rule.get("time_window"):
        grid.append(("Hours", rule["time_window"]))
    if season_label(rule):
        grid.append(("Season", season_label(rule)))
    if rule.get("last_checked"):
        grid.append(("Last checked", rule["last_checked"]))
    parts.append('<div class="rulegrid">' + "".join(
        f'<div><h4>{esc(k)}</h4><p>{esc(v)}</p></div>' for k, v in grid) + "</div>")

    if rule.get("obligations"):
        parts.append("<h4>What it requires</h4><ul>" + "".join(
            f"<li>{esc(o)}</li>" for o in rule["obligations"]) + "</ul>")

    if rule.get("records_required"):
        parts.append('<div class="recbox"><h4>Keeping the records</h4><ul>' + "".join(
            f"<li>{esc(o)}</li>" for o in rule["records_required"]) + "</ul>"
            '<p style="font-size:12px;margin:0">HeatWatch publishes the public facts. '
            'Each employer keeps their own records; this page does not hold them.</p></div>')

    srcs = []
    for s in rule.get("sources") or []:
        tag = "primary" if s.get("type") == "primary" else "secondary"
        srcs.append(f'<a href="{esc(s.get("url",""))}" rel="nofollow noopener">'
                    f'{esc(s.get("publisher","source"))}</a> ({tag}, {esc(s.get("date",""))})')
    if srcs:
        parts.append('<h4>Sources</h4><p class="srcs">' + " · ".join(srcs) + "</p>")

    if rule.get("change_log"):
        parts.append("<h4>Change history</h4><p class=\"srcs\">" + " · ".join(
            f'{esc(c.get("date",""))}: {esc(c.get("field",""))} '
            f'{esc(c.get("old",""))} &rarr; {esc(c.get("new",""))}'
            for c in rule["change_log"]) + "</p>")
    else:
        parts.append('<h4>Change history</h4><p class="srcs">No recorded change since this '
                     'record was created.</p>')

    if not is_confirmed(rule):
        parts.append('<div class="unconf"><h4>Not confirmed</h4><p>This record has not yet '
                     'been confirmed against a primary source. It is shown for information and '
                     'is not counted as a rule in force anywhere on this page.</p></div>')
    parts.append("</div>")
    return "".join(parts)


def hub_dialogs(hubs, rules, today):
    """The hub detail as a modal, not an expanding panel under the table.

    Inline, it opened below eighteen rows of table: on a laptop the click
    produced no visible change at all, because the thing that appeared was two
    screens down. A native <dialog> puts it in front of the reader, and brings
    Esc, a focus trap and inert background with it rather than hand-rolled."""
    out = []
    for hub in hubs:
        blocks = "".join(rule_detail_html(rules[rid], today)
                         for rid in hub.get("rule_ids") or [] if rid in rules)
        elev = (" · " + str(int(hub["elevation_m"])) + " m"
                if hub.get("elevation_m") is not None else "")
        out.append(
            f'<dialog class="hubdlg" id="hd-{esc(hub["id"])}" '
            f'aria-labelledby="hdt-{esc(hub["id"])}">'
            f'<form method="dialog" class="hubclose">'
            f'<button aria-label="Close">Close &times;</button></form>'
            f'<div class="hubdlgbody">'
            f'<h3 id="hdt-{esc(hub["id"])}">{esc(hub["name"])}</h3>'
            f'<div class="hubmeta">{esc(hub["admin"])} · {esc(hub["sectors"])}{elev}</div>'
            f'<p class="sowhat" data-sowhat></p>'
            f'<div class="barwrap" data-bars></div>'
            f'{blocks}</div></dialog>')
    return "".join(out)


def season_record_html(rules, today):
    """Italy, days a regional ordinance applied, by region.

    Filled from the ordinance records' own season windows, which is real data.
    It is NOT the number of days a ban actually bit -- that needs the daily
    Worklimate risk map, which has no public data terms yet, so the column says
    what it is: the period the ordinance covered."""
    rows = []
    for r in rules.values():
        if r.get("level") != "regional" or not str(r.get("jurisdiction", "")).startswith("IT-"):
            continue
        season = r.get("season") or {}
        if not season.get("start"):
            continue
        y = today.year
        try:
            start = date(y, *(int(x) for x in season["start"].split("-")[-2:]))
            end = date(y, *(int(x) for x in season["end"].split("-")[-2:]))
        except ValueError:
            continue
        region = r.get("title", "").replace(" heat ordinance 2026", "")
        rows.append((region, start, end, (end - start).days + 1, r.get("time_window", ""),
                     is_confirmed(r)))
    rows.sort(key=lambda t: -t[3])
    if not rows:
        return '<p class="emptyrow">No ordinance records yet.</p>'
    tr = "".join(
        f'<tr><td>{esc(reg)}</td><td class="n">{s.strftime("%-d %b")}</td>'
        f'<td class="n">{e.strftime("%-d %b")}</td><td class="n">{n}</td>'
        f'<td class="n">{esc(win)}</td></tr>'
        for reg, s, e, n, win, _c in rows)
    return (f'<table class="season"><thead><tr><th>Region</th><th>Ordinance from</th>'
            f'<th>To</th><th>Days covered</th><th>Hours</th></tr></thead>'
            f'<tbody>{tr}</tbody></table>'
            f'<p class="srcline">Days covered is the period each 2026 ordinance ran, not the '
            f'number of days a stoppage was actually called — that depends on the daily risk '
            f'map for each comune, which has no public data terms yet. Records marked '
            f'unconfirmed are not counted as rules in force elsewhere on this page.</p>')


# The row markup exists twice, here and in JS_WK below. They must stay in step:
# the server render is what a reader without JavaScript gets and what the
# internal-term check sees, and the JS render is what every control change
# produces. Change one, change the other.
def row_html(hub, comp, rules, today, workload, setting, acc, days_meta):
    key = combo_key(workload, setting, acc)
    hrs = comp["hours"][key]
    total = sum(h for h in hrs if h is not None)
    limit = wbgt.limit_for(workload, acc)
    cov, reasons = coverage(hub, rules, today, limit)
    rule = primary_rule(hub, rules)

    def cell(n):
        if n is None:
            return '<span class="cellv nod" title="No forecast for this day">&ndash;</span>'
        return f'<span class="cellv {band_for(n)}">{n}</span>'
    cells = "".join(f'<td class="dayc">{cell(n)}</td>' for n in hrs)
    week = '<td class="week">' + "".join(
        f'<span class="d"><span class="dl">{esc(dl)}</span>{cell(n)}</span>'
        for n, (dl, _short, _full) in zip(hrs, days_meta)) + "</td>"
    rs = esc(first_sentence(rule.get("summary_en"))) if rule else "No record"
    return (f'<tr data-hub="{esc(hub["id"])}" data-tags="{esc(" ".join(hub.get("region_tags") or []))}" '
            f'tabindex="0" role="button" aria-haspopup="dialog">'
            f'<td><span class="hubname">{esc(hub["name"])}</span>'
            f'<span class="hubsec">{esc(hub["sectors"])}</span></td>'
            f'{cells}{week}'
            f'<td class="totc"><span class="tot">{total}</span></td>'
            f'<td class="rulecell"><span class="rt">{esc(trigger_label(rule)) if rule else "—"}</span>'
            f'{rs}</td>'
            f'<td class="covcell"><span class="chip {COVER_BAND[cov]}">{COVER_LABEL[cov]}</span>'
            f'<span class="covst">{esc(reasons[0] if reasons else DEFAULT_REASON[cov])}'
            f'</span></td></tr>')


JS_WK = r"""
var WK=__WK__;
var ST={region:'all',workload:'heavy',setting:'sun',acc:1};
function K(){return ST.workload+'-'+ST.setting+'-'+(ST.acc?'acc':'new');}
function lim(){return WK.limits[ST.workload+'-'+(ST.acc?'acc':'new')];}
function band(n){return n<=0?'b0':n<=2?'b1':n<=4?'b2':n<=6?'b3':n<=8?'b4':'b5';}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function vis(){return WK.hubs.filter(function(h){
  return ST.region==='all'||h.tags.indexOf(ST.region)>=0;});}
/* a day with no forecast is null, not 0 -- it must not pull a total down */
function sum(a){var t=0;for(var i=0;i<a.length;i++)if(a[i]!==null)t+=a[i];return t;}

function row(h){
  var hrs=h.h[K()],tot=sum(hrs),c=h.cov[K()],state=c[0],reason=WK.reasons[c[1]];
  var lab={covered:'Covered',partial:'Partial',gap:'No rule in force'}[state];
  var bnd={covered:'good',partial:'warning',gap:'critical'}[state];
  var cells='',week='';
  for(var i=0;i<hrs.length;i++){
    var cv=hrs[i]===null
      ? '<span class="cellv nod" title="No forecast for this day">\u2013</span>'
      : '<span class="cellv '+band(hrs[i])+'">'+hrs[i]+'</span>';
    cells+='<td class="dayc">'+cv+'</td>';
    week+='<span class="d"><span class="dl">'+WK.days[i][0]+'</span>'+cv+'</span>';
  }
  return '<tr data-hub="'+h.id+'" data-tags="'+h.tags.join(' ')+'" tabindex="0" role="button" '
    +'aria-haspopup="dialog"><td><span class="hubname">'+esc(h.name)+'</span>'
    +'<span class="hubsec">'+esc(h.sec)+'</span></td>'+cells
    +'<td class="week">'+week+'</td>'
    +'<td class="totc"><span class="tot">'+tot+'</span></td>'
    +'<td class="rulecell"><span class="rt">'+esc(h.rt)+'</span>'+esc(h.rs)+'</td>'
    +'<td class="covcell"><span class="chip '+bnd+'">'+lab+'</span>'
    +'<span class="covst">'+esc(reason)+'</span></td></tr>';
}

function tiles(hs){
  var total=0,unprot=0,nhubs=0,worst=null;
  hs.forEach(function(h){
    var t=sum(h.h[K()]);total+=t;
    if(t>0)nhubs++;
    if(h.cov[K()][0]!=='covered'){unprot+=t;
      if(t>0&&(!worst||t>sum(worst.h[K()])))worst=h;}
  });
  var pct=total?Math.round(100*unprot/total):0;
  set('kn-total',total);set('kn-total-s','across '+hs.length+' hub'+(hs.length===1?'':'s'));
  set('kn-unprot',unprot);set('kn-unprot-s',pct+'% of the hours shown');
  set('kn-hubs',nhubs);set('kn-hubs-s','of '+hs.length+' in this filter');
  if(worst){set('kn-worst',sum(worst.h[K()])+' h');
    set('kn-worst-k',worst.name);set('kn-worst-s',WK.reasons[worst.cov[K()][1]]);}
  else{set('kn-worst','0 h');set('kn-worst-k','None');
    set('kn-worst-s','every unsafe hour shown is covered');}
}
function set(id,v){var e=document.getElementById(id);if(e)e.textContent=v;}

function draw(h){
  var p=h.p[ST.setting],L=lim(),w=560,hh=190,pad=66,bw=(w-pad-10)/7;
  var top=Math.max(L+4,Math.max.apply(null,p.filter(function(x){return x!==null;})))+2;
  var bot=Math.min(L-6,Math.min.apply(null,p.filter(function(x){return x!==null;})))-1;
  function y(v){return 12+(hh-40)*(1-(v-bot)/(top-bot));}
  var s='<svg viewBox="0 0 '+w+' '+hh+'" role="img" aria-label="Daily peak WBGT against the '
    +'limit for '+esc(h.name)+'">';
  for(var i=0;i<p.length;i++){
    if(p[i]===null)continue;
    var x=pad+i*bw,yy=y(p[i]),hgt=y(bot)-yy;
    var over=p[i]>L;
    s+='<rect x="'+(x+4)+'" y="'+yy+'" width="'+(bw-9)+'" height="'+Math.max(hgt,1)+'" rx="2" '
      +'fill="'+(over?'var(--h4)':'var(--c3)')+'"/>';
    /* a bar that ends near the limit put its own value on top of the dashed
       line, which read as a strikethrough; lift the label clear when they meet */
    var ly=yy-4; if(Math.abs(yy-y(L))<11)ly=yy-13;
    s+='<text x="'+(x+bw/2-2)+'" y="'+ly+'" font-size="10" font-family="Space Mono,monospace" '
      +'fill="var(--ink-dim)" text-anchor="middle">'+p[i].toFixed(1)+'</text>';
    s+='<text x="'+(x+bw/2-2)+'" y="'+(hh-6)+'" font-size="9" font-family="Space Mono,monospace" '
      +'fill="var(--muted)" text-anchor="middle">'+WK.days[i][1]+'</text>';
  }
  s+='<line x1="'+pad+'" x2="'+(w-6)+'" y1="'+y(L)+'" y2="'+y(L)+'" stroke="var(--critical)" '
    +'stroke-width="1.4" stroke-dasharray="5 3"/>';
  /* in the left gutter, not over the first bar: dark red on the ramp's orange is
     close to unreadable, and this label is the only thing explaining the line */
  s+='<text x="2" y="'+(y(L)+3.5)+'" font-size="9.5" font-family="Space Mono,monospace" '
    +'fill="var(--critical)">LIMIT '+L+'°C</text></svg>';
  return s;
}

function sowhat(h){
  var hrs=h.h[K()],tot=sum(hrs),L=lim(),st=h.cov[K()][0];
  var names={light:'light',moderate:'moderate',heavy:'heavy'};
  if(!tot)return 'No working hour this week is forecast above WBGT '+L+'°C for '
    +names[ST.workload]+' work in the '+ST.setting+' at '+h.name+'.';
  var wi=-1;for(var i=0;i<hrs.length;i++){
    if(hrs[i]===null)continue;
    if(wi<0||hrs[i]>hrs[wi])wi=i;}
  if(wi<0)return 'No forecast for '+h.name+' this week.';
  var why=WK.reasons[h.cov[K()][1]].replace(/\.$/,'');
  var tail=st==='covered'?'A rule in force covers those hours.'
    :st==='partial'?'Cover is partial \u2014 '+why+'.'
    :'No binding rule covers those hours \u2014 '+why+'.';
  return tot+' working hour'+(tot===1?'':'s')+' this week are forecast above WBGT '+L
    +'°C for '+names[ST.workload]+' work in the '+ST.setting+' at '+h.name
    +', the worst on '+WK.days[wi][2]+' with '+hrs[wi]+'. '+tail;
}

/* the sticky filter bar's height drives the scroll offset of the heading below it */
(function(){
 var bar=document.querySelector('.ctlbar');
 if(!bar)return;
 function sync(){
  var h=bar.offsetHeight;
  document.documentElement.style.setProperty('--ctlbar-h',h+'px');
  /* the tab marker's threshold has to clear this bar too, or jumping to By hub
     leaves the marker reading This week */
  window.__navLine=106+h+18;
 }
 sync();
 if(window.ResizeObserver)new ResizeObserver(sync).observe(bar);
 else addEventListener('resize',sync,{passive:true});
})();

var SEL=null;
function fill(id){
  var h=WK.hubs.filter(function(x){return x.id===id;})[0];
  var d=document.getElementById('hd-'+id);
  if(!h||!d)return null;
  var b=d.querySelector('[data-bars]');if(b)b.innerHTML=draw(h);
  var s=d.querySelector('[data-sowhat]');if(s)s.textContent=sowhat(h);
  return d;
}
function select(id){
  var d=fill(id);if(!d)return;
  SEL=id;
  if(!d.open&&d.showModal)d.showModal();
}
/* a click on the dialog element itself is a click on its backdrop: the body is a
   child, so anything inside it never reaches here */
document.addEventListener('click',function(e){
  if(e.target.classList&&e.target.classList.contains('hubdlg'))e.target.close();
});
document.querySelectorAll('.hubdlg').forEach(function(d){
  d.addEventListener('close',function(){SEL=null;});
});

function render(){
  var hs=vis().slice().sort(function(a,b){return sum(b.h[K()])-sum(a.h[K()]);});
  var body=document.getElementById('wkbody');
  body.innerHTML=hs.length?hs.map(row).join('')
    :'<tr><td colspan="11" class="emptyrow">No hubs in this filter.</td></tr>';
  tiles(hs);
  var L=lim();
  var accs=ST.acc?'acclimatised':'new to heat';
  set('limitv','WBGT '+L+'°C');
  set('limitrest',' · ISO 7243, '+ST.workload+' work, '+accs+', in the '+ST.setting);
  document.querySelectorAll('[data-ctl]').forEach(function(b){
    b.setAttribute('aria-pressed',String(ST[b.dataset.ctl]===
      (b.dataset.ctl==='acc'?Number(b.dataset.val):b.dataset.val)));});
  /* keep an open dialog in step with the controls behind it */
  if(SEL){
    if(hs.some(function(h){return h.id===SEL;}))fill(SEL);
    else{var d=document.getElementById('hd-'+SEL);if(d&&d.open)d.close();SEL=null;}
  }
}

document.addEventListener('click',function(e){
  var b=e.target.closest('[data-ctl]');
  if(b){ST[b.dataset.ctl]=b.dataset.ctl==='acc'?Number(b.dataset.val):b.dataset.val;
    render();return;}
  var tr=e.target.closest('#wkbody tr[data-hub]');
  if(tr)select(tr.dataset.hub);
});
document.addEventListener('keydown',function(e){
  if(e.key!=='Enter'&&e.key!==' ')return;
  var tr=e.target.closest&&e.target.closest('#wkbody tr[data-hub]');
  if(tr){e.preventDefault();select(tr.dataset.hub);}
});
render();
"""



def wbgt_explainer():
    """What WBGT is, in the words an HSE manager would use.

    Folded into a <details> and placed where the term first bites -- directly
    under the limit line -- rather than banished to Method. A reader meets "WBGT
    26 C" in the controls and in every row of the table; the explanation has to be
    within reach of that, and closed by default so it never pushes the data down.

    The one thing worth a picture is the weighting: people assume a heat index is
    mostly temperature, and the wet-bulb term carries seven tenths of it. That is
    the whole reason a 30 C forecast tells you so little."""
    parts = [
        ("wx1", "Natural wet bulb", "70%",
         "A thermometer with a wet sleeve, left in the open air. It measures how "
         "well sweat can evaporate \u2014 which is how a body actually sheds heat. "
         "It falls as the air gets drier and windier, and rises as it gets more humid."),
        ("wx2", "Globe", "20%",
         "A matt black sphere the size of a grapefruit. It measures radiant heat, "
         "which outdoors is mostly the sun. This is the term that makes shade worth "
         "having."),
        ("wx3", "Air temperature", "10%",
         "The ordinary dry-bulb reading a weather forecast gives you \u2014 the "
         "smallest part of the answer."),
    ]
    key = "".join(
        f'<li><span class="sw {cls}"></span>'
        f'<span class="hd"><b>{esc(name)}</b><span class="pc">{pc}</span></span>'
        f'<span class="ds">{esc(desc)}</span></li>'
        for cls, name, pc, desc in parts)
    return f"""<details class="wbgtx"><summary>What is WBGT, and why not just the
 air temperature?</summary>
<div class="wxbody">
<p><b>WBGT</b> is the wet-bulb globe temperature: one number combining the four
things that decide whether a body can stay cool outdoors \u2014 humidity, radiant
heat, air temperature and wind. Occupational heat standards are written against it,
ISO 7243 among them, which is why this page counts hours in WBGT rather than in
degrees of air temperature.</p>
<p>Air temperature on its own is a poor guide. 30&deg;C in dry shade with a breeze
and 30&deg;C in humid air under open sun are the same forecast and a different day's
work. The body sheds heat by sweating, and sweat stops evaporating once the air is
already wet \u2014 so humidity, not heat, is usually what makes outdoor work
unsafe.</p>
<p>That is why the terms are weighted the way they are:</p>
<div class="wxbar" role="img" aria-label="WBGT is 70 percent natural wet bulb,
 20 percent globe temperature and 10 percent air temperature">
  <span class="wxseg wx1" style="flex:70"></span>
  <span class="wxseg wx2" style="flex:20"></span>
  <span class="wxseg wx3" style="flex:10"></span>
</div>
<ul class="wxkey">{key}</ul>
<p style="margin-top:14px">The limit is not a single number either. Harder work
produces more heat, and a worker not yet used to heat has less room before it
becomes dangerous, so ISO 7243 sets six of them \u2014 from 30&deg;C for light work
by an acclimatised worker down to 22&deg;C for heavy work by someone new to it. The
Workload and Workers controls switch between the six.</p>
<p><b>What this is not.</b> These hours are computed from a public weather forecast
for each hub's location. They are not a reading taken on your site, where shade,
surfaces, enclosure and the work itself all move the number, and they are not an
instruction to stop work. What the law requires is in the rule column beside them,
and it comes from dated records, not from this forecast.</p>
</div></details>"""


def controls_html():
    def grp(label, ctl, opts, default):
        b = "".join(
            f'<button class="wkopt" data-ctl="{ctl}" data-val="{esc(v)}" '
            f'aria-pressed="{"true" if v == default else "false"}">{esc(lab)}</button>'
            for v, lab in opts)
        return (f'<div class="wkgrp"><span class="ctrllab">{esc(label)}</span>'
                f'<div class="wkopts">{b}</div></div>')
    return (
        '<div class="wkctl">'
        + grp("Region", "region", REGIONS, "all")
        + grp("Workload", "workload", [(k, lab) for k, lab in wbgt.WORKLOADS], "heavy")
        + grp("Setting", "setting", [(k, lab) for k, lab in wbgt.SETTINGS], "sun")
        + grp("Workers", "acc", [("1", "Acclimatised"), ("0", "New to heat")], "1")
        + '</div>'
        '<p class="limitline">Limit: <b id="limitv">WBGT 26&deg;C</b>'
        '<span id="limitrest"> &middot; ISO 7243, heavy work, acclimatised, in the sun</span>'
        '</p>')


def key_numbers_html():
    tiles = [
        ("kn-total", "0", "Unsafe working hours", "kn-total-s"),
        ("kn-unprot", "0", "Of those, not covered by a rule in force", "kn-unprot-s"),
        ("kn-hubs", "0", "Hubs with at least one unsafe hour", "kn-hubs-s"),
        ("kn-worst", "0 h", None, "kn-worst-s"),
    ]
    out = []
    for vid, v, label, sid in tiles:
        k = (f'<div class="mk" id="kn-worst-k">—</div>' if label is None
             else f'<div class="mk">{esc(label)}</div>')
        out.append(f'<div class="metric"><div class="mv" id="{vid}">{v}</div>{k}'
                   f'<div class="ms" id="{sid}"></div></div>')
    return f'<div class="metrics">{"".join(out)}</div>'


def render(core_dir, today, issued):
    """Everything the Workability page needs: the sections, the CSS and the JS.

    Returns None when there is no stored forecast for the date, so a build on a
    day the fetch did not run produces the Updates page alone rather than a
    Workability page full of blanks."""
    hubs = load_hubs(core_dir)
    rules = load_rules(core_dir)
    fc = load_forecast(core_dir, today.isoformat())
    if not hubs or not rules or not fc:
        return None

    computed = {}
    for hub in hubs:
        fh = (fc.get("hubs") or {}).get(hub["id"])
        if fh:
            computed[hub["id"]] = compute_hub(hub, fh, today)
    hubs = [h for h in hubs if h["id"] in computed]
    if not hubs:
        return None

    days = computed[hubs[0]["id"]]["days"]
    days_meta = []
    for d in days:
        dt = date.fromisoformat(d)
        days_meta.append((dt.strftime("%a")[0], dt.strftime("%-d %b"),
                          dt.strftime("%A %-d %B")))

    # Coverage for all 12 combinations, with the reason strings pooled so the
    # payload carries each sentence once rather than 18 times.
    reasons, rindex = [], {}

    def ridx(s):
        if s not in rindex:
            rindex[s] = len(reasons)
            reasons.append(s)
        return rindex[s]

    payload_hubs = []
    for hub in hubs:
        c = computed[hub["id"]]
        cov = {}
        for workload, setting, acc in COMBOS:
            key = combo_key(workload, setting, acc)
            state, why = coverage(hub, rules, today, wbgt.limit_for(workload, acc))
            cov[key] = [state, ridx(why[0] if why else DEFAULT_REASON[state])]
        rule = primary_rule(hub, rules)
        payload_hubs.append({
            "id": hub["id"], "name": hub["name"], "sec": hub["sectors"],
            "tags": hub.get("region_tags") or [],
            "h": c["hours"], "p": c["peaks"], "cov": cov,
            "rt": trigger_label(rule) if rule else "—",
            "rs": first_sentence(rule.get("summary_en")) if rule else "No record",
        })

    payload = {
        "days": [[a, b, c2] for a, b, c2 in days_meta],
        "hubs": payload_hubs, "reasons": reasons,
        "limits": {f"{w}-{'acc' if a else 'new'}": wbgt.limit_for(w, a)
                   for w, _ in wbgt.WORKLOADS for a, _ in wbgt.ACCLIM},
    }

    # Server-rendered initial state, so the page works with JavaScript off and so
    # the internal-term check sees real rows rather than a script tag.
    order = sorted(hubs, key=lambda h: -sum(
        x for x in computed[h["id"]]["hours"][combo_key("heavy", "sun", True)] if x is not None))
    rows = "".join(row_html(h, computed[h["id"]], rules, today, "heavy", "sun", True, days_meta)
                   for h in order)
    heads = "".join(f'<th class="dayc" scope="col" title="{esc(full)}">{esc(i)}<br>'
                    f'<span style="font-weight:400">{esc(short.split()[0])}</span></th>'
                    for i, short, full in days_meta)

    legend = "".join(
        f'<span class="lg"><span class="lgd {cls}"></span>{esc(lab)} h</span>'
        for _lo, _hi, cls, lab in BANDS)

    sections = f"""
<div class="filterscope">
<section class="card" id="week">
  <h2>Working hours too hot for outdoor work</h2>
  <p class="lede">Hours in the working day when the forecast wet-bulb globe temperature is
  above the ISO 7243 limit for the work being done, at {len(hubs)} work hubs — set against
  the rule that applies there and whether it covers those hours.</p>
  {key_numbers_html()}
  {wbgt_explainer()}
  <p class="srcline">Working day {wbgt.WORK_START:02d}:00–{wbgt.WORK_END:02d}:00 local.
  WBGT computed hour by hour after Liljegren et al. (2008) from Open-Meteo forecast data
  (CC BY 4.0); limits from ISO 7243:2017. Shade recomputes the model with the direct beam
  removed. The hours are a forecast, not an official status: the rule column comes from
  dated rule records and is kept separate for that reason.</p>
</section>

<div class="ctlbar"><div class="ctlinner">{controls_html()}</div></div>

<section class="card ctlcard" id="hubs">
  <h2>By hub</h2>
  <p class="lede">Select a hub for its daily peaks, the rule in full, and what an employer
  there has to keep.</p>
  <div class="wkwrap"><table class="wk"><thead><tr>
    <th scope="col">Hub</th>{heads}
    <th scope="col">Week</th><th scope="col">Rule</th><th scope="col">Coverage</th>
  </tr></thead><tbody id="wkbody">{rows}</tbody></table></div>
  <div class="wklegend"><span>Hours above the limit</span>{legend}</div>
  <p class="dls"><a href="workability-week.csv" download>Download this week (CSV)</a>
   · <a href="archive/manifest/{today.isoformat()}.json">Archive manifest for today</a></p>
  {hub_dialogs(hubs, rules, today)}
</section>
</div>

<section class="card" id="season">
  <h2>Season record</h2>
  <p class="lede">The regional ordinances that ran this year, and the window each covered.</p>
  {season_record_html(rules, today)}
</section>
"""
    js = JS_WK.replace("__WK__", json.dumps(payload, separators=(",", ":")))
    return {"sections": sections, "js": js, "css": CSS, "hubs": hubs,
            "computed": computed, "rules": rules, "days": days}


# ---------------------------------------------------------------------------- #
# Build guards

VALID_STATUS = {"in_force", "in_force_seasonal_inactive", "draft", "consultation",
                "expired", "none"}
VALID_TRIGGER = {"calendar", "weather_alert", "forecast_index", "wbgt", "air_temperature",
                 "heat_index", "advisory", "general_duty", "none"}
VALID_LEVEL = {"supranational", "national", "regional", "municipal"}
STALE_DAYS = 14


def check_rules(hubs, rules):
    """Fail the build on a rules database that cannot be rendered honestly, and
    print the review queue for the rest.

    Structural problems fail: a hub with no rule record would render a blank
    coverage chip, and an unknown status enum would silently fall through the
    coverage ladder into "gap", which understates cover rather than overstating
    it but is still wrong.

    Missing primary sources and stale checks WARN rather than fail. They are real
    gaps, and the page already refuses to print "In force" for them, but a build
    that dies because a record is 15 days old stops the site publishing over
    something that is a review task, not a defect."""
    hard, soft = [], []
    for rid, r in sorted(rules.items()):
        if r.get("status") not in VALID_STATUS:
            hard.append(f"{rid}: status {r.get('status')!r} not in the enum")
        if r.get("trigger_type") not in VALID_TRIGGER:
            hard.append(f"{rid}: trigger_type {r.get('trigger_type')!r} not in the enum")
        if r.get("level") not in VALID_LEVEL:
            hard.append(f"{rid}: level {r.get('level')!r} not in the enum")
        if r.get("confidence") not in ("sourced", "inferred"):
            hard.append(f"{rid}: confidence {r.get('confidence')!r} not in the enum")
        srcs = r.get("sources") or []
        if not srcs or not all((s or {}).get("url") for s in srcs):
            hard.append(f"{rid}: every record needs at least one source with a URL")
        if not r.get("summary_en"):
            hard.append(f"{rid}: no plain-language summary")
        else:
            # Dates in published strings take a human form ("15 September"), never
            # an internal-looking one. The seeded Gulf and Italian summaries shipped
            # "from 06-15 to 09-15" and "from 2026-05-29 to 2026-09-15" straight
            # into the rule column, which reads like a database field, not a rule.
            iso = re.search(r"\b\d{4}-\d{2}-\d{2}\b", r["summary_en"])
            mmdd = re.search(r"(?<![\d:-])\d{2}-\d{2}(?![\d-])", r["summary_en"])
            if iso or mmdd:
                hard.append(f"{rid}: summary_en carries a machine date "
                            f"({(iso or mmdd).group(0)}) -- use a human form")
        if not any((s or {}).get("type") == "primary" for s in srcs):
            soft.append(f"{rid}: no primary source yet")
        last = r.get("last_checked")
        if not last:
            soft.append(f"{rid}: never checked")
        else:
            try:
                age = (date.today() - date.fromisoformat(last)).days
                if age > STALE_DAYS:
                    soft.append(f"{rid}: last checked {age} days ago")
            except ValueError:
                hard.append(f"{rid}: last_checked {last!r} is not a date")

    for hub in hubs:
        live = [rid for rid in hub.get("rule_ids") or [] if rid in rules]
        if not live:
            hard.append(f"hub {hub['id']}: no rule record")
        missing = [rid for rid in hub.get("rule_ids") or [] if rid not in rules]
        if missing:
            hard.append(f"hub {hub['id']}: rule_ids not found: {missing}")

    if hard:
        raise SystemExit("RULES DATABASE UNUSABLE:\n  " + "\n  ".join(hard))
    confirmed = sum(1 for r in rules.values() if is_confirmed(r))
    print(f"rules check: {len(rules)} records, {confirmed} confirmed against a primary source")
    if soft:
        print(f"rules review queue — {len(soft)} item(s) for a human to check:")
        for w in soft:
            print(f"    {w}")
    return len(soft)
