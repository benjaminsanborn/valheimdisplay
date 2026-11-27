"""Low-detail terrain for everywhere players have explored, for flying between places (Huginn mode).

usage: export_world.py <world dir> <out dir (web/assets)>

The world is cut into 512 m tiles (8 x 8 zones) sampled every 4 m. Each tile is written in the same
layout as a place's terrain (see export_region.py) so the viewer draws it the same way, plus one byte
per vertex saying how explored it is:
    float32 height[n], uint8 weights[n * 12], uint8 variation[n], uint8 explored[n]     n = 129 * 129
Writes <out>/world/<tx>_<tz>.bin and <out>/world/tiles.json. A tile is only regenerated when the zones
explored in and around it change.

The trees and rocks the world save holds for each tile (outside places, which draw their own) go in
<out>/world/<tx>_<tz>.obj.bin, sorted by model:
    uint32 count, uint16 model[count] (index into tiles.json "models"), float32 pos[count * 3] (three.js
    coordinates: x, y, -z), int8 quat[count * 4] (* 127), uint16 scale[count * 3] (* 4096)
The model names are added to needed_models.txt so the build exports them.
"""
import hashlib, json, math, os, re, struct, sys

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

sys.path.insert(0, os.path.dirname(__file__))
import terrain, vworld  # noqa: E402
from export_region import euler_to_quat_rh, H_CREATOR, H_SCALE, H_SCALAR  # noqa: E402

TILE, STEP = 512, 4.0
N = int(TILE / STEP) + 1            # neighbouring tiles share their edge row, so there are no seams
WATER_LEVEL = 30.0
ZR = 170                            # the zone grid spans -170..170 zones (+-10880 m)
# natural things big enough to see from the air
WILD = re.compile(r'^(Beech|Birch|Oak|Pinetree|FirTree|SwampTree|YggaShoot|Rock_|rock|Rock|MineRock|cliff_|giant_|'
                  r'mudpile|HugeRoot|Bush|shrub|stubbe|caverock|ice_rock|silvervein|MineRock|AshlandsTree|Ashlands_rock|'
                  r'Leviathan|lighttree|cloudberry|HeathRockPillar|tarpit)', re.I)
WILD_SKIP = re.compile(r'_frac|_destruction|Pickable|log|Log|stub$|_broken|spawner|Seeds|Cone', re.I)
LAYER_OF = {terrain.MEADOWS: 0, terrain.BLACKFOREST: 1, terrain.SWAMP: 2, terrain.PLAINS: 3,
            terrain.MOUNTAIN: 4, terrain.DEEPNORTH: 4, terrain.OCEAN: 5, terrain.MISTLANDS: 1, terrain.ASHLANDS: 6}


def weights(wg, wxs, wzs, hgt):
    """Texture blend weights per vertex, as export_region.py does for a place (minus painted ground)."""
    biome = wg.biome(wxs, wzs)
    wts = np.zeros(hgt.shape + (12,))
    for b, layer in LAYER_OF.items():
        wts[..., layer] += biome == b
    for layer in range(12):          # soften hard biome borders (4 m, as in a place)
        wts[..., layer] = gaussian_filter(wts[..., layer], 4.0 / STEP)
    patch = np.clip((terrain.perlin(wxs * 0.03 + 7.3, wzs * 0.03 + 1.1) - 0.62) * 5, 0, 0.6)
    wts[..., 1] += wts[..., 0] * patch
    wts[..., 0] *= 1 - patch

    def overlay(layer, amount):
        nonlocal wts
        a = np.clip(amount, 0, 1)[..., None]
        wts = wts * (1 - a)
        wts[..., layer] += a[..., 0]

    gyy, gxx = np.gradient(hgt, STEP)
    overlay(5, (WATER_LEVEL + 1.5 - hgt) / 1.5)          # beach sand near / under water
    overlay(6, (np.hypot(gxx, gyy) - 0.8) / 0.5)          # cliffs
    wts /= np.maximum(wts.sum(-1, keepdims=True), 1e-6)
    return wts


def place_rects():
    """The zone-aligned squares places are exported over (as export_region.py does)."""
    rects = []
    places = json.load(open('data/places.json')) if os.path.exists('data/places.json') else []
    for p in places:
        r = p['radius']
        x0, x1 = math.floor((p['x'] - r + 32) / 64) * 64 - 32, math.floor((p['x'] + r + 32) / 64) * 64 + 32
        z0, z1 = math.floor((p['z'] - r + 32) / 64) * 64 - 32, math.floor((p['z'] + r + 32) / 64) * 64 + 32
        rects.append((x0, z0, x1, z1))
    return rects


def wild_objects(world, out):
    """Natural trees and rocks per tile, skipping those inside places and ones too small to matter."""
    names = {int(k): v for k, v in json.load(open('data/prefab_names.json')).items()}
    manifest_path = os.path.join(out, 'models.json')
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    rects = place_rects()
    per_tile, models = {}, {}
    for z in vworld.read_zdos(world):
        if H_CREATOR in z.longs:
            continue
        name = names.get(z.prefab)
        if not name or not WILD.match(name) or WILD_SKIP.search(name):
            continue
        x, y, zz = z.pos
        if y > 1000 or any(a <= x <= c and b <= zz <= d for a, b, c, d in rects):
            continue
        sc = z.vec3s.get(H_SCALE)
        if sc is None and H_SCALAR in z.floats:
            sc = (z.floats[H_SCALAR],) * 3
        sc = sc or (1.0, 1.0, 1.0)
        mi = manifest.get(name)
        if mi and (mi['max'][1] - mi['min'][1]) * sc[1] < 1.0:   # pebbles and little shrubs
            continue
        q = euler_to_quat_rh(*z.rot)
        key = (math.floor((x + 32) / TILE), math.floor((zz + 32) / TILE))
        per_tile.setdefault(key, []).append((models.setdefault(name, len(models)), x, y, -zz, q, sc))
    return per_tile, list(models)


