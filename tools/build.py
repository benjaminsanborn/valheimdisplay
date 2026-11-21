"""Rebuild the viewer data: places (tools/places.py), terrain, models, world map, portal links.

usage: build.py [--models-only] [slug ...]
"""
import json, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, 'tools')
import vworld

from places import build_places
py = [sys.executable]
GAME = os.environ.get('VALHEIM_GAME_DATA', 'data/game/gamedata')  # the server's valheim_server_Data folder
os.makedirs('web/assets/regions', exist_ok=True)
# prefab hash -> name table, regenerated when the game updates
names_json = 'data/prefab_names.json'
newest_game_file = max(os.path.getmtime(os.path.join(dp, f)) for dp, _, fs in os.walk(GAME) for f in fs)
if not os.path.exists(names_json) or os.path.getmtime(names_json) < newest_game_file:
    print('indexing prefab names...', flush=True)
    subprocess.run(py + ['tools/prefab_names.py', GAME, names_json], check=True)
subprocess.run(py + ['tools/history.py', 'add', 'data/world'], check=True)   # timelapse history
regions = build_places()   # which places to render: see tools/places.py for the rule
json.dump(regions, open('data/places.json', 'w'), indent=1)
only = [a for a in sys.argv[1:] if not a.startswith('--')]
if '--models-only' not in sys.argv:
    for r in regions:
        if only and r['slug'] not in only:
            continue
        subprocess.run(py + ['tools/export_region.py', 'data/world', 'web/assets', r['slug'], r['title'],
                             str(r['x']), str(r['z']), str(r.get('radius', 120))], check=True)
if not os.path.exists('web/assets/terrain/layer0.jpg'):
    subprocess.run(py + ['tools/export_terrain_textures.py', GAME, 'web/assets/terrain'], check=True)
manifest = json.load(open('web/assets/models.json')) if os.path.exists('web/assets/models.json') else {}
need = [n for n in open('web/assets/needed_models.txt').read().split() if n not in manifest]
skip = set(open('data/no_model.txt').read().split()) if os.path.exists('data/no_model.txt') else set()
need = [n for n in need if n not in skip]
if need:
    open('data/todo_models.txt', 'w').write('\n'.join(need))
    print(f'exporting {len(need)} models...', flush=True)
    subprocess.run(py + ['tools/export_models.py', GAME, 'web/assets', '--list', 'data/todo_models.txt'], check=True)
    manifest = json.load(open('web/assets/models.json'))
    open('data/no_model.txt', 'a').write(''.join(n + '\n' for n in need if n not in manifest))
subprocess.run(py + ['tools/export_icons.py', GAME, 'web/assets/icons'], check=True)
subprocess.run(py + ['tools/export_worldmap.py', 'data/world', 'web/assets/worldmap.png', '1024'], check=True)

# link portals: each portal label gets the place + spot its partner (same tag) is in
portals = []
for r in regions:
    path = f"web/assets/regions/{r['slug']}.json"
    if not os.path.exists(path):
        continue
    info = json.load(open(path))
    for L in info['labels']:
        if L['kind'].startswith('portal'):
            portals.append((r, L))
for r, L in portals:
    partners = [(r2, L2) for r2, L2 in portals if L2['text'] == L['text'] and L2 is not L]
    L['target'] = None
    if partners:
        r2, L2 = partners[0]
        L['target'] = dict(slug=r2['slug'], title=r2['title'], pos=L2['pos'])
for r in regions:
    path = f"web/assets/regions/{r['slug']}.json"
    if not os.path.exists(path):
        continue
    info = json.load(open(path))
    mine = {tuple(L['world']): L for rr, L in portals if rr is r}
    for L in info['labels']:
        if 'world' in L and tuple(L['world']) in mine:
            L['target'] = mine[tuple(L['world'])]['target']
    json.dump(info, open(path, 'w'), separators=(',', ':'))

meta = vworld.read_meta('data/world')
idx = dict(world=meta.name, seed=meta.seed_name,
           radius=10500, regions=[dict(slug=r['slug'], title=r['title'], x=r['x'], z=r['z']) for r in regions if os.path.exists(f"web/assets/regions/{r['slug']}.json")])
