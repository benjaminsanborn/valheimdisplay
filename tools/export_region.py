"""Export one region of the world (terrain + objects) for the web viewer.

usage: export_region.py <world dir> <out dir> <slug> <title> <x> <z> [radius]

Writes <out>/regions/<slug>.json + <slug>.terrain.bin and appends the
prefab names it needs to <out>/needed_models.txt.
Coordinates in the output are three.js (right-handed): (x, y, -z_unity).
"""
from __future__ import annotations

import gzip
import json
import math
import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import terrain  # noqa: E402
import vworld  # noqa: E402
from vworld import stable_hash  # noqa: E402

H_CREATOR = stable_hash('creator')
H_TEXT = stable_hash('text')
H_TAG = stable_hash('tag')
H_TCDATA = stable_hash('TCData')
H_SCALE = stable_hash('scale')
H_SCALAR = stable_hash('scaleScalar')
H_CREATOR_NAME = stable_hash('creatorName')
TC = stable_hash('_TerrainCompiler')

# Things that are never worth drawing (effects, spawners, creatures, loose items).
SKIP_SUBSTR = ('spawner', 'Spawner', '_TerrainCompiler', 'LocationProxy', 'ZoneCtrl', 'sfx_', 'vfx_', 'fx_',
               'Player', 'Ragdoll', 'projectile', 'Wishbone')
SKIP_EXACT = {'Boar', 'Neck', 'Deer', 'Greyling', 'Greydwarf', 'Greydwarf_Elite', 'Greydwarf_Shaman', 'Troll', 'Skeleton',
              'Draugr', 'Draugr_Elite', 'Blob', 'Leech', 'Wraith', 'Surtling', 'Wolf', 'Drake', 'Goblin', 'Lox', 'Deathsquito',
              'Serpent', 'Crow', 'Seagal', 'Fish1', 'Fish2', 'Fish3', 'Hen', 'Chicken', 'Ghost', 'Bat', 'Abomination', 'Fenring',
              'Ulv', 'StoneGolem', 'Hatchling', 'Odin', 'Wolf_cub', 'Boar_piggy', 'Lox_Calf', 'Tick', 'Seeker', 'Gjall',
              'Dverger', 'Hare', 'Neck_Ragdoll', 'Greyling_Ragdoll', 'Deer_ragdoll'}

GROUND_TYPES = ('Pickable_', 'Beech', 'FirTree', 'Pinetree', 'Birch', 'Oak', 'Bush', 'SwampTree', 'shrub', 'Rock_', 'rock')


def euler_to_quat_rh(ex, ey, ez):
    """Unity Quaternion.Euler (degrees, applied Z, X, Y) -> quaternion in three.js (z-mirrored) space."""
    hx, hy, hz = (math.radians(a) * 0.5 for a in (ex, ey, ez))
    cx, sx, cy, sy, cz, sz = math.cos(hx), math.sin(hx), math.cos(hy), math.sin(hy), math.cos(hz), math.sin(hz)
    # q = qy * qx * qz
    w = cy * cx * cz + sy * sx * sz
    x = cy * sx * cz + sy * cx * sz
    y = sy * cx * cz - cy * sx * sz
    z = cy * cx * sz - sy * sx * cz
    return (-x, -y, z, w)


def read_terrain_comp(z):
    data = z.bytearrays.get(H_TCDATA)
    if not data:
        return None
    r = vworld.Reader(gzip.decompress(data))
    r.int()
    r.int()
    r.vec3()
    r.float()
    n = r.int()
    level = np.zeros(n)
    smooth = np.zeros(n)
    for i in range(n):
        if r.bool():
            level[i] = r.float()
            smooth[i] = r.float()
    m = r.int()
    paint = np.zeros((m, 4))
    painted = np.zeros(m, dtype=bool)
    for i in range(m):
        if r.bool():
            paint[i] = (r.float(), r.float(), r.float(), r.float())
            painted[i] = True
    return level, smooth, paint, painted


BIOME_COLORS = {
    terrain.MEADOWS: (0.42, 0.55, 0.20),
    terrain.BLACKFOREST: (0.30, 0.36, 0.17),
    terrain.SWAMP: (0.33, 0.30, 0.18),
    terrain.MOUNTAIN: (0.88, 0.90, 0.95),
    terrain.PLAINS: (0.62, 0.58, 0.30),
    terrain.OCEAN: (0.62, 0.56, 0.40),
    terrain.MISTLANDS: (0.33, 0.33, 0.30),
    terrain.ASHLANDS: (0.30, 0.18, 0.14),
    terrain.DEEPNORTH: (0.85, 0.90, 0.95),
}
SAND = np.array((0.76, 0.68, 0.48))
ROCK = np.array((0.42, 0.40, 0.38))
DIRT = np.array((0.42, 0.32, 0.20))
CULTIVATED = np.array((0.30, 0.22, 0.13))
PAVED = np.array((0.50, 0.48, 0.45))
WATER_LEVEL = 30.0


