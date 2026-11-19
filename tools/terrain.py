"""Port of Valheim's WorldGenerator height/biome functions (numpy-vectorized).

Source: decompiled assembly_valheim.dll (WorldGenerator, HeightmapBuilder),
plus re-implementations of UnityEngine.Mathf.PerlinNoise and UnityEngine.Random.
Ashlands / Deep North specific shapes are not ported (they fall back to forest
height); everything within ~8 km of the world centre is covered.
"""
from __future__ import annotations

import math

import numpy as np

f32 = np.float32

# ---------------------------------------------------------------- Unity Random

class UnityRandom:
    """UnityEngine.Random (Xorshift128)."""

    def __init__(self, seed: int):
        s0 = seed & 0xFFFFFFFF
        s1 = (s0 * 1812433253 + 1) & 0xFFFFFFFF
        s2 = (s1 * 1812433253 + 1) & 0xFFFFFFFF
        s3 = (s2 * 1812433253 + 1) & 0xFFFFFFFF
        self.s = [s0, s1, s2, s3]

    def copy(self):
        r = UnityRandom.__new__(UnityRandom)
        r.s = list(self.s)
        return r

    def next_u32(self) -> int:
        s0, s1, s2, s3 = self.s
        t = (s0 ^ (s0 << 11)) & 0xFFFFFFFF
        s3n = (s3 ^ (s3 >> 19) ^ t ^ (t >> 8)) & 0xFFFFFFFF
        self.s = [s1, s2, s3, s3n]
        return s3n

    def value(self) -> float:
        return float(f32(self.next_u32() & 0x7FFFFF) * f32(1.0 / 8388607.0))

    def range_float(self, lo: float, hi: float) -> float:
        t = f32(self.value())
        return float(f32(f32(1.0) - t) * f32(lo) + t * f32(hi))

    def range_int(self, lo: int, hi: int) -> int:
        if hi > lo:
            span = (hi - lo) & 0xFFFFFFFF
            r = lo + (self.next_u32() % span)
        elif hi < lo:
            span = (lo - hi) & 0xFFFFFFFF
            r = lo - (self.next_u32() % span)
        else:
            return lo
        r &= 0xFFFFFFFF
        return r - (1 << 32) if r & 0x80000000 else r


# ---------------------------------------------------------------- Unity Perlin

_P = [151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225, 140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23,
      190, 6, 148, 247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32, 57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175, 74, 165, 71, 134, 139, 48, 27, 166,
      77, 146, 158, 231, 83, 111, 229, 122, 60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54, 65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169, 200, 196,
      135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64, 52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212, 207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42,
      223, 183, 170, 213, 119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9, 129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104, 218, 246, 97, 228,
      251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241, 81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157, 184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254,
      138, 236, 205, 93, 222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180]
PERM = np.array(_P + _P, dtype=np.int32)


def _grad(h, x, y):
    # Ken Perlin's improved-noise gradient, 3D with z = 0
    h = h & 15
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, f32(0)))
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


def perlin(x, y):
    """UnityEngine.Mathf.PerlinNoise(x, y) -> roughly [0, 1]."""
    x = np.asarray(x, dtype=f32)
    y = np.asarray(y, dtype=f32)
    fx = np.floor(x)
    fy = np.floor(y)
    X = fx.astype(np.int64) & 255
    Y = fy.astype(np.int64) & 255
    x = (x - fx).astype(f32)
    y = (y - fy).astype(f32)
    u = x * x * x * (x * (x * f32(6) - f32(15)) + f32(10))
    v = y * y * y * (y * (y * f32(6) - f32(15)) + f32(10))
    A = PERM[X] + Y
    B = PERM[X + 1] + Y
    # 3D improved noise with z = 0: AA = p[A] + 0, hash = p[AA]
    g00 = _grad(PERM[PERM[A]], x, y)
    g10 = _grad(PERM[PERM[B]], x - f32(1), y)
    g01 = _grad(PERM[PERM[A + 1]], x, y - f32(1))
    g11 = _grad(PERM[PERM[B + 1]], x - f32(1), y - f32(1))
    a = g00 + u * (g10 - g00)
    b = g01 + u * (g11 - g01)
    n = a + v * (b - a)
    return ((n + f32(0.69)) / f32(1.483)).astype(np.float64)


