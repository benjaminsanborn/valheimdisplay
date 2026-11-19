import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = (id) => document.getElementById(id);
const SUN_ANGLE = 215;
const NUM_LAYERS = 10;
// per-layer tints for the terrain texture array (see tools/export_terrain_textures.py)
const LAYER_TINT = [
  [1.0, 1.0, 1.0], [0.95, 0.95, 0.9], [0.9, 0.9, 0.85], [1.0, 0.97, 0.9], [1.0, 1.0, 1.0],
  [1.0, 1.0, 1.0], [0.95, 0.95, 0.95], [0.95, 0.9, 0.85], [0.55, 0.45, 0.38], [1.0, 1.0, 1.0],
];
// grass colours (sRGB) per terrain layer that grows grass: meadows, forest, swamp, plains
const GRASS = { 0: [0.4, 0.55, 0.21], 1: [0.3, 0.4, 0.17], 2: [0.38, 0.36, 0.2], 3: [0.72, 0.66, 0.32] };
const GRASS_DENSITY = { 0: 2.6, 1: 0.5, 2: 0.6, 3: 2.4 };

// ---------------------------------------------------------------- renderer & scene
const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
$('view').appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1915);
const hemi = new THREE.HemisphereLight(0xcfe3ff, 0x5a4a32, 1.1);
const sun = new THREE.DirectionalLight(0xfff1d6, 2.6);
sun.castShadow = true;
sun.shadow.mapSize.set(4096, 4096);
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.6;
scene.add(hemi, sun, sun.target);

const aspect = () => window.innerWidth / window.innerHeight;
const camera = new THREE.OrthographicCamera(-100, 100, 100, -100, -2000, 4000);
let orthoSize = 120;
function setFrustum() {
  const a = aspect();
  camera.left = -orthoSize * a; camera.right = orthoSize * a;
  camera.top = orthoSize; camera.bottom = -orthoSize;
  camera.updateProjectionMatrix();
}
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.maxPolarAngle = Math.PI * 0.47;
controls.screenSpacePanning = false;
controls.minZoom = 0.4;
controls.maxZoom = 12;

const clock = new THREE.Clock();
const timeUniform = { value: 0 };
const texLoader = new THREE.TextureLoader();

// ---------------------------------------------------------------- shared textures
function loadImage(url) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; });
}
async function loadLayerArray() {
  const S = 256;
  const data = new Uint8Array(S * S * 4 * NUM_LAYERS);
  const cv = document.createElement('canvas');
  cv.width = cv.height = S;
  const ctx = cv.getContext('2d', { willReadFrequently: true });
  const imgs = await Promise.all(Array.from({ length: NUM_LAYERS }, (_, i) => loadImage(`assets/terrain/layer${i}.jpg`)));
  imgs.forEach((img, i) => {
    ctx.drawImage(img, 0, 0, S, S);
    data.set(ctx.getImageData(0, 0, S, S).data, i * S * S * 4);
  });
  const t = new THREE.DataArrayTexture(data, S, S, NUM_LAYERS);
  t.format = THREE.RGBAFormat;
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  t.magFilter = THREE.LinearFilter;
  t.generateMipmaps = true;
  t.anisotropy = 8;
  t.needsUpdate = true;
  return t;
}
const shared = {};
async function loadShared() {
  const [layers, grass, nmap, foam] = await Promise.all([
    loadLayerArray(),
    texLoader.loadAsync('assets/terrain/grass_meadows.png'),
    texLoader.loadAsync('assets/terrain/water_normals.png'),
    texLoader.loadAsync('assets/terrain/foam.jpg'),
  ]);
  grass.colorSpace = THREE.SRGBColorSpace;
  for (const t of [nmap, foam]) t.wrapS = t.wrapT = THREE.RepeatWrapping;
  Object.assign(shared, { layers, grass, nmap, foam });
}

// ---------------------------------------------------------------- models
const gltf = new GLTFLoader();
const modelCache = new Map();
let modelInfo = {};
function loadModel(name) {
  if (!modelCache.has(name)) {
    modelCache.set(name, new Promise((resolve) => {
      gltf.load(`assets/models/${encodeURIComponent(name)}.glb`, (g) => {
        const parts = [];
        g.scene.traverse((o) => {
          if (!o.isMesh) return;
          const m = o.material;
          if (m.map) m.map.anisotropy = 4;
          if (m.alphaTest > 0) { m.side = THREE.DoubleSide; m.alphaTest = 0.45; }
          m.roughness = 0.95; m.metalness = 0;
          parts.push({ geometry: o.geometry, material: m });
        });
        resolve(parts);
      }, undefined, () => resolve(null));
    }));
  }
  return modelCache.get(name);
}

