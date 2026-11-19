"""Decide which places to render.

Rule:
  1. Group every player-built piece into clusters (pieces within LINK m of each other join).
  2. A cluster becomes a place if it has at least MIN_PIECES pieces, or it contains a portal
     (so every portal has somewhere to lead to).
  3. Clusters whose centres are within MERGE m are shown as one place.
  4. Size: the cluster's extent plus a margin, clamped to [MIN_R, MAX_R], then widened by AREA_SCALE
     to show the surroundings (a radius in regions.json is scaled the same way).
  5. Name: an entry in regions.json near the place wins; otherwise the portal tag used to
     reach it, else the text of a sign there, else "Outpost <n>".

Writes data/places.json: [{slug, title, x, z, radius, pieces, portals}]
"""
import json, math, os, re, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
import vworld
from vworld import stable_hash

LINK, MIN_PIECES, MERGE, MIN_R, MAX_R, MARGIN = 40.0, 15, 150.0, 60.0, 160.0, 45.0
AREA_SCALE = 1.5


def build_places(world='data/world', names_path='data/prefab_names.json', overrides_path='regions.json'):
    names = {int(k): v for k, v in json.load(open(names_path)).items()}
    creator, tag, text = stable_hash('creator'), stable_hash('tag'), stable_hash('text')
    built = [z for z in vworld.read_zdos(world) if creator in z.longs]
    pts = [(z.pos[0], z.pos[2]) for z in built]

    # 1. single-linkage clustering on a grid
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    grid = defaultdict(list)
    for i, (x, y) in enumerate(pts):
        grid[(int(x // LINK), int(y // LINK))].append(i)
    for (gx, gy), idx in grid.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), []):
                    for i in idx:
                        if math.dist(pts[i], pts[j]) < LINK:
                            parent[find(i)] = find(j)
    clusters = defaultdict(list)
    for i in range(len(pts)):
        clusters[find(i)].append(i)

    # 2. keep big clusters and anything with a portal
    keep = []
    for idx in clusters.values():
        portals = [built[i] for i in idx if names[built[i].prefab].startswith('portal')]
        if len(idx) >= MIN_PIECES or portals:
            keep.append(idx)

    # 3. merge close clusters
    def centre(idx):
        return (sum(pts[i][0] for i in idx) / len(idx), sum(pts[i][1] for i in idx) / len(idx))

    merged = True
    while merged:
        merged = False
        for a in range(len(keep)):
            for b in range(a + 1, len(keep)):
                if math.dist(centre(keep[a]), centre(keep[b])) < MERGE:
                    keep[a] = keep[a] + keep[b]
                    del keep[b]
                    merged = True
                    break
            if merged:
                break

    # portal tags -> how many portals carry them (a tag used by the hub names the far end)
    all_portals = [z for z in built if names[z.prefab].startswith('portal')]
    tag_count = Counter(z.strings.get(tag, '') for z in all_portals)
    overrides = json.load(open(overrides_path)) if os.path.exists(overrides_path) else []

    places = []
    for idx in sorted(keep, key=len, reverse=True):
        cx, cz = centre(idx)
        ext = max(math.dist((cx, cz), pts[i]) for i in idx)
        radius = max(MIN_R, min(MAX_R, ext + MARGIN))
        portals = [built[i] for i in idx if names[built[i].prefab].startswith('portal')]
        title = slug = None
        for o in overrides:
            if abs(o['x'] - cx) < radius and abs(o['z'] - cz) < radius:
                title, slug = o['title'], o['slug']
                if 'radius' in o:
                    radius = o['radius']
                break
        if not title:
            # a place with a single portal is usually named by that portal's tag
            tags = [p.strings.get(tag, '') for p in portals if tag_count[p.strings.get(tag, '')] == 2]
            signs = [built[i].strings.get(text, '') for i in idx if built[i].strings.get(text)]
            if not tags:
                tags = [p.strings.get(tag, '') for p in portals if p.strings.get(tag)]
            if len(tags) == 1:
                title = tags[0]
            elif signs:
                title = signs[0]
            if title:
                title = title.strip()[:40]
        radius *= AREA_SCALE
        places.append(dict(slug=slug, title=title, x=round(cx), z=round(cz), radius=round(radius),
                           pieces=len(idx), portals=len(portals)))
    n = 0
    used = set()
    for p in places:
        if not p['title']:
            n += 1
            p['title'] = f'Outpost {n}'
        if not p['slug']:
            base = re.sub(r'[^a-z0-9]+', '-', p['title'].lower()).strip('-') or 'place'
            s, k = base, 2
            while s in used:
                s, k = f'{base}-{k}', k + 1
            p['slug'] = s
        used.add(p['slug'])
    return places


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    places = build_places()
    json.dump(places, open('data/places.json', 'w'), indent=1)
    for p in places:
        print(f"{p['slug']:22s} {p['title']:22s} ({p['x']:6d},{p['z']:6d}) r={p['radius']:3d} pieces={p['pieces']:4d} portals={p['portals']}")
