import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { createWeather, pickWeather, params as weatherParams, BIOME_WEATHER, BIOME_NAMES, WEATHER } from './weather.js';

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
const GRASS_SCALE = matchMedia('(pointer: coarse)').matches ? 0.55 : 1;
const GRASS_DENSITY = { 0: 2.6, 1: 0.5, 2: 0.6, 3: 2.4 };

// ---------------------------------------------------------------- renderer & scene
// phones and tablets: fewer pixels, frames and grass blades, so they don't run hot
const MOBILE = matchMedia('(pointer: coarse)').matches;
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: MOBILE ? 'low-power' : 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, MOBILE ? 1.5 : 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
// the sun never moves within a place, so the shadow map is drawn only when something changes
// (place, sun, timeline) instead of re-rendering every model into it each frame
renderer.shadowMap.autoUpdate = false;
const redrawShadows = () => { renderer.shadowMap.needsUpdate = true; };
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
sun.shadow.mapSize.set(MOBILE ? 2048 : 4096, MOBILE ? 2048 : 4096);
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

// ---------------------------------------------------------------- Huginn: fly freely as Odin's raven
// a perspective camera next to the isometric one; WASD to fly, drag to look, slider for field of view
const raven = new THREE.PerspectiveCamera(70, aspect(), 0.3, 6000);
raven.rotation.order = 'YXZ';
const huginn = { on: false, start: new URLSearchParams(location.search).get('huginn') === '1', yaw: 0, pitch: -0.35, keys: new Set(), vel: new THREE.Vector3(), drag: null,
  stick: { x: 0, y: 0 }, gyro: null };   // gyro: { q: phone orientation, off: yaw added by dragging }
try { raven.fov = +localStorage.getItem('huginnFov') || 70; } catch {}
const view = () => (huginn.on ? raven : camera);