PN = perlin

# ---------------------------------------------------------------- helpers


def lerp_step(l, h, v):
    return np.clip((v - l) / (h - l), 0.0, 1.0)


def smooth_step(lo, hi, x):
    t = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def world_angle(wx, wy):
    return np.sin(np.arctan2(wx, wy).astype(f32) * 20.0)


# biome ids (Heightmap.Biome flags)
MEADOWS, SWAMP, MOUNTAIN, BLACKFOREST, PLAINS, ASHLANDS, DEEPNORTH, OCEAN, MISTLANDS = 1, 2, 4, 8, 16, 32, 64, 256, 512
BIOME_NAMES = {MEADOWS: "Meadows", SWAMP: "Swamp", MOUNTAIN: "Mountain", BLACKFOREST: "BlackForest", PLAINS: "Plains",
               ASHLANDS: "AshLands", DEEPNORTH: "DeepNorth", OCEAN: "Ocean", MISTLANDS: "Mistlands"}


class WorldGen:
    def __init__(self, seed: int, worldgen_version: int = 2, rivers: bool = True):
        self.seed = seed
        self.min_mountain_distance = 1500.0 if worldgen_version <= 0 else 1000.0
        self.min_darkland_noise = 0.5 if worldgen_version <= 1 else 0.4
        self.max_marsh_distance = 8000.0 if worldgen_version <= 1 else 6000.0
        rnd = UnityRandom(seed)
        self.o0 = float(rnd.range_int(-10000, 10000))
        self.o1 = float(rnd.range_int(-10000, 10000))
        self.o2 = float(rnd.range_int(-10000, 10000))
        self.o3 = float(rnd.range_int(-10000, 10000))
        self.river_seed = rnd.range_int(-2**31, 2**31 - 1)
        self.stream_seed = rnd.range_int(-2**31, 2**31 - 1)
        self.o4 = float(rnd.range_int(-10000, 10000))
        self.river_points: dict[tuple, list] = {}
        self._rp_arrays: dict[tuple, np.ndarray] = {}
        if rivers:
            from rivers import pregenerate
            pregenerate(self)

    # -- base height -----------------------------------------------------------
    def base_height(self, wx, wy):
        wx = np.asarray(wx, dtype=np.float64)
        wy = np.asarray(wy, dtype=np.float64)
        dist = np.hypot(wx, wy)
        x = wx + 100000.0 + self.o0
        y = wy + 100000.0 + self.o1
        h = PN(x * 0.002 * 0.5, y * 0.002 * 0.5) * PN(x * 0.003 * 0.5, y * 0.003 * 0.5)
        h = h + PN(x * 0.002, y * 0.002) * PN(x * 0.003, y * 0.003) * h * 0.9
        h = h + PN(x * 0.005, y * 0.005) * PN(x * 0.01, y * 0.01) * 0.5 * h
        h = h - 0.07
        n10 = PN(x * 0.002 * 0.25 + 0.123, y * 0.002 * 0.25 + 0.15123)
        n11 = PN(x * 0.002 * 0.25 + 0.321, y * 0.002 * 0.25 + 0.231)
        v = np.abs(n10 - n11)
        r = 1.0 - lerp_step(0.02, 0.12, v)
        r = r * smooth_step(744.0, 1000.0, dist)
        h = h * (1.0 - r)
        # world edge
        edge = dist > 10000.0
        if np.any(edge):
            he = lerp(h, -0.2, lerp_step(10000.0, 10500.0, dist))
            he = np.where(dist > 10490.0, lerp(he, -2.0, lerp_step(10490.0, 10500.0, dist)), he)
            h = np.where(edge, he, h)
        mmd = self.min_mountain_distance
        m = (~edge) & (dist < mmd) & (h > 0.28)
        if np.any(m):
            t3 = np.clip((h - 0.28) / 0.1, 0.0, 1.0)
            hm = lerp(lerp(0.28, 0.38, t3), h, lerp_step(mmd - 400.0, mmd, dist))
            h = np.where(m, hm, h)
        return h

    # -- biome -------------------------------------------------------------------
    def biome(self, wx, wy):
        wx = np.asarray(wx, dtype=np.float64)
        wy = np.asarray(wy, dtype=np.float64)
        dist = np.hypot(wx, wy)
        bh = self.base_height(wx, wy)
        ang = world_angle(wx, wy) * 100.0
        out = np.full(np.broadcast(wx, wy).shape, MEADOWS, dtype=np.int32)
        undecided = np.ones(out.shape, dtype=bool)

        def assign(cond, b):
            nonlocal undecided
            c = cond & undecided
            out[c] = b
            undecided = undecided & ~c

        assign(np.hypot(wx, wy - 4000.0) > 12000.0 + ang, ASHLANDS)  # y + ashlandsYOffset(-4000)
        assign(bh <= 0.02, OCEAN)
        assign(np.hypot(wx, wy + 4000.0) > 12000.0 + ang, DEEPNORTH)
        assign(bh > 0.4, MOUNTAIN)
        n = lambda o: PN((o + wx).astype(f32) * 0.001, (o + wy).astype(f32) * 0.001)
        assign((n(self.o0) > 0.6) & (dist > 2000) & (dist < self.max_marsh_distance) & (bh > 0.05) & (bh < 0.25), SWAMP)
        assign((n(self.o4) > self.min_darkland_noise) & (dist > 6000 + ang) & (dist < 10000), MISTLANDS)
        assign((n(self.o1) > 0.4) & (dist > 3000 + ang) & (dist < 8000), PLAINS)
        assign((n(self.o2) > 0.4) & (dist > 600 + ang) & (dist < 6000), BLACKFOREST)
        assign(dist > 5000 + ang, BLACKFOREST)
        return out

    # -- rivers ------------------------------------------------------------------
    def add_rivers(self, wx, wy, h):
        if not self.river_points:
            return h
        gx = np.floor((wx + 32.0) / 64.0).astype(np.int64)
        gy = np.floor((wy + 32.0) / 64.0).astype(np.int64)
        weight = np.zeros(h.shape)
        width = np.zeros(h.shape)
        keys = set(zip(gx.ravel().tolist(), gy.ravel().tolist()))
        for key in keys:
            pts = self._rp_arrays.get(key)
            if pts is None:
                lst = self.river_points.get(key)
                if not lst:
                    continue
                pts = self._rp_arrays[key] = np.array(lst)
            m = (gx == key[0]) & (gy == key[1])
            px, py = wx[m], wy[m]
            d2 = (pts[None, :, 0] - px[:, None]) ** 2 + (pts[None, :, 1] - py[:, None]) ** 2
            w = pts[None, :, 2]
            inside = d2 < w * w
            t = np.where(inside, 1.0 - np.sqrt(d2) / w, 0.0)
            weight[m] = t.max(axis=1)
            s = t.sum(axis=1)
            width[m] = np.where(s > 0, (t * w).sum(axis=1) / np.where(s > 0, s, 1), 0)
        has = weight > 0
        t = lerp_step(20.0, 60.0, width)
        a = lerp(0.14, 0.12, t)
        b = lerp(0.139, 0.128, t)
        h2 = np.where(h > a, lerp(h, a, weight), h)
        h2 = np.where(h2 > b, lerp(h2, b, lerp_step(0.85, 1.0, weight)), h2)
        return np.where(has, h2, h)

    # -- per-biome heights -----------------------------------------------------
    def _detail(self, wx, wy, o):
        x = (wx + 100000.0 + o).astype(f32).astype(np.float64)
        y = (wy + 100000.0 + o).astype(f32).astype(np.float64)
        return x, y

    def _hills(self, x, y):
        n = PN(x * 0.01, y * 0.01) * PN(x * 0.02, y * 0.02)
        return n + PN(x * 0.05, y * 0.05) * PN(x * 0.1, y * 0.1) * n * 0.5

    def meadows_plains_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        x, y = self._detail(wx, wy, self.o3)
        h = bh + self._hills(x, y) * 0.1
        over = h - 0.15
        k = np.clip(bh / 0.4, 0.0, 1.0)
        h = np.where(over > 0, h - over * ((1.0 - k) * 0.75), h)
        h = self.add_rivers(wx, wy, h)
        h = h + PN(x * 0.1, y * 0.1) * 0.01
        return h + PN(x * 0.4, y * 0.4) * 0.003

    def forest_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        x, y = self._detail(wx, wy, self.o3)
        h = bh + self._hills(x, y) * 0.1
        h = self.add_rivers(wx, wy, h)
        h = h + PN(x * 0.1, y * 0.1) * 0.01
        return h + PN(x * 0.4, y * 0.4) * 0.003

    def marsh_height(self, wx, wy):
        x = (wx + 100000.0).astype(f32).astype(np.float64)
        y = (wy + 100000.0).astype(f32).astype(np.float64)
        h = 0.137 + PN(x * 0.04, y * 0.04) * PN(x * 0.08, y * 0.08) * 0.03
        h = self.add_rivers(wx, wy, h)
        h = h + PN(x * 0.1, y * 0.1) * 0.01
        return h + PN(x * 0.4, y * 0.4) * 0.003

    def mountain_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        tilt = (np.abs(self.base_height(wx + 1.0, wy) - self.base_height(wx - 1.0, wy))
                + np.abs(self.base_height(wx, wy - 1.0) - self.base_height(wx, wy + 1.0)))
        x, y = self._detail(wx, wy, self.o3)
        h = bh + (bh - 0.4)
        n = PN(x * 0.01, y * 0.01) * PN(x * 0.02, y * 0.02)
        n = n + PN(x * 0.05, y * 0.05) * PN(x * 0.1, y * 0.1) * n * 0.5
        h = h + n * 0.2
        h = self.add_rivers(wx, wy, h)
        h = h + PN(x * 0.1, y * 0.1) * 0.01
        h = h + PN(x * 0.4, y * 0.4) * 0.003
        return h + PN(x * 0.2, y * 0.2) * 2.0 * tilt

    def mistlands_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        x, y = self._detail(wx, wy, self.o3)
        n = PN(x * 0.02 * 0.7, y * 0.02 * 0.7) * PN(x * 0.04 * 0.7, y * 0.04 * 0.7)
        n = n + PN(x * 0.03 * 0.7, y * 0.03 * 0.7) * PN(x * 0.05 * 0.7, y * 0.05 * 0.7) * n * 0.5
        n = np.where(n > 0, np.power(np.maximum(n, 0), 1.5), n)
        h = bh + n * 0.4
        h = self.add_rivers(wx, wy, h)
        k = np.clip(n * 7.0, 0.0, 1.0)
        h = h + PN(x * 0.1, y * 0.1) * 0.03 * k
        h = h + PN(x * 0.4, y * 0.4) * 0.01 * k
        a = h + PN(x * 0.4, y * 0.4) * 0.002
        stepped = np.ceil(h * 400.0) / 400.0
        return lerp(a, stepped, k)

    def deepnorth_pregen_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        x, y = self._detail(wx, wy, self.o3)
        h = bh + np.maximum(0.0, bh - 0.4)
        n = PN(x * 0.01, y * 0.01) * PN(x * 0.02, y * 0.02)
        n = n + PN(x * 0.05, y * 0.05) * PN(x * 0.1, y * 0.1) * n * 0.5
        h = (h + n * 0.2) * 1.2
        h = self.add_rivers(wx, wy, h)
        h = h + PN((x.astype(f32) * f32(0.1)), (y.astype(f32) * f32(0.1))) * 0.01
        return h + PN((x.astype(f32) * f32(0.4)), (y.astype(f32) * f32(0.4))) * 0.003

    def ashlands_pregen_height(self, wx, wy):
        bh = self.base_height(wx, wy)
        x, y = self._detail(wx, wy, self.o3)
        h = bh + self._hills(x, y) * 0.1 + 0.1
        h = h + PN(x * 0.1, y * 0.1) * 0.01
        h = h + PN(x * 0.4, y * 0.4) * 0.003
        return self.add_rivers(wx, wy, h)

    def biome_height(self, biome: int, wx, wy, pregen: bool = False):
        """Height in metres (before ashlands / deep-north gap factors)."""
        wx = np.asarray(wx, dtype=np.float64)
        wy = np.asarray(wy, dtype=np.float64)
        if pregen and biome == DEEPNORTH:
            h = self.deepnorth_pregen_height(wx, wy)
        elif pregen and biome == ASHLANDS:
            h = self.ashlands_pregen_height(wx, wy)
        elif pregen and biome == MISTLANDS:
            h = self.forest_height(wx, wy)
        elif biome in (MEADOWS, PLAINS):
            h = self.meadows_plains_height(wx, wy)
        elif biome in (BLACKFOREST, ASHLANDS, DEEPNORTH):
            h = self.forest_height(wx, wy)
        elif biome == SWAMP:
            h = self.marsh_height(wx, wy)
        elif biome == MOUNTAIN:
            h = self.mountain_height(wx, wy)
        elif biome == OCEAN:
            h = self.base_height(wx, wy)
        elif biome == MISTLANDS:
            h = self.mistlands_height(wx, wy)
        else:
            h = np.zeros(np.broadcast(wx, wy).shape)
        h = h * 200.0
        return np.where(np.hypot(wx, wy) > 10500.0, -400.0, h)

    def height(self, wx, wy, pregen: bool = False):
        """WorldGenerator.GetHeight / GetPregenerationHeight."""
        wx = np.asarray(wx, dtype=np.float64)
        wy = np.asarray(wy, dtype=np.float64)
        b = self.biome(wx, wy)
        out = np.zeros(b.shape)
        for bid in np.unique(b):
            m = b == bid
            out[m] = self.biome_height(int(bid), wx[m], wy[m], pregen)
        return out

    def zone_heightmap(self, zx: int, zy: int):
        """HeightmapBuilder.Build for zone (zx, zy): 65x65 heights, row = z, col = x."""
        cx, cy = zx * 64.0 - 32.0, zy * 64.0 - 32.0
        corners = self.biome(np.array([cx, cx + 64, cx, cx + 64]), np.array([cy, cy, cy + 64, cy + 64]))
        k = np.arange(65, dtype=np.float64)
        wy, wx = np.meshgrid(cy + k, cx + k, indexing="ij")
        if np.all(corners == corners[0]):
            return self.biome_height(int(corners[0]), wx, wy), corners
        t = smooth_step(0.0, 1.0, k / 64.0)
        t2 = t[None, :]
        t1 = t[:, None]
        hs = [self.biome_height(int(b), wx, wy) for b in corners]
        a = lerp(hs[0], hs[1], t2)
        b = lerp(hs[2], hs[3], t2)
        return lerp(a, b, t1), corners


def _blended(self, wx, wy):
    """Terrain height as the game meshes it: per-zone bilinear blend of the 4 corner biomes."""
    wx = np.asarray(wx, dtype=np.float64)
    wy = np.asarray(wy, dtype=np.float64)
    zx = np.floor((wx + 32.0) / 64.0)
    zy = np.floor((wy + 32.0) / 64.0)
    x0 = zx * 64.0 - 32.0
    y0 = zy * 64.0 - 32.0
    corners = [self.biome(x0, y0), self.biome(x0 + 64, y0), self.biome(x0, y0 + 64), self.biome(x0 + 64, y0 + 64)]
    hs = []
    for c in corners:
        h = np.zeros(wx.shape)
        for bid in np.unique(c):
            m = c == bid
            h[m] = self.biome_height(int(bid), wx[m], wy[m])
        hs.append(h)
    t2 = smooth_step(0.0, 1.0, (wx - x0) / 64.0)
    t1 = smooth_step(0.0, 1.0, (wy - y0) / 64.0)
    return lerp(lerp(hs[0], hs[1], t2), lerp(hs[2], hs[3], t2), t1)


WorldGen.terrain_height = _blended
