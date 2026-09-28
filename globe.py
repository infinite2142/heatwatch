"""Orthographic globe with a climate-anomaly field. Build-time only; emits inline
SVG with no external requests. Geometry from world_paths.json (Natural Earth 110m,
public domain) by inverting its Robinson projection back to lat/lon -- parameters
fitted and validated to sub-degree longitude accuracy (see globe_params.json)."""
import json, math, os, re
import urllib.parse

NUM = re.compile(r'-?\d+(?:\.\d+)?')
TBL = [(0,1.0000,0.0000),(5,.9986,.0620),(10,.9954,.1240),(15,.9900,.1860),(20,.9822,.2480),
       (25,.9730,.3100),(30,.9600,.3720),(35,.9427,.4340),(40,.9216,.4958),(45,.8962,.5571),
       (50,.8679,.6176),(55,.8350,.6769),(60,.7986,.7346),(65,.7597,.7903),(70,.7186,.8435),
       (75,.6732,.8936),(80,.6213,.9394),(85,.5722,.9761),(90,.5322,1.0000)]
HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_JSON = os.path.join(HERE, "world_paths.json")

# Robinson inversion parameters, fitted once and validated against known
# coordinates (Iceland -19.4 vs -19, New Zealand 173.8 vs 174, Madagascar 47.0
# vs 47; max|lon| 180.4, the dateline). world_paths.json is a projected map with
# no lat/lon in it, so recovering coordinates is the only way to reproject it.
R_, CX, CY, K = 187.21, 438.59, 248.51, 253.16


def _XY(phi):
    a = abs(phi)
    for i in range(len(TBL)-1):
        p0,x0,y0 = TBL[i]; p1,x1,y1 = TBL[i+1]
        if p0 <= a <= p1:
            t = (a-p0)/(p1-p0)
            return x0+t*(x1-x0), y0+t*(y1-y0)
    return TBL[-1][1], TBL[-1][2]


def _phi(Yv):
    s = 1 if Yv >= 0 else -1; Yv = abs(Yv)
    for i in range(len(TBL)-1):
        p0,_,y0 = TBL[i]; p1,_,y1 = TBL[i+1]
        if y0 <= Yv <= y1:
            t = (Yv-y0)/(y1-y0) if y1 > y0 else 0
            return s*(p0+t*(p1-p0))
    return s*90.0


def to_lonlat(x, y):
    phi = _phi((CY-y)/K)
    return math.degrees((x-CX)/(0.8487*R_*_XY(phi)[0])), phi


def rings(d):
    """world_paths uses 'M x,y x,y ... Z' per subpath."""
    out = []
    for chunk in d.split('M'):
        c = chunk.strip().rstrip('Zz').strip()
        if not c: continue
        n = [float(v) for v in NUM.findall(c)]
        if len(n) >= 6:
            out.append(list(zip(n[0::2], n[1::2])))
    return out


# Field: a plausible climate-anomaly profile by latitude. Hottest through the
# subtropics (the desert belt), warm at the equator, falling away to the poles.
# Two phases so the illustration can cross-fade between them.
def field(lat, warm=False):
    t = max(0.0, 1.0 - abs(abs(lat) - 18.0) / 74.0)     # 0 at poles, 1 near 18 deg
    t = t ** 1.15
    if warm: t = min(1.0, t * 1.13 + 0.06)
    # A reserved ramp, NOT the map's h1..h5. Mean OKLab chroma 0.060 against the
    # map's 0.160, so the globe reads as atmosphere and the map keeps the loud
    # colour for actual data. Brightens to the khaki midpoint then darkens into
    # brick, the way a real anomaly map does.
    stops = [(0.00, "#3f5a66"), (0.17, "#5c7a80"), (0.36, "#87958a"),
             (0.55, "#b0a179"), (0.72, "#bd8b61"), (0.88, "#a8674a"), (1.00, "#8a4a38")]
    for i in range(len(stops)-1):
        a, ca = stops[i]; b, cb = stops[i+1]
        if a <= t <= b:
            u = (t-a)/(b-a) if b > a else 0
            ra, ga, ba_ = int(ca[1:3],16), int(ca[3:5],16), int(ca[5:7],16)
            rb, gb, bb = int(cb[1:3],16), int(cb[3:5],16), int(cb[5:7],16)
            return "#%02x%02x%02x" % (round(ra+u*(rb-ra)), round(ga+u*(gb-ga)), round(ba_+u*(bb-ba_)))
    return stops[-1][1]


