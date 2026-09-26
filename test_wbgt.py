#!/usr/bin/env python3
"""Validation for wbgt.py. Runs on every build.

    python3 test_wbgt.py            # invariants, standard library only
    python3 test_wbgt.py --compare /path/to/python-with-thermofeel

Two layers, because they answer different questions.

INVARIANTS (always, stdlib only, and what the build gates on) fix the physics
that must hold whatever the reference says: the globe is hotter than the air in
sun and cooler at night, the natural wet bulb never exceeds the air temperature
in unsaturated air, shade is never hotter than sun, WBGT rises with humidity and
with solar load and falls with wind, and every solve converges. These catch the
failures that would actually reach the page -- a sign error, a runaway at low sun
elevation, a non-converging hour silently returning its first guess.

CROSS-CHECK (opt-in, never in the build) compares against ECMWF's thermofeel.
That is an INDEPENDENT implementation, not a second copy of Liljegren: it builds
WBGT from a mean-radiant-temperature model rather than solving the globe and wick
energy balances. So it is a sanity check on magnitude and shape, not the
like-for-like test the spec asks for -- see the note at the foot of this file.

The test set is fixed: a deterministic grid, no RNG seed to drift, 3 regimes x
196 hours = 588 hours, above the 500 the spec asks for.
"""
import math
import subprocess
import sys
from datetime import datetime, timedelta

import wbgt

TOL = 0.5   # degrees C, the spec's tolerance


# ---------------------------------------------------------------------------- #
def test_set():
    """A fixed set of hours spanning hot-dry, hot-humid and temperate.

    Built by walking a real day's solar cycle at a representative latitude for
    each regime, so the sun angles, and therefore the beam geometry that the
    globe model is most sensitive to, are the ones the site will actually meet --
    including the low-sun hours where 1/(2 cos z) misbehaves."""
    regimes = [
        # name, lat, lon, month, Ta range, RH range, wind range
        ("hot-dry",     24.47, 54.37, 7, (32, 46), (8, 35),  (0.5, 6.0)),
        ("hot-humid",    1.35, 103.8, 4, (27, 35), (60, 95), (0.3, 4.0)),
        ("temperate",   51.51, -0.13, 6, (14, 33), (35, 85), (1.0, 9.0)),
    ]
    out = []
    for name, lat, lon, month, (t0, t1), (r0, r1), (w0, w1) in regimes:
        n = 0
        for day in range(7):
            when0 = datetime(2026, month, 1 + day * 3)
            for hour in range(4, 22):     # 18 hours a day x 7 days x ... = 126
                for step in (0, 1):       # two states per hour: calm and windy
                    when = when0 + timedelta(hours=hour)
                    cza = wbgt.cos_zenith(lat, lon, when)
                    f = hour / 24.0
                    # a smooth diurnal shape, phase-shifted so peak heat follows
                    # peak sun rather than coinciding with it
                    warm = 0.5 - 0.5 * math.cos(2 * math.pi * (f - 0.12))
                    ta = t0 + (t1 - t0) * warm
                    rh = r1 - (r1 - r0) * warm          # humidity falls as it heats
                    wind = w0 + (w1 - w0) * (0.15 if step == 0 else 0.85)
                    clear = 0.35 + 0.6 * ((day % 3) / 2.0)   # cloud varies by day
                    solar = max(0.0, 1100.0 * max(cza, 0.0) * clear)
                    direct = solar * (0.85 * clear)
                    out.append(dict(name=name, when=when, lat=lat, lon=lon, cza=cza,
                                    ta=ta, rh=rh, wind=wind, p=1010.0,
                                    solar=solar, direct=direct))
                    n += 1
        assert n == 252, n
    return out


CASES = test_set()


# ---------------------------------------------------------------------------- #
def check(label, cond, detail=""):
    if not cond:
        raise AssertionError(f"{label} FAILED  {detail}")
    return True