def write_objects(path, items):
    items.sort(key=lambda o: o[0])
    n = len(items)
    buf = bytearray(struct.pack('<I', n))
    buf += np.array([o[0] for o in items], dtype=np.uint16).tobytes()
    buf += np.array([o[1:4] for o in items], dtype=np.float32).tobytes()
    buf += np.clip(np.round(np.array([o[4] for o in items]) * 127), -127, 127).astype(np.int8).tobytes()
    buf += np.clip(np.round(np.array([o[5] for o in items]) * 4096), 0, 65535).astype(np.uint16).tobytes()
    sig = hashlib.sha1(buf).hexdigest()[:12]
    old = open(path, 'rb').read() if os.path.exists(path) else None
    if old != bytes(buf):
        open(path, 'wb').write(buf)
        if os.path.exists(path + '.gz'):
            os.remove(path + '.gz')
    return sig


def main():
    world, out = sys.argv[1], sys.argv[2]
    meta = vworld.read_meta(world)
    zones = {z for z in vworld.read_generated_zones(world) if abs(z[0]) <= ZR and abs(z[1]) <= ZR}
    grid = np.zeros((2 * ZR + 1, 2 * ZR + 1))        # [zz + ZR, zx + ZR]
    for zx, zz in zones:
        grid[zz + ZR, zx + ZR] = 1.0
    explored = np.clip(gaussian_filter(grid, 0.8) * 1.6, 0, 1)

    # tile (tx, tz) holds zones tx*8 .. tx*8+7; its grid starts at the south-west corner of the first zone
    tiles = sorted({(zx // 8, zz // 8) for zx, zz in zones})
    folder = os.path.join(out, 'world')
    os.makedirs(folder, exist_ok=True)
    manifest_path = os.path.join(folder, 'tiles.json')
    old = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    old_sig = {tuple(t[:2]): t[2] for t in old.get('tiles', [])} if old.get('seed') == meta.seed_name else {}

    wild, wild_models = wild_objects(world, out)
    wg = None
    made = 0
    listed = []
    for tx, tz in tiles:
        # what's explored in and next to the tile decides how it looks
        near = grid[tz * 8 + ZR - 1: tz * 8 + ZR + 10, tx * 8 + ZR - 1: tx * 8 + ZR + 10]
        sig = hashlib.sha1(np.packbits(near.astype(bool)).tobytes()).hexdigest()[:12]
        items = wild.get((tx, tz))
        listed.append([tx, tz, sig, write_objects(os.path.join(folder, f'{tx}_{tz}.obj.bin'), items) if items else None])
        path = os.path.join(folder, f'{tx}_{tz}.bin')
        if old_sig.get((tx, tz)) == sig and os.path.exists(path):
            continue
        if wg is None:
            wg = terrain.WorldGen(meta.seed, meta.worldgen_version, rivers=True)
        ox, oz = tx * TILE - 32.0, tz * TILE - 32.0
        k = np.arange(N) * STEP
        wxs, wzs = np.meshgrid(ox + k, oz + k)            # rows = z ascending, as in a place
        hgt = wg.height(wxs, wzs)
        wts = weights(wg, wxs, wzs, hgt)
        variation = terrain.perlin(wxs * 0.05, wzs * 0.05) * 0.6 + terrain.perlin(wxs * 0.2 + 3, wzs * 0.2) * 0.4
        # zone centres sit at multiples of 64 m
        exp = map_coordinates(explored, [wzs / 64.0 + ZR, wxs / 64.0 + ZR], order=1, mode='constant')
        with open(path, 'wb') as f:
            f.write(hgt.astype(np.float32).tobytes())
            f.write(np.round(wts * 255).astype(np.uint8).tobytes())
            f.write(np.clip(variation * 255, 0, 255).astype(np.uint8).tobytes())
            f.write(np.clip(exp * 255, 0, 255).astype(np.uint8).tobytes())
        for stale in (path + '.gz',):
            if os.path.exists(stale):
                os.remove(stale)
        made += 1
    keep = {f'{tx}_{tz}.bin' for tx, tz, *_ in listed} | {f'{tx}_{tz}.obj.bin' for tx, tz, _, o in listed if o}
    for name in os.listdir(folder):
        if name.endswith(('.bin', '.bin.gz')) and name.replace('.gz', '') not in keep:
            os.remove(os.path.join(folder, name))
    json.dump(dict(seed=meta.seed_name, tile=TILE, step=STEP, n=N, water=WATER_LEVEL, models=wild_models, tiles=listed),
              open(manifest_path, 'w'), separators=(',', ':'))
    # the build exports every model something needs
    need = os.path.join(out, 'needed_models.txt')
    have = set(open(need).read().split()) if os.path.exists(need) else set()
    open(need, 'w').write('\n'.join(sorted(have | set(wild_models))) + '\n')
    n_wild = sum(len(v) for v in wild.values())
    print(f'world tiles: {len(listed)} ({made} regenerated), {len(zones)} explored zones, {n_wild} trees and rocks')


if __name__ == '__main__':
    main()
