// Weather for the viewer: each place gets weather that fits its biome, picked per day so the
// timelapse sees it change. Particles (rain, snow, ash, embers, motes) live in a box that follows
// the camera; mist is a few dozen soft billboards over the place; fog uses three's linear fog.
import * as THREE from 'three';

// what each biome can have, with weights (loosely after the game's own weather tables)
export const BIOME_WEATHER = {
  Meadows: [['clear', 6], ['lightrain', 2], ['mist', 1], ['storm', 0.6]],
  BlackForest: [['forestmist', 4], ['rain', 2], ['clear', 1], ['storm', 1]],
  Swamp: [['swamprain', 1]],
  Mountain: [['snow', 3], ['snowstorm', 2], ['coldclear', 1]],
  DeepNorth: [['snowstorm', 2], ['snow', 1]],
  Plains: [['heath', 4], ['lightrain', 1], ['mist', 1]],
  Ocean: [['rain', 2], ['clear', 2], ['storm', 1]],
  Mistlands: [['mistlands', 3], ['mistrain', 1]],
  AshLands: [['ashrain', 3], ['ashstorm', 1]],
};
export const BIOME_NAMES = {
  Meadows: 'Meadows', BlackForest: 'Black Forest', Swamp: 'Swamp', Mountain: 'Mountains', DeepNorth: 'Deep North',
  Plains: 'Plains', Ocean: 'Ocean', Mistlands: 'Mistlands', AshLands: 'Ashlands',
};

// sun/hemi: light multipliers; tint: [colour, amount] mixed into the light; fog: [colour, strength 0..1];
// overcast: greys the sky reflected in water; wind: m/s (x, z)
const BASE = { sun: 1, hemi: 1, tint: null, fog: null, overcast: 0, wind: [1, 0.4],
  rain: 0, snow: 0, ash: 0, embers: 0, motes: 0, moteColor: [1, 1, 0.92], mist: 0, mistColor: 0xdfe4e6, lightning: false };
export const WEATHER = {
  clear: { name: 'Clear', motes: 0.4 },
  heath: { name: 'Clear', motes: 1, moteColor: [1, 0.88, 0.55], fog: [0xd9c79a, 0.12], tint: [0xffd9a0, 0.15] },
  lightrain: { name: 'Light rain', rain: 0.3, fog: [0x9aa3a8, 0.18], sun: 0.6, hemi: 0.9, overcast: 0.5 },
  rain: { name: 'Rain', rain: 0.75, fog: [0x8a949a, 0.32], sun: 0.35, hemi: 0.8, overcast: 0.8, wind: [3, 1] },
  storm: { name: 'Thunderstorm', rain: 1, fog: [0x6f7a82, 0.42], sun: 0.2, hemi: 0.65, overcast: 1, wind: [7, 2.5], lightning: true },
  mist: { name: 'Misty', mist: 0.6, fog: [0xb8c0c4, 0.32], sun: 0.7, overcast: 0.5 },
  forestmist: { name: 'Forest mist', mist: 0.75, mistColor: 0xc9d2c4, fog: [0x8e9a8c, 0.36], sun: 0.55, hemi: 0.9, overcast: 0.6, motes: 0.25 },
  swamprain: { name: 'Swamp rain', rain: 0.65, mist: 0.7, mistColor: 0xb7c0a0, fog: [0x6f7a5e, 0.5], sun: 0.3, hemi: 0.75,
    tint: [0x9fae7c, 0.35], overcast: 0.9, wind: [2, 1] },
  snow: { name: 'Snow', snow: 0.55, fog: [0xd5dde6, 0.28], sun: 0.6, overcast: 0.6, wind: [1.5, 0.5] },
  snowstorm: { name: 'Snowstorm', snow: 1, fog: [0xdfe6ee, 0.55], sun: 0.35, overcast: 0.9, wind: [9, 3] },
  coldclear: { name: 'Clear and cold', snow: 0.06, tint: [0xcfe0ff, 0.2] },
  mistlands: { name: 'Mist', mist: 1, mistColor: 0xd8d4e6, fog: [0xa7a2b8, 0.55], sun: 0.45, hemi: 0.85,
    tint: [0xb9b0d8, 0.25], overcast: 0.8, motes: 0.3, moteColor: [0.8, 0.85, 1] },
  mistrain: { name: 'Mist and rain', mist: 0.8, mistColor: 0xc8c4d6, rain: 0.55, fog: [0x8f8aa0, 0.55], sun: 0.3, hemi: 0.8,
    tint: [0xa9a0c8, 0.25], overcast: 0.9, wind: [2, 1] },
  ashrain: { name: 'Ash rain', ash: 0.8, embers: 0.6, fog: [0x7a4a38, 0.4], sun: 0.6, tint: [0xff7a4a, 0.4], overcast: 0.6 },
  ashstorm: { name: 'Ash storm', ash: 1, embers: 1, fog: [0x5a3226, 0.55], sun: 0.35, tint: [0xff5a2a, 0.5], overcast: 0.8,
    wind: [6, 2], lightning: true },
};
export const params = (key) => ({ ...BASE, ...(WEATHER[key] || {}) });

