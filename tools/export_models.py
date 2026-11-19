"""Export Valheim prefabs from the game's asset bundles to GLB files.

For each prefab name: find the root GameObject, walk the active hierarchy,
keep only LOD0 renderers, bake transforms into one mesh (per material), and
convert from Unity (left-handed) to glTF / three.js (right-handed) by
negating Z and flipping triangle winding.

usage: export_models.py <gamedata dir> <out dir> name [name ...] | --list file
"""
from __future__ import annotations

import io
import json
import math
import os
import struct
import sys

import numpy as np
import UnityPy
from PIL import Image
from UnityPy.helpers.MeshHelper import MeshHandler

TEX_MAX = 512
SKIP_EXT = ('.dll', '.so', '.json', '.xml', '.config', '.manifest', '.resS', '.resource')


def load_env(root):
    paths = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith(SKIP_EXT):
                paths.append(os.path.join(dp, f))
    return UnityPy.load(*paths)


def comp_list(go):
    out = []
    for c in go.m_Component:
        cc = c.component if hasattr(c, 'component') else c
        try:
            o = cc.read()
            out.append((o.object_reader.type.name, o))
        except Exception:
            pass
    return out


def trs(t):
    p, r, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
    x, y, z, w = r.x, r.y, r.z, r.w
    R = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    M = np.eye(4)
    M[:3, :3] = R * np.array([s.x, s.y, s.z])[None, :]
    M[:3, 3] = [p.x, p.y, p.z]
    return M