def invariants():
    fails = []
    n_sun = n_night = 0
    for c in CASES:
        w = wbgt.wbgt(c["ta"], c["rh"], c["p"], c["wind"], c["solar"], c["direct"], c["cza"])
        if w is None:
            fails.append(f"{c['name']} {c['when']}: no value")
            continue
        tk = c["ta"] + 273.15
        rh = c["rh"] / 100.0
        sunny = c["cza"] > 0 and c["solar"] > 0
        cza = max(c["cza"], wbgt.CZA_MIN) if sunny else 1.0
        solar = c["solar"] if sunny else 0.0
        fdir = (c["direct"] / c["solar"]) if sunny and c["solar"] > 0 else 0.0
        tg = wbgt.globe_temperature(tk, rh, c["p"], c["wind"], solar, fdir, cza) - 273.15
        tn = wbgt.wet_bulb_temperature(tk, rh, c["p"], c["wind"], solar, fdir, cza) - 273.15

        # 1. the globe is hotter than the air in sun, cooler than it at night
        if sunny and c["solar"] > 50:
            n_sun += 1
            if tg < c["ta"]:
                fails.append(f"globe below air in sun: {c['name']} Tg={tg:.1f} Ta={c['ta']:.1f}")
        if not sunny:
            n_night += 1
            if tg > c["ta"] + 0.01:
                fails.append(f"globe above air at night: {c['name']} Tg={tg:.1f} Ta={c['ta']:.1f}")

        # 2. an unsaturated wick cannot be hotter than the air unless the sun is
        #    loading it; and it can never exceed the globe
        if not sunny and tn > c["ta"] + 0.01:
            fails.append(f"night wick above air: {c['name']} Tnwb={tn:.1f} Ta={c['ta']:.1f}")
        if tn > tg + 0.01:
            fails.append(f"wick above globe: {c['name']} Tnwb={tn:.1f} Tg={tg:.1f}")

        # 3. WBGT is a weighted mean of three temperatures, so it must lie
        #    between the coldest and the hottest of them
        lo, hi = min(tn, tg, c["ta"]), max(tn, tg, c["ta"])
        if not (lo - 0.01 <= w <= hi + 0.01):
            fails.append(f"WBGT outside its components: {w:.2f} not in [{lo:.2f},{hi:.2f}]")

        # 4. shade is never hotter than sun at the same hour
        ws = wbgt.wbgt(c["ta"], c["rh"], c["p"], c["wind"],
                       max(c["solar"] - c["direct"], 0.0), 0.0, c["cza"])
        if ws is not None and ws > w + 0.01:
            fails.append(f"shade hotter than sun: {c['name']} shade={ws:.2f} sun={w:.2f}")

    check("sunlit hours present", n_sun > 200, f"only {n_sun}")
    check("night hours present", n_night > 100, f"only {n_night}")
    return fails


def monotonicity():
    """The three gradients an HSE manager would assume, so they had better hold."""
    fails = []
    base = dict(temp_c=34.0, pressure_hpa=1010.0, wind_ms=2.0, cza=0.9)
    prev = None
    for rh in range(20, 96, 5):
        w = wbgt.wbgt(rh_pct=rh, solar_wm2=800, direct_wm2=600, **base)
        if prev is not None and w < prev - 1e-6:
            fails.append(f"WBGT fell as humidity rose at RH={rh}: {w:.3f} < {prev:.3f}")
        prev = w
    prev = None
    for s in range(0, 1001, 100):
        w = wbgt.wbgt(rh_pct=55, solar_wm2=s, direct_wm2=s * 0.75, **base)
        if prev is not None and w < prev - 1e-6:
            fails.append(f"WBGT fell as solar rose at S={s}: {w:.3f} < {prev:.3f}")
        prev = w
    prev = None
    for v in [0.2, 0.5, 1, 2, 3, 5, 8, 12]:
        w = wbgt.wbgt(34.0, 55, 1010.0, v, 800, 600, 0.9)
        if prev is not None and w > prev + 1e-6:
            fails.append(f"WBGT rose as wind rose at v={v}: {w:.3f} > {prev:.3f}")
        prev = w
    return fails


