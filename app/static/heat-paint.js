/* Multi-colour crime heat: each mapped crime type glows in its own colour; where types overlap the colours mix in
   OKLab by their true shares (council colour model, 27 Oct 2026).

   - density: one triweight kernel (same size for every type) per incident, in screen space on a coarse grid
   - colour: OKLab mean of the types' (a, b) vectors weighted by their densities; tone from the total only:
       t = 1 - exp(-T / D0),  alpha = 0.9 (2t - t^2),  L* = 0.78 - 0.18 t (light) / 0.60 + 0.18 t (dark),
     with the foreground's luminance fixed at L*^3 so the mix of types never changes how strong a place looks
   - D0 = Q95 / ln 20 of the density at every incident, for the current zoom (held while panning or hiding types)
   Exposed as window.HeatPaint. */
(() => {
  "use strict";
  const HUES = { murder: 19, assault: 86, robbery: 305, theft: 132, kidnapping: 208, drugs_arms: 169,
                 fraud_extortion: 266, other: 342 };
  const KEYS = Object.keys(HUES), K = KEYS.length, IDX = Object.fromEntries(KEYS.map((k, i) => [k, i]));
  const CHROMA = 0.15;                                   // "Vivid"; gamut-guarded below
  const AB = KEYS.map((k) => [CHROMA * Math.cos(HUES[k] * Math.PI / 180), CHROMA * Math.sin(HUES[k] * Math.PI / 180)]);

  const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  function labToLin(L, a, b) {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
          s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s];
  }
  // Foreground colour for a mixture direction (a, b) at strength t; luminance normalised to L*^3, gamut by shrinking (a, b)
  function foreground(a, b, t, dark, out) {
    const L = dark ? 0.60 + 0.18 * t : 0.78 - 0.18 * t, Y0 = L * L * L;
    let k = 1, V;
    for (let i = 0; i < 6; i++) {
      V = labToLin(L, a * k, b * k);
      const f = Y0 / (0.2126 * V[0] + 0.7152 * V[1] + 0.0722 * V[2]);
      V[0] *= f; V[1] *= f; V[2] *= f;
      if (V[0] >= 0 && V[0] <= 1 && V[1] >= 0 && V[1] <= 1 && V[2] >= 0 && V[2] <= 1) break;
      k *= 0.8;
    }
    for (let j = 0; j < 3; j++) out[j] = Math.round(255 * toSrgb(Math.min(1, Math.max(0, V[j]))));
    return out;
  }

  // Kernel size grows with zoom (half as fast as the map) so hotspots stay readable from country to street.
  const sigmaPx = (z) => Math.max(9, Math.min(55, 20 * 2 ** ((z - 12) * 0.45)));
  const kernelR = (z) => 2.5 * sigmaPx(z);                  // triweight reaches exactly 0 here: no rims
  const tri = (d2, R2) => (d2 < R2 ? (1 - d2 / R2) ** 3 : 0);

  // Web Mercator world pixels at zoom z (for D0, independent of the map engine and of panning)
  function world(lng, lat, z) {
    const s = 256 * 2 ** z, sin = Math.sin(lat * Math.PI / 180);
    return [(lng + 180) / 360 * s, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s];
  }

  const state = { pts: [], off: new Set(), d0: null, d0zoom: null, grid: null, rev: 0 };

  function setData(pts) {
    state.pts = pts.filter((p) => p.lat != null && IDX[p.category] !== undefined);
    state.d0 = null; state.rev++;
  }
  function setHidden(keys) { state.off = new Set(keys); }   // hidden types are masked; D0 keeps every type

  // D0 for zoom z: density at each incident (all mapped types), Q95 / ln 20
  function computeD0(z) {
    const R = kernelR(z), R2 = R * R, bins = new Map(), P = state.pts.map((p) => world(p.lng, p.lat, z));
    P.forEach(([x, y], i) => { const key = `${Math.floor(x / R)},${Math.floor(y / R)}`; (bins.get(key) || bins.set(key, []).get(key)).push(i); });
    const dens = new Float64Array(P.length);
    P.forEach(([x, y], i) => {
      const bx = Math.floor(x / R), by = Math.floor(y / R); let s = 0;
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const list = bins.get(`${bx + dx},${by + dy}`); if (!list) continue;
        for (const j of list) { const ex = P[j][0] - x, ey = P[j][1] - y; s += tri(ex * ex + ey * ey, R2); }
      }
      dens[i] = s;
    });
    const sorted = Array.from(dens).sort((a, b) => a - b);
    const q95 = sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] : 1;
    return Math.max(q95, 1) / Math.log(20);
  }

  /* Paint the view (CSS size w x h) into a small image; the map shows it stretched over the view's bounds.
     `project(lng, lat)` -> [x, y] CSS pixels; `fast` = coarser grid while moving. Returns a canvas or null. */
  function paint(w, h, zoom, project, dark, fast) {
    if (!w || !h || !state.pts.length) { state.grid = null; return null; }
    if (state.d0 == null || Math.abs(state.d0zoom - zoom) > 0.25) { state.d0 = computeD0(zoom); state.d0zoom = zoom; }
    const CELL = fast ? 6 : 3, W = Math.ceil(w / CELL), H = Math.ceil(h / CELL);
    const D = new Float32Array(W * H * K);
    const Rc = kernelR(zoom) / CELL, r = Math.ceil(Rc), R2 = Rc * Rc, kern = [];
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) { const v = tri(dx * dx + dy * dy, R2); if (v > 0) kern.push(dx, dy, v); }
    for (const p of state.pts) {
      const k = IDX[p.category];
      const [x, y] = project(p.lng, p.lat);
      const cx = Math.round(x / CELL), cy = Math.round(y / CELL);
      if (cx < -r || cy < -r || cx > W + r || cy > H + r) continue;
      for (let i = 0; i < kern.length; i += 3) {
        const gx = cx + kern[i], gy = cy + kern[i + 1];
        if (gx < 0 || gy < 0 || gx >= W || gy >= H) continue;
        D[(gy * W + gx) * K + k] += kern[i + 2];
      }
    }
    const on = KEYS.map((k) => !state.off.has(k));
    const img = new ImageData(W, H), px = img.data, rgb = [0, 0, 0], D0 = state.d0;
    for (let c = 0; c < W * H; c++) {
      let T = 0, a = 0, b = 0;
      for (let k = 0; k < K; k++) { if (!on[k]) continue; const d = D[c * K + k]; if (d) { T += d; a += d * AB[k][0]; b += d * AB[k][1]; } }
      if (T < 1e-3) continue;
      const t = 1 - Math.exp(-T / D0);
      foreground(a / T, b / T, t, dark, rgb);
      px[c * 4] = rgb[0]; px[c * 4 + 1] = rgb[1]; px[c * 4 + 2] = rgb[2];
      px[c * 4 + 3] = Math.round(255 * 0.9 * (2 * t - t * t));
    }
    state.grid = { W, H, CELL, D, on };
    const small = document.createElement("canvas"); small.width = W; small.height = H;   // a new image each time
    small.getContext("2d").putImageData(img, 0, 0);
    return small;
  }

  function clear() { state.grid = null; }

  /* Shares of the glow at screen point (x, y), from the same densities that painted it: [[key, share], ...] or null */
  function sample(x, y) {
    const g = state.grid; if (!g) return null;
    const gx = Math.round(x / g.CELL), gy = Math.round(y / g.CELL);
    if (gx < 0 || gy < 0 || gx >= g.W || gy >= g.H) return null;
    const c = gy * g.W + gx; let T = 0;
    for (let k = 0; k < K; k++) if (g.on[k]) T += g.D[c * K + k];
    if (T < 0.02) return null;
    return KEYS.map((k, i) => [k, g.on[i] ? g.D[c * K + i] / T : 0]).filter((r) => r[1] >= 0.01).sort((p, q) => q[1] - p[1]);
  }

  // Solid colour of a type at full strength (legend swatches)
  const swatch = (key, dark) => { const [a, b] = AB[IDX[key]]; return `rgb(${foreground(a, b, 1, dark, [0, 0, 0]).join(",")})`; };

  window.HeatPaint = { KEYS, setData, setHidden, paint, clear, sample, swatch };
})();
