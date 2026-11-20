"""Render a round world map (biomes + hill shading) with unexplored areas fogged.

usage: export_worldmap.py <world dir> <out png> [size]
Explored = zones the server has generated (players have been nearby).
"""
import os, sys
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, zoom

sys.path.insert(0, os.path.dirname(__file__))
import terrain, vworld

world, out = sys.argv[1], sys.argv[2]
N = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
R = 10500.0
meta = vworld.read_meta(world)
wg = terrain.WorldGen(meta.seed, meta.worldgen_version, rivers=False)

c = (np.arange(N) + 0.5) / N * 2 * R - R
X, Z = np.meshgrid(c, -c)          # image row 0 = north (+z)
h = np.zeros((N, N))
b = np.zeros((N, N), dtype=np.int32)
for i in range(0, N, 64):          # in strips to keep memory down
    xs, zs = X[i:i + 64], Z[i:i + 64]
    b[i:i + 64] = wg.biome(xs, zs)
    h[i:i + 64] = wg.height(xs, zs)

PAL = {terrain.MEADOWS: (110, 150, 62), terrain.BLACKFOREST: (52, 82, 42), terrain.SWAMP: (104, 86, 58),
       terrain.MOUNTAIN: (226, 232, 240), terrain.PLAINS: (198, 182, 98), terrain.OCEAN: (52, 104, 140),
       terrain.MISTLANDS: (96, 88, 112), terrain.ASHLANDS: (136, 52, 38), terrain.DEEPNORTH: (210, 226, 240)}
img = np.zeros((N, N, 3))
for k, v in PAL.items():
    img[b == k] = v
water = h < 30.0
depth = np.clip((30.0 - h) / 60.0, 0, 1)[..., None]
img = np.where(water[..., None], np.array([70, 128, 160]) * (1 - depth) + np.array([24, 58, 92]) * depth, img)
beach = (~water) & (h < 31.5)
img[beach] = img[beach] * 0.4 + np.array([200, 186, 140]) * 0.6
# hill shading from the north-west
px = 2 * R / N
gy, gx = np.gradient(np.where(water, 30.0, h), px)
shade = np.clip(1.0 + (-gx + gy) * 2.2, 0.7, 1.3)[..., None]
img = np.where(water[..., None], img, img * shade)
# fog of war: zones players have been near
zones = [z for z in vworld.read_generated_zones(world) if abs(z[0]) <= 170 and abs(z[1]) <= 170]
zr = 170
grid = np.zeros((2 * zr + 1, 2 * zr + 1))
for zx, zz in zones:
    grid[zr - zz, zx + zr] = 1.0     # row 0 = north
grid = gaussian_filter(grid, 0.8)
explored = zoom(grid, N / grid.shape[0], order=1)
explored = np.clip(explored[:N, :N] * 1.6, 0, 1)
# Zone grid spans -170..170 zones = +-10880 m; crop to +-R
scale = (2 * zr + 1) * 64 / (2 * R)
cy = cx = explored.shape[0] / 2
ii = (np.arange(N) - N / 2) * scale + cy
explored = explored[np.clip(ii.astype(int), 0, N - 1)][:, np.clip(ii.astype(int), 0, N - 1)]
grey = gaussian_filter(img.mean(-1), 3.0)[..., None]
fog = np.array([46, 50, 58]) * 0.75 + grey * 0.22
e = explored[..., None]
r = np.hypot(X, Z)
alpha = np.clip((R - r) / (px * 1.5), 0, 1)


def write(path, pixels):
    pixels = pixels.copy()
    pixels[r > R] = (0, 0, 0)
    Image.fromarray(np.dstack([np.clip(pixels, 0, 255), alpha * 255]).astype(np.uint8), 'RGBA').save(path, optimize=True)


write(out, img * e + fog * (1 - e))            # today's map, fog of war baked in
# for the timelapse the browser draws the fog itself: an unfogged map plus an all-fog layer
base = out[:-4] if out.endswith('.png') else out
write(base + '_color.png', img)
write(base + '_fog.png', fog * np.ones_like(img))
print(f'world map {N}px, {len(zones)} explored zones -> {out}')