class Exporter:
    def __init__(self, env, out_dir):
        self.env = env
        self.out = out_dir
        os.makedirs(os.path.join(out_dir, 'tex'), exist_ok=True)
        self.roots = {}
        for obj in env.objects:
            if obj.type.name != 'GameObject':
                continue
            try:
                go = obj.read()
            except Exception:
                continue
            comps = comp_list(go)
            tf = next((o for n, o in comps if n == 'Transform'), None)
            if tf is None or tf.m_Father.path_id != 0:
                continue
            prev = self.roots.get(go.m_Name)
            fname = str(getattr(obj.assets_file, 'name', ''))
            # prefer prefabs from asset bundles; scene copies are static-batched in world space
            rank = 2 if 'CAB-' in fname or 'cab-' in fname else (1 if 'resources' in fname else 0)
            score = rank * 10000 + len(comps) + 10 * len(tf.m_Children)
            if prev is None or score > prev[0]:
                self.roots[go.m_Name] = (score, go, tf)
        self.tex_cache = {}

    # -- textures ------------------------------------------------------------
    def texture(self, pptr):
        if pptr is None or pptr.path_id == 0:
            return None
        key = (id(pptr.assetsfile), pptr.path_id)
        if key in self.tex_cache:
            return self.tex_cache[key]
        try:
            tex = pptr.read()
            img = tex.image
            name = f"{tex.m_Name}_{abs(pptr.path_id) % 100000}".replace('/', '_').replace(' ', '_')
            alpha = img.mode in ('RGBA', 'LA') and img.getextrema()[-1][0] < 250
            img.thumbnail((TEX_MAX, TEX_MAX))
            if alpha:
                fn = f"tex/{name}.png"
                img.convert('RGBA').save(os.path.join(self.out, fn), optimize=True)
            else:
                fn = f"tex/{name}.jpg"
                img.convert('RGB').save(os.path.join(self.out, fn), quality=85)
            res = (fn, alpha)
        except Exception as e:
            print('   texture failed', e, file=sys.stderr)
            res = None
        self.tex_cache[key] = res
        return res

    def material(self, mat_pptr):
        try:
            m = mat_pptr.read()
        except Exception:
            return dict(name='missing', color=[0.6, 0.6, 0.6, 1], tex=None, alpha=False, shader='')
        props = m.m_SavedProperties
        texs = dict((k, v) for k, v in props.m_TexEnvs)
        cols = dict((k, v) for k, v in props.m_Colors)
        floats = dict((k, v) for k, v in props.m_Floats)
        try:
            shader = m.m_Shader.read().m_ParsedForm.m_Name
        except Exception:
            shader = ''
        main = texs.get('_MainTex')
        tex = self.texture(main.m_Texture) if main else None
        c = cols.get('_Color')
        color = [c.r, c.g, c.b, c.a] if c else [1, 1, 1, 1]
        cutoff = floats.get('_Cutoff')
        alpha_test = ('Vegetation' in shader or 'Grass' in shader or cutoff is not None and cutoff > 0) and tex and tex[1]
        return dict(name=m.m_Name, color=color, tex=tex[0] if tex else None,
                    alpha=bool(alpha_test), shader=shader,
                    emission='_EmissionColor' in cols and max(cols['_EmissionColor'].r, cols['_EmissionColor'].g) > 0.5 and 'Lit' in m.m_Name)

    # -- prefab --------------------------------------------------------------
    def export(self, name):
        if name not in self.roots:
            return None
        _, go, tf = self.roots[name]
        parts = []  # (verts, normals, uvs, indices, material dict)
        root_inv = np.linalg.inv(trs(tf))  # bake relative to root (root placed by ZDO)

        def walk(t, parent_m, lod_excluded):
            g = t.m_GameObject.read()
            # plants: show the grown look instead of the fresh sprout
            active = {'healthy': False, 'healthy_grown': True}.get(g.m_Name, g.m_IsActive)
            if not active:
                return
            M = parent_m @ trs(t)
            comps = comp_list(g)
            excl = set(lod_excluded)
            for n, o in comps:
                if n == 'LODGroup' and len(o.m_LODs) > 1:
                    for lod in o.m_LODs[1:]:
                        for r in lod.renderers:
                            excl.add(r.renderer.path_id)
                    for r in o.m_LODs[0].renderers:
                        excl.discard(r.renderer.path_id)
            mf = next((o for n, o in comps if n == 'MeshFilter'), None)
            mr = next((o for n, o in comps if n == 'MeshRenderer'), None)
            if mf is not None and mr is not None and mr.m_Enabled and mr.object_reader.path_id not in excl:
                try:
                    self.add_mesh(parts, mf.m_Mesh.read(), mr, M)
                except Exception as e:
                    print('   mesh failed', g.m_Name, e, file=sys.stderr)
            for ch in t.m_Children:
                walk(ch.read(), M, excl)

        walk(tf, root_inv, set())
        if not parts:
            return None
        return self.write_glb(name, parts)

    def add_mesh(self, parts, mesh, renderer, M):
        h = MeshHandler(mesh)
        h.process()
        nv = h.m_VertexCount

        def arr(a, k):
            a = np.array(a, dtype=np.float64)
            if a.ndim == 1:
                a = a.reshape(nv, -1) if nv and a.size % nv == 0 else a.reshape(-1, k)
            return a[:, :k]

        if not nv or not h.m_Vertices:
            return
        v = arr(h.m_Vertices, 3)
        n = arr(h.m_Normals, 3) if h.m_Normals else None
        uv = arr(h.m_UV0, 2) if h.m_UV0 else np.zeros((len(v), 2))
        vw = (M[:3, :3] @ v.T).T + M[:3, 3]
        if n is not None and len(n) == len(v):
            nm = np.linalg.inv(M[:3, :3]).T
            nw = (nm @ n.T).T
            nw /= np.maximum(np.linalg.norm(nw, axis=1, keepdims=True), 1e-9)
        else:
            nw = None
        flip = np.linalg.det(M[:3, :3]) < 0
        tris = h.get_triangles()
        sbi = renderer.m_StaticBatchInfo
        first = sbi.firstSubMesh if sbi and sbi.subMeshCount else 0
        count = sbi.subMeshCount if sbi and sbi.subMeshCount else len(tris)
        mats = renderer.m_Materials
        for si in range(first, min(first + count, len(tris))):
            idx = np.array(tris[si], dtype=np.int64).reshape(-1, 3)
            if len(idx) == 0:
                continue
            mi = si - first
            mat = self.material(mats[min(mi, len(mats) - 1)]) if mats else self.material(None)
            if flip:
                idx = idx[:, ::-1]
            used, inv = np.unique(idx, return_inverse=True)
            parts.append((vw[used], None if nw is None else nw[used], uv[used], inv.reshape(-1, 3), mat))

    # -- glb -------------------------------------------------------------------
    def write_glb(self, name, parts):
        # merge parts by material
        groups = {}
        for v, n, uv, idx, mat in parts:
            key = (mat['name'], mat['tex'], tuple(round(c, 3) for c in mat['color']), mat['alpha'])
            groups.setdefault(key, [mat, []])[1].append((v, n, uv, idx))
        bin_ = bytearray()
        accessors, views, meshes_prims, materials, images, textures = [], [], [], [], [], []
        img_index = {}

        def add_view(data: bytes, target=None):
            while len(bin_) % 4:
                bin_.append(0)
            off = len(bin_)
            bin_.extend(data)
            views.append(dict(buffer=0, byteOffset=off, byteLength=len(data), **({'target': target} if target else {})))
            return len(views) - 1

        def add_acc(arr, typ, comp, target, minmax=False):
            vi = add_view(arr.tobytes(), target)
            a = dict(bufferView=vi, componentType=comp, count=int(arr.shape[0]), type=typ)
            if minmax:
                a['min'] = arr.min(axis=0).tolist()
                a['max'] = arr.max(axis=0).tolist()
            accessors.append(a)
            return len(accessors) - 1

        lo = np.array([1e9] * 3)
        hi = -lo
        for (mname, tex, color, alpha), (mat, items) in groups.items():
            V, N, U, I = [], [], [], []
            base = 0
            for v, n, uv, idx in items:
                V.append(v)
                N.append(n if n is not None else np.tile([0, 1, 0], (len(v), 1)))
                U.append(uv)
                I.append(idx + base)
                base += len(v)
            V = np.concatenate(V)
            N = np.concatenate(N)
            U = np.concatenate(U)
            I = np.concatenate(I)
            # Unity LH -> RH: z = -z, reverse winding, flip v
            V = V * np.array([1, 1, -1])
            N = N * np.array([1, 1, -1])
            U = np.stack([U[:, 0], 1.0 - U[:, 1]], 1)
            I = I[:, ::-1]
            lo = np.minimum(lo, V.min(0))
            hi = np.maximum(hi, V.max(0))
            attrs = dict(
                POSITION=add_acc(V.astype(np.float32), 'VEC3', 5126, 34962, True),
                NORMAL=add_acc(N.astype(np.float32), 'VEC3', 5126, 34962),
                TEXCOORD_0=add_acc(U.astype(np.float32), 'VEC2', 5126, 34962),
            )
            itype = (np.uint16, 5123) if base < 65536 else (np.uint32, 5125)
            ind = add_acc(I.reshape(-1).astype(itype[0]), 'SCALAR', itype[1], 34963)
            m = dict(name=mname, pbrMetallicRoughness=dict(baseColorFactor=[min(1, max(0, c)) for c in color], metallicFactor=0.0, roughnessFactor=0.9))
            if tex:
                if tex not in img_index:
                    images.append(dict(uri='../' + tex))
                    textures.append(dict(source=len(images) - 1, sampler=0))
                    img_index[tex] = len(textures) - 1
                m['pbrMetallicRoughness']['baseColorTexture'] = dict(index=img_index[tex])
            if alpha:
                m['alphaMode'] = 'MASK'
                m['alphaCutoff'] = 0.5
                m['doubleSided'] = True
            if mat.get('emission'):
                m['emissiveFactor'] = [1.0, 0.6, 0.3]
            materials.append(m)
            meshes_prims.append(dict(attributes=attrs, indices=ind, material=len(materials) - 1))
        gltf = dict(asset=dict(version='2.0', generator='valheimdisplay'), scene=0, scenes=[dict(nodes=[0])],
                    nodes=[dict(mesh=0, name=name)], meshes=[dict(primitives=meshes_prims)],
                    accessors=accessors, bufferViews=views, buffers=[dict(byteLength=len(bin_))], materials=materials)
        if images:
            gltf['images'] = images
            gltf['textures'] = textures
            gltf['samplers'] = [dict(magFilter=9729, minFilter=9987, wrapS=10497, wrapT=10497)]
        js = json.dumps(gltf).encode()
        while len(js) % 4:
            js += b' '
        while len(bin_) % 4:
            bin_.append(0)
        total = 12 + 8 + len(js) + 8 + len(bin_)
        os.makedirs(os.path.join(self.out, 'models'), exist_ok=True)
        with open(os.path.join(self.out, 'models', name + '.glb'), 'wb') as f:
            f.write(struct.pack('<III', 0x46546C67, 2, total))
            f.write(struct.pack('<II', len(js), 0x4E4F534A) + js)
            f.write(struct.pack('<II', len(bin_), 0x004E4942) + bytes(bin_))
        return dict(min=lo.tolist(), max=hi.tolist(), prims=len(meshes_prims))


def main():
    root, out = sys.argv[1], sys.argv[2]
    names = sys.argv[3:]
    if names and names[0] == '--list':
        names = [l.strip() for l in open(names[1]) if l.strip()]
    env = load_env(root)
    ex = Exporter(env, out)
    print(f'{len(ex.roots)} root prefabs indexed', file=sys.stderr)
    manifest_path = os.path.join(out, 'models.json')
    manifest = json.load(open(manifest_path)) if os.path.exists(manifest_path) else {}
    for n in names:
        try:
            r = ex.export(n)
        except Exception as e:
            print('FAIL', n, e, file=sys.stderr)
            r = None
        print(n, r, file=sys.stderr)
        if r:
            manifest[n] = r
    json.dump(manifest, open(manifest_path, 'w'), indent=1)


if __name__ == '__main__':
    main()
