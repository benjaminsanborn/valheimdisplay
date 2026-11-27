// Weather for the viewer: each place gets weather that fits its biome, picked per day so the
// timelapse sees it change. It's shown through light, fog and tint (no particles); mist is a few dozen
// soft billboards over the place; fog uses three's linear fog.
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
  mist: 0, mistColor: 0xdfe4e6, lightning: false };
export const WEATHER = {
  clear: { name: 'Clear' },
  heath: { name: 'Clear', fog: [0xd9c79a, 0.12], tint: [0xffd9a0, 0.15] },
  lightrain: { name: 'Light rain', fog: [0x9aa3a8, 0.18], sun: 0.6, hemi: 0.9, overcast: 0.5 },
  rain: { name: 'Rain', fog: [0x8a949a, 0.32], sun: 0.35, hemi: 0.8, overcast: 0.8, wind: [3, 1] },
  storm: { name: 'Thunderstorm', fog: [0x6f7a82, 0.42], sun: 0.2, hemi: 0.65, overcast: 1, wind: [7, 2.5], lightning: true },
  mist: { name: 'Misty', mist: 0.6, fog: [0xb8c0c4, 0.32], sun: 0.7, overcast: 0.5 },
  forestmist: { name: 'Forest mist', mist: 0.75, mistColor: 0xc9d2c4, fog: [0x8e9a8c, 0.36], sun: 0.55, hemi: 0.9, overcast: 0.6 },
  swamprain: { name: 'Swamp rain', mist: 0.7, mistColor: 0xb7c0a0, fog: [0x6f7a5e, 0.5], sun: 0.3, hemi: 0.75,
    tint: [0x9fae7c, 0.35], overcast: 0.9, wind: [2, 1] },
  snow: { name: 'Snow', fog: [0xd5dde6, 0.28], sun: 0.6, overcast: 0.6, wind: [1.5, 0.5] },
  snowstorm: { name: 'Snowstorm', fog: [0xdfe6ee, 0.55], sun: 0.35, overcast: 0.9, wind: [9, 3] },
  coldclear: { name: 'Clear and cold', tint: [0xcfe0ff, 0.2] },
  mistlands: { name: 'Mist', mist: 1, mistColor: 0xd8d4e6, fog: [0xa7a2b8, 0.55], sun: 0.45, hemi: 0.85,
    tint: [0xb9b0d8, 0.25], overcast: 0.8 },
  mistrain: { name: 'Mist and rain', mist: 0.8, mistColor: 0xc8c4d6, fog: [0x8f8aa0, 0.55], sun: 0.3, hemi: 0.8,
    tint: [0xa9a0c8, 0.25], overcast: 0.9, wind: [2, 1] },
  ashrain: { name: 'Ash rain', fog: [0x7a4a38, 0.4], sun: 0.6, tint: [0xff7a4a, 0.4], overcast: 0.6 },
  ashstorm: { name: 'Ash storm', fog: [0x5a3226, 0.55], sun: 0.35, tint: [0xff5a2a, 0.5], overcast: 0.8,
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
    mist.group.visible = p.mist > 0;
    const mc = new THREE.Color(p.mistColor);
    mist.sprites.forEach((s, i) => {
      s.visible = i < mist.sprites.length * p.mist;
      s.material.color.copy(mc);
    });
    w.fogStrength = p.fog ? p.fog[1] : 0;
    if (p.fog) w.fogColor.set(p.fog[0]);
  }

  // per frame: place fog around the view, drift the mist, lightning
  function update(t, dt, camera, target, orthoSize) {
    const persp = camera.isPerspectiveCamera;   // Huginn's raven: fog by distance from the eye
    const hh = persp ? 0 : orthoSize / camera.zoom;
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