// ---------------------------------------------------------------- terrain
function terrainMaterial(waterLevel) {
  const mat = new THREE.MeshStandardMaterial({ roughness: 1, metalness: 0 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.waterLevel = { value: waterLevel };
    sh.uniforms.layers = { value: shared.layers };
    sh.uniforms.tints = { value: LAYER_TINT.map((c) => new THREE.Vector3(...c)) };
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', `#include <common>
        attribute vec4 w0; attribute vec4 w1; attribute vec4 w2; attribute float variation;
        varying vec4 vW0; varying vec4 vW1; varying vec4 vW2; varying float vVar; varying vec2 vXZ; varying float vY;`)
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vW0 = w0; vW1 = w1; vW2 = w2; vVar = variation; vXZ = position.xz; vY = position.y;`);
    sh.fragmentShader = sh.fragmentShader
      .replace('#include <common>', `#include <common>
        precision highp sampler2DArray;
        uniform sampler2DArray layers; uniform vec3 tints[${NUM_LAYERS}]; uniform float waterLevel;
        varying vec4 vW0; varying vec4 vW1; varying vec4 vW2; varying float vVar; varying vec2 vXZ; varying float vY;
        vec3 layerCol(float i, float w, vec2 uv) {
          if (w < 0.004) return vec3(0.0);
          int k = int(i);
          // two scales mixed to hide tiling
          vec3 a = texture(layers, vec3(uv / 3.5, i)).rgb;
          vec3 b = texture(layers, vec3(uv / 11.0 + 0.37, i)).rgb;
          return w * mix(a, b, 0.4) * tints[k];
        }`)
      .replace('#include <map_fragment>', `
        vec3 tc = layerCol(0., vW0.x, vXZ) + layerCol(1., vW0.y, vXZ) + layerCol(2., vW0.z, vXZ) + layerCol(3., vW0.w, vXZ)
                + layerCol(4., vW1.x, vXZ) + layerCol(5., vW1.y, vXZ) + layerCol(6., vW1.z, vXZ) + layerCol(7., vW1.w, vXZ)
                + layerCol(8., vW2.x, vXZ) + layerCol(9., vW2.y, vXZ);
        float wsum = dot(vW0, vec4(1.)) + dot(vW1, vec4(1.)) + vW2.x + vW2.y;
        tc /= max(wsum, 0.001);
        diffuseColor.rgb *= tc * (0.82 + 0.36 * vVar);
        float under = smoothstep(0.0, 4.0, waterLevel - vY);
        diffuseColor.rgb = mix(diffuseColor.rgb, diffuseColor.rgb * vec3(0.35, 0.5, 0.55), under);`);
  };
  return mat;
}

