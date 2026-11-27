"""Export the boss trophy icons and the map's pin icons from the game's asset bundles to web/assets/icons/<name>.png.

  export_icons.py <game data dir> <out dir>
"""
import os
import sys

import UnityPy

WANT = ['TrophyEikthyr', 'TrophyTheElder', 'TrophyBonemass', 'TrophyDragonQueen', 'TrophyGoblinKing',
        'TrophySeekerQueen', 'TrophyFader', 'TrophyGoblin',
        'mapicon_fire', 'mapicon_house', 'mapicon_hammer', 'mapicon_pin', 'mapicon_portal', 'mapicon_bed',
        'mapicon_boss_colored', 'mapicon_hildir1', 'mapicon_hildir2', 'mapicon_hildir3']


def main():
    root, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    todo = set(WANT) - {n for n in WANT if os.path.exists(os.path.join(out, n + '.png'))}
    paths = sorted((os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                    if not f.endswith(('.dll', '.so', '.json', '.xml', '.config', '.manifest', '.resS', '.resource'))),
                   key=os.path.getsize)
    for p in paths:
        if not todo:
            break
        try:
            env = UnityPy.load(p)
        except Exception:
            continue
        for o in env.objects:
            if o.type.name != 'Sprite':
                continue
            try:
                name = o.peek_name()
            except Exception:
                continue
            if name in todo:
                img = o.read().image
                img.thumbnail((96, 96))
                img.save(os.path.join(out, name + '.png'))
                todo.discard(name)
    if todo:
        print('icons not found:', sorted(todo), file=sys.stderr)


if __name__ == '__main__':
    main()