def _land(lon0, r, cx, cy, min_step, min_area):
    """Projected land polygons for the visible hemisphere, each as
    (points, mean_lat).

    Decimation is passed in rather than derived: the hero at r=148 and the 34px
    thumbnail need opposite trade-offs, and a single scaling rule got one of them
    wrong every time -- too coarse for the thumb, or 15KB of coastline for a
    shape the size of a fingernail."""
    W = json.load(open(WORLD_JSON))

    def proj(lon, lat):
        dl = math.radians(lon - lon0)
        while dl > math.pi: dl -= 2*math.pi
        while dl < -math.pi: dl += 2*math.pi
        p_ = math.radians(lat)
        if math.cos(dl) < 0: return None
        return cx + r*math.cos(p_)*math.sin(dl), cy - r*math.sin(p_)

    out = []
    for rec in W["countries"].values():
        d = rec.get("d") if isinstance(rec, dict) else rec
        if not d: continue
        for ring in rings(d):
            run, lats = [], []
            for x, y in ring:
                lon, lat = to_lonlat(x, y)
                pt = proj(lon, lat)
                if pt:
                    if run:
                        dx, dy = pt[0]-run[-1][0], pt[1]-run[-1][1]
                        if dx*dx + dy*dy < min_step*min_step:
                            continue
                    run.append(pt); lats.append(lat)
                else:
                    if len(run) >= 3: out.append((run, sum(lats)/len(lats)))
                    run, lats = [], []
            if len(run) >= 3:
                out.append((run, sum(lats)/len(lats)))
    keep = []
    for run, lat in out:
        xs = [q[0] for q in run]; ys = [q[1] for q in run]
        if (max(xs)-min(xs)) * (max(ys)-min(ys)) < min_area:
            continue
        keep.append((run, lat))
    return keep


def land_paths(lon0=20.0, r=17.0, cx=27.2, cy=20.0, min_step=1.15, min_area=1.6):
    """Bare land polygons, no field and no shading -- for the small
    black-and-white globe used as the 'Global' thumbnail."""
    return "".join(
        f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in run)}"/>'
        for run, _lat in _land(lon0, r, cx, cy, min_step, min_area))


# Latitude bands for the animated globe. The land's fill is field(mean latitude),
# and latitude does not change when the globe spins -- so the rings can be grouped
# into a handful of bands once, and the browser then updates one <path> per band
# rather than a hundred <polygon> elements a frame.
BANDS = list(range(-75, 90, 15))


def _band(lat):
    i = min(range(len(BANDS)), key=lambda k: abs(BANDS[k] - lat))
    return i


def land_lonlat(step=1.8, min_span=4.0):
    """Every coastline ring in lon/lat, decimated, grouped by latitude band.

    This is what the browser spins. Shipping coordinates rather than pre-rendered
    frames is the whole trick: one frame of projected geometry is 35KB, so a
    24-frame animation would be most of a megabyte, while the source coordinates
    are 20KB once and the projection is eight lines of arithmetic.

    Tenths of a degree, as integers -- "123" is shorter than "12.3" over 2000
    points, and a tenth of a degree is a quarter of a pixel at hero size."""
    W = json.load(open(WORLD_JSON))
    out = [[] for _ in BANDS]
    for rec in W["countries"].values():
        d = rec.get("d") if isinstance(rec, dict) else rec
        if not d:
            continue
        for ring in rings(d):
            pts, last = [], None
            for x, y in ring:
                lon, lat = to_lonlat(x, y)
                if last is not None:
                    dlon = abs(lon - last[0])
                    dlon = min(dlon, 360 - dlon)
                    if max(dlon * math.cos(math.radians(lat)),
                           abs(lat - last[1])) < step:
                        continue
                pts.append((lon, lat))
                last = (lon, lat)
            if len(pts) < 4:
                continue
            lons = [q[0] for q in pts]
            lats = [q[1] for q in pts]
            if max(max(lons) - min(lons), max(lats) - min(lats)) < min_span:
                continue
            flat = []
            for lon, lat in pts:
                flat.append(int(round(lon * 10)))
                flat.append(int(round(lat * 10)))
            out[_band(sum(lats) / len(lats))].append(flat)
    return {"bands": [field(b) for b in BANDS], "rings": out}


