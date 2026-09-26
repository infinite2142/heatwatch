#!/usr/bin/env python3
"""Outdoor WBGT from standard meteorological inputs — Liljegren et al. (2008).

    Liljegren, Carhart, Lawday, Tschopp, Sharp (2008), "Modeling the Wet Bulb
    Globe Temperature Using Standard Meteorological Measurements",
    Journal of Occupational and Environmental Hygiene 5:10, 645-655.

WBGT = 0.7*Tnwb + 0.2*Tg + 0.1*Ta outdoors in sun. Neither Tnwb (natural wet
bulb) nor Tg (globe) is measured by a weather service, so both are solved from an
energy balance on the sensor itself — a wetted wick and a 50mm black globe. That
is the whole reason this file exists: the "simple" WBGT approximations in
circulation are regressions against air temperature and humidity that ignore sun
and wind, and sun and wind are exactly what decides whether an outdoor shift is
workable.

Standard library only, same rule as the rest of the build. No numpy: the whole
site is 18 hubs x 168 hours x 2 lighting cases, which is a few thousand solves
and runs in about a second.

The iteration is Liljegren's own: solve, damp the update 90/10, repeat. Damping
is not decoration — the globe balance has a T^4 term against a linear convective
term, and an undamped fixed point oscillates instead of converging on hot, still,
sunlit hours, which are precisely the hours the site is about.
"""
import math

# ---------------------------------------------------------------------------- #
# Physical constants and sensor geometry. Values are Liljegren's, not rounded:
# the globe solution is a fourth-root, so a "tidied" emissivity moves the answer.
STEFANB = 5.6696e-8         # Stefan-Boltzmann, W/m2/K4
CP = 1003.5                 # specific heat of dry air, J/(kg K)
M_AIR = 28.97               # molecular weight of dry air, kg/kmol
M_H2O = 18.015              # molecular weight of water vapour, kg/kmol
R_GAS = 8314.34             # universal gas constant, J/(kmol K)
R_AIR = R_GAS / M_AIR
PR = CP / (CP + 1.25 * R_AIR)   # Prandtl number

EMIS_GLOBE = 0.95           # black globe
ALB_GLOBE = 0.05
D_GLOBE = 0.0508            # 2-inch standard globe, m

EMIS_WICK = 0.95            # wetted wick over the natural wet-bulb thermometer
ALB_WICK = 0.4
D_WICK = 0.007
L_WICK = 0.0254

EMIS_SFC = 0.999            # ground
ALB_SFC = 0.45

RATIO = CP * M_AIR / M_H2O
CONVERGENCE = 0.02          # K
MAX_ITER = 100

# Below about 5 degrees of solar elevation the direct beam's geometry factor
# 1/(2*cos z) runs away, and the model is outside its validity anyway. Clamping
# the cosine bounds that factor near 5.7 instead of letting a sunrise hour
# produce a globe temperature of several hundred degrees.
CZA_MIN = 0.0871557         # cos(85 degrees)

# Wind: Liljegren's convective terms are fitted for a moving sensor, and at zero
# wind the sphere Nusselt number collapses to pure conduction, which overstates
# the globe temperature badly. A floor of 0.13 m/s is the value used in the
# reference implementation.
SPEED_MIN = 0.13


def esat(tk):
    """Saturation vapour pressure over water, hPa, with Liljegren's 1.004
    enhancement factor for moist air."""
    return 1.004 * 6.1121 * math.exp(17.502 * (tk - 273.15) / (tk - 32.18))


def dew_point(e_hpa):
    """Inverted Magnus, K. Used only as the first guess for the wet-bulb
    iteration, so the inversion's own error is irrelevant — it converges from
    anywhere sensible, and starting at the dew point is what keeps the iteration
    count in single figures."""
    e = max(e_hpa, 1e-6)
    z = math.log(e / (1.004 * 6.1121))
    return 273.15 + 240.97 * z / (17.502 - z)


def emis_atm(tk, rh):
    """Clear-sky atmospheric emissivity (Brutsaert form as Liljegren uses it).
    rh is a fraction, not a percentage."""
    e = rh * esat(tk)
    return 0.575 * e ** 0.143


def viscosity(tk):
    """Dynamic viscosity of air, kg/(m s)."""
    omega = (tk / 97.0 - 2.9) / 0.4 * (-0.034) + 1.048
    return 2.6693e-6 * math.sqrt(M_AIR * tk) / (3.617 ** 2 * omega)


def thermal_cond(tk):
    """Thermal conductivity of air, W/(m K)."""
    return (CP + 1.25 * R_AIR) * viscosity(tk)