export function pickWeather(biome, slug, date) {
  const opts = BIOME_WEATHER[biome] || BIOME_WEATHER.Meadows;
  let h = 2166136261;
  for (const c of `${slug}|${date}`) h = Math.imul(h ^ c.charCodeAt(0), 16777619);
  h ^= h >>> 15; h = Math.imul(h, 2246822507); h ^= h >>> 13;
  const total = opts.reduce((s, o) => s + o[1], 0);
  let r = ((h >>> 0) / 4294967296) * total;
  for (const [k, w] of opts) if ((r -= w) < 0) return k;
  return opts[0][0];
}

// ---------------------------------------------------------------- particles
const VS = `
  uniform float uTime; uniform vec3 uCenter; uniform vec3 uBox; uniform vec3 uVel; uniform float uWobble;
  uniform float uPx; uniform float uSize; uniform float uMinPx; uniform float uStreak;
  attribute vec3 seed; attribute float tail;
  varying float vAlpha; varying float vSeed;
  void main() {
    float sp = 0.7 + 0.6 * fract(seed.x * 13.7 + seed.z * 3.1);
    vec3 lo = uCenter - uBox;
    vec3 p = seed * 2.0 * uBox + uVel * sp * uTime;
    p.x += sin(uTime * 1.1 + seed.y * 37.0) * uWobble;
    p.z += cos(uTime * 0.9 + seed.x * 29.0) * uWobble;
    p.y += sin(uTime * 0.7 + seed.z * 23.0) * uWobble * 0.3;
    p = lo + mod(p - lo, 2.0 * uBox);       // wrap inside the box, anchored to the world
    p -= uVel * sp * tail * uStreak;        // rain: the tail end of the streak
    vSeed = seed.y;
    float h = (p.y - lo.y) / (2.0 * uBox.y);
    vec2 e = abs(p.xz - uCenter.xz) / uBox.xz;
    vAlpha = smoothstep(0.0, 0.12, h) * smoothstep(1.0, 0.85, h) * smoothstep(1.0, 0.85, max(e.x, e.y)) * (1.0 - 0.6 * tail);
    gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
    gl_PointSize = max(uMinPx, uSize * uPx);
  }`;
const FS = (points) => `
  uniform vec3 uColor; uniform float uOpacity; uniform float uFlicker; uniform float uTime; uniform float uNight; uniform float uDim;
  varying float vAlpha; varying float vSeed;
  void main() {
    float a = 1.0;
    ${points ? 'a = smoothstep(0.5, 0.12, length(gl_PointCoord - 0.5));' : ''}
    float fl = mix(1.0, 0.45 + 0.55 * sin(uTime * 7.0 + vSeed * 60.0), uFlicker);
    vec3 c = uColor * mix(1.0, uDim, uNight);
    gl_FragColor = vec4(c, a * vAlpha * uOpacity * fl);
  }`;

