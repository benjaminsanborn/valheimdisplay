"""Collect GameObject names from all Unity asset files; write hash->name JSON."""
import json, os, sys
import UnityPy
sys.path.insert(0, os.path.dirname(__file__))
from vworld import stable_hash

root = sys.argv[1]
names = set()
for dp, _, fs in os.walk(root):
    for f in fs:
        p = os.path.join(dp, f)
        if f.endswith(('.dll', '.so', '.json', '.xml', '.config', '.manifest', '.resS', '.resource')):
            continue
        try:
            env = UnityPy.load(p)
        except Exception as e:
            continue
        for obj in env.objects:
            if obj.type.name == 'GameObject':
                try:
                    names.add(obj.read().m_Name)
                except Exception:
                    pass
print(len(names), file=sys.stderr)
json.dump({str(stable_hash(n)): n for n in sorted(names)}, open(sys.argv[2], 'w'), indent=0)
