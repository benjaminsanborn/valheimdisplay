"""Reader for Valheim chunked world saves (world version >= 40, "ChunkedSave").

Layout of a world folder (e.g. worlds_local/Dedicated/):
  _main.N.fwl2    world metadata (name, seed, ...)
  _main.N.chunks  index: list of (chunk id, size, version, numZDOs)
  _main.N.db2     global state (not needed for rendering)
  XX_YY__S_V.chunk  ZDOs (world objects) for one chunk

Format reverse-engineered from the decompiled assembly_valheim.dll
(ZDOMan.LoadChunks, ChunkSaveMapping.Load, ZDO.Load, ZPackage).
"""
from __future__ import annotations

import glob
import math
import os
import re
import struct
from dataclasses import dataclass, field


def stable_hash(s: str) -> int:
    """Valheim's string.GetStableHashCode (used for prefab and ZDO key hashes)."""
    a = b = 5381
    i = 0
    n = len(s)
    while i < n:
        a = (((a << 5) + a) ^ ord(s[i])) & 0xFFFFFFFF
        if i == n - 1:
            break
        b = (((b << 5) + b) ^ ord(s[i + 1])) & 0xFFFFFFFF
        i += 2
    r = (a + b * 1566083941) & 0xFFFFFFFF
    return r - (1 << 32) if r & 0x80000000 else r


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def _u(self, fmt: str, size: int):
        v = struct.unpack_from(fmt, self.d, self.p)[0]
        self.p += size
        return v

    def byte(self):   return self._u("<B", 1)
    def short(self):  return self._u("<h", 2)
    def ushort(self): return self._u("<H", 2)
    def int(self):    return self._u("<i", 4)
    def uint(self):   return self._u("<I", 4)
    def long(self):   return self._u("<q", 8)
    def float(self):  return self._u("<f", 4)
    def bool(self):   return self.byte() != 0

    def vec3(self):
        v = struct.unpack_from("<3f", self.d, self.p)
        self.p += 12
        return v

    def quat(self):
        v = struct.unpack_from("<4f", self.d, self.p)
        self.p += 16
        return v

    def string(self) -> str:
        # .NET BinaryReader: 7-bit encoded length, then UTF-8 bytes
        n = shift = 0
        while True:
            b = self.byte()
            n |= (b & 0x7F) << shift
            shift += 7
            if not b & 0x80:
                break
        s = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return s

    def bytearray(self) -> bytes:
        n = self.int()
        v = self.d[self.p:self.p + n]
        self.p += n
        return v

    def num_items(self) -> int:
        n = self.byte()
        if n & 0x80:
            n = ((n & 0x7F) << 8) | self.byte()
        return n

    def small_rotation(self):
        num = self.ushort()
        if num & 0x8000:
            return (0.0, (num & 0x7FFF) * 0.5, 0.0)
        num = (num << 16) | self.ushort()
        return ((num & 0x3FF) * 0.5, ((num >> 10) & 0x3FF) * 0.5, ((num >> 20) & 0x3FF) * 0.5)


@dataclass
class ZDO:
    prefab: int
    pos: tuple
    rot: tuple  # Euler angles in degrees (Unity order Z, X, Y)
    persistent: bool
    distant: bool
    type: int
    connection: tuple | None = None
    floats: dict = field(default_factory=dict)
    vec3s: dict = field(default_factory=dict)
    quats: dict = field(default_factory=dict)
    ints: dict = field(default_factory=dict)
    longs: dict = field(default_factory=dict)
    strings: dict = field(default_factory=dict)
    bytearrays: dict = field(default_factory=dict)


def read_zdo(r: Reader) -> ZDO:
    flags = r.ushort()
    small_pos = flags & 0x2000
    has_rot = flags & 0x1000
    if small_pos:
        x, z = r.short(), r.short()
        pos = (float(x), 0.0, float(z))
    else:
        pos = r.vec3()
    prefab = r.int()
    rot = r.small_rotation() if has_rot else (0.0, 0.0, 0.0)
    z = ZDO(prefab, pos, rot, bool(flags & 0x100), bool(flags & 0x200), (flags >> 10) & 3)
    if flags & 0xFF:
        if flags & 0x01:
            z.connection = (r.byte(), r.int())
        for bit, target, fn in (
            (0x02, z.floats, r.float),
            (0x04, z.vec3s, r.vec3),
            (0x08, z.quats, r.quat),
            (0x10, z.ints, r.int),
            (0x20, z.longs, r.long),
            (0x40, z.strings, r.string),
            (0x80, z.bytearrays, r.bytearray),
        ):
            if flags & bit:
                for _ in range(r.num_items()):
                    k = r.int()
                    target[k] = fn()
    return z