const clock = new THREE.Clock();
let dayIdx = null;        // timelapse: index into index.dates (null = latest)
let night = new URLSearchParams(location.search).get('night') === '1';
const timeUniform = { value: 0 };
const nightUniform = { value: 0 };
const overcastUniform = { value: 0 };
const windUniform = { value: 1 };
const weather = createWeather(scene, nightUniform, MOBILE ? 0.5 : 1);
// 'auto' = picked for the place's biome and the day; or a WEATHER key; or 'off'
let weatherMode = new URLSearchParams(location.search).get('weather') || 'auto';
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
    fog: true,
    uniforms: { ...THREE.UniformsUtils.clone(THREE.UniformsLib.fog), time: timeUniform, nmap: { value: shared.nmap },
      foam: { value: shared.foam }, sunDir: { value: sunDir }, night: nightUniform, overcast: overcastUniform },
    vertexShader: `
      attribute float depth;
      varying float vDepth; varying vec3 vWorld;
      #include <fog_pars_vertex>
      void main() {
        vDepth = depth;
        vec4 wp = modelMatrix * vec4(position, 1.0);
        vWorld = wp.xyz;
        vec4 mvPosition = viewMatrix * wp;
        gl_Position = projectionMatrix * mvPosition;
        #include <fog_vertex>
      }`,
    fragmentShader: `
      uniform float time; uniform sampler2D nmap; uniform sampler2D foam; uniform vec3 sunDir; uniform float night; uniform float overcast;
      varying float vDepth; varying vec3 vWorld;
      #include <fog_pars_fragment>
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
        vec3 col = mix(shallow, deep, smoothstep(0.0, 7.0, d)) * mix(1.0, 0.28, night);
        float fres = 0.04 + 0.96 * pow(1.0 - max(dot(n, V), 0.0), 5.0);
        vec3 sky = mix(mix(vec3(0.55, 0.68, 0.82), vec3(0.36, 0.39, 0.42), overcast), vec3(0.06, 0.09, 0.17), night);
        col = mix(col, sky, clamp(fres, 0.0, 0.35));
        vec3 H = normalize(sunDir + V);
        float spec = pow(max(dot(n, H), 0.0), 2500.0) * 0.5 * (1.0 - 0.85 * overcast);
        col += mix(vec3(1.0, 0.93, 0.8), vec3(0.25, 0.3, 0.4), night) * spec;
        // shoreline foam: texture + bands rolling in towards the beach
        float f = texture2D(foam, uv / 5.0 + vec2(time * 0.015, -time * 0.01)).r;
        float shore = 1.0 - smoothstep(0.0, 0.45, d);
        float bands = smoothstep(0.62, 0.95, f + 0.3 * sin(d * 14.0 - time * 1.4));
        float foamAmt = clamp(shore * (0.15 + bands * 0.7), 0.0, 1.0);
        col = mix(col, vec3(0.86, 0.9, 0.9) * mix(1.0, 0.3, night), foamAmt * 0.7);
        float alpha = mix(0.3, 0.92, smoothstep(0.0, 2.5, d));
        alpha = max(alpha, foamAmt * 0.7);
        gl_FragColor = vec4(col, alpha);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
        #include <fog_fragment>
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
      const count = Math.floor(dens * GRASS_SCALE + rnd());
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
    sh.uniforms.wind = windUniform;
    // light both sides of a blade as if it faced the sky (no dark back faces)
    sh.fragmentShader = sh.fragmentShader.replace('#include <normal_fragment_begin>', '#include <normal_fragment_begin>\n normal = normalize(vNormal);');
    sh.vertexShader = sh.vertexShader
      .replace('#include <common>', '#include <common>\nuniform float time; uniform float wind;')
      .replace('#include <begin_vertex>', `#include <begin_vertex>
        vec3 ip = vec3(instanceMatrix[3][0], instanceMatrix[3][1], instanceMatrix[3][2]);
        float sway = sin(time * 1.6 + ip.x * 0.35 + ip.z * 0.22) + 0.5 * sin(time * 2.7 + ip.x * 0.9);
        transformed.x += sway * 0.09 * wind * uv.y;
        transformed.z += sway * 0.05 * wind * uv.y;`);
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
  const timed = [];
  group.userData.timed = timed;
  let done = 0;
  await Promise.all([...byModel.entries()].map(async ([mi, items]) => {
    const parts = await loadModel(info.models[mi]);
    onProgress(++done, byModel.size);
    if (!parts) return;
    for (const part of parts) {
      const im = new THREE.InstancedMesh(part.geometry, part.material, items.length);
      im.name = info.models[mi];
      items.forEach((o, k) => {
        im.setMatrixAt(k, m4.compose(p.set(o[1], o[2], o[3]), q.set(o[4], o[5], o[6], o[7]), s.set(o[8], o[9], o[10])));
      });
      if (items.some((o) => o[11] === 1)) {
        im.userData.items = items;
        im.userData.mats = im.instanceMatrix.array.slice();
        timed.push(im);
      }
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
  redrawShadows();
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
  if (huginn.on) perchRaven();
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
  region = { info, extent: T.extent, center: T.center, focus, buildRadius: radius, sample: T.sample, T };
  if (arrive) region.focus = new THREE.Vector3(arrive.pos[0], arrive.pos[1], arrive.pos[2]);
  placeSun();
  // arriving through a portal: start close to the portal you came out of
  resetView(arrive ? Math.max(1, (region.buildRadius * 0.9) / 30) : undefined);
  if (huginn.start) { huginn.start = false; toggleHuginn(true); }
  world.add(T.mesh, T.skirt, buildWater(info, T));
  $('loading').textContent = 'Growing grass…';
  await new Promise((r) => setTimeout(r, 0));
  world.add(buildGrass(info, T));
  const objects = await buildObjects(info, (d, n) => { $('loading').textContent = `Loading models ${d}/${n}…`; });
  if (token !== loadToken) return;
  world.add(objects);
  region.timed = objects.userData.timed;
  region.fires = buildFires(info, T);
  weather.setRegion(T, info.water);
  world.add(region.fires.group);
  applyNight();
  applyDay();

  const lbl = $('labels');
  lbl.innerHTML = '';
  labelKey = '';
  labelEls = info.labels.map((L) => {
    const el = document.createElement('div');
    const portal = L.kind.startsWith('portal');
    el.className = 'lbl' + (portal ? ' portal' : '') + (L.target ? ' link' : '');
    el.textContent = (portal ? '◈ ' : '') + L.text;
    if (portal) el.title = L.target ? `Portal to ${L.target.title}` : 'Portal (no partner portal)';
    if (L.target) el.onclick = () => travel(L.target);
    lbl.appendChild(el);
    // the sign/portal piece itself, so the label follows the timeline
    const obj = info.objects.find((o) => o[11] === 1 && Math.abs(o[1] - L.pos[0]) < 0.05 && Math.abs(o[3] - L.pos[2]) < 0.05);
    return { el, portal, obj, target: L.target, base: new THREE.Vector3(L.pos[0], L.pos[1] + 1.6, L.pos[2]),
             pos: new THREE.Vector3(L.pos[0], L.pos[1] + (portal ? 4 : 2.2), L.pos[2]) };
  });
  $('loading').style.display = 'none';
}

// ---------------------------------------------------------------- timelapse
const ZERO = new THREE.Matrix4().makeScale(0, 0, 0).elements;
function visibleOn(o, d) { return o[11] !== 1 || o.length < 14 || (o[12] <= d && d <= o[13]); }
function regionDay() {
  // the region's dates may lag the index's (a place exported before the latest snapshot)
  const dates = region?.info.dates || [];
  if (!dates.length) return 0;
  const want = index.dates[dayIdx ?? index.dates.length - 1];
  let k = 0;
  dates.forEach((dd, i) => { if (dd <= want) k = i; });
  return k;
}
function applyDay() {
  if (!region || !region.timed) return;
  const d = regionDay();
  for (const im of region.timed) {
    const arr = im.instanceMatrix.array, src = im.userData.mats;
    im.userData.items.forEach((o, k) => {
      if (visibleOn(o, d)) arr.set(src.subarray(k * 16, k * 16 + 16), k * 16);
      else arr.set(ZERO, k * 16);
    });
    im.instanceMatrix.needsUpdate = true;
  }
  redrawShadows();
  for (const f of region.fires?.items || []) f.on = visibleOn(f.o, d);
  refreshWeather();
  updateWorldState();
  drawFog();
  updateTimelineUI();
}

let fogCtx = null, zoneList = null, fogImg = null;
function drawFog() {
  if (!fogCtx || !zoneList) return;
  const day = dayIdx ?? index.dates.length - 1;
  const c = fogCtx.canvas, N = c.width, R = index.radius;
  const mask = document.createElement('canvas');
  mask.width = mask.height = N;
  const m = mask.getContext('2d');
  m.fillStyle = '#fff';
  const z = (64 / (2 * R)) * N;
  for (const [zx, zy, d] of zoneList) {
    if (d > day) continue;
    m.fillRect(((zx * 64 - 32 + R) / (2 * R)) * N, ((R - (zy * 64 + 32)) / (2 * R)) * N, z + 0.6, z + 0.6);
  }
  fogCtx.globalCompositeOperation = 'source-over';
  fogCtx.filter = 'none';
  fogCtx.clearRect(0, 0, N, N);
  fogCtx.drawImage(fogImg, 0, 0, N, N);
  fogCtx.globalCompositeOperation = 'destination-out';
  fogCtx.filter = `blur(${1.5 * N / 1024}px)`;
  fogCtx.drawImage(mask, 0, 0);
  fogCtx.filter = 'none';
}

function fmtDate(iso) {
  return new Date(iso + 'T12:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}
function updateTimelineUI() {
  const n = index.dates.length, d = dayIdx ?? n - 1;
  $('day').value = d;
  const gd = index.days?.[d];
  $('daylabel').textContent = fmtDate(index.dates[d]) + (gd != null ? ` · Day ${gd}` : '') + (d === n - 1 ? ' · latest' : '');
  document.querySelectorAll('.mk').forEach((m) => {
    const r = index.regions.find((x) => x.slug === m.dataset.slug);
    m.classList.toggle('future', r.first != null && r.first > d);
  });
}
// ---------------------------------------------------------------- weather
const placeBiome = (r) => r?.biome || region?.info.biome || 'Meadows';
const autoWeather = (r) => pickWeather(placeBiome(r), r.slug, index.dates?.[dayIdx ?? index.dates.length - 1] || '');
function weatherKey() {
  const r = index?.regions.find((x) => x.slug === current);
  if (weatherMode === 'off') return null;
  if (weatherMode !== 'auto' && WEATHER[weatherMode]) return weatherMode;
  return r ? autoWeather(r) : null;
}
function refreshWeather() {
  const key = weatherKey();
  weather.set(key);
  applyLighting();
  const r = index?.regions.find((x) => x.slug === current);
  if (!r) return;
  const biome = r.biome || region?.info.biome;
  const parts = [biome && BIOME_NAMES[biome], key ? WEATHER[key].name : null, `${Math.round(r.x)}, ${Math.round(r.z)}`].filter(Boolean);
  const sm = $('placename').querySelector('small');
  if (sm) sm.textContent = parts.join(' \u00b7 ');
  const btn = $('weather');
  btn.classList.toggle('off', weatherMode === 'off');
  btn.title = weatherMode === 'off' ? 'Weather: off' : `Weather: ${key ? WEATHER[key].name : 'clear'}${weatherMode === 'auto' ? ' (for this biome and day)' : ''}`;
}
// the button walks through: this day's weather, the biome's other weathers, off
function cycleWeather() {
  const r = index.regions.find((x) => x.slug === current);
  const opts = (BIOME_WEATHER[placeBiome(r)] || BIOME_WEATHER.Meadows).map((o) => o[0]);
  const auto = autoWeather(r);
  const seq = ['auto', ...opts.filter((k) => k !== auto), 'off'];
  weatherMode = seq[(seq.indexOf(weatherMode) + 1) % seq.length] || 'auto';
  const u = new URL(location.href);
  if (weatherMode === 'auto') u.searchParams.delete('weather'); else u.searchParams.set('weather', weatherMode);
  history.replaceState(null, '', u);
  refreshWeather();
}

// ---------------------------------------------------------------- bosses, game day, players
let players = null;
const viewDay = () => dayIdx ?? (index.dates?.length ? index.dates.length - 1 : 0);
const beaten = (b) => b.defeated != null && b.defeated <= viewDay();
// a boss shows once its altar has been found (or it has been beaten); undiscovered ones stay a surprise
const known = (b) => beaten(b) || (index.locations || []).some((L) =>
  L.kind === 'boss' && index.bosses[L.boss] === b && L.found <= viewDay());
function gameDay() {
  if (dayIdx == null || !index.days) return index.day;
  return index.days[dayIdx] ?? index.day;
}
function updateWorldState() {
  if (!index?.bosses) return;
  const d = viewDay();
  document.querySelectorAll('.lt, #trails line').forEach((el) => el.classList.toggle('future', +(el.dataset.found || 0) > d));
  document.querySelectorAll('.poi').forEach((el) => {
    el.classList.toggle('future', +(el.dataset.found || 0) > d);
    if (el.dataset.boss != null) {
      const b = index.bosses[+el.dataset.boss];
      el.classList.toggle('alive', !beaten(b));
      el.classList.toggle('beaten', beaten(b));
      el.querySelector('span').textContent = `${b.name} \u00b7 ${beaten(b) ? 'defeated' : 'not yet defeated'}`;
    }
  });
  renderHud();
  if ($('panel').classList.contains('on')) renderPanel();
}
function renderHud() {
  const hud = $('hud');
  hud.style.display = '';
  const n = index.bosses.filter(beaten).length;
  const shown = index.bosses.filter(known);
  const online = players?.online || [];
  const latest = dayIdx == null || dayIdx === index.dates.length - 1;
  hud.innerHTML = `<span class="day">Day ${gameDay()}</span>
    <span class="trophies" title="${n} boss${n === 1 ? '' : 'es'} defeated">${shown.map((b) =>
      `<img src="${b.icon}" class="${beaten(b) ? '' : 'alive'}" title="${b.name}${beaten(b) ? ' \u2713' : ''}" alt="">`).join('')}</span>
    ${players && latest ? `<span class="who"><span class="dot ${online.length ? 'on' : ''}"></span>${online.length
      ? `<b>${online.map((o) => esc(o.name)).join(', ')}</b> online` : 'nobody online'}</span>` : ''}`;
}
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function ago(iso) {
  const m = (Date.now() - new Date(iso)) / 60000;
  if (m < 60) return `${Math.max(1, Math.round(m))} min ago`;
  if (m < 60 * 36) return `${Math.round(m / 60)} h ago`;
  return `${Math.round(m / 1440)} days ago`;
}
function renderPanel() {
  const P = $('panel');
  const date = (i) => fmtDate(index.dates[i]);
  let h = `<h3>Bosses \u00b7 ${index.bosses.filter(beaten).length} defeated</h3><div class="bosses">${index.bosses.filter(known).map((b) =>
    `<div class="boss ${beaten(b) ? '' : 'alive'}"><img src="${b.icon}" alt=""><b>${b.name}</b>${beaten(b)
      ? `by ${date(b.defeated)}` : 'altar found'}</div>`).join('')}</div>`;
  if (players) {
    h += `<h3>Vikings</h3><table><tr><th>Name</th><th class="n">Hours</th><th class="n">Deaths</th><th class="n">Last seen</th></tr>${players.players.map((p) =>
      `<tr><td><span class="dot ${p.online ? 'on' : ''}"></span>${esc(p.name)}</td><td class="n">${p.hours}</td><td class="n">${p.deaths}</td>
       <td class="n">${p.online ? 'online now' : ago(p.last)}</td></tr>`).join('')}</table>`;
    // hours played per day, last 30 days
    const days = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(Date.now() - i * 86400000);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
      const by = players.days[key] || {};
      days.push({ key, mins: Object.values(by).reduce((s, v) => s + v[0], 0), by });
    }
    const max = Math.max(60, ...days.map((d) => d.mins));
    h += `<h3>Hours played, last 30 days</h3><div class="bars">${days.map((d) =>
      `<div style="height:${(d.mins / max) * 100}%" title="${fmtDate(d.key)}: ${(d.mins / 60).toFixed(1)} h${Object.keys(d.by).length ? '\n' +
        Object.entries(d.by).map(([n, v]) => `${n} ${(v[0] / 60).toFixed(1)} h${v[1] ? `, ${v[1]} death${v[1] > 1 ? 's' : ''}` : ''}`).join('\n') : ''}"></div>`).join('')}</div>
      <div class="axis"><span>${fmtDate(days[0].key)}</span><span>today</span></div>
      <div class="note">From the server log since ${fmtDate(players.players.reduce((a, p) => (p.first < a ? p.first : a), '9').slice(0, 10))}. Crossplay disconnects don't name the player, so hours are approximate.</div>`;
  }
  P.innerHTML = h;
}
async function loadPlayers() {
  try {
    players = await fetch('assets/players.json', { cache: 'no-cache' }).then((r) => (r.ok ? r.json() : null));
  } catch { players = null; }
  if (index) renderHud();
  if ($('panel').classList.contains('on')) renderPanel();
}

