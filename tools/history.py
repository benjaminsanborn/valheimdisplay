"""World history for the timelapse: when each built piece existed and when each zone was explored.

  history.py add <world dir>            record a save (dated by its _main.N.ok file)
  history.py backfill <tar.gz|dir> ...  record every save found in backups (tarballs or folders)

Keeps data/history/built.json, zones.json and world.json (the in-game day of each save, and the
first save each global key, like a boss kill, appeared in). Snapshots can be added in any order.
A piece is identified by prefab + exact position, so a piece that was torn down keeps its
first/last dates and can still be shown when looking at an earlier day.
"""
import datetime as dt
import glob
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile

sys.path.insert(0, os.path.dirname(__file__))
import vworld
from common import enter_home
from vworld import stable_hash

HIST = 'data/history'
DAY_SECONDS = 1200  # EnvMan.m_dayLengthSec
H_CREATOR = stable_hash('creator')
H_SCALE = stable_hash('scale')


def piece_key(name, pos):
    return f'{name}:{pos[0]:.2f}:{pos[1]:.2f}:{pos[2]:.2f}'


def load():
    built = json.load(open(f'{HIST}/built.json')) if os.path.exists(f'{HIST}/built.json') else {'dates': [], 'pieces': {}}
    zones = json.load(open(f'{HIST}/zones.json')) if os.path.exists(f'{HIST}/zones.json') else {}
    world = json.load(open(f'{HIST}/world.json')) if os.path.exists(f'{HIST}/world.json') else {}
    built['world'] = {'days': {}, 'keys': {}, **world}
    return built, zones


def save(built, zones):
    os.makedirs(HIST, exist_ok=True)
    built['dates'] = sorted(set(built['dates']))
    json.dump(built.pop('world'), open(f'{HIST}/world.json', 'w'), indent=1)
    json.dump(built, open(f'{HIST}/built.json', 'w'), separators=(',', ':'))
    json.dump(zones, open(f'{HIST}/zones.json', 'w'), separators=(',', ':'))


def save_date(world):
    ok = vworld.find_main(world, 'ok')
    return dt.datetime.fromtimestamp(os.path.getmtime(ok)).date().isoformat()


def add(world, built, zones, names):
    day = save_date(world)
    pieces = built['pieces']
    n_new = 0
    for z in vworld.read_zdos(world):
        if H_CREATOR not in z.longs or z.pos[1] > 1000:
            continue
        name = names.get(z.prefab)
        if not name:
            continue
        k = piece_key(name, z.pos)
        p = pieces.get(k)
        if p is None:
            sc = z.vec3s.get(H_SCALE)
            pieces[k] = dict(name=name, pos=[round(v, 3) for v in z.pos], rot=list(z.rot),
                             scale=[round(v, 3) for v in sc] if sc else None, first=day, last=day)
            n_new += 1
        else:
            p['first'] = min(p['first'], day)
            p['last'] = max(p['last'], day)
    state = vworld.read_world_state(world)
    w = built['world']
    w['days'][day] = max(w['days'].get(day, 0), int(state['net_time'] // DAY_SECONDS))
    for k in state['global_keys']:
        w['keys'][k] = min(w['keys'].get(k, day), day)
    for zx, zy in state['zones']:
        if abs(zx) <= 170 and abs(zy) <= 170:
            k = f'{zx},{zy}'
            zones[k] = min(zones.get(k, day), day)
    built['dates'].append(day)
    print(f'{day}: {n_new} new pieces, {len(pieces)} known, {len(zones)} explored zones', file=sys.stderr)


def main():
    enter_home()
    names = {int(k): v for k, v in json.load(open('data/prefab_names.json')).items()}
    built, zones = load()
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'add':
        add(args[0], built, zones, names)
    elif cmd == 'backfill':
        for src in args:
            tmp = None
            root = src
            if src.endswith(('.tar.gz', '.tgz')):
                tmp = tempfile.mkdtemp(prefix='vhist-')
                with tarfile.open(src) as t:
                    t.extractall(tmp, filter='data')
                root = tmp
            for ok in sorted(glob.glob(os.path.join(root, '**', '_main.*.ok'), recursive=True)):
                try:
                    add(os.path.dirname(ok), built, zones, names)
                except Exception as e:  # a damaged backup shouldn't stop the rest
                    print(f'skipped {os.path.dirname(ok)}: {e}', file=sys.stderr)
            if tmp:
                shutil.rmtree(tmp)
    else:
        sys.exit(__doc__)
    save(built, zones)


if __name__ == '__main__':
    main()