function buildTerrain(info, buf) {
  const { w, d, x0, z0, step } = info.grid;
  const n = w * d;
  const heights = new Float32Array(buf, 0, n);
  const weights = new Uint8Array(buf, n * 4, n * 12);
  const variation = new Uint8Array(buf, n * 16, n);
  const pos = new Float32Array(n * 3);
  const w0 = new Uint8Array(n * 4), w1 = new Uint8Array(n * 4), w2 = new Uint8Array(n * 4);
  for (let k = 0; k < n; k++) {
    const i = k % w, j = (k / w) | 0;
    pos[k * 3] = x0 + i * step;
    pos[k * 3 + 1] = heights[k];
    pos[k * 3 + 2] = -(z0 + j * step);
    for (let c = 0; c < 4; c++) {
      w0[k * 4 + c] = weights[k * 12 + c];
      w1[k * 4 + c] = weights[k * 12 + 4 + c];
      w2[k * 4 + c] = weights[k * 12 + 8 + c];
    }
  }
  const idx = new Uint32Array((w - 1) * (d - 1) * 6);
  let t = 0;
  for (let j = 0; j < d - 1; j++) {
    for (let i = 0; i < w - 1; i++) {
      const a = j * w + i, b = a + 1, c = a + w, e = c + 1;
      idx[t++] = a; idx[t++] = b; idx[t++] = c;
      idx[t++] = b; idx[t++] = e; idx[t++] = c;
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('w0', new THREE.BufferAttribute(w0, 4, true));
  g.setAttribute('w1', new THREE.BufferAttribute(w1, 4, true));
  g.setAttribute('w2', new THREE.BufferAttribute(w2, 4, true));
  g.setAttribute('variation', new THREE.BufferAttribute(variation, 1, true));
  g.setIndex(new THREE.BufferAttribute(idx, 1));
  g.computeVertexNormals();
  const mesh = new THREE.Mesh(g, terrainMaterial(info.water));
  mesh.receiveShadow = true;
  mesh.castShadow = true;

  // diorama skirt: earth walls down to a base, with the water level shown on the sides
  let minH = Infinity;
  for (let k = 0; k < n; k += 7) minH = Math.min(minH, heights[k]);
  const floorY = Math.min(minH, info.water) - 12;
  const group = new THREE.Group();
  const earth = new THREE.MeshStandardMaterial({ color: 0x4a3b2a, roughness: 1, side: THREE.DoubleSide });
  const waterSide = new THREE.MeshStandardMaterial({ color: 0x1d4f66, roughness: 0.3, transparent: true, opacity: 0.8, side: THREE.DoubleSide });
  const edges = [
    Array.from({ length: w }, (_, i) => i),
    Array.from({ length: w }, (_, i) => (d - 1) * w + (w - 1 - i)),
    Array.from({ length: d }, (_, j) => (d - 1 - j) * w),
    Array.from({ length: d }, (_, j) => j * w + w - 1),
  ];
  const midX = x0 + (w - 1) * step / 2, midZ = -(z0 + (d - 1) * step / 2);
  for (const e of edges) {
    for (const [mat, top, bottom, offset] of [
      [earth, (k) => heights[k], () => floorY, 0],
      [waterSide, () => info.water, (k) => Math.max(floorY, heights[k]), 0.05],
    ]) {
      const p = new Float32Array(e.length * 6);
      e.forEach((k, s) => {
        const x = pos[k * 3], z = pos[k * 3 + 2];
        const ox = Math.sign(x - midX) * offset, oz = Math.sign(z - midZ) * offset;
        const tY = top(k), bY = bottom(k);
        p.set([x + ox, Math.max(tY, bY), z + oz], s * 6);
        p.set([x + ox, bY, z + oz], s * 6 + 3);
      });
      const ix = [];
      for (let s = 0; s < e.length - 1; s++) { const a = s * 2; ix.push(a, a + 1, a + 2, a + 2, a + 1, a + 3); }
      const sg = new THREE.BufferGeometry();
      sg.setAttribute('position', new THREE.BufferAttribute(p, 3));
      sg.setIndex(ix);
      sg.computeVertexNormals();
      group.add(new THREE.Mesh(sg, mat));
    }
  }
  const W = (w - 1) * step, D = (d - 1) * step;
  const cx = x0 + W / 2, cz = -(z0 + D / 2);
  const bottom = new THREE.Mesh(new THREE.PlaneGeometry(W, D), earth);
  bottom.rotation.x = Math.PI / 2;
  bottom.position.set(cx, floorY, cz);
  group.add(bottom);
  const sample = (x, z) => {   // bilinear terrain height at three.js (x, z)
    const fi = (x - x0) / step, fj = (-z - z0) / step;
    const i = Math.max(0, Math.min(w - 2, Math.floor(fi))), j = Math.max(0, Math.min(d - 2, Math.floor(fj)));
    const u = Math.min(1, Math.max(0, fi - i)), v = Math.min(1, Math.max(0, fj - j));
    const h = (a, b) => heights[(j + b) * w + i + a];
    return (h(0, 0) * (1 - u) + h(1, 0) * u) * (1 - v) + (h(0, 1) * (1 - u) + h(1, 1) * u) * v;
  };
  return { mesh, skirt: group, heights, weights, variation, extent: Math.max(W, D), center: new THREE.Vector3(cx, info.water, cz), sample, W, D, cx, cz };
}

// ---------------------------------------------------------------- water
function buildWater(info, T) {
  const step = 2;
  const nx = Math.ceil(T.W / step) + 1, nz = Math.ceil(T.D / step) + 1;
  const g = new THREE.PlaneGeometry(T.W, T.D, nx - 1, nz - 1);
  g.rotateX(-Math.PI / 2);
  g.translate(T.cx, info.water, T.cz);
  const p = g.attributes.position;
  const depth = new Float32Array(p.count);
  for (let k = 0; k < p.count; k++) depth[k] = info.water - T.sample(p.getX(k), p.getZ(k));
  g.setAttribute('depth', new THREE.BufferAttribute(depth, 1));
  const sunDir = new THREE.Vector3().subVectors(sun.position, sun.target.position).normalize();
  const mat = new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: { time: timeUniform, nmap: { value: shared.nmap }, foam: { value: shared.foam }, sunDir: { value: sunDir } },
    vertexShader: `
      attribute float depth;
      varying float vDepth; varying vec3 vWorld;
      void main() {
        vDepth = depth;
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vWorld = wp.xyz;
        gl_Position = projectionMatrix * viewMatrix * wp;
      }`,
    fragmentShader: `
      uniform float time; uniform sampler2D nmap; uniform sampler2D foam; uniform vec3 sunDir;
      varying float vDepth; varying vec3 vWorld;
      void main() {
        if (vDepth < -0.3) discard;
        vec2 uv = vWorld.xz;
        vec3 n1 = texture2D(nmap, uv / 16.0 + vec2(time * 0.010, time * 0.007)).xyz * 2.0 - 1.0;
        vec3 n2 = texture2D(nmap, uv / 7.0 + vec2(-time * 0.013, time * 0.011)).xyz * 2.0 - 1.0;
        vec3 n = normalize(vec3(n1.x + n2.x * 0.6, 4.5, n1.y + n2.y * 0.6));
        vec3 V = normalize(cameraPosition - vWorld);
        float d = max(vDepth, 0.0);
        vec3 shallow = vec3(0.10, 0.36, 0.36);
        vec3 deep = vec3(0.012, 0.07, 0.12);
        vec3 col = mix(shallow, deep, smoothstep(0.0, 7.0, d));
        float fres = 0.04 + 0.96 * pow(1.0 - max(dot(n, V), 0.0), 5.0);
        vec3 sky = vec3(0.55, 0.68, 0.82);
        col = mix(col, sky, clamp(fres, 0.0, 0.35));
        vec3 H = normalize(sunDir + V);
        float spec = pow(max(dot(n, H), 0.0), 2500.0) * 0.5;
        col += vec3(1.0, 0.93, 0.8) * spec;
        // shoreline foam: texture + bands rolling in towards the beach
        float f = texture2D(foam, uv / 5.0 + vec2(time * 0.015, -time * 0.01)).r;
        float shore = 1.0 - smoothstep(0.0, 0.45, d);
        float bands = smoothstep(0.62, 0.95, f + 0.3 * sin(d * 14.0 - time * 1.4));
        float foamAmt = clamp(shore * (0.15 + bands * 0.7), 0.0, 1.0);
        col = mix(col, vec3(0.86, 0.9, 0.9), foamAmt * 0.7);
        float alpha = mix(0.3, 0.92, smoothstep(0.0, 2.5, d));
        alpha = max(alpha, foamAmt * 0.7);
        gl_FragColor = vec4(col, alpha);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const water = new THREE.Mesh(g, mat);
  water.renderOrder = 2;
  return water;
}

// ---------------------------------------------------------------- grass
function grassGeometry() {
  // three crossed cards, 1.1 m wide, 0.7 m tall; uv.y = 0 at the root
  const pos = [], uv = [], nrm = [], idx = [];
  for (let c = 0; c < 3; c++) {
    const a = (c / 3) * Math.PI, dx = Math.cos(a) * 0.55, dz = Math.sin(a) * 0.55;
    const b = pos.length / 3;
    pos.push(-dx, 0, -dz, dx, 0, dz, dx, 0.7, dz, -dx, 0.7, -dz);
    uv.push(0, 0, 1, 0, 1, 1, 0, 1);
    for (let k = 0; k < 4; k++) nrm.push(0, 1, 0);
    idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setIndex(idx);
  return g;
}

function builtFootprint(info, T) {
  // cells covered by built pieces sitting near the ground (floors, walls...), so no grass grows through them
  const { w, d, x0, z0 } = info.grid;
  const mask = new Uint8Array(w * d);
  const q = new THREE.Quaternion(), v = new THREE.Vector3();
  for (const o of info.objects) {
    if (o[11] !== 1) continue;
    const mi = modelInfo[info.models[o[0]]];
    if (!mi) continue;
    if (o[2] + mi.min[1] * o[9] > T.sample(o[1], o[3]) + 1.2) continue;
    q.set(o[4], o[5], o[6], o[7]);
    const corners = [[mi.min[0], mi.min[2]], [mi.max[0], mi.min[2]], [mi.max[0], mi.max[2]], [mi.min[0], mi.max[2]]]
      .map(([x, z]) => { v.set(x * o[8], 0, z * o[10]).applyQuaternion(q); return [v.x + o[1], v.z + o[3]]; });
    const xs = corners.map((c) => c[0]), zs = corners.map((c) => c[1]);
    for (let x = Math.floor(Math.min(...xs)); x <= Math.ceil(Math.max(...xs)); x++) {
      for (let z = Math.floor(Math.min(...zs)); z <= Math.ceil(Math.max(...zs)); z++) {
        let inside = true;
        for (let k = 0; k < 4 && inside; k++) {
          const [ax, az] = corners[k], [bx, bz] = corners[(k + 1) % 4];
          inside = (bx - ax) * (z - az) - (bz - az) * (x - ax) >= -0.6 * Math.hypot(bx - ax, bz - az);
        }
        if (!inside) continue;
        const i = Math.round(x - x0), j = Math.round(-z - z0);
        if (i >= 0 && j >= 0 && i < w && j < d) mask[j * w + i] = 1;
      }
    }
  }
  return mask;
}

function buildDistance(info) {
  // distance (m) from each 8 m cell to the nearest built piece, for thinning grass away from bases
  const { w, d, x0, z0 } = info.grid, C = 8;
  const cw = Math.ceil(w / C), cd = Math.ceil(d / C);
  const built = info.objects.filter((o) => o[11] === 1);
  const dist = new Float32Array(cw * cd).fill(1e9);
  for (let cj = 0; cj < cd; cj++) for (let ci = 0; ci < cw; ci++) {
    const x = x0 + ci * C + C / 2, z = -(z0 + cj * C + C / 2);
    let best = 1e9;
    for (const o of built) { const dd = (o[1] - x) ** 2 + (o[3] - z) ** 2; if (dd < best) best = dd; }
    dist[cj * cw + ci] = Math.sqrt(best);
  }
  return (i, j) => dist[Math.floor(j / C) * cw + Math.floor(i / C)];
}

function buildGrass(info, T) {
  const { w, d, x0, z0 } = info.grid;
  const blocked = builtFootprint(info, T);
  const distTo = buildDistance(info);
  let seed = 12345;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const items = [];
  const col = new THREE.Color();
  for (let j = 0; j < d - 1; j++) {
    for (let i = 0; i < w - 1; i++) {
      const k = j * w + i;
      if (blocked[k] || T.heights[k] < info.water + 0.25) continue;
      let dens = 0, r = 0, g = 0, b = 0;
      for (const L of [0, 1, 2, 3]) {
        const wt = T.weights[k * 12 + L] / 255;
        dens += wt * GRASS_DENSITY[L];
        r += wt * GRASS[L][0]; g += wt * GRASS[L][1]; b += wt * GRASS[L][2];
      }
      const wsum = (T.weights[k * 12] + T.weights[k * 12 + 1] + T.weights[k * 12 + 2] + T.weights[k * 12 + 3]) / 255;
      if (wsum < 0.05) continue;
      dens *= Math.max(0.2, Math.min(1, 1 - (distTo(i, j) - 50) / 120));
      const count = Math.floor(dens + rnd());
      const vv = T.variation[k] / 255;
      for (let c = 0; c < count; c++) {
        const x = x0 + i + rnd(), z = -(z0 + j + rnd());
        const s = 0.75 + rnd() * 0.6;
        const shade = 0.8 + vv * 0.35 + rnd() * 0.1;
        col.setRGB((r / wsum) * shade, (g / wsum) * shade, (b / wsum) * shade, THREE.SRGBColorSpace);
        items.push([x, T.sample(x, z) - 0.05, z, rnd() * Math.PI, s, col.r, col.g, col.b]);
      }
    }
  }
  const mat = new THREE.MeshStandardMaterial({ map: shared.grass, alphaTest: 0.25, alphaToCoverage: true, side: THREE.DoubleSide, roughness: 1 });
  mat.onBeforeCompile = (sh) => {
    sh.uniforms.time = timeUniform;
    // light both sides of a blade as if it faced the sky (no dark back faces)
    sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_begin>', '#include <normal_fragment_begin>\n normal = normalize(vNormal);');
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float time;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vec3 ip = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);
        float sway = sin(time * 1.6 + ip.x * 0.35 + ip.z * 0.22) + 0.5 * sin(time * 2.7 + ip.x * 0.9);
        transformed.x += sway * 0.09 * uv.y;
        transformed.z += sway * 0.05 * uv.y;`);
  };
  const mesh = new THREE.InstancedMesh(grassGeometry(), mat, Math.max(1, items.length));
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
  items.forEach((it, n) => {
    p.set(it[0], it[1], it[2]);
    q.setFromAxisAngle(up, it[3]);
    s.set(it[4], it[4] * (0.8 + 0.4 * ((n * 7919) % 100) / 100), it[4]);
    mesh.setMatrixAt(n, m4.compose(p, q, s));
    mesh.setColorAt(n, col.setRGB(it[5], it[6], it[7]));
  });
  mesh.count = items.length;
  mesh.receiveShadow = true;
  mesh.frustumCulled = false;
  return mesh;
}

