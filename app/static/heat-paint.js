/* Multi-colour crime heat: each mapped crime type glows in its own colour; where types overlap the colours mix in
   OKLab by their true shares (council colour model, 27 Oct 2026; high-contrast colours 29 Oct).

   - density: one triweight kernel (same size for every type) per incident, in screen space on a coarse grid
   - colour: the types' colours blended in OKLab by their density shares, chroma-preserving (council, 29 Oct): L and
     the hue direction are the weighted mean, but the chroma is the weighted mean of the types' chromas, so a mix stays
     as vivid as its parts instead of averaging to grey-brown (thanas below C 0.05: 39 -> 5 on 90 days of data).
     A mixed hue can resemble a third type; the tap card lists the exact counts.
   - strength from the total only: t = 1 - exp(-3 s), s = sqrt(T / Q95) zoomed in and log(1+T)/log(1+Q95)
     at country zoom (see strength()), alpha = 0.95 (2t - t^2); faint glow is also lighter
     (blended toward white), the core is the full colour. On the near-white map, strength reads as opacity.
   - Q95 = 95th percentile of the density at every incident, for the current zoom (held while panning or hiding
     types). The square root compresses the total only (never a type's share).
   Exposed as window.HeatPaint. */
(() => {
  "use strict";
  // The mapped categories and their colours come from the server's category list (configure()).
  let KEYS = [], K = 0, IDX = {}, LAB = [], HEX = [], CH = [];
  const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  function hexToLab(hex) {
    const [r, g, b] = [1, 3, 5].map((i) => toLin(parseInt(hex.slice(i, i + 2), 16) / 255));
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s, 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s];
  }
  function configure(categories) {                       // [{key, color}], mapped categories only, in display order
    KEYS = categories.map((c) => c.key); K = KEYS.length; IDX = Object.fromEntries(KEYS.map((k, i) => [k, i]));
    HEX = categories.map((c) => c.color); LAB = HEX.map(hexToLab); CH = LAB.map(([, a, b]) => Math.hypot(a, b));
    state.pts = []; state.d0 = null;
  }

  const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
  function labToLin(L, a, b) {
    const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3,
          s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
    return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s];
  }
  // sRGB colour of a mix (OKLab L, a, b) at strength t: the full colour at t = 1, lighter toward the faint edge;
  // out-of-gamut mixes keep their lightness and lose a little chroma
  // chroma-preserving blend: (L, A, B) weighted means, Ct = weighted mean chroma; scale (A, B) to Ct
  function vivid(L, A, B, Ct, out3) {
    const m = Math.hypot(A, B);
    if (m > 1e-9) { A *= Ct / m; B *= Ct / m; } else { A = 0; B = 0; }
    out3[0] = L; out3[1] = A; out3[2] = B; return out3;
  }
  function foreground(L, a, b, t, out) {
    const Lt = L + (1 - t) * (0.97 - L) * 0.6;
    let k = 1, V;
    for (let i = 0; i < 6; i++) {
      V = labToLin(Lt, a * k, b * k);
      if (V[0] >= 0 && V[0] <= 1 && V[1] >= 0 && V[1] <= 1 && V[2] >= 0 && V[2] <= 1) break;
      k *= 0.85;
    }
    for (let j = 0; j < 3; j++) out[j] = Math.round(255 * toSrgb(Math.min(1, Math.max(0, V[j]))));
    return out;
  }

  // Kernel size grows with zoom (half as fast as the map) so hotspots stay readable from country to street.
  // the floor (11 px) keeps a lone incident visible when zoomed out without smearing whole regions together
  const sigmaPx = (z) => Math.max(11, Math.min(55, 20 * 2 ** ((z - 12) * 0.45)));
  const kernelR = (z) => 2.5 * sigmaPx(z);                  // triweight reaches exactly 0 here: no rims
  const tri = (d2, R2) => (d2 < R2 ? (1 - d2 / R2) ** 3 : 0);

  /* Strength 0..1 of a total density T (reference D0 = Q95 at this zoom). Zoomed in: sqrt(T/D0) as before. Zoomed out
     to the country: a log scale, because Dhaka has hundreds of times the reports of a typical district and a sqrt
     scale left most districts invisible (council: 3 -> 39 of 57 districts clearly visible); blended between 8 and 10. */
  function strength(T, D0, z) {
    const sq = Math.sqrt(T / D0), lg = Math.log1p(T) / Math.log1p(D0);
    const w = Math.min(1, Math.max(0, (z - 8) / 2));
    return 1 - Math.exp(-((1 - w) * 2.2 * lg + w * 3 * sq));      // country: a lone report pale, Dhaka deep
  }

  // Web Mercator world pixels at zoom z (for D0, independent of the map engine and of panning)
  function world(lng, lat, z) {
    const s = 256 * 2 ** z, sin = Math.sin(lat * Math.PI / 180);
    return [(lng + 180) / 360 * s, (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s];
  }

  const state = { pts: [], off: new Set(), d0: null, d0zoom: null, grid: null, rev: 0 };

  // Incidents at the same point and of the same type are painted once with a weight (most share an area centre).
  function setData(pts) {
    const groups = new Map();
    for (const p of pts) {
      if (p.lat == null || IDX[p.category] === undefined) continue;
      const key = `${p.lng},${p.lat},${p.category}`;
      const g = groups.get(key);
      if (g) g.n += 1; else groups.set(key, { lng: p.lng, lat: p.lat, k: IDX[p.category], n: 1 });
    }
    state.pts = [...groups.values()];
    state.d0 = null; state.rev++;
  }
  function setHidden(keys) { state.off = new Set(keys); }   // hidden types are masked; D0 keeps every type

  // Reference for zoom z: density at each incident (all mapped types, incident-weighted 95th percentile)
  function computeD0(z) {
    const R = kernelR(z), R2 = R * R, bins = new Map(), P = state.pts.map((p) => world(p.lng, p.lat, z));
    P.forEach(([x, y], i) => { const key = `${Math.floor(x / R)},${Math.floor(y / R)}`; (bins.get(key) || bins.set(key, []).get(key)).push(i); });
    const dens = new Float64Array(P.length);
    P.forEach(([x, y], i) => {
      const bx = Math.floor(x / R), by = Math.floor(y / R); let s = 0;
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
        const list = bins.get(`${bx + dx},${by + dy}`); if (!list) continue;
        for (const j of list) { const ex = P[j][0] - x, ey = P[j][1] - y; s += state.pts[j].n * tri(ex * ex + ey * ey, R2); }
      }
      dens[i] = s;
    });
    const order = Array.from(dens.keys()).sort((a, b) => dens[a] - dens[b]);
    const total = state.pts.reduce((s, p) => s + p.n, 0);
    let seen = 0, q95 = 1;
    for (const i of order) { seen += state.pts[i].n; if (seen >= 0.95 * total) { q95 = dens[i]; break; } }
    return Math.max(q95, 1);
  }

  /* Paint the view (CSS size w x h) into a small image; the map shows it stretched over the view's bounds.
     `project(lng, lat)` -> [x, y] CSS pixels; `fast` = coarser grid while moving. Returns a canvas or null. */
  function paint(w, h, zoom, project, fast) {
    if (!w || !h || !state.pts.length) { state.grid = null; return null; }
    if (state.d0 == null || Math.abs(state.d0zoom - zoom) > 0.25) { state.d0 = computeD0(zoom); state.d0zoom = zoom; }
    const CELL = fast ? 6 : 3, W = Math.ceil(w / CELL), H = Math.ceil(h / CELL);
    const D = new Float32Array(W * H * K);
    const Rc = kernelR(zoom) / CELL, r = Math.ceil(Rc), R2 = Rc * Rc, kern = [];
    for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) { const v = tri(dx * dx + dy * dy, R2); if (v > 0) kern.push(dx, dy, v); }
    for (const p of state.pts) {
      const k = p.k, n = p.n;
      const [x, y] = project(p.lng, p.lat);
      const cx = Math.round(x / CELL), cy = Math.round(y / CELL);
      if (cx < -r || cy < -r || cx > W + r || cy > H + r) continue;
      for (let i = 0; i < kern.length; i += 3) {
        const gx = cx + kern[i], gy = cy + kern[i + 1];
        if (gx < 0 || gy < 0 || gx >= W || gy >= H) continue;
        D[(gy * W + gx) * K + k] += n * kern[i + 2];
      }
    }
    const on = KEYS.map((k) => !state.off.has(k));
    const img = new ImageData(W, H), px = img.data, rgb = [0, 0, 0], lab = [0, 0, 0], D0 = state.d0;
    for (let c = 0; c < W * H; c++) {
      let T = 0, L = 0, a = 0, b = 0, ch = 0;
      for (let k = 0; k < K; k++) {
        if (!on[k]) continue;
        const d = D[c * K + k];
        if (d) { T += d; L += d * LAB[k][0]; a += d * LAB[k][1]; b += d * LAB[k][2]; ch += d * CH[k]; }
      }
      if (T < 1e-3) continue;
      const t = strength(T, D0, zoom);
      vivid(L / T, a / T, b / T, ch / T, lab);
      foreground(lab[0], lab[1], lab[2], t, rgb);
      px[c * 4] = rgb[0]; px[c * 4 + 1] = rgb[1]; px[c * 4 + 2] = rgb[2];
      px[c * 4 + 3] = Math.round(255 * 0.95 * (2 * t - t * t));
    }
    state.grid = { W, H, CELL, D, on };
    const small = document.createElement("canvas"); small.width = W; small.height = H;
    small.getContext("2d").putImageData(img, 0, 0);
    // smooth upscale in the browser (the GPU's texture filtering left a grain); a new image each time
    const big = document.createElement("canvas"); big.width = W * CELL; big.height = H * CELL;
    const ctx = big.getContext("2d");
    ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = "high";
    ctx.drawImage(small, 0, 0, big.width, big.height);
    return big;
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

  /* Colour of a district bubble: the OKLab mean of the types' vectors weighted by their counts, at a fixed strong
     tone (same colour model as the heat, so a bubble and the heat of the same mix match). counts: {key: n} */
  function mixColor(counts, t = 1) {
    let T = 0, L = 0, a = 0, b = 0, ch = 0;
    for (const [k, n] of Object.entries(counts)) {
      const i = IDX[k]; if (i === undefined || !n) continue;
      T += n; L += n * LAB[i][0]; a += n * LAB[i][1]; b += n * LAB[i][2]; ch += n * CH[i];
    }
    if (!T) return [120, 120, 120];
    const v = vivid(L / T, a / T, b / T, ch / T, [0, 0, 0]);
    return foreground(v[0], v[1], v[2], t, [0, 0, 0]);
  }

  // Solid colour of a type at full strength (legend swatches)
  const swatch = (key) => HEX[IDX[key]] || "#898781";

  window.HeatPaint = { configure, setData, setHidden, paint, clear, sample, swatch, mixColor, keys: () => KEYS.slice(),
                       radius: (z) => kernelR(z) };          // how far (px) one incident's glow reaches
})();