# timelapse: history dates and the day each zone was first explored
hist = json.load(open('data/history/built.json'))
zones = json.load(open('data/history/zones.json'))
dates = sorted(set(hist['dates']))
di = {d: i for i, d in enumerate(dates)}
idx['dates'] = dates
for r in idx['regions']:   # first day anything was built there, for dimming future places on the map
    info = json.load(open(f"web/assets/regions/{r['slug']}.json"))
    firsts = [info['dates'][o[12]] for o in info['objects'] if o[11] == 1 and len(o) > 13]
    r['first'] = di[min(firsts)] if firsts else 0
    r['biome'] = info.get('biome')

# world state: in-game day, bosses, boss altars and traders found, ships and carts
world_hist = json.load(open('data/history/world.json'))
state = vworld.read_world_state('data/world')
idx['day'] = int(state['net_time'] // 1200)
idx['days'] = [world_hist['days'].get(d) for d in dates]
BOSSES = [('defeated_eikthyr', 'Eikthyr', 'TrophyEikthyr', 'Eikthyrnir'),
          ('defeated_gdking', 'The Elder', 'TrophyTheElder', 'GDKing'),
          ('defeated_bonemass', 'Bonemass', 'TrophyBonemass', 'Bonemass'),
          ('defeated_dragon', 'Moder', 'TrophyDragonQueen', 'Dragonqueen'),
          ('defeated_goblinking', 'Yagluth', 'TrophyGoblinKing', 'GoblinKing'),
          ('defeated_queen', 'The Queen', 'TrophySeekerQueen', 'Mistlands_DvergrBossEntrance1'),
          ('defeated_fader', 'Fader', 'TrophyFader', 'FaderLocation')]
TRADERS = {'Vendor_BlackForest': 'Haldor', 'Hildir_camp': 'Hildir', 'BogWitch_Camp': 'Bog Witch'}
keys = set(state['global_keys'])
idx['bosses'] = [dict(key=k, name=n, icon=f'assets/icons/{icon}.png',
                      defeated=(di.get(world_hist['keys'].get(k), len(dates) - 1) if k in keys else None))
                 for k, n, icon, _ in BOSSES]
loc_kind = {vworld.stable_hash(loc): ('boss', i) for i, (_, _, _, loc) in enumerate(BOSSES)}
loc_kind.update({vworld.stable_hash(k): ('trader', v) for k, v in TRADERS.items()})


def zone_day(x, z):
    return di.get(zones.get(f'{int((x + 32) // 64)},{int((z + 32) // 64)}'), 0)


idx['locations'] = []
for h, (x, y, z), placed in state['locations']:
    if placed and h in loc_kind:
        kind, what = loc_kind[h]
        idx['locations'].append(dict(kind=kind, boss=what if kind == 'boss' else None, name=what if kind == 'trader' else BOSSES[what][1],
                                     x=round(x), z=round(z), found=zone_day(x, z)))
names = {int(k): v for k, v in json.load(open('data/prefab_names.json')).items()}
VEHICLES = {'Raft': 'Raft', 'Karve': 'Karve', 'VikingShip': 'Longship', 'VikingShip_Ashlands': 'Drakkar', 'Cart': 'Cart'}
idx['vehicles'] = [dict(kind=VEHICLES[names[zd.prefab]], x=round(zd.pos[0]), z=round(zd.pos[2]))
                   for zd in vworld.read_zdos('data/world') if names.get(zd.prefab) in VEHICLES and zd.pos[1] < 1000]
# players: sessions/deaths from the server log (also refreshed every few minutes by valheimdisplay-players.timer)
try:
    subprocess.run(py + ['tools/players.py'], check=True)
except subprocess.CalledProcessError:
    print('players: could not read the server log', file=sys.stderr)

json.dump([[int(a), int(b), di.get(d, 0)] for k, d in zones.items() for a, b in [k.split(',')]],
          open('web/assets/zones.json', 'w'), separators=(',', ':'))
json.dump(idx, open('web/assets/regions/index.json', 'w'), indent=1)
print('regions:', [r['slug'] for r in idx['regions']])

# gzip the big data files once at build time; the web server sends these .gz copies
import gzip, glob
for f in glob.glob('web/assets/**/*', recursive=True):
    if f.endswith(('.bin', '.json', '.glb')) and os.path.isfile(f) and not f.endswith('players.json'):
        gz = f + '.gz'
        if not os.path.exists(gz) or os.path.getmtime(gz) < os.path.getmtime(f):
            with open(f, 'rb') as src, gzip.open(gz, 'wb', compresslevel=9) as dst:
                dst.write(src.read())