// ---------------------------------------------------------------- objects
const TREE_RE = /tree|Tree|Beech|Birch|Oak|Pine|Fir|shrub|stubbe|YggaShoot|Bush/;
function nearBuild(info) {
  const CLEAR = 45, cell = CLEAR;
  const grid = new Map();
  for (const o of info.objects) if (o[11] === 1) {
    const k = `${Math.floor(o[1] / cell)},${Math.floor(o[3] / cell)}`;
    if (!grid.has(k)) grid.set(k, []);
    grid.get(k).push(o);
  }
  // a tree of height h hides ground up to ~h / tan(35deg) behind it from the isometric camera
  return (x, z, h) => {
    const r = Math.min(CLEAR, 8 + h * 1.3);
    const cx = Math.floor(x / cell), cz = Math.floor(z / cell);
    for (let i = -1; i <= 1; i++) for (let j = -1; j <= 1; j++) {
      for (const o of grid.get(`${cx + i},${cz + j}`) || []) if (Math.hypot(o[1] - x, o[3] - z) < r) return true;
    }
    return false;
  };
}

async function buildObjects(info, onProgress) {
  const byModel = new Map();
  const near = nearBuild(info);
  for (const o of info.objects) {
    const name = info.models[o[0]];
    const mi = modelInfo[name];
    const th = mi ? (mi.max[1] - mi.min[1]) * o[9] : 0;
    if (o[11] !== 1 && TREE_RE.test(name) && th > 2.5 && near(o[1], o[3], th)) continue; // clear trees around builds
    if (!byModel.has(o[0])) byModel.set(o[0], []);
    byModel.get(o[0]).push(o);
  }
  const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), p = new THREE.Vector3(), s = new THREE.Vector3();
  const group = new THREE.Group();
  let done = 0;
  await Promise.all([...byModel.entries()].map(async ([mi, items]) => {
    const parts = await loadModel(info.models[mi]);
    onProgress(++done, byModel.size);
    if (!parts) return;
    for (const part of parts) {
      const im = new THREE.InstancedMesh(part.geometry, part.material, items.length);
      items.forEach((o, k) => {
        im.setMatrixAt(k, m4.compose(p.set(o[1], o[2], o[3]), q.set(o[4], o[5], o[6], o[7]), s.set(o[8], o[9], o[10])));
      });
      im.castShadow = true;
      im.receiveShadow = true;
      im.computeBoundingSphere();
      group.add(im);
    }
  }));
  return group;
}

