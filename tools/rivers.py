"""Port of WorldGenerator.Pregenerate: lakes, rivers and streams (deep-north streams skipped)."""
import math
import numpy as np
from terrain import UnityRandom, f32

F = lambda v: float(f32(v))


def _merge_points(points, rng):
    out = []
    points = list(points)
    while points:
        v = points.pop(0)
        while points:
            best, bd = -1, 99999.0
            for i, q in enumerate(points):
                if q == v:
                    continue
                d = math.hypot(v[0] - q[0], v[1] - q[1])
                if d < rng and d < bd:
                    best, bd = i, d
            if best == -1:
                break
            q = points[best]
            v = (F((v[0] + q[0]) * 0.5), F((v[1] + q[1]) * 0.5))
            points[best] = points[-1]
            points.pop()
        out.append(v)
    return out


def find_lakes(wg):
    ys, xs = np.meshgrid(np.arange(-10000.0, 10000.0 + 1, 128.0), np.arange(-10000.0, 10000.0 + 1, 128.0), indexing="ij")
    xs, ys = xs.ravel(), ys.ravel()
    ok = np.hypot(xs, ys) <= 10000.0
    bh = wg.base_height(xs, ys)
    ok &= bh < 0.05
    pts = [(float(x), float(y)) for x, y in zip(xs[ok], ys[ok])]
    return _merge_points(pts, 800.0)


def _river_allowed_batch(wg, p0, ends, step=128.0, limit=0.4):
    """IsRiverAllowed for p0 -> each end, vectorised."""
    res = []
    segs = []
    for e in ends:
        dx, dy = e[0] - p0[0], e[1] - p0[1]
        d = math.hypot(dx, dy)
        nx, ny = (dx / d, dy / d) if d > 0 else (0.0, 0.0)
        ts = []
        t = step
        while t <= F(d - step):
            ts.append(t)
            t = F(t + step)
        segs.append((nx, ny, ts))
    allx, ally, owner = [], [], []
    for k, (nx, ny, ts) in enumerate(segs):
        for t in ts:
            allx.append(p0[0] + nx * t); ally.append(p0[1] + ny * t); owner.append(k)
    h = wg.base_height(np.array(allx), np.array(ally)) if allx else np.array([])
    owner = np.array(owner, dtype=np.int64)
    for k in range(len(ends)):
        hk = h[owner == k]
        if np.any(hk > limit):
            res.append(False)
        elif np.all(hk <= 0.05):
            res.append(False)
        else:
            res.append(True)
    return res


def _have_river(rivers, a, b=None):
    for r in rivers:
        if b is None:
            if r["p0"] == a or r["p1"] == a:
                return True
        elif (r["p0"] == a and r["p1"] == b) or (r["p0"] == b and r["p1"] == a):
            return True
    return False


def _random_end(wg, rnd, rivers, lakes, p, maxd):
    cand = [i for i, q in enumerate(lakes) if q != p and math.hypot(p[0] - q[0], p[1] - q[1]) < maxd and not _have_river(rivers, p, q)]
    if cand:
        ok = _river_allowed_batch(wg, p, [lakes[i] for i in cand])
        cand = [i for i, o in zip(cand, ok) if o]
    if not cand:
        return -1
    return cand[rnd.range_int(0, len(cand))]


def _river(p0, p1, wmin, wmax):
    d = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return dict(p0=p0, p1=p1, widthMin=wmin, widthMax=wmax, curveWidth=F(d / 15.0), curveWavelength=F(d / 20.0))


def place_rivers(wg, lakes):
    rnd = UnityRandom(wg.river_seed)
    rivers = []
    pending = list(lakes)
    while len(pending) > 1:
        v = pending[0]
        n = _random_end(wg, rnd, rivers, lakes, v, 2000.0)
        if n == -1 and not _have_river(rivers, v):
            n = _random_end(wg, rnd, rivers, lakes, v, 5000.0)
        if n != -1:
            wmax = rnd.range_float(60.0, 100.0)
            wmin = rnd.range_float(60.0, wmax)
            rivers.append(_river(v, lakes[n], wmin, wmax))
        else:
            pending.pop(0)
    render_rivers(wg, rivers, rnd)
    return rivers