def diffusivity(tk, p_hpa):
    """Diffusivity of water vapour in air, m2/s."""
    pcrit13 = (36.4 * 218.0) ** (1.0 / 3.0)
    tcrit512 = (132.0 * 647.3) ** (5.0 / 12.0)
    tcrit12 = math.sqrt(132.0 * 647.3)
    mmix = math.sqrt(1.0 / M_AIR + 1.0 / M_H2O)
    return 0.000364 * (tk / tcrit12) ** 2.334 * pcrit13 * tcrit512 * mmix / (p_hpa / 1013.25) * 1e-4


def evap(tk):
    """Latent heat of vaporisation, J/kg."""
    return (313.15 - tk) / 30.0 * (-71100.0) + 2.4073e6


def h_sphere_in_air(tk, speed, p_hpa, diameter=D_GLOBE):
    """Convective heat transfer coefficient for a sphere, W/(m2 K)."""
    density = p_hpa * 100.0 / (R_AIR * tk)
    re = max(speed, SPEED_MIN) * density * diameter / viscosity(tk)
    nu = 2.0 + 0.6 * math.sqrt(re) * PR ** 0.3333
    return nu * thermal_cond(tk) / diameter


def h_cylinder_in_air(tk, speed, p_hpa):
    """Convective heat transfer coefficient for the wick, W/(m2 K)."""
    a, b, c = 0.56, 0.281, 0.4
    density = p_hpa * 100.0 / (R_AIR * tk)
    re = max(speed, SPEED_MIN) * density * D_WICK / viscosity(tk)
    nu = b * re ** (1.0 - c) * PR ** (1.0 - a)
    return nu * thermal_cond(tk) / D_WICK


def globe_temperature(tk, rh, p_hpa, speed, solar, fdir, cza):
    """Black-globe temperature, K.

    Radiative gain from sky and ground, plus the solar beam seen by a sphere,
    balanced against convection to the air. The beam term's 1/(2*cos z) is the
    ratio of a sphere's projected area to its horizontal-plane equivalent: a low
    sun heats a globe far more than it heats the ground under it, which is why a
    17:00 hour can stay unworkable after the air has started to cool."""
    tsfc = tk
    prev = tk
    for _ in range(MAX_ITER):
        tref = 0.5 * (prev + tk)
        h = h_sphere_in_air(tref, speed, p_hpa)
        beam = fdir * (1.0 / (2.0 * cza) - 1.0) + 1.0 + ALB_SFC
        inner = (0.5 * (emis_atm(tk, rh) * tk ** 4 + EMIS_SFC * tsfc ** 4)
                 - h / (EMIS_GLOBE * STEFANB) * (prev - tk)
                 + solar / (2.0 * EMIS_GLOBE * STEFANB) * (1.0 - ALB_GLOBE) * beam)
        # A very cold, very windy hour can drive the bracket slightly negative;
        # the fourth root of a negative is not a temperature. Clamping to a floor
        # keeps the solver on the real line — the hours this happens in are tens
        # of degrees below any working limit, so the clamp never reaches the page.
        tg = max(inner, 1.0) ** 0.25
        if abs(tg - prev) < CONVERGENCE:
            return tg
        prev = 0.9 * prev + 0.1 * tg
    return prev


def wet_bulb_temperature(tk, rh, p_hpa, speed, solar, fdir, cza, radiative=True):
    """Wet-bulb temperature, K. radiative=True gives the NATURAL wet bulb (the
    wick sees sun and sky, which is what a WBGT sensor measures); False gives the
    psychrometric wet bulb, used only by the tests."""
    tsfc = tk
    sza = math.acos(max(min(cza, 1.0), -1.0))
    eair = rh * esat(tk)
    prev = dew_point(eair)
    irad = 1.0 if radiative else 0.0
    for _ in range(MAX_ITER):
        tref = 0.5 * (prev + tk)
        h = h_cylinder_in_air(tref, speed, p_hpa)
        # tan(sza) is unbounded at the horizon for the same reason the globe's
        # beam factor is; the cza clamp caps it at tan(85 deg).
        fatm = (STEFANB * EMIS_WICK
                * (0.5 * (emis_atm(tk, rh) * tk ** 4 + EMIS_SFC * tsfc ** 4) - prev ** 4)
                + (1.0 - ALB_WICK) * solar
                * ((1.0 - fdir) * (1.0 + 0.25 * D_GLOBE / L_WICK)
                   + fdir * (math.tan(sza) / math.pi + 0.25 * D_GLOBE / L_WICK)
                   + ALB_SFC))
        ewick = esat(prev)
        density = p_hpa * 100.0 / (tref * R_AIR)
        sc = viscosity(tref) / (density * diffusivity(tref, p_hpa))
        twb = (tk - evap(tref) / RATIO * (ewick - eair) / (p_hpa - ewick) * (PR / sc) ** 0.56
               + fatm / h * irad)
        if abs(twb - prev) < CONVERGENCE:
            return twb
        prev = 0.9 * prev + 0.1 * twb
    return prev