// ---------------------------------------------------------------- region loading
let region = null;
let world = new THREE.Group();
scene.add(world);
let labelEls = [];
let loadToken = 0;

function placeSun() {
  const a = THREE.MathUtils.degToRad(SUN_ANGLE);
  const r = region.extent, c = region.center;
  sun.position.set(c.x + Math.cos(a) * r, c.y + r * 0.9, c.z + Math.sin(a) * r);
  sun.target.position.copy(c);
  sun.target.updateMatrixWorld();
  const sc = sun.shadow.camera, h = r * 0.75;
  sc.left = -h; sc.right = h; sc.top = h; sc.bottom = -h; sc.near = 1; sc.far = r * 4;
  sc.updateProjectionMatrix();
}

function resetView(zoom) {
  const c = region.focus;
  camera.position.copy(c).addScaledVector(new THREE.Vector3(1, 0.9, 1).normalize(), 780);
  camera.lookAt(c);
  camera.zoom = zoom || +(new URLSearchParams(location.search).get('zoom') || 1);
  orthoSize = Math.max(25, region.buildRadius * 0.9);
  setFrustum();
  controls.target.copy(c);
  controls.update();
}

function findFocus(info, fallback) {
  const built = info.objects.filter((o) => o[11] === 1);
  const focus = fallback.clone();
  if (built.length) {
    const sample = built.length > 1500 ? built.filter((_, i) => i % 3 === 0) : built;
    let best = sample[0], bestN = -1;
    for (const a of sample) {
      let n = 0;
      for (const b of sample) if (Math.abs(a[1] - b[1]) < 25 && Math.abs(a[3] - b[3]) < 25 && Math.hypot(a[1] - b[1], a[3] - b[3]) < 25) n++;
      if (n > bestN) { bestN = n; best = a; }
    }
    const nb = built.filter((b) => Math.hypot(best[1] - b[1], best[3] - b[3]) < 40);
    focus.set(0, 0, 0);
    nb.forEach((o) => focus.add(new THREE.Vector3(o[1], o[2], o[3])));
    focus.divideScalar(nb.length);
  }
  const dists = built.map((o) => Math.hypot(o[1] - focus.x, o[3] - focus.z)).filter((d) => d < 120).sort((a, b) => a - b);
  const radius = Math.min(140, Math.max(18, dists.length ? dists[Math.floor(dists.length * 0.9)] : 40));
  return { focus, radius };
}

