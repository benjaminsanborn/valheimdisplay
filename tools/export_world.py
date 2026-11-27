"""Low-detail terrain for everywhere players have explored, for flying between places (Huginn mode).

usage: export_world.py <world dir> <out dir (web/assets)>

The world is cut into 512 m tiles (8 x 8 zones) sampled every 4 m. Each tile is written in the same
layout as a place's terrain (see export_region.py) so the viewer draws it the same way, plus one byte
per vertex saying how explored it is:
    float32 height[n], uint8 weights[n * 12], uint8 variation[n], uint8 explored[n]     n = 129 * 129
Writes <out>/world/<tx>_<tz>.bin and <out>/world/tiles.json. A tile is only regenerated when the zones
explored in and around it change.
"""
import hashlib, json, os, sys

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates

sys.path.insert(0, os.path.dirname(__file__))
import terrain, vworld  # noqa: E402

TILE, STEP = 512, 4.0
N = int(TILE / STEP) + 1            # neighbouring tiles share their edge row, so there are no seams
WATER_LEVEL = 30.0
ZR = 170                            # the zone grid spans -170..170 zones (+-10880 m)
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

    wg = None
    made = 0
    listed = []
    for tx, tz in tiles:
        # what's explored in and next to the tile decides how it looks
        near = grid[tz * 8 + ZR - 1: tz * 8 + ZR + 10, tx * 8 + ZR - 1: tx * 8 + ZR + 10]
        sig = hashlib.sha1(np.packbits(near.astype(bool)).tobytes()).hexdigest()[:12]
        listed.append([tx, tz, sig])
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
    keep = {f'{tx}_{tz}.bin' for tx, tz, _ in listed}
    for name in os.listdir(folder):
        if name.endswith(('.bin', '.bin.gz')) and name.replace('.gz', '') not in keep:
            os.remove(os.path.join(folder, name))
    json.dump(dict(seed=meta.seed_name, tile=TILE, step=STEP, n=N, water=WATER_LEVEL, tiles=listed),
              open(manifest_path, 'w'), separators=(',', ':'))
    print(f'world tiles: {len(listed)} ({made} regenerated), {len(zones)} explored zones')


if __name__ == '__main__':
    main()