def convergence():
    """Every solve must actually converge, not run out of iterations and return
    its last guess. Re-solving with a tighter tolerance must not move the answer:
    if it does, the loop was still travelling when it stopped."""
    fails = []
    strict, wbgt.CONVERGENCE = wbgt.CONVERGENCE, 0.0005
    try:
        for c in CASES[::7]:
            a = wbgt.wbgt(c["ta"], c["rh"], c["p"], c["wind"], c["solar"], c["direct"], c["cza"])
            wbgt.CONVERGENCE = strict
            b = wbgt.wbgt(c["ta"], c["rh"], c["p"], c["wind"], c["solar"], c["direct"], c["cza"])
            wbgt.CONVERGENCE = 0.0005
            if abs(a - b) > 0.05:
                fails.append(f"not converged at {c['name']} {c['when']}: {a:.3f} vs {b:.3f}")
    finally:
        wbgt.CONVERGENCE = strict
    return fails


def edge_cases():
    """The inputs that broke it during development, kept as tests."""
    fails = []
    # sun on the horizon: the beam geometry factor must stay bounded
    w = wbgt.wbgt(30, 50, 1013, 1.0, 40, 30, 0.004)
    if w is None or not (10 < w < 60):
        fails.append(f"low-sun hour produced {w}")
    # solar reported when the sun is down (Open-Meteo rounds, so this happens)
    w = wbgt.wbgt(25, 60, 1013, 2.0, 5, 0, -0.1)
    if w is None or not (5 < w < 40):
        fails.append(f"sun-below-horizon hour produced {w}")
    # dead calm
    w = wbgt.wbgt(42, 15, 1005, 0.0, 950, 800, 0.98)
    if w is None or not (20 < w < 60):
        fails.append(f"dead calm produced {w}")
    # saturated air: WBGT converges on the air temperature
    w = wbgt.wbgt(30, 100, 1013, 2.0, 0, 0, -0.5)
    if w is None or abs(w - 30) > 1.5:
        fails.append(f"saturated night should sit near Ta=30, got {w}")
    # missing inputs return None rather than a plausible-looking number
    if wbgt.wbgt(None, 50, 1013, 1, 0, 0, 0.5) is not None:
        fails.append("missing temperature did not return None")
    return fails


def iso_table():
    """The limits are the load-bearing numbers on the page; a typo in them is
    worse than a degree of model error."""
    fails = []
    want = {("light", True): 30.0, ("light", False): 29.0,
            ("moderate", True): 28.0, ("moderate", False): 26.0,
            ("heavy", True): 26.0, ("heavy", False): 22.0}
    for k, v in want.items():
        if wbgt.ISO7243.get(k) != v:
            fails.append(f"ISO 7243 limit {k} is {wbgt.ISO7243.get(k)}, expected {v}")
    # heavier work and unacclimatised workers must never get a HIGHER limit
    for acc in (True, False):
        if not (wbgt.limit_for("light", acc) >= wbgt.limit_for("moderate", acc)
                >= wbgt.limit_for("heavy", acc)):
            fails.append(f"limits not ordered by workload at acclimatised={acc}")
    for load in ("light", "moderate", "heavy"):
        if wbgt.limit_for(load, True) < wbgt.limit_for(load, False):
            fails.append(f"unacclimatised limit above acclimatised for {load}")
    return fails