async function loadRegion(slug, arrive) {
  const token = ++loadToken;
  $('loading').style.display = '';
  $('loading').textContent = 'Loading terrain…';
  const [info, buf] = await Promise.all([
    fetch(`assets/regions/${slug}.json`).then((r) => r.json()),
    fetch(`assets/regions/${slug}.terrain.bin`).then((r) => r.arrayBuffer()),
  ]);
  if (token !== loadToken) return;
  scene.remove(world);
  world = new THREE.Group();
  scene.add(world);
  const T = buildTerrain(info, buf);
  const { focus, radius } = findFocus(info, T.center);
  region = { info, extent: T.extent, center: T.center, focus, buildRadius: radius };
  if (arrive) region.focus = new THREE.Vector3(arrive.pos[0], arrive.pos[1], arrive.pos[2]);
  placeSun();
  // arriving through a portal: start close to the portal you came out of
  resetView(arrive ? Math.max(1, (region.buildRadius * 0.9) / 30) : undefined);
  world.add(T.mesh, T.skirt, buildWater(info, T));
  $('loading').textContent = 'Growing grass…';
  await new Promise((r) => setTimeout(r, 0));
  world.add(buildGrass(info, T));
  const objects = await buildObjects(info, (d, n) => { $('loading').textContent = `Loading models ${d}/${n}…`; });
  if (token !== loadToken) return;
  world.add(objects);

  const lbl = $('labels');
  lbl.innerHTML = '';
  labelEls = info.labels.map((L) => {
    const el = document.createElement('div');
    const portal = L.kind.startsWith('portal');
    el.className = 'lbl' + (portal ? ' portal' : '') + (L.target ? ' link' : '');
    el.textContent = (portal ? '◈ ' : '') + L.text;
    if (portal) el.title = L.target ? `Portal to ${L.target.title}` : 'Portal (no partner portal)';
    if (L.target) el.onclick = () => travel(L.target);
    lbl.appendChild(el);
    return { el, portal, target: L.target, base: new THREE.Vector3(L.pos[0], L.pos[1] + 1.6, L.pos[2]),
             pos: new THREE.Vector3(L.pos[0], L.pos[1] + (portal ? 4 : 2.2), L.pos[2]) };
  });
  $('loading').style.display = 'none';
}