def build(lon0=20.0, r=150.0, cx=300.0, cy=160.0):
    """Equatorial orthographic view. With lat0=0 every parallel projects to a
    straight horizontal line, so the anomaly field is one vertical gradient --
    exact rather than approximated, and cheap."""
    land = _land(lon0, r, cx, cy, min_step=3.0, min_area=10.0)

    # gradient stops: offset from y = r*sin(lat)
    def grad(gid, warm):
        st = []
        for lat in range(90, -95, -5):
            off = (1 - math.sin(math.radians(lat))) / 2
            st.append(f'<stop offset="{off*100:.1f}%" stop-color="{field(lat, warm)}"/>')
        return f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">{"".join(st)}</linearGradient>'

    paras = "".join(
        f'<line x1="{cx-r*math.cos(math.radians(l)):.1f}" y1="{cy-r*math.sin(math.radians(l)):.1f}" '
        f'x2="{cx+r*math.cos(math.radians(l)):.1f}" y2="{cy-r*math.sin(math.radians(l)):.1f}"/>'
        for l in range(-60, 90, 30))
    # Meridians are the NEAR HALF only, one arc per longitude, pole to pole.
    #
    # Drawn as full ellipses they showed the far side too, and -- worse -- at 30
    # degree spacing the set of |sin(M - lon0)| values repeats every 30 degrees,
    # so the whole graticule returned to an identical configuration nine seconds
    # into every rotation. It pulsed in place while the continents travelled,
    # which read as a second static set of meridians. A half arc belongs to one
    # longitude, enters at one limb and leaves at the other, so it turns with the
    # land. rx collapsing to 0 at the centre is right: that meridian is edge-on,
    # and SVG draws a zero-radius arc as the straight line it should be.
    def meridian(m):
        a = math.radians(m - lon0)
        return (f'<path d="M{cx:.1f} {cy - r:.1f}A{abs(r * math.sin(a)):.1f} {r:.1f} '
                f'0 0 {1 if math.sin(a) > 0 else 0} {cx:.1f} {cy + r:.1f}"/>')
    merids = "".join(meridian(m) for m in range(0, 360, 30)
                     if math.cos(math.radians(m - lon0)) > 0.03)
    polys = "".join(
        f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in run)}" '
        f'fill="{field(lat)}" fill-opacity=".52"/>' for run, lat in land)

    # The viewBox height follows cy, so the disc is always vertically centred and
    # the poles cannot be clipped by a viewBox someone forgot to grow. Width stays
    # 600: the element's on-screen scale is width/600, so holding it fixed means r
    # is the only thing that changes the rendered size.
    vb_h = 2 * cy
    if r > cy - 2:
        raise SystemExit(f"globe: r={r} does not fit a viewBox of height {vb_h} "
                         f"(needs cy >= r + 2)")
    return f"""<svg class="hero-art" viewBox="0 0 600 {vb_h:.0f}" role="img"
 aria-label="Illustration: a globe centred on Africa and Europe, shaded with a climate anomaly gradient from cool at the poles through the hot subtropical belt">
<defs>
  {grad('gA', False)}
  {grad('gB', True)}
  <radialGradient id="limb" cx="50%" cy="50%" r="50%">
    <stop offset="62%" stop-color="#000" stop-opacity="0"/>
    <stop offset="92%" stop-color="#000" stop-opacity=".30"/>
    <stop offset="100%" stop-color="#000" stop-opacity=".55"/></radialGradient>
  <radialGradient id="spec" cx="33%" cy="28%" r="46%">
    <stop offset="0%" stop-color="#fff" stop-opacity=".30"/>
    <stop offset="100%" stop-color="#fff" stop-opacity="0"/></radialGradient>
  <clipPath id="disc"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>
</defs>
<g clip-path="url(#disc)">
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#gA)"/>
  <circle class="cyc" cx="{cx}" cy="{cy}" r="{r}" fill="url(#gB)"/>
  <g class="grat" fill="none" stroke="#000" stroke-opacity=".13" stroke-width=".7">
    {paras}<g id="gl-mer">{merids}</g></g>
  <g class="land" id="gl-land" stroke="#3a2a18" stroke-opacity=".34" stroke-width=".5"
     data-cx="{cx}" data-cy="{cy}" data-r="{r}" data-lon0="{lon0}">{polys}</g>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#limb)"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#spec)"/>
</g>
<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#000" stroke-opacity=".20" stroke-width="1"/>
</svg>"""