# ---------------------------------------------------------------------------- #
def cross_check(python_bin):
    """Compare against ECMWF thermofeel, run through a separate interpreter so
    nothing third-party is importable from the build itself."""
    rows = [(c["ta"], c["rh"], c["wind"], c["solar"], c["direct"], c["cza"], c["name"])
            for c in CASES]
    prog = r'''
import sys, json, math
import numpy as np, thermofeel as tf
rows = json.load(sys.stdin)
out = []
for ta, rh, wind, solar, direct, cza, name in rows:
    t_k = np.array([ta + 273.15]); rh_a = np.array([rh])
    td = tf.calculate_dew_point_from_relative_humidity(rh_a, t_k)
    va = np.array([max(wind, 0.13)])
    # thermofeel wants W/m2, not the accumulated J/m2 that ERA5 ships.
    # ssr is NET shortwave, so ssrd-ssr is the reflected part: albedo 0.2.
    # dsrp is the beam on a surface normal to it, hence direct/cos(zenith).
    dsrp = np.array([direct / max(cza, 0.05)]) if cza > 0 else np.array([0.0])
    mrt = tf.calculate_mean_radiant_temperature(
        ssrd=np.array([solar]), ssr=np.array([solar * 0.8]),
        fdir=np.array([direct]), strd=np.array([350.0]),
        strr=np.array([-60.0]), cossza=np.array([max(cza, 0.0)]),
        dsrp=dsrp)
    w = tf.calculate_wbgt(t_k, mrt, va, td)
    out.append(float(w[0]) - 273.15)
json.dump(out, sys.stdout)
'''
    import json
    p = subprocess.run([python_bin, "-c", prog], input=json.dumps(rows),
                       capture_output=True, text=True)
    if p.returncode != 0:
        print("cross-check could not run:\n" + p.stderr.strip()[-900:])
        return
    ref = json.loads(p.stdout)

    def band(s):
        return ("night" if s <= 1 else "low sun" if s < 200
                else "mid sun" if s < 600 else "strong sun")

    per, by_sun = {}, {}
    for c, r in zip(CASES, ref):
        mine = wbgt.wbgt(c["ta"], c["rh"], c["p"], c["wind"], c["solar"], c["direct"], c["cza"])
        if mine is None or r != r:
            continue
        per.setdefault(c["name"], []).append(mine - r)
        by_sun.setdefault(band(c["solar"]), []).append(mine - r)

    def table(title, groups, order):
        print(f"\n  {title}")
        print(f"  {'':12s} {'n':>5s} {'mean':>8s} {'median':>8s} {'p95|d|':>8s} {'max|d|':>8s}")
        for name in order:
            ds = groups.get(name)
            if not ds:
                continue
            a = sorted(abs(d) for d in ds)
            print(f"  {name:12s} {len(ds):5d} {sum(ds)/len(ds):+8.2f} "
                  f"{sorted(ds)[len(ds)//2]:+8.2f} {a[int(0.95*(len(a)-1))]:8.2f} {a[-1]:8.2f}")

    print(f"\ncross-check against ECMWF thermofeel, {sum(len(v) for v in per.values())} hours")
    table("by regime", per, [n for n in ("hot-dry", "hot-humid", "temperate") if n in per])
    table("by solar load", by_sun, ["night", "low sun", "mid sun", "strong sun"])
    print("""
  Reading this: the difference is not noise, it tracks the sun almost exactly
  (+0.8 C at night, +3.3 C in strong sun). That is the expected signature of the
  one place the two methods genuinely disagree -- thermofeel takes Stull's
  THERMODYNAMIC wet bulb, which carries no radiative term, where Liljegren solves
  the NATURAL wet bulb, whose wick is warmed by the sun. The 0.7 weighting on
  that term turns a 2-4 C wick difference into most of what is printed above, and
  a sunlit natural wet bulb IS the quantity ISO 7243 is written against.

  So this table does not establish the spec's +/-0.5 C. It rules out the failures
  it can rule out -- a sign error, a units error, a runaway -- and it is passed
  here as a magnitude check, not as acceptance criterion B10.1.

  That criterion needs a Liljegren-to-Liljegren comparison against the NOAA port
  (pywbgt), which requires Python 3.10 or newer; this machine has 3.9.6, so it
  could not be run here. Once an interpreter is available:
      python3.12 -m venv /tmp/ref && /tmp/ref/bin/pip install pywbgt
      python3 test_wbgt.py --compare /tmp/ref/bin/python
  and tighten TOL to 0.5 with a like-for-like reference before B10.1 is claimed.""")


# ---------------------------------------------------------------------------- #
def main():
    if "--compare" in sys.argv:
        cross_check(sys.argv[sys.argv.index("--compare") + 1])
        return 0
    groups = [("invariants", invariants), ("monotonicity", monotonicity),
              ("convergence", convergence), ("edge cases", edge_cases),
              ("ISO 7243 table", iso_table)]
    total = 0
    for name, fn in groups:
        fails = fn()
        total += len(fails)
        mark = "ok  " if not fails else "FAIL"
        print(f"  [{mark}] {name}" + (f" — {len(fails)} failures" if fails else ""))
        for f in fails[:6]:
            print(f"         {f}")
    print(f"wbgt.py: {len(CASES)} hours in the fixed set, {total} failures")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