let playTimer = null;
function setDay(d) {
  dayIdx = d >= index.dates.length - 1 ? null : d;
  applyDay();
}
function togglePlay(force) {
  const playing = force ?? !playTimer;
  clearInterval(playTimer);
  playTimer = null;
  $('play').textContent = playing ? '\u275A\u275A' : '\u25B6';
  if (!playing) return;
  let d = (dayIdx ?? index.dates.length - 1);
  if (d >= index.dates.length - 1) d = -1;   // restart from the first day
  const step = () => {
    d++;
    setDay(d);
    if (d >= index.dates.length - 1) togglePlay(false);
  };
  step();
  playTimer = setInterval(step, 1400);
}
function buildTimeline() {
  const n = index.dates.length;
  if (n < 2) return;
  $('timeline').style.display = '';
  $('day').max = n - 1;
  $('day').oninput = (e) => { togglePlay(false); setDay(+e.target.value); };
  $('play').onclick = () => togglePlay();
  updateTimelineUI();
}

// ---------------------------------------------------------------- night
const FIRE_RE = /torch|fire_pit|bonfire|hearth|brazier|candle|lantern|sconce|smelter|kiln|blastfurnace|forge$|piece_forge|bathtub|firepit/i;
let glowTex = null;
function glowTexture() {
  if (glowTex) return glowTex;
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grad.addColorStop(0, 'rgba(255,240,200,1)');
  grad.addColorStop(0.2, 'rgba(255,170,70,0.8)');
  grad.addColorStop(0.55, 'rgba(255,110,30,0.22)');
  grad.addColorStop(1, 'rgba(255,90,20,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  glowTex = new THREE.CanvasTexture(c);
  glowTex.colorSpace = THREE.SRGBColorSpace;
  return glowTex;
}
function buildFires(info, T) {
  const group = new THREE.Group();
  const items = [];
  const flameMat = new THREE.SpriteMaterial({ map: glowTexture(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, fog: false });
  const poolMat = new THREE.MeshBasicMaterial({ map: glowTexture(), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true, opacity: 0.55, fog: false });
  const poolGeo = new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
  for (const o of info.objects) {
    if (o[11] !== 1) continue;
    const name = info.models[o[0]];
    if (!FIRE_RE.test(name)) continue;
    const mi = modelInfo[name];
    const low = /fire_pit|bonfire|hearth|firepit|smelter|kiln|forge|blastfurnace/i.test(name);
    const h = low ? 0.6 : (mi ? mi.max[1] * o[9] * 0.92 : 1.5);
    const big = /bonfire|hearth|fire_pit|firepit/i.test(name) ? 1.6 : 1;
    const flame = new THREE.Sprite(flameMat.clone());
    flame.position.set(o[1], o[2] + h, o[3]);
    flame.scale.setScalar(3.2 * big);
    const pool = new THREE.Mesh(poolGeo, poolMat.clone());
    const gy = T.sample(o[1], o[3]);
    pool.position.set(o[1], Math.max(gy, o[2]) + 0.12, o[3]);
    pool.scale.setScalar(14 * big);
    group.add(flame, pool);
    items.push({ o, flame, pool, phase: Math.random() * 10, on: true, pos: flame.position });
  }
  // a few real lights on the fires nearest the middle of the place, so walls catch the glow
  const lights = [];
  const near = [...items].sort((a, b) => a.pos.distanceTo(region.focus) - b.pos.distanceTo(region.focus)).slice(0, 8);
  for (const it of near) {
    const L = new THREE.PointLight(0xff9a4a, 0, 22, 1.6);
    L.position.copy(it.pos);
    it.light = L;
    lights.push(L);
  }
  return { group, items, lights };
}
// day/night and the weather together; cheap enough to run every frame (lightning)
const tint = new THREE.Color();
function applyLighting() {
  const p = weather.state.p, f = weather.state.flash;
  hemi.color.set(night ? 0x5d6f9e : 0xcfe3ff);
  hemi.groundColor.set(night ? 0x1a1c2a : 0x5a4a32);
  sun.color.set(night ? 0x9fb4ff : 0xfff1d6);
  if (p.tint) {
    tint.set(p.tint[0]);
    hemi.color.lerp(tint, p.tint[1]);
    sun.color.lerp(tint, p.tint[1]);
  }
  hemi.intensity = (night ? 0.55 : 1.1) * p.hemi + f * (night ? 3 : 1.6);
  sun.intensity = (night ? 0.45 : 2.6) * p.sun;
  overcastUniform.value = p.overcast;
  windUniform.value = 1 + Math.hypot(p.wind[0], p.wind[1]) / 3;
  if (p.fog) {
    scene.fog.color.copy(weather.state.fogColor).multiplyScalar(night ? 0.13 : 1);
    if (f) scene.fog.color.lerp(tint.set(0xdde6ff), Math.min(1, f * 0.25));
    scene.background.copy(scene.fog.color);
  } else {
    scene.background.set(huginn.on ? (night ? 0x0d1424 : 0x9db4c8) : night ? 0x0b0e16 : 0x1b1915);
  }
}
function applyNight() {
  nightUniform.value = night ? 1 : 0;
  applyLighting();
  renderer.toneMappingExposure = night ? 1.25 : 1.05;
  $('night').textContent = night ? '\u2600' : '\u263E';
  $('night').title = night ? 'Day' : 'Night';
  if (!region || !region.fires) return;
  region.fires.group.visible = night;
  for (const L of region.fires.lights) {
    if (night && !L.parent) world.add(L);
    if (!night && L.parent) L.parent.remove(L);
  }
}
function animateFires(t) {
  if (!night || !region?.fires) return;
  for (const f of region.fires.items) {
    const k = 0.82 + 0.12 * Math.sin(t * 9 + f.phase) + 0.08 * Math.sin(t * 23 + f.phase * 3);
    f.flame.visible = f.pool.visible = f.on;
    f.flame.material.opacity = k;
    f.pool.material.opacity = 0.5 * k;
    if (f.light) f.light.intensity = f.on ? 55 * k : 0;
  }
}

function updateLabels() {
  const w = window.innerWidth, h = window.innerHeight;
  const v = new THREE.Vector3();
  const placed = [];
  const cam = view();
  const zoomedIn = huginn.on || camera.zoom > 1.8;
  const big = document.body.classList.contains('big');
  const d = regionDay();
  for (const L of labelEls) {
    const near = !huginn.on || L.pos.distanceTo(raven.position) < (L.portal ? 260 : 90);
    v.copy(L.pos).project(cam);
    let on = (L.portal || zoomedIn) && near && !big && (!L.obj || visibleOn(L.obj, d)) && v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
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
  // the enlarged globe can be pinched / wheeled into: zoom about the disc centre, then pan
  const z = big ? gz.zoom : 1, px = big ? gz.x : 0, py = big ? gz.y : 0;
  const layerSize = (2 * R / span) * size * z;
  const L = $('layer');
  L.style.width = L.style.height = `${layerSize}px`;
  L.style.left = `${size / 2 + px - ((cx + R) / (2 * R)) * layerSize}px`;
  L.style.top = `${size / 2 + py - ((R - cz) / (2 * R)) * layerSize}px`;
  if (big) requestAnimationFrame(declutterMarkers);
}

// ---- zooming into the enlarged globe (pinch on touch, wheel on desktop, drag to pan)
const gz = { zoom: 1, x: 0, y: 0 };
const GZ_MAX = 8;
function zoomGlobe(zoom, fx, fy) {
  // fx, fy: focal point in px from the disc centre; the map point under it stays put
  const size = $('disc').getBoundingClientRect().width;
  const z = Math.min(GZ_MAX, Math.max(1, zoom));
  gz.x = fx - (fx - gz.x) * (z / gz.zoom);
  gz.y = fy - (fy - gz.y) * (z / gz.zoom);
  gz.zoom = z;
  panGlobe(0, 0, size);
}
function panGlobe(dx, dy, size = $('disc').getBoundingClientRect().width) {
  // keep the unzoomed view's area filling the disc
  const lim = ((gz.zoom - 1) * size) / 2;
  gz.x = Math.min(lim, Math.max(-lim, gz.x + dx));
  gz.y = Math.min(lim, Math.max(-lim, gz.y + dy));
  layoutGlobe();
}
function animateZoom(to, fx, fy) {
  const from = gz.zoom, t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / 220), e = 1 - (1 - k) ** 3;
    zoomGlobe(from * (to / from) ** e, fx, fy);
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
function setupGlobeZoom() {
  const disc = $('disc');
  const pts = new Map();
  let pinch = null, moved = false, startAt = null;
  const centre = () => { const r = disc.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
  const big = () => document.body.classList.contains('big');
  disc.addEventListener('pointerdown', (e) => {
    if (!big()) return;
    pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pts.size === 1) { moved = false; startAt = [e.clientX, e.clientY]; }
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]), zoom: gz.zoom };
    }
  });
  window.addEventListener('pointermove', (e) => {
    const prev = pts.get(e.pointerId);
    if (!prev) return;
    const cur = [e.clientX, e.clientY];
    pts.set(e.pointerId, cur);
    if (!moved && Math.hypot(cur[0] - startAt[0], cur[1] - startAt[1]) > 6) moved = true;
    if (pts.size >= 2 && pinch) {
      moved = true;
      const [a, b] = [...pts.values()];
      const [cx, cy] = centre();
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      // pan by half this finger's motion (the midpoint moves half as far), then zoom about the midpoint
      gz.x += (cur[0] - prev[0]) / 2; gz.y += (cur[1] - prev[1]) / 2;
      zoomGlobe(pinch.zoom * Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.d, mx - cx, my - cy);
    } else if (moved && gz.zoom > 1) {
      panGlobe(cur[0] - prev[0], cur[1] - prev[1]);
    }
  });
  const up = (e) => {
    if (!pts.delete(e.pointerId)) return;
    if (pts.size < 2) pinch = null;
    if (pts.size === 1) startAt = [...pts.values()][0];
  };
  window.addEventListener('pointerup', up);
  window.addEventListener('pointercancel', up);
  // a drag or pinch is not a tap: don't let it close the globe or pick a place
  let tapTimer = null;
  disc.addEventListener('click', (e) => {
    if (moved) { e.stopPropagation(); e.preventDefault(); moved = false; return; }
    if (!big() || e.target.closest('.mk, .poi')) return;
    // on the open map, one tap closes it and two taps zoom in (or back out once fully zoomed)
    e.stopPropagation();
    if (tapTimer) {
      clearTimeout(tapTimer); tapTimer = null;
      const [cx, cy] = centre();
      animateZoom(gz.zoom >= GZ_MAX - 0.01 ? 1 : gz.zoom * 2.5, e.clientX - cx, e.clientY - cy);
    } else {
      tapTimer = setTimeout(() => { tapTimer = null; toggleGlobe(false); }, 260);
    }
  }, true);
  disc.addEventListener('wheel', (e) => {
    if (!big()) return;
    e.preventDefault();
    const [cx, cy] = centre();
    zoomGlobe(gz.zoom * Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX - cx, e.clientY - cy);
  }, { passive: false });
}