function updateLabels() {
  const w = window.innerWidth, h = window.innerHeight;
  const v = new THREE.Vector3();
  const placed = [];
  const zoomedIn = camera.zoom > 1.8;
  const big = document.body.classList.contains('big');
  for (const L of labelEls) {
    v.copy(L.pos).project(camera);
    let on = (L.portal || zoomedIn) && !big && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
    const x = (v.x * 0.5 + 0.5) * w, y = (-v.y * 0.5 + 0.5) * h;
    if (on) {
      const bw = L.w || 80;
      if (placed.some((p) => Math.abs(p[0] - x) < (p[2] + bw) / 2 + 4 && Math.abs(p[1] - y) < 22)) on = false;
      else placed.push([x, y, bw]);
    }
    L.el.style.display = on ? '' : 'none';
    if (on) { L.el.style.left = `${x}px`; L.el.style.top = `${y}px`; if (!L.w) L.w = L.el.offsetWidth; }
  }
}

// ---------------------------------------------------------------- globe place picker
let index;
let current;
function layoutGlobe() {
  const big = document.body.classList.contains('big');
  const size = $('disc').getBoundingClientRect().width;
  const R = index.radius;
  // fit the explored places; the enlarged globe shows a little more of the world around them
  const xs = index.regions.map((r) => r.x), zs = index.regions.map((r) => r.z);
  const fit = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs));
  const span = Math.min(2 * R, big ? fit * 1.5 + 2500 : fit * 1.35 + 1500);
  // the wider the view, the more it centres on the middle of the world so the world's edge stays round
  const t = Math.min(1, Math.max(0, (span - 1.2 * R) / (0.8 * R)));
  const cx = ((Math.min(...xs) + Math.max(...xs)) / 2) * (1 - t);
  const cz = ((Math.min(...zs) + Math.max(...zs)) / 2) * (1 - t);
  const layerSize = (2 * R / span) * size;
  const L = $('layer');
  L.style.width = L.style.height = `${layerSize}px`;
  L.style.left = `${size / 2 - ((cx + R) / (2 * R)) * layerSize}px`;
  L.style.top = `${size / 2 - ((R - cz) / (2 * R)) * layerSize}px`;
  if (big) requestAnimationFrame(declutterMarkers);
}