def wbgt(temp_c, rh_pct, pressure_hpa, wind_ms, solar_wm2, direct_wm2, cza):
    """Outdoor WBGT in degrees C.

    temp_c       air temperature, C
    rh_pct       relative humidity, %
    pressure_hpa surface pressure, hPa
    wind_ms      wind speed at 10 m, m/s
    solar_wm2    global horizontal shortwave irradiance, W/m2
    direct_wm2   the direct (beam) part of that, on the horizontal, W/m2
    cza          cosine of the solar zenith angle

    Returns None for inputs that are not physical, rather than a number that
    looks like a reading.
    """
    if temp_c is None or rh_pct is None or wind_ms is None:
        return None
    tk = temp_c + 273.15
    rh = max(min(rh_pct / 100.0, 1.0), 0.01)
    p = pressure_hpa if pressure_hpa else 1013.25
    solar = max(solar_wm2 or 0.0, 0.0)
    direct = max(min(direct_wm2 or 0.0, solar), 0.0)

    # At night there is no beam and no zenith geometry to apply.
    if cza <= 0.0 or solar <= 0.0:
        solar, fdir, cza_eff = 0.0, 0.0, 1.0
    else:
        fdir = direct / solar if solar > 0 else 0.0
        cza_eff = max(cza, CZA_MIN)

    tg = globe_temperature(tk, rh, p, wind_ms, solar, fdir, cza_eff)
    tnwb = wet_bulb_temperature(tk, rh, p, wind_ms, solar, fdir, cza_eff)
    return 0.7 * (tnwb - 273.15) + 0.2 * (tg - 273.15) + 0.1 * temp_c


# ---------------------------------------------------------------------------- #
# Solar position: NOAA's algorithm, good to well under a degree, which is far
# inside what a 1/(2*cos z) term needs. Implemented here so the build keeps its
# no-dependency rule.

def cos_zenith(lat, lon, when_utc):
    """Cosine of the solar zenith angle at a point and a UTC datetime."""
    jd = _julian_day(when_utc)
    t = (jd - 2451545.0) / 36525.0
    # geometric mean longitude and anomaly of the sun
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    mrad = math.radians(m)
    c = (math.sin(mrad) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mrad) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mrad) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    e0 = (23.0 + (26.0 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813)))) / 60.0) / 60.0)
    e = e0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.asin(math.sin(math.radians(e)) * math.sin(math.radians(app_long)))

    # equation of time, minutes
    y = math.tan(math.radians(e / 2.0)) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r)
        - 2.0 * 0.016708634 * math.sin(mrad)
        + 4.0 * 0.016708634 * y * math.sin(mrad) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r)
        - 1.25 * 0.016708634 ** 2 * math.sin(2 * mrad))

    minutes = when_utc.hour * 60.0 + when_utc.minute + when_utc.second / 60.0
    true_solar = (minutes + eot + 4.0 * lon) % 1440.0
    hour_angle = math.radians(true_solar / 4.0 - 180.0)
    latr = math.radians(lat)
    return (math.sin(latr) * math.sin(decl)
            + math.cos(latr) * math.cos(decl) * math.cos(hour_angle))


def _julian_day(dt):
    y, mo = dt.year, dt.month
    d = dt.day + (dt.hour + dt.minute / 60.0 + dt.second / 3600.0) / 24.0
    if mo <= 2:
        y -= 1
        mo += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (mo + 1)) + d + b - 1524.5


# ---------------------------------------------------------------------------- #
# ISO 7243:2017 reference values, degrees C WBGT. The table is the whole point of
# the page: "too hot to work" is not one number, it is six, and which one applies
# depends on how hard the work is and whether the worker is used to the heat.
ISO7243 = {
    ("light",    True):  30.0,
    ("light",    False): 29.0,
    ("moderate", True):  28.0,
    ("moderate", False): 26.0,
    ("heavy",    True):  26.0,
    ("heavy",    False): 22.0,
}

WORKLOADS = [("light", "Light"), ("moderate", "Moderate"), ("heavy", "Heavy")]
SETTINGS = [("sun", "Sun"), ("shade", "Shade")]
ACCLIM = [(True, "Acclimatised"), (False, "New to heat")]

# The working day the hour counts are taken over. Stated on the page, because an
# "8 unsafe hours" figure means nothing without it.
WORK_START, WORK_END = 6, 20


def limit_for(workload, acclimatised):
    return ISO7243[(workload, bool(acclimatised))]