function declutterMarkers() {
  // in the big globe every label is shown; hide ones that would overlap (hover or a tap still reveals them).
  // Tapped labels win, then the current place, other places, and points of interest; zooming in makes room for more.
  const rank = (m) => (m.classList.contains('pin') ? 0 : m.dataset.slug === current ? 1 : m.classList.contains('mk') ? 2 : 3);
  const mks = [...document.querySelectorAll('.mk, .poi:not(.future)')].sort((a, b) => rank(a) - rank(b));
  mks.forEach((m) => m.classList.remove('hide'));                        // all writes, then all reads: one layout
  const rects = mks.map((m) => m.querySelector('span').getBoundingClientRect());
  const disc = $('disc').getBoundingClientRect();
  const placed = [];
  mks.forEach((m, i) => {
    const r = rects[i];
    const off = r.right < disc.left || r.left > disc.right || r.bottom < disc.top || r.top > disc.bottom;
    if (!off && placed.some((p) => r.left < p.right + 4 && r.right > p.left - 4 && r.top < p.bottom + 2 && r.bottom > p.top - 2)) m.classList.add('hide');
    else if (!off) placed.push(r);
  });
}

// ---------------------------------------------------------------- Huginn flight
const _v = new THREE.Vector3(), _f = new THREE.Vector3(), _r = new THREE.Vector3();
const UP = new THREE.Vector3(0, 1, 0);
// lowest the raven may fly at (x, z): over the ground, the water, and the edge skirt
function floorAt(x, z) {
  const T = region.T;
  const inside = Math.abs(x - T.cx) < T.W / 2 && Math.abs(z - T.cz) < T.D / 2;
  return Math.max(inside ? T.sample(x, z) : -1e9, region.info.water) + 1.6;
}
function clampRaven() {
  if (!region) return;
  const p = raven.position, T = region.T, m = 40;
  p.x = THREE.MathUtils.clamp(p.x, T.cx - T.W / 2 - m, T.cx + T.W / 2 + m);
  p.z = THREE.MathUtils.clamp(p.z, T.cz - T.D / 2 - m, T.cz + T.D / 2 + m);
  p.y = THREE.MathUtils.clamp(p.y, floorAt(p.x, p.z), region.center.y + region.extent * 1.2);
}
function aimRaven() {
  if (huginn.gyro?.q) return;   // the phone aims; see gyroAim
  huginn.pitch = THREE.MathUtils.clamp(huginn.pitch, -1.5, 1.5);
  raven.rotation.set(huginn.pitch, huginn.yaw, 0);
  raven.updateMatrixWorld();
}
// take off from where the isometric view is looking, seeing about as much of the place
function perchRaven() {
  const c = controls.target;
  _f.subVectors(c, camera.position).normalize();
  huginn.yaw = Math.atan2(-_f.x, -_f.z);
  huginn.pitch = -0.45;
  const hh = orthoSize / camera.zoom;
  const d = THREE.MathUtils.clamp(hh / Math.tan(THREE.MathUtils.degToRad(raven.fov / 2)), 12, 400);
  aimRaven();
  raven.getWorldDirection(_v);
  raven.position.copy(c).addScaledVector(_v, -d);
  huginn.vel.set(0, 0, 0);
  clampRaven();
  raven.updateMatrixWorld();
}
// land: the isometric view centres on the ground the raven was looking at
function landRaven() {
  raven.getWorldDirection(_v);
  let t = 60;
  if (_v.y < -0.05) t = Math.min(400, Math.max(5, (raven.position.y - region.center.y) / -_v.y));
  const off = _r.subVectors(camera.position, controls.target);
  controls.target.copy(raven.position).addScaledVector(_v, t);
  controls.target.y = Math.max(floorAt(controls.target.x, controls.target.z) - 1.6, region.center.y);
  camera.position.copy(controls.target).add(off);
  controls.update();
}
function ravenAhead() {
  raven.getWorldDirection(_v);
  return _f.copy(raven.position).addScaledVector(_v, 15).add(_r.set(0, -25, 0));
}
const FLY_KEYS = { KeyW: 1, KeyA: 1, KeyS: 1, KeyD: 1, KeyQ: 1, KeyE: 1, Space: 1, ShiftLeft: 1, ShiftRight: 1, ControlLeft: 1,
  ArrowUp: 1, ArrowDown: 1, ArrowLeft: 1, ArrowRight: 1 };