def is_deepnorth(x, y):
    ang = math.sin(F(math.atan2(x, y)) * 20.0) * 100.0
    return math.hypot(x, y + 4000.0) > 12000.0 + ang


def render_rivers(wg, rivers, rnd, skip_deepnorth=False):
    for r in rivers:
        if skip_deepnorth and is_deepnorth(*r["p0"]):
            continue
        step = F(r["widthMin"] / 8.0)
        dx, dy = r["p1"][0] - r["p0"][0], r["p1"][1] - r["p0"][1]
        d = math.hypot(dx, dy)
        nx, ny = dx / d, dy / d
        px, py = -ny, nx
        t = 0.0
        while t <= d:
            a = F(t / r["curveWavelength"])
            off = math.sin(a) * math.sin(a * 0.634119987487793) * math.sin(a * 0.3341200053691864) * r["curveWidth"]
            w = rnd.range_float(r["widthMin"], r["widthMax"])
            x = r["p0"][0] + nx * t + px * off
            y = r["p0"][1] + ny * t + py * off
            gx = math.floor((x + 32.0) / 64.0)
            gy = math.floor((y + 32.0) / 64.0)
            k = math.ceil(w / 64.0)
            for j in range(gy - k, gy + k + 1):
                for i in range(gx - k, gx + k + 1):
                    if abs(x - i * 64.0) < w + 32.0 and abs(y - j * 64.0) < w + 32.0:
                        wg.river_points.setdefault((i, j), []).append((x, y, w))
            t = F(t + step)
    wg._rp_arrays.clear()


def place_streams(wg):
    rnd = UnityRandom(wg.stream_seed)
    streams = []
    for _ in range(3000):
        # FindStreamStartPoint: up to 100 tries of (x, y), height in (26, 31)
        trial = rnd.copy()
        xs, ys = [], []
        for _i in range(100):
            xs.append(trial.range_float(-10000.0, 10000.0)); ys.append(trial.range_float(-10000.0, 10000.0))
        h = wg.height(np.array(xs), np.array(ys), pregen=True)
        ok = np.nonzero((h > 26.0) & (h < 31.0))[0]
        used = (ok[0] + 1) if len(ok) else 100
        for _i in range(2 * used):
            rnd.next_u32()
        if not len(ok):
            continue
        p = (xs[ok[0]], ys[ok[0]])
        # FindStreamEndPoint: 100 tries, distance shrinking from 200 to 80
        trial = rnd.copy()
        step = F((200.0 - 80.0) / 100)
        dist = 200.0
        ex, ey = [], []
        for _i in range(100):
            dist = F(dist - step)
            f = trial.range_float(0.0, F(math.pi * 2))
            ex.append(F(p[0] + F(math.sin(f)) * dist)); ey.append(F(p[1] + F(math.cos(f)) * dist))
        h = wg.height(np.array(ex), np.array(ey), pregen=True)
        ok = np.nonzero((h > 36.0) & (h < 44.0))[0]
        used = (ok[0] + 1) if len(ok) else 100
        for _i in range(used):
            rnd.next_u32()
        if not len(ok):
            continue
        end = (ex[ok[0]], ey[ok[0]])
        c = (F((p[0] + end[0]) * 0.5), F((p[1] + end[1]) * 0.5))
        hc = float(wg.height(np.array([c[0]]), np.array([c[1]]), pregen=True)[0])
        if hc < 26.0 or hc > 44.0:
            continue
        streams.append(_river(p, end, 20.0, 20.0))
    render_rivers(wg, streams, rnd, skip_deepnorth=True)
    return streams


def pregenerate(wg):
    import time
    t0 = time.time()
    wg.lakes = find_lakes(wg)
    wg.rivers = place_rivers(wg, wg.lakes)
    t1 = time.time()
    wg.streams = place_streams(wg)
    print(f"pregenerate: {len(wg.lakes)} lakes, {len(wg.rivers)} rivers ({t1-t0:.0f}s), {len(wg.streams)} streams ({time.time()-t1:.0f}s)")