function layer({ n, lines = false, color, opacity, size = 0.1, minPx = 2, wobble = 0, flicker = 0, additive = false, dim = 0.35, nightU }) {
  const g = new THREE.BufferGeometry();
  const verts = lines ? n * 2 : n;
  const seed = new Float32Array(verts * 3), tail = new Float32Array(verts), pos = new Float32Array(verts * 3);
  for (let i = 0; i < n; i++) {
    const s = [Math.random(), Math.random(), Math.random()];
    for (let v = 0; v < (lines ? 2 : 1); v++) {
      const k = lines ? i * 2 + v : i;
      seed.set(s, k * 3);
      tail[k] = v;
    }
  }
  g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  g.setAttribute('seed', new THREE.BufferAttribute(seed, 3));
  g.setAttribute('tail', new THREE.BufferAttribute(tail, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, fog: false,
    blending: additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    uniforms: {
      uTime: { value: 0 }, uCenter: { value: new THREE.Vector3() }, uBox: { value: new THREE.Vector3(1, 1, 1) },
      uVel: { value: new THREE.Vector3() }, uWobble: { value: wobble }, uPx: { value: 1 }, uSize: { value: size },
      uMinPx: { value: minPx }, uStreak: { value: 0 }, uColor: { value: new THREE.Color(...color) },
      uOpacity: { value: opacity }, uFlicker: { value: flicker }, uNight: nightU, uDim: { value: additive ? 1 : dim },
    },
    vertexShader: VS, fragmentShader: FS(!lines),
  });
  const obj = lines ? new THREE.LineSegments(g, mat) : new THREE.Points(g, mat);
  obj.frustumCulled = false;
  obj.renderOrder = 3;
  obj.userData.n = n;
  obj.userData.lines = lines;
  obj.userData.minPx = minPx;
  return obj;
}