def icon(size=22):
    """Icon-scale globe for the compressed header. Same field gradient as the
    hero so they are visibly the same object; coastlines omitted because at 22px
    they degrade into speckle."""
    st = []
    for lat in range(90, -95, -10):
        off = (1 - math.sin(math.radians(lat))) / 2
        st.append(f'<stop offset="{off*100:.1f}%" stop-color="{field(lat)}"/>')
    r = size / 2 - 1
    c = size / 2
    return (f'<svg class="brandmark" viewBox="0 0 {size} {size}" aria-hidden="true">'
            f'<defs><linearGradient id="gi" x1="0" y1="0" x2="0" y2="1">{"".join(st)}</linearGradient>'
            f'<radialGradient id="li" cx="50%" cy="50%" r="50%">'
            f'<stop offset="60%" stop-color="#000" stop-opacity="0"/>'
            f'<stop offset="100%" stop-color="#000" stop-opacity=".45"/></radialGradient></defs>'
            f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="url(#gi)"/>'
            f'<g fill="none" stroke="#000" stroke-opacity=".28" stroke-width=".7">'
            f'<ellipse cx="{c}" cy="{c}" rx="{r*0.42:.1f}" ry="{r:.1f}"/>'
            f'<line x1="{c-r:.1f}" y1="{c}" x2="{c+r:.1f}" y2="{c}"/></g>'
            f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="url(#li)"/>'
            f'<circle cx="{c}" cy="{c}" r="{r:.1f}" fill="none" stroke="#000" '
            f'stroke-opacity=".22" stroke-width=".8"/></svg>')


def favicon():
    """Favicon as a data URI, so it costs no request and needs no entry in the
    Pages allowlist. A disc carrying the same field gradient as the hero globe:
    cool at the poles, hot through the middle. At 16px a graticule turns to
    stripes, so there is none -- the gradient alone reads as a planet."""
    stops = "".join(
        f'<stop offset="{(1 - math.sin(math.radians(lat))) / 2 * 100:.0f}%" '
        f'stop-color="{field(lat)}"/>'
        for lat in (90, 55, 20, -20, -55, -90))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>'
           '<radialGradient id="s" cx="36%" cy="30%" r="48%">'
           '<stop offset="0%" stop-color="#fff" stop-opacity=".34"/>'
           '<stop offset="100%" stop-color="#fff" stop-opacity="0"/></radialGradient></defs>'
           '<circle cx="16" cy="16" r="15" fill="url(#g)"/>'
           '<circle cx="16" cy="16" r="15" fill="url(#s)"/>'
           '<circle cx="16" cy="16" r="15" fill="none" stroke="#2b1c12" '
           'stroke-opacity=".55" stroke-width="1.6"/></svg>')
    return "data:image/svg+xml," + urllib.parse.quote(svg, safe="")