function declutterMarkers() {
  // in the big globe every label is shown; hide ones that would overlap (hover still reveals them)
  const placed = [];
  const mks = [...document.querySelectorAll('.mk')].sort((a, b) => (b.dataset.slug === current) - (a.dataset.slug === current));
  for (const m of mks) {
    m.classList.remove('hide');
    const r = m.querySelector('span').getBoundingClientRect();
    if (placed.some((p) => r.left < p.right + 4 && r.right > p.left - 4 && r.top < p.bottom + 2 && r.bottom > p.top - 2)) m.classList.add('hide');
    else placed.push(r);
  }
}

// ---------------------------------------------------------------- portal travel
function travel(target) {
  const fx = $('flash');
  fx.classList.add('on');
  setTimeout(() => {
    setPlace(target.slug, target);
    setTimeout(() => fx.classList.remove('on'), 350);
  }, 280);
}

// clicking (not dragging) on or near a linked portal model takes you through it
function portalAt(clientX, clientY) {
  const v = new THREE.Vector3();
  let best = null;
  const r = 34 * Math.min(2.5, Math.max(0.6, camera.zoom));   // px
  for (const L of labelEls) {
    if (!L.target) continue;
    v.copy(L.base).project(camera);
    const d = Math.hypot((v.x * 0.5 + 0.5) * innerWidth - clientX, (-v.y * 0.5 + 0.5) * innerHeight - clientY);
    if (d < r && (!best || d < best.d)) best = { L, d };
  }
  return best && best.L;
}
let downAt = null;
renderer.domElement.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) return;
  const L = portalAt(e.clientX, e.clientY);
  if (L) travel(L.target);
});
renderer.domElement.addEventListener('pointermove', (e) => {
  if (e.buttons) return;
  const L = portalAt(e.clientX, e.clientY);
  renderer.domElement.style.cursor = L ? 'pointer' : '';
  for (const x of labelEls) x.el.classList.toggle('hot', x === L);
});

function setPlace(slug, arrive) {
  current = slug;
  const r = index.regions.find((x) => x.slug === slug);
  document.querySelectorAll('.mk').forEach((m) => m.classList.toggle('on', m.dataset.slug === slug));
  $('placename').innerHTML = `${r.title}<small>${Math.round(r.x)}, ${Math.round(r.z)}</small>`;
  const u = new URL(location.href);
  u.searchParams.set('place', slug);
  history.replaceState(null, '', u);
  loadRegion(slug, arrive);
}

function toggleGlobe(force) {
  document.body.classList.toggle('big', force);
  // layout once now (start of the CSS transition) and again when it settles
  requestAnimationFrame(layoutGlobe);
  setTimeout(layoutGlobe, 320);
}

function buildGlobe() {
  const mk = $('markers');
  for (const r of index.regions) {
    const el = document.createElement('div');
    el.className = 'mk';
    el.dataset.slug = r.slug;
    el.style.left = `${((r.x + index.radius) / (2 * index.radius)) * 100}%`;
    el.style.top = `${((index.radius - r.z) / (2 * index.radius)) * 100}%`;
    el.innerHTML = `<i></i><span>${r.title}</span>`;
    el.onclick = (e) => {
      e.stopPropagation();
      toggleGlobe(false);
      if (r.slug !== current) setPlace(r.slug);
    };
    mk.appendChild(el);
  }
  new ResizeObserver(() => layoutGlobe()).observe($('disc'));
  $('disc').onclick = () => toggleGlobe();
  $('backdrop').onclick = () => toggleGlobe(false);
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape') toggleGlobe(false); });
  layoutGlobe();
}

async function init() {
  [index, modelInfo] = await Promise.all([
    fetch('assets/regions/index.json').then((r) => r.json()),
    fetch('assets/models.json').then((r) => r.json()),
    loadShared(),
  ]);
  buildGlobe();
  const q = new URLSearchParams(location.search).get('place');
  setPlace(index.regions.some((r) => r.slug === q) ? q : index.regions[0].slug);
}

window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight);
  setFrustum();
  if (index) layoutGlobe();
});

function loop() {
  requestAnimationFrame(loop);
  timeUniform.value = clock.getElapsedTime();
  controls.update();
  renderer.render(scene, camera);
  updateLabels();
}
setFrustum();
init();
loop();
window.__viewerReady = () => $('loading').style.display === 'none';