function cloudTexture() {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  for (let i = 0; i < 26; i++) {
    const a = Math.random() * Math.PI * 2, r = Math.random() * 60;
    const x = 128 + Math.cos(a) * r, y = 128 + Math.sin(a) * r * 0.7, s = 40 + Math.random() * 50;
    const grad = g.createRadialGradient(x, y, 0, x, y, s);
    grad.addColorStop(0, 'rgba(255,255,255,0.22)');
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    g.fillStyle = grad;
    g.fillRect(0, 0, 256, 256);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function createWeather(scene, nightU, scale = 1) {
  const group = new THREE.Group();
  scene.add(group);
  const dpr = () => Math.min(window.devicePixelRatio, 2);
  const L = {
    rain: layer({ n: Math.round(14000 * scale), lines: true, color: [0.72, 0.78, 0.86], opacity: 0.42, dim: 0.3, nightU }),
    snow: layer({ n: Math.round(11000 * scale), color: [1, 1, 1], opacity: 0.95, size: 0.18, minPx: 3.2, wobble: 0.7, dim: 0.3, nightU }),
    ash: layer({ n: Math.round(9000 * scale), color: [0.22, 0.2, 0.2], opacity: 0.9, size: 0.15, minPx: 2.8, wobble: 0.9, dim: 0.6, nightU }),
    embers: layer({ n: Math.round(2200 * scale), color: [1, 0.45, 0.12], opacity: 1, size: 0.12, minPx: 3, wobble: 1.3, flicker: 1, additive: true, nightU }),
    motes: layer({ n: Math.round(900 * scale), color: [1, 1, 1], opacity: 0.75, size: 0.07, minPx: 1.8, wobble: 1.6, flicker: 0.3, dim: 0.25, nightU }),
  };
  Object.values(L).forEach((o) => group.add(o));

  const fog = new THREE.Fog(0xffffff, 1e6, 1e6 + 1);
  scene.fog = fog;
  const mist = { group: new THREE.Group(), sprites: [], tex: null, bounds: null };
  group.add(mist.group);

  const w = { key: null, p: params(null), flash: 0, nextFlash: 4, flashAt: -10, fogColor: new THREE.Color(), fogStrength: 0 };

  function setRegion(T, waterLevel) {
    mist.group.clear();
    mist.sprites = [];
    mist.tex = mist.tex || cloudTexture();
    mist.bounds = { x0: T.cx - T.W / 2, z0: T.cz - T.D / 2, W: T.W, D: T.D };
    const mat = new THREE.SpriteMaterial({ map: mist.tex, transparent: true, depthWrite: false, fog: false });
    for (let i = 0; i < Math.round(70 * scale); i++) {
      const s = new THREE.Sprite(mat.clone());
      const x = mist.bounds.x0 + Math.random() * T.W, z = mist.bounds.z0 + Math.random() * T.D;
      s.position.set(x, 0, z);
      s.userData = { lift: 1.5 + Math.random() * 5, k: 0.5 + Math.random() * 0.5, sample: T.sample, water: waterLevel, phase: Math.random() * 6 };
      s.scale.setScalar(28 + Math.random() * 34);
      s.renderOrder = 3;
      mist.group.add(s);
      mist.sprites.push(s);
    }
    set(w.key);
  }

  function set(key) {
    w.key = key;
    const p = w.p = params(key);
    const wind = new THREE.Vector3(p.wind[0], 0, p.wind[1]);
    L.rain.material.uniforms.uVel.value.set(wind.x, -22, wind.z);
    L.snow.material.uniforms.uVel.value.set(wind.x * 0.8, -1.7, wind.z * 0.8);
    L.ash.material.uniforms.uVel.value.set(wind.x * 0.7, -1.1, wind.z * 0.7);
    L.embers.material.uniforms.uVel.value.set(wind.x * 0.4, 1.4, wind.z * 0.4);
    L.motes.material.uniforms.uVel.value.set(wind.x * 0.3 + 0.3, 0.05, wind.z * 0.3);
    L.motes.material.uniforms.uColor.value.setRGB(...p.moteColor);
    for (const [k, o] of Object.entries(L)) {
      const amt = p[k] || 0;
      o.visible = amt > 0;
      const n = Math.round(o.userData.n * amt);
      o.geometry.setDrawRange(0, o.userData.lines ? n * 2 : n);
    }
    mist.group.visible = p.mist > 0;
    const mc = new THREE.Color(p.mistColor);
    mist.sprites.forEach((s, i) => {
      s.visible = i < mist.sprites.length * p.mist;
      s.material.color.copy(mc);
    });
    w.fogStrength = p.fog ? p.fog[1] : 0;
    if (p.fog) w.fogColor.set(p.fog[0]);
  }

  // per frame: follow the camera, size flakes for the zoom, place fog around the view, lightning
  function update(t, dt, camera, target, orthoSize, viewH) {
    // Huginn's perspective camera: a fixed box of weather around the raven, sized as seen ~25 m away
    const persp = camera.isPerspectiveCamera;
    const hh = persp ? 45 : orthoSize / camera.zoom, hw = persp ? hh * camera.aspect : hh * (camera.right / camera.top);
    const B = ((hw + hh / 0.67) / Math.SQRT2) * 1.15, By = hh * 1.05;
    const ppm = persp ? (viewH * dpr()) / (2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 25) : (viewH * dpr()) / (2 * hh);
    for (const o of Object.values(L)) {
      if (!o.visible) continue;
      const u = o.material.uniforms;
      u.uTime.value = t;
      u.uCenter.value.set(target.x, target.y + By * 0.55, target.z);
      u.uBox.value.set(B, By, B);
      u.uPx.value = ppm;
      u.uMinPx.value = o.userData.minPx * dpr();
    }
    L.rain.material.uniforms.uStreak.value = Math.max(1.1, 16 / ppm) / 22;
    // fog: a = amount at the middle of the view, b = at the far edge
    const D = camera.position.distanceTo(target), R = hh * 1.3, s = w.fogStrength;
    if (s > 0 && persp) {
      fog.near = 4 + 90 * (1 - s);
      fog.far = fog.near + 40 + 260 * (1 - s);
    } else if (s > 0) {
      const a = 0.55 * s, b = Math.min(0.95, a + 0.3 + 0.25 * s), len = R / (b - a);
      fog.near = D - a * len;
      fog.far = fog.near + len;
    } else {
      fog.near = 1e6; fog.far = 1e6 + 1;
    }
    // mist drifts with the wind and wraps around the place
    if (mist.group.visible && mist.bounds) {
      const { x0, z0, W, D: Dd } = mist.bounds;
      const op = 0.32 * (nightU.value ? 0.6 : 1);
      for (const sp of mist.sprites) {
        if (!sp.visible) continue;
        const ud = sp.userData;
        sp.position.x = x0 + ((((sp.position.x - x0) + w.p.wind[0] * 0.35 * ud.k * dt) % W) + W) % W;
        sp.position.z = z0 + ((((sp.position.z - z0) + w.p.wind[1] * 0.35 * ud.k * dt) % Dd) + Dd) % Dd;
        sp.position.y = Math.max(ud.sample(sp.position.x, sp.position.z), ud.water) + ud.lift;
        sp.material.opacity = op * (0.75 + 0.25 * Math.sin(t * 0.2 + ud.phase));
      }
    }
    // lightning: a double flash every 5-17 s
    w.flash = 0;
    if (w.p.lightning) {
      if (t > w.nextFlash) { w.flashAt = t; w.nextFlash = t + 5 + Math.random() * 12; }
      const e = t - w.flashAt;
      if (e < 0.8) w.flash = Math.exp(-e * 16) + (e > 0.2 ? 0.8 * Math.exp(-(e - 0.2) * 10) : 0);
    }
  }

  return { set, setRegion, update, state: w };
}