@dataclass
class WorldMeta:
    version: int
    name: str
    seed_name: str
    seed: int
    uid: int
    worldgen_version: int


def find_main(folder: str, ext: str) -> str:
    """Newest complete save: the game writes _main.N.ok last, so only trust N with an .ok file."""
    nums = [int(re.search(r"_main\.(\d+)\.ok$", f).group(1)) for f in glob.glob(os.path.join(folder, "_main.*.ok"))]
    if not nums:
        raise FileNotFoundError(f"no complete save (_main.*.ok) in {folder}")
    path = os.path.join(folder, f"_main.{max(nums)}.{ext}")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path


def read_meta(folder: str) -> WorldMeta:
    data = open(find_main(folder, "fwl2"), "rb").read()
    n = struct.unpack_from("<i", data, 0)[0]
    r = Reader(data[4:4 + n])
    version = r.int()
    name = r.string()
    seed_name = r.string()
    seed = r.int()
    uid = r.long()
    wgv = r.int() if version >= 26 else 0
    return WorldMeta(version, name, seed_name, seed, uid, wgv)


def read_chunk_index(folder: str):
    r = Reader(open(find_main(folder, "chunks"), "rb").read())
    r.ushort()
    total = r.int()
    count = r.int()
    chunks = []
    for _ in range(count):
        chunk = r.ushort()
        size = r.byte()
        ver = r.uint()
        nz = r.int()
        chunks.append((chunk, size, ver, nz))
    return total, chunks


def chunk_filename(chunk: int, size: int, ver: int) -> str:
    return f"{chunk >> 8:02x}_{chunk & 0xFF:02x}__{size}_{ver}.chunk"


def read_zdos(folder: str):
    """Yield every ZDO in the world."""
    _, chunks = read_chunk_index(folder)
    for chunk, size, ver, nz in chunks:
        path = os.path.join(folder, chunk_filename(chunk, size, ver))
        r = Reader(open(path, "rb").read())
        r.short()  # world version
        n = r.int()
        for _ in range(n):
            yield read_zdo(r)
        if r.p != len(r.d):
            raise ValueError(f"{path}: {len(r.d) - r.p} trailing bytes")


def read_world_state(folder: str):
    """From _main.N.db2: game time, generated zones (everywhere a player has been nearby),
    global keys (bosses beaten etc.) and the placed locations (boss altars, traders...)."""
    import gzip as _gz
    data = open(find_main(folder, "db2"), "rb").read()
    r = Reader(data)
    r.int()                       # version
    net_time = r._u("<d", 8)
    n = r.int()
    raw = data[r.p:r.p + n]
    try:
        body = _gz.decompress(raw)
    except OSError:
        import brotli  # type: ignore
        body = brotli.decompress(raw)
    z = Reader(body)
    zones = [(z.short(), z.short()) for _ in range(z.int())]
    state = dict(net_time=net_time, zones=zones, global_keys=[], locations=[])
    try:
        z.int()                   # location version
        state['global_keys'] = [z.string() for _ in range(z.int())]
        z.bool()                  # locations generated
        for _ in range(z.int()):
            h = z.int()
            pos = (z.float(), z.float(), z.float())
            state['locations'].append((h, pos, z.bool()))
    except Exception:             # older/newer layouts: keep what we have
        pass
    return state


def read_shared_pins(data: bytes):
    """The pins on a cartography table's shared map (its ZDO's "data"): [(name, (x, y, z), type)].
    The layout is Minimap.GetSharedMapData's: gzip of version, the explored bitmap, then the pins."""
    import gzip as _gz
    r = Reader(_gz.decompress(data))
    ver = r.int()
    n = r.int()
    r.p += n                      # explored, one byte per map pixel
    pins = []
    for _ in range(r.int()):
        r.long()                  # owner
        name = r.string()
        pos = r.vec3()
        kind = r.int()
        r.bool()                  # checked (crossed out)
        if ver >= 3:
            r.string()            # who shared it
        pins.append((name, pos, kind))
    return pins


def read_generated_zones(folder: str):
    return read_world_state(folder)['zones']
