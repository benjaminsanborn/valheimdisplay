"""Export the game's terrain tiles, grass sprites and water textures for the viewer.

Terrain layers (index = layer in the shader's texture array):
  0 meadows grass, 1 forest floor, 2 swamp, 3 plains, 4 snow, 5 sand, 6 rock,
  7 dirt, 8 cultivated, 9 paved
"""
import os, sys
import numpy as np
import UnityPy
from PIL import Image

LAYERS = ['terraintile_0', 'terraintile_1', 'terraintile_10', 'terraintile_11', 'terraintile_4',
          'terraintile_9', 'terraintile_13', 'terraintile_3', 'terraintile_3', 'terraintile_12']
EXTRA = ['grass_meadows', 'grass_meadows_short', 'water_normals', 'foam']

root, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
want = set(LAYERS) | set(EXTRA)
got = {}
bundles = sorted((os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs
                  if not f.endswith(('.dll', '.so', '.json', '.xml', '.config', '.manifest', '.resS', '.resource'))),
                 key=os.path.getsize, reverse=True)
for path in bundles:
    try:
        env = UnityPy.load(path)
    except Exception:
        continue
    for o in env.objects:
        if o.type.name == 'Texture2D':
            t = o.read()
            if t.m_Name in want and t.m_Name not in got:
                got[t.m_Name] = t.image
    if want <= set(got):
        break
missing = want - set(got)
if missing:
    sys.exit(f'missing textures: {missing}')
for i, n in enumerate(LAYERS):
    im = got[n].convert('RGB').resize((256, 256))
    if i == 4:  # snow: brighten the grey rock tile into a snowy surface
        a = np.asarray(im).astype(float)
        lum = a.mean(axis=2, keepdims=True)
        a = 200 + (lum - lum.mean()) * 0.6 + np.array([0, 4, 14])
        im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    im.save(os.path.join(out, f'layer{i}.jpg'), quality=90)
# grass blades: white blades with alpha (tinted in the shader)
from PIL import ImageFilter
for n in ['grass_meadows', 'grass_meadows_short']:
    im = got[n].convert('RGBA').resize((256, 256), Image.NEAREST)
    a = im.getchannel('A').filter(ImageFilter.MaxFilter(3))  # thicken the 1px blades so they survive mipmapping
    im = Image.merge('RGBA', (*Image.new('RGB', im.size, (255, 255, 255)).split(), a))
    im.save(os.path.join(out, f'{n}.png'))
# water normal map is DXT5nm style: x in alpha, y in green -> repack into an ordinary RGB normal map
a = np.asarray(got['water_normals'].convert('RGBA')).astype(float) / 255.0
nx, ny = a[..., 3] * 2 - 1, a[..., 1] * 2 - 1
nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
Image.fromarray((np.stack([nx, ny, nz], -1) * 127.5 + 127.5).astype(np.uint8)).save(os.path.join(out, 'water_normals.png'))
got['foam'].convert('L').save(os.path.join(out, 'foam.jpg'), quality=90)
print('terrain textures written to', out)