def main():
    world, out, slug, title = sys.argv[1:5]
    cx, cz = float(sys.argv[5]), float(sys.argv[6])
    radius = float(sys.argv[7]) if len(sys.argv) > 7 else 160.0
    names = {int(k): v for k, v in json.load(open(os.path.join(os.path.dirname(world.rstrip('/')), 'prefab_names.json'))).items()}
    meta = vworld.read_meta(world)

    zx0 = math.floor((cx - radius + 32) / 64)
    zx1 = math.floor((cx + radius + 32) / 64)
    zz0 = math.floor((cz - radius + 32) / 64)
    zz1 = math.floor((cz + radius + 32) / 64)
    nzx, nzz = zx1 - zx0 + 1, zz1 - zz0 + 1
    ox, oz = zx0 * 64 - 32.0, zz0 * 64 - 32.0  # unity world coords of grid [0, 0]
    W, D = nzx * 64 + 1, nzz * 64 + 1
    print(f'{slug}: zones x {zx0}..{zx1} z {zz0}..{zz1} -> grid {W}x{D}', file=sys.stderr)

    print('reading world...', file=sys.stderr)
    xmin, xmax, zmin, zmax = ox, ox + (W - 1), oz, oz + (D - 1)
    zdos = [z for z in vworld.read_zdos(world) if xmin <= z.pos[0] <= xmax and zmin <= z.pos[2] <= zmax]

    wg = terrain.WorldGen(meta.seed, meta.worldgen_version, rivers=False)
    hgt = np.zeros((D, W))
    base = np.zeros((D, W))
    paint = np.zeros((D, W, 4))
    painted = np.zeros((D, W), dtype=bool)
    tcs = {}
    for z in zdos:
        if z.prefab == TC:
            key = (math.floor((z.pos[0] + 32) / 64), math.floor((z.pos[2] + 32) / 64))
            tcs[key] = z
    for j in range(nzz):
        for i in range(nzx):
            zx, zz = zx0 + i, zz0 + j
            hm, _ = wg.zone_heightmap(zx, zz)
            sl = (slice(j * 64, j * 64 + 65), slice(i * 64, i * 64 + 65))
            base[sl] = hm
            h = hm.copy()
            tc = tcs.get((zx, zz))
            if tc is not None:
                res = read_terrain_comp(tc)
                if res:
                    level, smooth, pnt, pd = res
                    if len(level) == 65 * 65:
                        d = (level + smooth).reshape(65, 65)
                        h = np.where(d != 0, np.clip(hm + d, hm - 8, hm + 8), hm)
                    if len(pnt) == 65 * 65:
                        pm = paint[sl]
                        pdm = painted[sl]
                        pm[pd.reshape(65, 65)] = pnt[pd].reshape(-1, 4)
                        pdm |= pd.reshape(65, 65)
            hgt[sl] = h

    # Correct terrain where our generator disagrees with the real ground (rivers, location
    # terrain modifiers): use naturally placed objects as ground-truth height samples.
    samp = [z for z in zdos if z.pos[1] != 0 and (
        (H_CREATOR not in z.longs and names.get(z.prefab, '').startswith(GROUND_TYPES[:7]))
        or names.get(z.prefab, '').startswith('sapling_'))]  # planted crops sit exactly on the ground
    corrected = 0
    if samp:
        from scipy.spatial import cKDTree
        sx = np.array([z.pos[0] for z in samp]) - ox
        sz = np.array([z.pos[2] for z in samp]) - oz
        sy = np.array([z.pos[1] for z in samp])
        gi = np.clip(np.round(sx).astype(int), 0, W - 1)
        gj = np.clip(np.round(sz).astype(int), 0, D - 1)
        resid = sy - hgt[gj, gi]
        tree = cKDTree(np.stack([sx, sz], 1))
        gz, gx = np.mgrid[0:D, 0:W]
        pts = np.stack([gx.ravel(), gz.ravel()], 1).astype(float)
        dist, idx = tree.query(pts, k=12, distance_upper_bound=40.0)
        valid = np.isfinite(dist)
        sigma = 8.0
        w = np.where(valid, np.exp(-(np.where(valid, dist, 0) ** 2) / (2 * sigma * sigma)), 0.0)
        r = np.where(valid, resid[np.minimum(idx, len(resid) - 1)], 0.0)
        # median-ish robustness: clip extreme residuals from objects not on the ground
        r = np.clip(r, -30, 30)
        num = (w * r).sum(1)
        den = w.sum(1)
        corr = (num / (den + 0.05)).reshape(D, W)
        big = np.abs(corr) > 0.3
        corrected = int(big.sum())
        hgt = hgt + np.where(big, corr, 0.0)

    # texture blend weights per vertex (layers match export_terrain_textures.py)
    from scipy.ndimage import gaussian_filter
    gz, gx = np.mgrid[0:D, 0:W]
    wxs = (ox + gx).astype(float)
    wzs = (oz + gz).astype(float)
    biome = wg.biome(wxs, wzs)
    NL = 12
    wts = np.zeros((D, W, NL))
    layer_of = {terrain.MEADOWS: 0, terrain.BLACKFOREST: 1, terrain.SWAMP: 2, terrain.PLAINS: 3,
                terrain.MOUNTAIN: 4, terrain.DEEPNORTH: 4, terrain.OCEAN: 5, terrain.MISTLANDS: 1, terrain.ASHLANDS: 6}
    for b, l in layer_of.items():
        wts[..., l] += biome == b
    for l in range(NL):  # soften hard biome borders
        wts[..., l] = gaussian_filter(wts[..., l], 4.0)
    # meadows: patches of forest floor for variety
    patch = np.clip((terrain.perlin(wxs * 0.03 + 7.3, wzs * 0.03 + 1.1) - 0.62) * 5, 0, 0.6)
    wts[..., 1] += wts[..., 0] * patch
    wts[..., 0] *= 1 - patch

    def overlay(layer, amount):
        nonlocal wts
        a = np.clip(amount, 0, 1)[..., None]
        wts = wts * (1 - a)
        wts[..., layer] += a[..., 0]

    gyy, gxx = np.gradient(hgt)
    slope = np.hypot(gxx, gyy)
    overlay(5, (WATER_LEVEL + 1.5 - hgt) / 1.5)          # beach sand near / under water
    overlay(6, (slope - 0.8) / 0.5)                      # cliffs
    if painted.any():
        m = painted.astype(float)
        overlay(7, paint[..., 0] * m)                    # dirt (paths, levelled ground)
        overlay(8, paint[..., 1] * m)                    # cultivated
        overlay(9, paint[..., 2] * m)                    # paved
    wts /= np.maximum(wts.sum(-1, keepdims=True), 1e-6)
    variation = (terrain.perlin(wxs * 0.05, wzs * 0.05) * 0.6 + terrain.perlin(wxs * 0.2 + 3, wzs * 0.2) * 0.4)
    # objects
    objects = []
    labels = []
    model_index = {}
    built = 0
    for z in zdos:
        name = names.get(z.prefab)
        if not name or name in SKIP_EXACT or any(s in name for s in SKIP_SUBSTR):
            continue
        is_built = H_CREATOR in z.longs
        built += is_built
        if name not in model_index:
            model_index[name] = len(model_index)
        x, y, zz = z.pos
        q = euler_to_quat_rh(*z.rot)
        sc = z.vec3s.get(H_SCALE)
        if sc is None and H_SCALAR in z.floats:
            s = z.floats[H_SCALAR]
            sc = (s, s, s)
        sc = sc or (1.0, 1.0, 1.0)
        objects.append([model_index[name], round(x - cx, 3), round(y, 3), round(-(zz - cz), 3),
                        round(q[0], 5), round(q[1], 5), round(q[2], 5), round(q[3], 5),
                        round(sc[0], 3), round(sc[1], 3), round(sc[2], 3), 1 if is_built else 0])
        text = z.strings.get(H_TEXT) or z.strings.get(H_TAG)
        if text and is_built:
            labels.append(dict(text=text[:60], kind=name, pos=[round(x - cx, 2), round(y, 2), round(-(zz - cz), 2)],
                               world=[round(x, 2), round(zz, 2)]))

    os.makedirs(os.path.join(out, 'regions'), exist_ok=True)
    # terrain binary, row-major (rows = unity z ascending):
    #   float32 height[n], uint8 weights[n * 12], uint8 variation[n]
    with open(os.path.join(out, 'regions', f'{slug}.terrain.bin'), 'wb') as f:
        f.write(hgt.astype(np.float32).tobytes())
        f.write(np.round(wts * 255).astype(np.uint8).tobytes())
        f.write(np.clip(variation * 255, 0, 255).astype(np.uint8).tobytes())
    info = dict(
        slug=slug, title=title, center=[cx, cz], seed=meta.seed_name,
        grid=dict(w=W, d=D, x0=ox - cx, z0=oz - cz, step=1.0),
        water=WATER_LEVEL,
        terrain_format=2,
        models=list(model_index.keys()),
        objects=objects,
        labels=labels,
        stats=dict(objects=len(objects), built=built, models=len(model_index), corrected_vertices=corrected,
                   edited_zones=len(tcs)),
    )
    json.dump(info, open(os.path.join(out, 'regions', f'{slug}.json'), 'w'), separators=(',', ':'))
    need = os.path.join(out, 'needed_models.txt')
    have = set(open(need).read().split()) if os.path.exists(need) else set()
    have |= set(model_index)
    open(need, 'w').write('\n'.join(sorted(have)) + '\n')
    print(json.dumps(info['stats']), file=sys.stderr)


if __name__ == '__main__':
    main()