function flyRaven(dt) {
  if (!region) return;
  const k = huginn.keys, has = (...c) => c.some((x) => k.has(x));
  gyroAim();
  const st = huginn.stick;
  const fwd = THREE.MathUtils.clamp((has('KeyW', 'ArrowUp') ? 1 : 0) - (has('KeyS', 'ArrowDown') ? 1 : 0) - st.y, -1, 1);
  const side = THREE.MathUtils.clamp((has('KeyD', 'ArrowRight') ? 1 : 0) - (has('KeyA', 'ArrowLeft') ? 1 : 0) + st.x, -1, 1);
  const up = (has('KeyE', 'Space') ? 1 : 0) - (has('KeyQ', 'ControlLeft') ? 1 : 0);
  // faster the higher you are, so crossing a big place doesn't take forever
  const height = raven.position.y - floorAt(raven.position.x, raven.position.z);
  const speed = (12 + height * 0.6) * (has('ShiftLeft', 'ShiftRight') ? 3.5 : 1);
  raven.getWorldDirection(_f);
  _r.crossVectors(_f, UP).normalize();
  _v.set(0, 0, 0).addScaledVector(_f, fwd).addScaledVector(_r, side).addScaledVector(UP, up);
  if (_v.lengthSq() > 1) _v.normalize();
  _v.multiplyScalar(speed);
  huginn.vel.lerp(_v, 1 - Math.exp(-dt * 8));     // glide in and out of moves
  if (huginn.vel.lengthSq() < 1e-4) return;
  raven.position.addScaledVector(huginn.vel, dt);
  clampRaven();
  raven.updateMatrixWorld();
}
// ---- phones: a thumbstick to fly, hold buttons to climb and dive, and the gyro to look around
function setupTouchFlight() {
  const stick = $('stick'), knob = stick.querySelector('i');
  let id = null;
  const move = (e) => {
    const r = stick.getBoundingClientRect(), R = r.width / 2;
    const x = (e.clientX - r.left - R) / R, y = (e.clientY - r.top - R) / R;
    const l = Math.max(Math.hypot(x, y), 1e-6), m = Math.min(l, 1);
    knob.style.transform = `translate(${(x / l) * m * R * 0.6}px, ${(y / l) * m * R * 0.6}px)`;
    // a small dead zone, then a curve for fine control near the middle
    const out = m < 0.12 ? 0 : ((m - 0.12) / 0.88) ** 1.5;
    huginn.stick.x = (x / l) * out; huginn.stick.y = (y / l) * out;
  };
  stick.addEventListener('pointerdown', (e) => { if (id != null) return; id = e.pointerId; stick.setPointerCapture(id); move(e); lastInput = performance.now(); });
  stick.addEventListener('pointermove', (e) => { if (e.pointerId === id) move(e); });
  const end = (e) => {
    if (e.pointerId !== id) return;
    id = null; huginn.stick.x = huginn.stick.y = 0; knob.style.transform = '';
  };
  stick.addEventListener('pointerup', end);
  stick.addEventListener('pointercancel', end);
  for (const [btn, code] of [['climb', 'KeyE'], ['dive', 'KeyQ']]) {
    const b = $(btn);
    b.addEventListener('pointerdown', (e) => { b.setPointerCapture(e.pointerId); huginn.keys.add(code); b.classList.add('on'); });
    const up = () => { huginn.keys.delete(code); b.classList.remove('on'); };
    b.addEventListener('pointerup', up);
    b.addEventListener('pointercancel', up);
    b.addEventListener('contextmenu', (e) => e.preventDefault());
  }
  if (!('DeviceOrientationEvent' in window) || !MOBILE) { $('gyro').style.display = 'none'; return; }
  $('gyro').onclick = async () => {
    if (huginn.gyro) { setGyro(false); return; }
    // iOS asks once, and only from a tap
    if (typeof DeviceOrientationEvent.requestPermission === 'function') {
      try { if (await DeviceOrientationEvent.requestPermission() !== 'granted') return; } catch { return; }
    }
    setGyro(true);
  };
}
const _e = new THREE.Euler(), _q = new THREE.Quaternion(), _qy = new THREE.Quaternion();
const Q_FLAT = new THREE.Quaternion(-Math.SQRT1_2, 0, 0, Math.SQRT1_2);   // looking out the back of the phone, not down at it
function onOrient(e) {
  const g = huginn.gyro;
  if (!g || e.alpha == null) return;
  const d = THREE.MathUtils.DEG2RAD;
  const screenAngle = (screen.orientation?.angle ?? window.orientation ?? 0) * d;
  _e.set(e.beta * d, e.alpha * d, -e.gamma * d, 'YXZ');
  const q = (g.q ||= new THREE.Quaternion());
  q.setFromEuler(_e).multiply(Q_FLAT).multiply(_qy.setFromAxisAngle(_r.set(0, 0, 1), -screenAngle));
  // first reading: keep facing the way the raven already was
  if (g.off == null) { _e.setFromQuaternion(q, 'YXZ'); g.off = huginn.yaw - _e.y; }
}
function gyroAim() {
  const g = huginn.gyro;
  if (!g?.q || g.off == null) return;
  raven.quaternion.copy(_qy.setFromAxisAngle(UP, g.off)).multiply(g.q);
  _e.setFromQuaternion(raven.quaternion, 'YXZ');
  huginn.yaw = _e.y; huginn.pitch = _e.x;
  raven.updateMatrixWorld();
}
function setGyro(on) {
  if (!on === !huginn.gyro) return;
  huginn.gyro = on ? { q: null, off: null } : null;
  if (on) window.addEventListener('deviceorientation', onOrient);
  else { window.removeEventListener('deviceorientation', onOrient); aimRaven(); }
  $('gyro').classList.toggle('on', on);
}
function toggleHuginn(force) {
  const on = force ?? !huginn.on;
  if (on === huginn.on || !region) return;
  huginn.on = on;
  if (on) perchRaven(); else landRaven();
  controls.enabled = !on;
  huginn.keys.clear();
  huginn.stick.x = huginn.stick.y = 0;
  if (!on) setGyro(false);
  document.body.classList.toggle('huginn', on);
  $('huginn').title = on ? 'Land (Esc)' : 'Huginn: fly as a raven (H)';
  const u = new URL(location.href);
  if (on) u.searchParams.set('huginn', '1'); else u.searchParams.delete('huginn');
  history.replaceState(null, '', u);
  applyLighting();
  redrawShadows();
}
function setupHuginn() {
  $('huginn').onclick = (e) => { e.currentTarget.blur(); toggleHuginn(); };
  const fov = $('fov');
  fov.value = raven.fov;
  $('fovval').textContent = `${Math.round(raven.fov)}°`;
  fov.oninput = () => {
    raven.fov = +fov.value;
    raven.updateProjectionMatrix();
    $('fovval').textContent = `${fov.value}°`;
    try { localStorage.setItem('huginnFov', fov.value); } catch {}
  };
  const typing = (e) => e.target.closest?.('input[type=text], textarea');
  window.addEventListener('keydown', (e) => {
    if (typing(e) || e.metaKey || e.altKey || document.body.classList.contains('big')) return;
    if (e.code === 'KeyH' && !e.ctrlKey) { toggleHuginn(); return; }
    if (!huginn.on) return;
    if (e.code === 'Escape') { toggleHuginn(false); return; }
    if (FLY_KEYS[e.code]) {
      huginn.keys.add(e.code);
      e.preventDefault();
      if (document.activeElement !== document.body) document.activeElement?.blur?.();   // Space mustn't press a button
    }
  });
  window.addEventListener('keyup', (e) => huginn.keys.delete(e.code));
  window.addEventListener('blur', () => huginn.keys.clear());
  // drag to look around; the wheel glides forward and back
  const el = renderer.domElement;
  el.addEventListener('pointerdown', (e) => {
    if (!huginn.on || huginn.drag) return;
    huginn.drag = [e.clientX, e.clientY, e.pointerId];
    el.setPointerCapture(e.pointerId);
  });
  el.addEventListener('pointermove', (e) => {
    if (!huginn.on || !huginn.drag || e.pointerId !== huginn.drag[2]) return;
    const s = THREE.MathUtils.degToRad(raven.fov) / innerHeight;   // drag one screen height = one field of view
    if (huginn.gyro) huginn.gyro.off += (e.clientX - huginn.drag[0]) * s;
    huginn.yaw += (e.clientX - huginn.drag[0]) * s;
    huginn.pitch += (e.clientY - huginn.drag[1]) * s;
    huginn.drag[0] = e.clientX; huginn.drag[1] = e.clientY;
    aimRaven();
  });
  const stop = (e) => { if (huginn.drag?.[2] === e.pointerId) huginn.drag = null; };
  el.addEventListener('pointerup', stop);
  el.addEventListener('pointercancel', stop);
  setupTouchFlight();
  el.addEventListener('wheel', (e) => {
    if (!huginn.on || !region) return;
    e.preventDefault();
    raven.getWorldDirection(_v);
    raven.position.addScaledVector(_v, -Math.sign(e.deltaY) * Math.min(30, Math.abs(e.deltaY) * 0.05));
    clampRaven();
    raven.updateMatrixWorld();
  }, { passive: false });
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
  const r = huginn.on ? 40 : 34 * Math.min(2.5, Math.max(0.6, camera.zoom));   // px
  for (const L of labelEls) {
    if (!L.target || (L.obj && !visibleOn(L.obj, regionDay()))) continue;
    v.copy(L.base).project(view());
    if (v.z > 1) continue;
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
  $('placename').innerHTML = `${r.title}<small></small>`;
  const u = new URL(location.href);
  u.searchParams.set('place', slug);
  history.replaceState(null, '', u);
  loadRegion(slug, arrive);
}

let hiMap = false;
function loadHiMap() {
  // a 4096 px map for zooming in; the small globe keeps the light 1024 px one
  hiMap = true;
  const img = $('layer').querySelector('img');
  const pre = new Image();
  pre.onload = () => {
    img.src = pre.src;
    if (fogCtx) { fogCtx.canvas.width = fogCtx.canvas.height = 2048; drawFog(); }
  };
  pre.src = fogCtx ? 'assets/worldmap_hi_color.webp' : 'assets/worldmap_hi.webp';
}
function toggleGlobe(force) {
  document.body.classList.toggle('big', force);
  if (!hiMap && document.body.classList.contains('big')) loadHiMap();
  document.querySelectorAll('.poi.pin').forEach((p) => p.classList.remove('pin'));
  Object.assign(gz, { zoom: 1, x: 0, y: 0 });
  // layout once now (start of the CSS transition) and again when it settles
  requestAnimationFrame(layoutGlobe);
  setTimeout(layoutGlobe, 320);
}

function placePoi(el, p) {
  el.style.left = `${((p.x + index.radius) / (2 * index.radius)) * 100}%`;
  el.style.top = `${((index.radius - p.z) / (2 * index.radius)) * 100}%`;
}
function buildGlobe() {
  const mk = $('markers');
  if (index.dates && index.dates.length > 1) {
    // draw the fog of war ourselves so it can follow the timeline
    const img = $('layer').querySelector('img');
    img.src = 'assets/worldmap_color.png';
    const cv = document.createElement('canvas');
    cv.width = cv.height = 1024;
    cv.className = 'fog';
    img.after(cv);
    fogCtx = cv.getContext('2d');
    fogImg = new Image();
    fogImg.onload = drawFog;
    fogImg.src = 'assets/worldmap_fog.png';
    fetch('assets/zones.json').then((r) => r.json()).then((z) => { zoneList = z; drawFog(); });
  }
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
  for (const L of index.locations || []) {
    const el = document.createElement('div');
    const boss = L.kind === 'boss' ? index.bosses[L.boss] : null;
    el.className = 'poi ' + L.kind;
    el.dataset.found = L.found;
    if (boss) el.dataset.boss = L.boss;
    el.innerHTML = boss ? `<i><img src="${boss.icon}" alt=""></i><span></span>` : `<i>\u2696</i><span>${L.name}</span>`;
    placePoi(el, L);
    mk.appendChild(el);
  }
  // torches and campfires out in the wild; torches close together are joined into lit trails
  const lights = index.lights || [];
  if (lights.length) {
    const R = index.radius, NS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(NS, 'svg');
    svg.id = 'trails';
    svg.setAttribute('viewBox', `${-R} ${-R} ${2 * R} ${2 * R}`);
    for (const [a, b] of index.trails || []) {
      const line = document.createElementNS(NS, 'line');
      const A = lights[a], B = lights[b];
      line.setAttribute('x1', A.x); line.setAttribute('y1', -A.z);
      line.setAttribute('x2', B.x); line.setAttribute('y2', -B.z);
      line.setAttribute('class', A.kind === 'wisp' && B.kind === 'wisp' ? 'wisp' : '');
      line.dataset.found = Math.max(A.found, B.found);
      svg.appendChild(line);
    }
    mk.before(svg);
    const TITLE = { wisp: 'Wisp torch', torch: 'Torch', fire: 'Campfire' };
    for (const L of lights) {
      const el = document.createElement('div');
      el.className = `lt ${L.kind}`;
      el.title = TITLE[L.kind];
      el.dataset.found = L.found;
      placePoi(el, L);
      mk.appendChild(el);
    }
  }
  for (const v of index.vehicles || []) {
    const el = document.createElement('div');
    el.className = 'poi vehicle';
    el.innerHTML = `<i>${v.kind === 'Cart' ? '\u{1F6D2}' : '\u26F5'}</i><span>${v.kind}</span>`;
    placePoi(el, v);
    mk.appendChild(el);
  }
  for (const b of index.beds || []) {
    const el = document.createElement('div');
    el.className = 'poi bed';
    el.dataset.found = b.found;
    el.innerHTML = `<i>\u{1F6CF}\uFE0F</i><span>${b.names.length > 1 ? `Beds: ${b.names.map(esc).join(', ')}` : `${esc(b.names[0])}'s bed`}</span>`;
    placePoi(el, b);
    mk.appendChild(el);
  }
  for (const g of index.graves || []) {
    const el = document.createElement('div');
    el.className = 'poi grave';
    el.dataset.found = g.found;
    el.innerHTML = `<i>\u271D</i><span>${esc(g.name)}'s grave${g.day != null ? ` \u00b7 died day ${g.day}` : ''}</span>`;
    placePoi(el, g);
    mk.appendChild(el);
  }
  mk.querySelectorAll('.poi').forEach((el) => {
    el.onclick = (e) => {
      if (!document.body.classList.contains('big')) return;   // the small globe: open the map as usual
      e.stopPropagation();
      el.classList.toggle('pin');
      declutterMarkers();
    };
  });
  new ResizeObserver(() => layoutGlobe()).observe($('disc'));
  $('disc').onclick = () => toggleGlobe();
  setupGlobeZoom();
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
  const dq = new URLSearchParams(location.search).get('day');
  if (dq != null && index.dates?.length > 1) dayIdx = Math.min(+dq, index.dates.length - 1);
  buildTimeline();
  $('night').onclick = () => {
    night = !night;
    const u = new URL(location.href);
    if (night) u.searchParams.set('night', '1'); else u.searchParams.delete('night');
    history.replaceState(null, '', u);
    applyNight();
  };
  $('weather').onclick = cycleWeather;
  setupHuginn();
  $('hud').onclick = (e) => {
    e.stopPropagation();
    const on = $('panel').classList.toggle('on');
    if (on) renderPanel();
  };
  $('panel').onclick = (e) => e.stopPropagation();
  window.addEventListener('pointerdown', (e) => { if (!$('panel').contains(e.target) && !$('hud').contains(e.target)) $('panel').classList.remove('on'); });
  updateWorldState();
  loadPlayers();
  setInterval(loadPlayers, 60000);
  applyNight();
  const q = new URLSearchParams(location.search).get('place');
  setPlace(index.regions.some((r) => r.slug === q) ? q : index.regions[0].slug);
}

window.addEventListener('resize', () => {
  renderer.setSize(window.innerWidth, window.innerHeight);
  setFrustum();
  raven.aspect = aspect(); raven.updateProjectionMatrix();
  if (index) layoutGlobe();
});

// frame budget: 30 fps on phones, and slower still once nobody has touched the view for a while
let lastInput = performance.now(), lastFrame = 0, labelKey = '';
for (const ev of ['pointerdown', 'pointermove', 'wheel', 'keydown', 'touchstart'])
  window.addEventListener(ev, () => { lastInput = performance.now(); }, { passive: true });
function loop(now) {
  requestAnimationFrame(loop);
  const idle = now - lastInput > 30000;
  const flying = huginn.keys.size || huginn.stick.x || huginn.stick.y || huginn.gyro;
  const fps = idle && !flying ? 15 : MOBILE ? 30 : 60;
  if (now - lastFrame < 1000 / fps - 2) return;
  lastFrame = now;
  const dt = Math.min(clock.getDelta(), 0.1);
  timeUniform.value = clock.elapsedTime;
  animateFires(timeUniform.value);
  if (huginn.on) {
    flyRaven(dt);
    weather.update(timeUniform.value, dt, raven, ravenAhead(), orthoSize, window.innerHeight);
  } else {
    weather.update(timeUniform.value, dt, camera, controls.target, orthoSize, window.innerHeight);
    controls.update();
  }
  if (weather.state.p.lightning) applyLighting();
  renderer.render(scene, view());
  // labels only move when the camera, timeline or globe does
  const key = view().matrixWorld.elements.join() + camera.zoom + raven.fov + regionDay() + document.body.className + innerWidth + innerHeight;
  if (key !== labelKey) { labelKey = key; updateLabels(); }
}
setFrustum();
init();
requestAnimationFrame(loop);
window.__viewerReady = () => $('loading').style.display === 'none';
