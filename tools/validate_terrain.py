import json, sys, collections, numpy as np
sys.path.insert(0, 'tools')
import vworld, terrain
H = {int(k): v for k, v in json.load(open('data/prefab_names.json')).items()}
meta = vworld.read_meta('data/world')
zs = list(vworld.read_zdos('data/world'))
tc = vworld.stable_hash('_TerrainCompiler')
edited = {(int(np.floor((z.pos[0]+32)/64)), int(np.floor((z.pos[2]+32)/64))) for z in zs if z.prefab == tc}
print('edited zones', len(edited))
creator = vworld.stable_hash('creator')
types = {'Pickable_Stone','Pickable_Branch','Pickable_Flint','Beech1','FirTree','Pinetree_01','Birch1','Birch2','Oak1','Pickable_Mushroom','Bush01','Pickable_Dandelion'}
samp = [z for z in zs if H[z.prefab] in types and creator not in z.longs and z.pos[1] != 0
        and (int(np.floor((z.pos[0]+32)/64)), int(np.floor((z.pos[2]+32)/64))) not in edited]
rng = np.random.default_rng(0); idx = rng.choice(len(samp), min(4000, len(samp)), replace=False)
samp = [samp[i] for i in idx]
x = np.array([z.pos[0] for z in samp]); y = np.array([z.pos[2] for z in samp]); obs = np.array([z.pos[1] for z in samp])
wg = terrain.WorldGen(meta.seed, meta.worldgen_version, rivers=('--rivers' in sys.argv))
print('offsets', wg.o0, wg.o1, wg.o2, wg.o3, wg.o4, wg.river_seed, wg.stream_seed)
h = wg.height(x, y)
err = obs - h
print('n', len(err), 'median |err|', np.median(np.abs(err)), 'p90', np.percentile(np.abs(err), 90), 'frac<0.5m', np.mean(np.abs(err) < 0.5))
bad = np.argsort(-np.abs(err))[:10]
for i in bad: print(H[samp[i].prefab], samp[i].pos, round(h[i], 2))
