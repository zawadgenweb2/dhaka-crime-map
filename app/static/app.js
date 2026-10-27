/* Dhaka Crime Map - dashboard. Google Maps + deck.gl when a key is configured, otherwise a deck.gl tile basemap. */
(() => {
  "use strict";

  const I18N = {
    bn: {
      title: "বাংলাদেশ অপরাধ মানচিত্র", district: "জেলা", allDistricts: "সব জেলা (৬টি)", allAreas: "সব থানা / উপজেলা", period: "সময়কাল", from: "শুরু", to: "শেষ",
      crimeType: "অপরাধের ধরন", all: "সব", area: "থানা / এলাকা", allDhaka: "সমগ্র ঢাকা", mapView: "মানচিত্র",
      heat: "হিটম্যাপ", both: "দুটোই", points: "ঘটনা", hotspots: "সবচেয়ে বেশি ঘটনা", timeOfDay: "দিনের কোন সময়ে",
      daily: "প্রতিদিনের ঘটনা", reports: "প্রতিবেদন", tabFilters: "ফিল্টার", tabMap: "মানচিত্র", tabFeed: "প্রতিবেদন",
      incidents: "ঘটনা", victims: "হতাহত", topArea: "শীর্ষ এলাকা", topCrime: "প্রধান অপরাধ",
      updated: "হালনাগাদ", topTime: "বেশি ঘটনার সময়", read: "পড়ুন:", moreReports: "আরও {n}টি প্রতিবেদন", noData: "এই ফিল্টারে কোনো ঘটনা নেই",
      exact: "নির্দিষ্ট স্থান", neighbourhood: "এলাকা", thana: "থানা পর্যায়", city: "স্থান অস্পষ্ট",
      unlocated: "{n}টি ঘটনার স্থান অস্পষ্ট, মানচিত্রে নেই", fewer: "কম", more: "বেশি", density: "ঘটনার ঘনত্ব", mixNote: "বৃত্ত: মানচিত্রে থাকা ঘটনার এলাকাভিত্তিক ধরন (জুম করুন)", areaTotal: "{n}টি ঘটনা", crimeMix: "অপরাধের ধরন",
      published: "প্রকাশ", killedInjured: "হতাহত {n}", noKey: "Google Maps কী সেট করা নেই; বিকল্প মানচিত্র দেখানো হচ্ছে।",
      keyFailed: "Google Maps কী কাজ করছে না; বিকল্প মানচিত্র দেখানো হচ্ছে।", failed: "শুরু করা যায়নি", days: "দিন", year: "বছর",
      sourceNote: "সূত্র: সংবাদপত্রের প্রতিবেদন · স্বয়ংক্রিয় বিশ্লেষণ, ভুল থাকতে পারে · প্রতিবেদিত ঘটনা, সব অপরাধ নয়", truncated: "অনেক ঘটনা; প্রথম {n}টি দেখানো হচ্ছে",
      showing: "{n}/{total}", offline: "সার্ভারে পৌঁছানো যাচ্ছে না; পুরোনো তথ্য দেখানো হচ্ছে",
    },
    en: {
      title: "Bangladesh Crime Map", district: "District", allDistricts: "All 6 districts", allAreas: "All thanas / upazilas", period: "Period", from: "From", to: "To",
      crimeType: "Crime type", all: "All", area: "Thana / area", allDhaka: "All of Dhaka", mapView: "Map",
      heat: "Heatmap", both: "Both", points: "Incidents", hotspots: "Most incidents", timeOfDay: "Time of day",
      daily: "Incidents per day", reports: "Reports", tabFilters: "Filters", tabMap: "Map", tabFeed: "Reports",
      incidents: "Incidents", victims: "Killed / injured", topArea: "Top area", topCrime: "Top crime",
      updated: "Updated", topTime: "Most common time", read: "Read on", moreReports: "{n} more reports", noData: "No incidents match these filters",
      exact: "Exact spot", neighbourhood: "Neighbourhood", thana: "Thana level", city: "Location unclear",
      unlocated: "{n} incidents have no clear location and are not on the map", fewer: "fewer", more: "more",
      density: "Incident density", mixNote: "Circles: crime mix of mapped incidents by area (zoom in)", areaTotal: "{n} incidents", crimeMix: "Crime mix", published: "Published", killedInjured: "{n} killed/injured",
      noKey: "No Google Maps key configured; showing the fallback map.",
      keyFailed: "Google Maps key was rejected; showing the fallback map.", failed: "Could not start", days: "days", year: "year",
      sourceNote: "Source: newspaper reports · automatically extracted, may contain errors · reported incidents, not all crime", truncated: "Many incidents; showing the first {n}",
      showing: "{n} of {total}", offline: "Server unreachable; showing the last data",
    },
  };
  const CAT_ORDER = ["murder", "assault", "robbery", "theft", "sexual_violence", "kidnapping", "drugs_arms", "fraud_extortion", "other"];
  // Light pink where there are few incidents, deep red where there are many (the busiest area is the darkest).
  // The lightest step must stay visible: one incident is only a small fraction of the busiest spot.
  const HEAT = [[253, 224, 217, 120], [252, 187, 161, 155], [251, 140, 110, 185], [239, 90, 70, 210], [214, 45, 40, 228],
    [175, 20, 28, 240], [127, 10, 18, 250]];
  const DHAKA = { lat: 23.785, lng: 90.395 };

  const $ = (s) => document.querySelector(s);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v; else if (k === "style") n.style.cssText = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined) n.setAttribute(k, v);
    }
    for (const k of kids.flat()) if (k !== null && k !== undefined) n.append(k.nodeType ? k : String(k));
    return n;
  };
  const fill = (node, ...kids) => node.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
  const store = {
    get(k, d) { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
  };

  const state = {
    lang: store.get("dcm.lang", "bn"), theme: store.get("dcm.theme", ""), days: 7, start: "", end: "",
    cats: new Set(CAT_ORDER), district: "", thana: "", mode: "heat", meta: null, incidents: [], stats: null, selected: null, area: null,
  };
  let engine = null;

  const t = (k, vars = {}) => (I18N[state.lang][k] || k).replace(/\{(\w+)\}/g, (_, v) => num(vars[v]));
  const num = (n) => state.lang === "bn" ? String(n).replace(/\d/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : String(n);
  const locale = () => (state.lang === "bn" ? "bn-BD" : "en-GB");
  const fmtDate = (s) => s ? new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" }).format(new Date(s + "T00:00:00")) : "";
  const fmtTime = (s) => s ? new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Dhaka" }).format(new Date(s)) : "";
  const catLabel = (k) => { const c = state.meta?.categories.find((x) => x.key === k); return c ? c[state.lang] : k; };
  const todLabel = (k) => { const c = state.meta?.time_of_day.find((x) => x.key === k); return c ? c[state.lang] : k; };
  const isDark = () => state.theme === "dark" || (!state.theme && matchMedia("(prefers-color-scheme: dark)").matches);
  const cssColor = (k) => getComputedStyle(document.documentElement).getPropertyValue(`--c-${k}`).trim() || "#898781";
  const rgb = (hex) => { const h = hex.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
  // Public summary: crime type and area (no model headline, no quote).
  const summary = (i) => `${catLabel(i.category)} · ${placeName(i)}`;
  const publisher = (i) => (state.lang === "bn" ? i.publisher_bn : i.publisher_en) || "";
  const placeName = (i) => (state.lang === "bn" ? i.place_bn || i.thana_bn : i.place_en || i.thana_en) || i.location_text || "—";
  const thanaName = (i) => (state.lang === "bn" ? i.thana_bn : i.thana_en) || "";

  /* ---------- map engines ---------- */
  function jitter(d) {
    // Spread incidents that share a gazetteer centroid so each point stays clickable.
    if (d.geocoded) return [d.lng, d.lat];
    const a = d.id * 2.399963, r = 0.00045 * Math.sqrt(((d.id * 7919) % 97) / 97 + 0.05);
    return [d.lng + Math.cos(a) * r, d.lat + Math.sin(a) * r];
  }

  // Blobs grow as you zoom in (half as fast as the map), so hotspots stay visible instead of shrinking to dots.
  const heatRadius = (zoom) => Math.max(60, Math.min(180, 80 * 2 ** ((zoom - 11.5) * 0.4)));
  // Square-root compression per map cell about half a blob wide: a cell with n incidents counts sqrt(n). The busiest
  // place stays the darkest, but quieter ones stay visible next to it, from a street up to the whole country
  // (zoomed out, a cell is a city: Dhaka 188 vs Chattogram 30 -> 13.7 vs 5.5, not 188 vs 30).
  const heatCell = (zoom) => Math.max(0.001, (heatRadius(zoom) / 2) * 360 / (256 * 2 ** zoom));
  function heatWeights(pts, zoom) {
    const c = heatCell(zoom);
    const key = (p) => `${Math.floor(p.lat / c)},${Math.floor(p.lng / c)}`;
    const n = {};
    for (const p of pts) n[key(p)] = (n[key(p)] || 0) + 1;
    return new Map(pts.map((p) => [p.id, 1 / Math.sqrt(n[key(p)])]));
  }

  // One warm ramp = how much crime. With exactly one crime type chosen, the ramp takes that type's colour.
  function heatRange() {
    if (state.cats.size !== 1) return HEAT;
    const c = rgb(cssColor([...state.cats][0]));
    const toWhite = (f, a) => [...c.map((v) => Math.round(255 + (v - 255) * f)), a];
    const shade = (f, a) => [...c.map((v) => Math.round(v * f)), a];
    return [toWhite(0.15, 120), toWhite(0.35, 155), toWhite(0.6, 185), toWhite(0.85, 210), shade(1, 228), shade(0.8, 240), shade(0.6, 250)];
  }
  const rampCss = () => `linear-gradient(90deg, ${heatRange().map(([r, g, b, a]) => `rgba(${r},${g},${b},${(a / 255).toFixed(2)})`).join(", ")})`;

  // Crime mix per area (thana, else place): position = mean of its incidents, counts per type, biggest first.
  function areaGroups(pts) {
    const by = new Map();
    for (const p of pts) {
      const k = p.thana_id || p.place_id;
      if (!k) continue;
      const g = by.get(k) || { id: k, name_bn: p.thana_bn || p.place_bn, name_en: p.thana_en || p.place_en, lat: 0, lng: 0, total: 0, mix: {} };
      g.lat += p.lat; g.lng += p.lng; g.total += 1; g.mix[p.category] = (g.mix[p.category] || 0) + 1;
      by.set(k, g);
    }
    const thanaPt = new Map(state.meta.thanas.map((x) => [x.id, x]));
    return [...by.values()].map((g) => {
      const tp = thanaPt.get(g.id);                 // the area's own point, so the donut doesn't drift with its incidents
      return { ...g, lat: tp && tp.lat != null ? tp.lat : g.lat / g.total, lng: tp && tp.lng != null ? tp.lng : g.lng / g.total,
      slices: Object.entries(g.mix).sort((a, b) => b[1] - a[1] || CAT_ORDER.indexOf(a[0]) - CAT_ORDER.indexOf(b[0])) };
    });
  }
  // A donut drawn as SVG: one stroke segment per crime type, the count in the middle. Icons are cached by mix.
  const ICONS = new Map();
  function donutIcon(g) {
    const id = `${g.slices.map(([k, n]) => k + n).join("-")}-${isDark() ? "d" : "l"}`;
    if (ICONS.has(id)) return ICONS.get(id);
    if (ICONS.size > 500) ICONS.clear();
    const R = 22, C = 2 * Math.PI * R; let off = 0;
    const segs = g.slices.map(([k, n]) => {
      const len = (n / g.total) * C;
      const seg = `<circle cx="32" cy="32" r="${R}" fill="none" stroke="${cssColor(k)}" stroke-width="14" stroke-dasharray="${len.toFixed(2)} ${(C - len).toFixed(2)}" stroke-dashoffset="${(-off).toFixed(2)}" transform="rotate(-90 32 32)"/>`;
      off += len; return seg;
    }).join("");
    const bg = isDark() ? "#1a1a19" : "#ffffff", fg = isDark() ? "#f2f1ed" : "#1a1a19";
    // thin gaps between slices so neighbouring types stay apart even when their colours are close
    let a0 = 0; const gaps = g.slices.length < 2 ? "" : g.slices.map(([, n]) => {
      const ang = (a0 / g.total) * 2 * Math.PI - Math.PI / 2; a0 += n;
      return `<line x1="${(32 + 14 * Math.cos(ang)).toFixed(2)}" y1="${(32 + 14 * Math.sin(ang)).toFixed(2)}" x2="${(32 + 30 * Math.cos(ang)).toFixed(2)}" y2="${(32 + 30 * Math.sin(ang)).toFixed(2)}" stroke="${bg}" stroke-width="2"/>`;
    }).join("");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><circle cx="32" cy="32" r="31" fill="${bg}" stroke="${fg}" stroke-opacity=".35" stroke-width="1"/>${segs}${gaps}`
      + `<text x="32" y="37" text-anchor="middle" font-family="sans-serif" font-size="15" font-weight="700" fill="${fg}">${g.total}</text></svg>`;
    const icon = { id, url: `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`, width: 64, height: 64 };
    ICONS.set(id, icon); return icon;
  }
  const MIX_MIN_ZOOM = 11;

  function layers() {
    const pts = state.incidents.filter((i) => i.lat != null);
    const out = [];
    if (state.mode !== "points") {
      const zoom = engine?.zoom ? engine.zoom() : 12;
      // Colours follow the view: the area with the most incidents is always the darkest.
      const w = heatWeights(pts, zoom);
      out.push(new deck.HeatmapLayer({
        id: "heat", data: pts, getPosition: (d) => [d.lng, d.lat], getWeight: (d) => w.get(d.id),
        radiusPixels: heatRadius(zoom), intensity: 1, threshold: 0.05, colorRange: heatRange(), aggregation: "SUM",
        updateTriggers: { getWeight: [pts.length, heatCell(zoom).toFixed(4)] },
      }));
    }
    const zoomNow = engine?.zoom ? engine.zoom() : 12;
    if (state.mode === "heat" && state.cats.size !== 1 && zoomNow >= MIX_MIN_ZOOM) {
      // Crime mix on top of the heat; small areas only appear once zoomed further in, so donuts don't pile up.
      const groups = areaGroups(pts).filter((g) => g.total >= (zoomNow >= 13 ? 1 : 2));
      const selA = state.area?.id;
      out.push(new deck.IconLayer({
        id: "mix", data: groups, pickable: true, sizeUnits: "pixels", getPosition: (g) => [g.lng, g.lat],
        getIcon: donutIcon, getSize: (g) => Math.min(56, 26 + 6 * Math.sqrt(g.total)) + (g.id === selA ? 6 : 0),
        updateTriggers: { getIcon: isDark(), getSize: selA },
        onHover: hoverArea, onClick: (info) => info.object && selectArea(info.object),
      }));
    }
    if (state.mode !== "heat") {
      const ring = isDark() ? [26, 26, 25] : [252, 252, 251];
      const colors = Object.fromEntries(CAT_ORDER.map((k) => [k, rgb(cssColor(k))]));
      const sel = state.selected?.id;
      out.push(new deck.ScatterplotLayer({
        id: "points", data: pts, pickable: true, stroked: true, radiusUnits: "pixels", lineWidthUnits: "pixels",
        getPosition: jitter, getRadius: (d) => (d.id === sel ? 10 : 6), getLineWidth: (d) => (d.id === sel ? 3 : 2),
        getFillColor: (d) => [...(colors[d.category] || colors.other), 235], getLineColor: ring,
        radiusMinPixels: 4, updateTriggers: { getRadius: sel, getLineWidth: sel, getFillColor: isDark(), getLineColor: isDark() },
        onHover: hover, onClick: (info) => info.object && select(info.object, false),
      }));
    }
    return out;
  }

  function hoverArea(info) {
    const tip = $("#tooltip");
    if (!info.object) { tip.hidden = true; return; }
    const g = info.object;
    fill(tip, el("div", {}, el("b", {}, state.lang === "bn" ? g.name_bn : g.name_en)),
      el("div", { class: "meta" }, t("areaTotal", { n: g.total })),
      ...g.slices.slice(0, 4).map(([k, n]) => el("div", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(k)}` }), `${catLabel(k)} ${num(n)}`)));
    tip.style.left = `${info.x + 12}px`; tip.style.top = `${info.y + 12}px`; tip.hidden = false;
  }

  function selectArea(g) {
    state.selected = null; state.area = g;
    renderSelected(); renderFeed(); engine?.render();
  }

  function hover(info) {
    const tip = $("#tooltip");
    if (!info.object) { tip.hidden = true; return; }
    const d = info.object;
    fill(tip, 
      el("div", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(d.category)}` }), catLabel(d.category)),
      el("div", {}, summary(d)),
      el("div", { class: "meta" }, `${placeName(d)} · ${fmtDate(d.event_date)}`));
    tip.style.left = `${info.x}px`; tip.style.top = `${info.y}px`; tip.hidden = false;
  }

  function loadGoogle(key) {
    return new Promise((resolve, reject) => {
      window.__dcmGoogleReady = resolve;
      window.gm_authFailure = () => { googleFailed(); };
      const s = document.createElement("script");
      const params = new URLSearchParams({ key, v: "weekly", loading: "async", language: state.lang, region: "BD", callback: "__dcmGoogleReady" });
      s.src = `https://maps.googleapis.com/maps/api/js?${params}`;
      s.async = true; s.onerror = () => reject(new Error("Google Maps failed to load"));
      document.head.append(s);
    });
  }

  const MAP_STYLE_LIGHT = [
    { featureType: "poi", stylers: [{ visibility: "off" }] }, { featureType: "transit", elementType: "labels.icon", stylers: [{ visibility: "off" }] },
    { elementType: "geometry", stylers: [{ saturation: -60 }, { lightness: 8 }] },
  ];
  const MAP_STYLE_DARK = [
    { elementType: "geometry", stylers: [{ color: "#1d1d1c" }] }, { elementType: "labels.text.fill", stylers: [{ color: "#9a9890" }] },
    { elementType: "labels.text.stroke", stylers: [{ color: "#1a1a19" }] }, { featureType: "poi", stylers: [{ visibility: "off" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: "#2e2e2c" }] }, { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#3a3a37" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#0f1a24" }] }, { featureType: "transit", stylers: [{ visibility: "off" }] },
  ];

  async function googleEngine(key, mapId) {
    await loadGoogle(key);
    const { Map } = await google.maps.importLibrary("maps");
    const opts = {
      center: startView().center, zoom: startView().zoom, minZoom: 6, maxZoom: 18, mapTypeControl: false,
      streetViewControl: false, fullscreenControl: false, zoomControl: false,
      clickableIcons: false, gestureHandling: "greedy", backgroundColor: isDark() ? "#1a1a19" : "#f2f1ed",
    };
    if (mapId) { opts.mapId = mapId; opts.colorScheme = isDark() ? "DARK" : "LIGHT"; } else { opts.styles = isDark() ? MAP_STYLE_DARK : MAP_STYLE_LIGHT; }
    const map = new Map($("#map"), opts);
    const overlay = new deck.GoogleMapsOverlay({ interleaved: Boolean(mapId), layers: [] });
    overlay.setMap(map);
    map.addListener("click", () => {});
    let lastZoom = map.getZoom();
    map.addListener("zoom_changed", () => { if (Math.abs(map.getZoom() - lastZoom) >= 0.5) { lastZoom = map.getZoom(); engine?.render(); } });
    return {
      name: "google",
      render() { overlay.setProps({ layers: layers() }); },
      zoom() { return map.getZoom() || 12; },
      zoomBy(dz) { map.setZoom(Math.max(6, Math.min(18, (map.getZoom() || 12) + dz))); },
      reset() { fitArea(); },
      flyTo(lat, lng, zoom) { map.panTo({ lat, lng }); if (zoom) map.setZoom(zoom); },
      fitTo(b) {
        if (b.single) { this.flyTo(b.lat, b.lng, 15); return; }
        map.fitBounds({ south: b.s, west: b.w, north: b.n, east: b.e }, FIT_PADDING);
        google.maps.event.addListenerOnce(map, "idle", () => { if (map.getZoom() > 16) map.setZoom(16); });
      },
      theme() { if (!mapId) map.setOptions({ styles: isDark() ? MAP_STYLE_DARK : MAP_STYLE_LIGHT, backgroundColor: isDark() ? "#1a1a19" : "#f2f1ed" }); },
      destroy() { try { overlay.setMap(null); overlay.finalize(); } catch (e) { /* map never initialised */ } fill($("#map")); },
    };
  }

  function tileEngine() {
    const tiles = () => "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
    const base = () => new deck.TileLayer({
      id: `base-${isDark() ? "d" : "l"}`, data: tiles(), minZoom: 0, maxZoom: 19, tileSize: 256,
      renderSubLayers: (props) => {
        const [[w, s], [e, n]] = props.tile.boundingBox;
        return new deck.BitmapLayer(props, {
          data: null, image: props.data, bounds: [w, s, e, n],
          desaturate: isDark() ? 0.9 : 0.55, tintColor: isDark() ? [95, 95, 100] : [255, 255, 255],
        });
      },
    });
    const sv = startView();
    let view = { longitude: sv.center.lng, latitude: sv.center.lat, zoom: sv.zoom, pitch: 0, bearing: 0, minZoom: 6, maxZoom: 18 };
    let heatZoom = Math.round(view.zoom * 2);
    const d = new deck.Deck({
      parent: $("#map"), initialViewState: view, controller: true, layers: [],
      onViewStateChange: ({ viewState }) => {
        view = viewState;
        if (Math.round(view.zoom * 2) !== heatZoom) { heatZoom = Math.round(view.zoom * 2); engine?.render(); }
      },
    });
    const goTo = (v) => d.setProps({ initialViewState: { ...view, ...v, transitionDuration: 300, transitionInterpolator: new deck.FlyToInterpolator() } });
    const attribution = el("div", { class: "muted", style: "position:absolute;right:6px;bottom:4px;z-index:4;font-size:11px;background:var(--surface);padding:0 6px;border-radius:4px" },
      "© OpenStreetMap contributors");
    $("#map").append(attribution);
    let baseLayer = base();
    return {
      name: "tiles",
      render() { d.setProps({ layers: [baseLayer, ...layers()] }); },
      zoom() { return view.zoom; },
      zoomBy(dz) { goTo({ zoom: Math.max(6, Math.min(18, view.zoom + dz)) }); },
      reset() { fitArea(); },
      flyTo(lat, lng, zoom) {
        d.setProps({ initialViewState: { ...view, latitude: lat, longitude: lng, zoom: zoom || view.zoom, transitionDuration: 700, transitionInterpolator: new deck.FlyToInterpolator() } });
      },
      fitTo(b) {
        if (b.single) { this.flyTo(b.lat, b.lng, 15); return; }
        const el = $("#map");
        const vp = new deck.WebMercatorViewport({ width: el.clientWidth || 800, height: el.clientHeight || 600 });
        const { longitude, latitude, zoom } = vp.fitBounds([[b.w, b.s], [b.e, b.n]], { padding: FIT_PADDING, maxZoom: 16 });
        this.flyTo(latitude, longitude, zoom);
      },
      theme() { baseLayer = base(); this.render(); },
      destroy() { d.finalize(); fill($("#map"), ); },
    };
  }

  // Optional start view from the address: #z=15&ll=23.80,90.35 (shareable views; also used for testing)
  function startView() {
    const h = new URLSearchParams(location.hash.slice(1));
    const z = parseFloat(h.get("z")), ll = (h.get("ll") || "").split(",").map(Number);
    return { zoom: z >= 6 && z <= 18 ? z : 11.2,
             center: ll.length === 2 && ll.every((x) => Number.isFinite(x)) ? { lat: ll[0], lng: ll[1] } : DHAKA };
  }

  function note(msg) { const n = $("#map-note"); n.textContent = msg; n.hidden = !msg; if (msg) setTimeout(() => (n.hidden = true), 9000); }

  function googleFailed() {
    if (engine?.name !== "google") return;
    engine.destroy(); engine = tileEngine(); engine.render(); note(t("keyFailed"));
  }

  async function initMap() {
    const key = state.meta.google_maps_api_key;
    if (key) {
      try { engine = await googleEngine(key, state.meta.google_maps_map_id); return; } catch (e) { console.warn(e); note(t("keyFailed")); }
    } else {
      note(t("noKey"));
    }
    engine = tileEngine();
  }

  const FIT_PADDING = { top: 80, right: 60, bottom: 190, left: 60 };

  // Zoom to the incidents currently shown, like a search result on Google Maps.
  function fitToResults(fallback) {
    const pts = state.incidents.filter((i) => i.lat != null);
    if (!engine) return;
    if (!pts.length) { if (fallback) engine.flyTo(fallback.lat, fallback.lng, fallback.zoom); return; }
    const lats = pts.map((i) => i.lat), lngs = pts.map((i) => i.lng);
    const b = { s: Math.min(...lats), n: Math.max(...lats), w: Math.min(...lngs), e: Math.max(...lngs) };
    b.single = (b.n - b.s) < 0.002 && (b.e - b.w) < 0.002;
    if (b.single) { b.lat = lats[0]; b.lng = lngs[0]; }
    engine.fitTo(b);
  }

  /* ---------- data ---------- */
  // Coverage is about days only: the same period, without category/thana filters
  function rangeQuery() {
    const p = new URLSearchParams();
    if (state.start && state.end) { p.set("start", state.start); p.set("end", state.end); } else p.set("days", state.days);
    return p.toString();
  }

  function query() {
    const p = new URLSearchParams();
    if (state.start && state.end) { p.set("start", state.start); p.set("end", state.end); } else p.set("days", state.days);
    if (state.cats.size && state.cats.size < CAT_ORDER.length) p.set("categories", [...state.cats].join(","));
    if (state.district) p.set("district", state.district);
    if (state.thana) p.set("thana", state.thana);
    return p.toString();
  }

  // Map view for the current district selection (or all six districts)
  function areaBounds() {
    const d = state.meta.districts.find((x) => x.id === state.district);
    const b = d ? d.bounds : state.meta.all_bounds;
    return b ? { ...b } : null;
  }
  function fitArea() { const b = areaBounds(); if (b && engine) engine.fitTo(b); }

  const getJSON = async (url) => {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
    return { data: await r.json(), headers: r.headers };
  };

  // Each refresh gets a number; an older response that arrives late never overwrites a newer one.
  let refreshSeq = 0;
  async function refresh(opts = {}) {
    const seq = ++refreshSeq;
    const q = query();
    const qc = new URLSearchParams(q); qc.delete("categories");  // chip counts ignore the category filter itself
    const [inc, stats, all] = await Promise.all([getJSON(`/api/incidents?${q}`), getJSON(`/api/stats?${q}`),
      qc.toString() === q ? null : getJSON(`/api/stats?${qc}`)]);
    if (seq !== refreshSeq) return false;
    state.incidents = inc.data; state.stats = stats.data; state.catCounts = (all || stats).data.by_category;
    state.truncated = inc.headers.get("X-Truncated") === "true";
    state.totalCount = +(inc.headers.get("X-Total-Count") || inc.data.length);
    // keep the open card, but show the freshly fetched version of it
    if (state.selected) state.selected = inc.data.find((i) => i.id === state.selected.id) || null;
    if (state.area) state.area = areaGroups(state.incidents.filter((i) => i.lat != null)).find((g) => g.id === state.area.id) || null;
    renderAll();
    if (state.truncated) note(t("truncated", { n: inc.data.length }));
    if (opts.fit) fitToResults(opts.fallback);
    return true;
  }

  // Public page: labels once (/api/config), then only the small data-version check (/api/version).
  async function loadConfig() {
    state.meta = (await getJSON("/api/config")).data;
  }

  async function loadVersion() {
    state.version = (await getJSON("/api/version")).data;
    state.offline = false;
    renderStatus();
  }

  /* ---------- rendering ---------- */
  function renderAll() {
    renderChips(); renderTiles(); renderRank(); renderTod(); renderTrend(); renderFeed(); renderLegend(); renderSelected();
    engine?.render();
  }

  function renderStatus() {
    const v = state.version;
    $("#status-line").textContent = state.offline ? t("offline") : v ? `${t("updated")}: ${fmtTime(v.updated_at)}` : "";
  }

  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
    document.querySelectorAll("#period button").forEach((b) => {
      const d = +b.dataset.days; b.textContent = d === 365 ? `১ ${t("year")}`.replace("১", num(1)) : `${num(d)} ${t("days")}`;
    });
    $("#lang-btn").textContent = state.lang === "bn" ? "EN" : "বাং";
    fill($("#district"), el("option", { value: "" }, t("allDistricts")),
      ...state.meta.districts.map((d) => el("option", { value: d.id }, state.lang === "bn" ? d.bn : d.en)));
    $("#district").value = state.district;
    renderThanaSelect();
    renderStatus();
  }

  // Thana / upazila drill-down inside the selected district
  function renderThanaSelect() {
    const sel = $("#thana");
    sel.hidden = !state.district;
    if (!state.district) { fill(sel); return; }
    const byName = (a, b) => (state.lang === "bn" ? a.name_bn.localeCompare(b.name_bn, "bn") : a.name_en.localeCompare(b.name_en));
    fill(sel, el("option", { value: "" }, t("allAreas")),
      ...state.meta.thanas.filter((p) => p.district === state.district).sort(byName)
        .map((p) => el("option", { value: p.id }, state.lang === "bn" ? p.name_bn : p.name_en)));
    sel.value = state.thana;
  }

  function renderChips() {
    const box = $("#cats");
    fill(box, ...CAT_ORDER.map((k) => el("button", {
      type: "button", class: `chip${state.cats.has(k) ? "" : " off"}`, "aria-pressed": String(state.cats.has(k)),
      onclick: () => { if (state.cats.size === CAT_ORDER.length) { state.cats = new Set([k]); } else if (state.cats.has(k)) { state.cats.delete(k); if (!state.cats.size) state.cats = new Set(CAT_ORDER); } else state.cats.add(k); refresh({ fit: true }); },
    }, el("span", { class: "dot", style: `background:${cssColor(k)}` }), catLabel(k), el("span", { class: "n" }, num(state.catCounts?.[k] || 0)))));
  }

  function renderTiles() {
    const s = state.stats;
    const topThana = state.district ? s.by_thana[0] : s.by_district[0] && { name_bn: s.by_district[0].bn, name_en: s.by_district[0].en };
    const topCat = Object.entries(s.by_category).sort((a, b) => b[1] - a[1])[0];
    const tile = (v, k, txt) => el("div", { class: "tile" }, el("div", { class: txt ? "v txt" : "v", title: v }, v), el("div", { class: "k" }, k));
    fill($("#tiles"), 
      tile(num(s.total), t("incidents")),
      tile((() => { const top = Object.entries(s.by_time_of_day).filter(([k]) => k !== "unknown").sort((a, b) => b[1] - a[1])[0];
        return top ? todLabel(top[0]) : "—"; })(), t("topTime"), true),
      tile(topThana ? (state.lang === "bn" ? topThana.name_bn : topThana.name_en) : "—", t("topArea"), true),
      tile(topCat ? catLabel(topCat[0]) : "—", t("topCrime"), true));
  }

  function renderRank() {
    if (!state.district) {   // all districts: rank the districts
      const ds = state.stats.by_district;
      const mx = Math.max(1, ...ds.map((r) => r.count));
      fill($("#rank"), ...(ds.length ? ds.map((r, i) => el("li", {}, el("button", {
        type: "button", onclick: () => selectDistrict(r.id),
      }, el("span", { class: "pos" }, num(i + 1)),
        el("span", { class: "name" }, el("b", {}, state.lang === "bn" ? r.bn : r.en),
          el("span", { class: "bar", style: `width:${(r.count / mx) * 100}%` }, el("i", { style: "flex:1;background:var(--accent)" }))),
        el("span", { class: "cnt" }, num(r.count))))) : [el("li", { class: "empty" }, t("noData"))]));
      return;
    }
    const rows = state.stats.by_thana.slice(0, 10);
    const max = Math.max(1, ...rows.map((r) => r.count));
    fill($("#rank"), ...(rows.length ? rows.map((r, i) => el("li", {}, el("button", {
      type: "button", class: state.thana === r.id ? "on" : "",
      onclick: () => { state.thana = state.thana === r.id ? "" : r.id; $("#thana").value = state.thana; refresh({ fit: true, fallback: r.lat ? { lat: r.lat, lng: r.lng, zoom: 13 } : null }); },
    },
      el("span", { class: "pos" }, num(i + 1)),
      el("span", { class: "name" }, el("b", {}, state.lang === "bn" ? r.name_bn : r.name_en),
        el("span", { class: "bar", style: `width:${(r.count / max) * 100}%` },
          ...CAT_ORDER.filter((k) => r.categories[k]).map((k) => el("i", { style: `flex:${r.categories[k]};background:${cssColor(k)}`, title: `${catLabel(k)}: ${r.categories[k]}` })))),
      el("span", { class: "cnt" }, num(r.count))))) : [el("li", { class: "empty" }, t("noData"))]));
  }

  function renderTod() {
    const keys = ["morning", "afternoon", "evening", "night", "unknown"];
    const max = Math.max(1, ...keys.map((k) => state.stats.by_time_of_day[k] || 0));
    fill($("#tod"), ...keys.map((k) => {
      const n = state.stats.by_time_of_day[k] || 0;
      return el("div", { class: "hbar" }, el("span", {}, todLabel(k)),
        el("span", { class: "track" }, el("span", { class: "fill", style: `width:${(n / max) * 100}%;${k === "unknown" ? "background:var(--muted)" : ""}` })),
        el("span", { class: "n" }, num(n)));
    }));
  }

  function renderTrend() {
    const { start, end } = state.stats.range;
    const counts = Object.fromEntries(state.stats.by_day.map((d) => [d.date, d.count]));
    const days = [];
    for (let d = new Date(start + "T00:00:00Z"); d <= new Date(end + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + 1)) days.push(d.toISOString().slice(0, 10));
    const shown = days.slice(-120);
    const status = {};
    const statusLabel = { not_collected: t("notCollected"), partial: t("partialDay"), processing: t("processingDay"), failed: t("failedDay") };
    const max = Math.max(1, ...shown.map((d) => counts[d] || 0));
    const tip = $("#tooltip");
    const box = $("#trend");
    fill(box, ...shown.map((d) => el("div", {
      class: `b${["not_collected", "partial"].includes(status[d]) ? (counts[d] ? " part" : " nc") : ["processing", "failed"].includes(status[d]) ? " proc" : ""}`,
      style: `height:${((counts[d] || 0) / max) * 100}%`,
      onmouseenter: (e) => { tip.textContent = `${fmtDate(d)}: ${num(counts[d] || 0)} ${t("incidents")}${statusLabel[status[d]] ? ` · ${statusLabel[status[d]]}` : ""}`; tip.hidden = false; const r = e.target.getBoundingClientRect(); tip.style.position = "fixed"; tip.style.left = `${r.left}px`; tip.style.top = `${r.top - 44}px`; },
      onmouseleave: () => { tip.hidden = true; tip.style.position = ""; },
    })));
    const axis = box.nextElementSibling?.classList.contains("trend-axis") ? box.nextElementSibling : box.after(el("div", { class: "trend-axis" })) || box.nextElementSibling;
    fill(axis, el("span", {}, fmtDate(shown[0])), el("span", {}, fmtDate(shown[shown.length - 1])));
  }

  function precisionBadge(p) { return el("span", { class: "badge" }, t(p || "city")); }

  function renderFeed() {
    const list = state.incidents.slice(0, 400);
    $("#feed-count").textContent = list.length < (state.totalCount || state.incidents.length)
      ? t("showing", { n: list.length, total: state.totalCount || state.incidents.length }) : num(state.incidents.length);
    fill($("#feed"), ...(list.length ? list.map((i) => el("li", {}, el("button", {
      type: "button", class: `item${state.selected?.id === i.id ? " on" : ""}`, onclick: () => select(i, true),
    },
      el("span", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(i.category)}` }), catLabel(i.category)),
      el("h3", {}, summary(i)),
      el("div", { class: "meta" }, el("span", {}, placeName(i)), el("span", {}, fmtDate(i.event_date)),
        i.time_of_day !== "unknown" ? el("span", {}, todLabel(i.time_of_day)) : null, precisionBadge(i.precision))))) : [el("li", { class: "empty" }, t("noData"))]));
  }

  function renderLegend() {
    const s = state.stats;
    fill($("#legend"), 
      state.mode !== "points" ? el("div", {}, el("div", { class: "muted" }, state.cats.size === 1 ? `${t("density")} · ${catLabel([...state.cats][0])}` : t("density")), el("div", { class: "ramp", style: `background:${rampCss()}` }), el("div", { class: "ends" }, el("span", {}, t("fewer")), el("span", {}, t("more")))) : null,
      state.mode === "heat" && state.cats.size !== 1 ? el("div", { class: "muted" }, t("mixNote")) : null,
      state.mode !== "heat" ? el("div", { class: "cats" }, ...CAT_ORDER.filter((k) => state.cats.has(k)).map((k) => el("span", {}, el("i", { style: `background:${cssColor(k)}` }), catLabel(k)))) : null,
      s.unlocated ? el("div", { class: "muted" }, t("unlocated", { n: s.unlocated })) : null,
      el("div", { class: "muted", style: "font-size:11px" }, t("sourceNote")));
  }

  function select(i, fly) {
    state.selected = i; state.area = null;
    if (fly && i.lat != null) engine?.flyTo(i.lat, i.lng, 15);
    if (fly && matchMedia("(max-width: 760px)").matches) setTab("map");
    renderSelected(); renderFeed(); engine?.render();
  }

  function renderSelected() {
    const card = $("#selected"); const i = state.selected;
    if (!i && state.area) { renderAreaCard(card, state.area); return; }
    if (!i) { card.hidden = true; return; }
    const loc = [i.location_text, thanaName(i) && thanaName(i) !== placeName(i) ? thanaName(i) : null].filter(Boolean).join(" · ");
    fill(card, 
      el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { state.selected = null; renderSelected(); renderFeed(); engine?.render(); } }, "×"),
      el("span", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(i.category)}` }), catLabel(i.category)),
      el("h3", {}, summary(i)),
      el("div", { class: "meta" }, el("span", {}, loc), precisionBadge(i.precision)),
      el("div", { class: "meta" }, el("span", {}, fmtDate(i.event_date)), i.time_of_day !== "unknown" ? el("span", {}, todLabel(i.time_of_day)) : null,
        null),
      el("div", { class: "meta" }, i.url ? el("a", { href: i.url, target: "_blank", rel: "noopener noreferrer" }, `${t("read")} ${publisher(i)} ↗`) : null,
        el("span", {}, `${t("published")}: ${fmtTime(i.published_at)}`),
        i.more_reports ? el("span", {}, t("moreReports", { n: i.more_reports })) : null));
    card.hidden = false;
  }

  function renderAreaCard(card, g) {
    const max = Math.max(1, ...g.slices.map(([, n]) => n));
    fill(card,
      el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { state.area = null; renderSelected(); engine?.render(); } }, "×"),
      el("h3", {}, state.lang === "bn" ? g.name_bn : g.name_en),
      el("div", { class: "meta" }, el("span", {}, t("areaTotal", { n: g.total }))),
      el("div", { class: "muted" }, t("crimeMix")),
      el("ul", { class: "mix" }, ...g.slices.map(([k, n]) => el("li", {},
        el("span", { class: "name" }, el("span", { class: "dot", style: `background:${cssColor(k)}` }), catLabel(k)),
        el("span", { class: "bar" }, el("i", { style: `width:${(n / max) * 100}%;background:${cssColor(k)}` })),
        el("span", { class: "cnt" }, num(n))))));
    card.hidden = false;
  }

  function setTab(tab) {
    document.body.dataset.tab = tab;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
  }

  function applyTheme() {
    if (state.theme) document.documentElement.dataset.theme = state.theme; else delete document.documentElement.dataset.theme;
  }

  /* ---------- wiring ---------- */
  function wire() {
    document.querySelectorAll("#period button").forEach((b) => b.addEventListener("click", () => {
      state.days = +b.dataset.days; state.start = state.end = ""; $("#start").value = $("#end").value = "";
      document.querySelectorAll("#period button").forEach((x) => x.classList.toggle("on", x === b)); refresh({ fit: true });
    }));
    const onDate = () => {
      state.start = $("#start").value; state.end = $("#end").value;
      if (state.start && state.end) { document.querySelectorAll("#period button").forEach((x) => x.classList.remove("on")); refresh(); }
    };
    $("#start").addEventListener("change", onDate); $("#end").addEventListener("change", onDate);
    $("#cats-all").addEventListener("click", () => { state.cats = new Set(CAT_ORDER); refresh({ fit: true }); });
    $("#district").addEventListener("change", (e) => selectDistrict(e.target.value));
    $("#thana").addEventListener("change", (e) => {
      state.thana = e.target.value; const p = state.meta.thanas.find((x) => x.id === state.thana);
      if (!state.thana) { refresh(); fitArea(); return; }
      refresh({ fit: true, fallback: p && p.lat ? { lat: p.lat, lng: p.lng, zoom: 13 } : null });
    });
    document.querySelectorAll("#mode button").forEach((b) => b.addEventListener("click", () => {
      state.mode = b.dataset.mode; document.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x === b));
      renderLegend(); engine?.render();
    }));
    $("#zoom-in").addEventListener("click", () => engine?.zoomBy(1));
    $("#zoom-out").addEventListener("click", () => engine?.zoomBy(-1));
    $("#zoom-reset").addEventListener("click", () => engine?.reset());
    $("#lang-btn").addEventListener("click", () => { state.lang = state.lang === "bn" ? "en" : "bn"; store.set("dcm.lang", state.lang); applyI18n(); renderAll(); });
    $("#theme-btn").addEventListener("click", () => {
      state.theme = isDark() ? "light" : "dark"; store.set("dcm.theme", state.theme); applyTheme(); engine?.theme(); renderAll();
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { if (!state.theme) { engine?.theme(); renderAll(); } });
    document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  }

  function selectDistrict(id) {
    state.district = id || ""; state.thana = "";
    $("#district").value = state.district; renderThanaSelect();
    refresh(); fitArea();
  }

  /* ---------- live updates ----------
     Every 60 s (and when the tab becomes visible) read the tiny /api/version. When its data_version moves, reload
     the data; the new version counts as seen only after that reload succeeded. */
  let seenVersion = null, ticking = false, timer = null;
  async function tick() {
    clearTimeout(timer);
    if (!ticking && !document.hidden) {
      ticking = true;
      try {
        await loadVersion();
        if (state.version.data_version !== seenVersion) {
          const v = state.version.data_version;
          if (await refresh()) seenVersion = v;
        }
      } catch (e) {
        console.warn(e); state.offline = true; renderStatus();
      } finally { ticking = false; }
    }
    timer = setTimeout(tick, 60000);
  }

  async function main() {
    applyTheme(); setTab("map");
    const hd = +new URLSearchParams(location.hash.slice(1)).get("d");
    const hm = new URLSearchParams(location.hash.slice(1)).get("m");
    if (["heat", "points", "both"].includes(hm)) {
      state.mode = hm;
      document.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x.dataset.mode === hm));
    }
    if ([7, 30, 90, 365].includes(hd)) {
      state.days = hd;
      document.querySelectorAll("#period button").forEach((x) => x.classList.toggle("on", +x.dataset.days === hd));
    }
    await loadConfig();
    applyI18n(); wire();
    await initMap();
    engine.render();                       // the base map appears at once; data follows
    if (!new URLSearchParams(location.hash.slice(1)).get("ll")) fitArea();
    loadVersion().catch(console.warn);
    await refresh();
    seenVersion = state.version?.data_version ?? null;
    tick();
    document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  }
  main().catch((e) => { console.error(e); note(String(e)); });
})();
