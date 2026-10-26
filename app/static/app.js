/* Dhaka Crime Map - dashboard. Google Maps + deck.gl when a key is configured, otherwise a deck.gl tile basemap. */
(() => {
  "use strict";

  const I18N = {
    bn: {
      title: "ঢাকা অপরাধ মানচিত্র", runNow: "এখনই সংগ্রহ", period: "সময়কাল", from: "শুরু", to: "শেষ",
      crimeType: "অপরাধের ধরন", all: "সব", area: "থানা / এলাকা", allDhaka: "সমগ্র ঢাকা", mapView: "মানচিত্র",
      heat: "হিটম্যাপ", both: "দুটোই", points: "ঘটনা", hotspots: "সবচেয়ে বেশি ঘটনা", timeOfDay: "দিনের কোন সময়ে",
      daily: "প্রতিদিনের ঘটনা", reports: "প্রতিবেদন", tabFilters: "ফিল্টার", tabMap: "মানচিত্র", tabFeed: "প্রতিবেদন",
      incidents: "ঘটনা", victims: "হতাহত", topArea: "শীর্ষ এলাকা", topCrime: "প্রধান অপরাধ",
      lastRun: "সর্বশেষ সংগ্রহ", nextRun: "পরবর্তী", running: "সংগ্রহ ও বিশ্লেষণ চলছে…", never: "এখনো হয়নি",
      model: "মডেল", read: "প্রথম আলোতে পড়ুন", moreReports: "আরও {n}টি প্রতিবেদন", noData: "এই ফিল্টারে কোনো ঘটনা নেই",
      exact: "নির্দিষ্ট স্থান", neighbourhood: "এলাকা", thana: "থানা পর্যায়", city: "স্থান অস্পষ্ট",
      unlocated: "{n}টি ঘটনার স্থান অস্পষ্ট, মানচিত্রে নেই", fewer: "কম", more: "বেশি", density: "ঘটনার ঘনত্ব",
      published: "প্রকাশ", killedInjured: "হতাহত {n}", noKey: "Google Maps কী সেট করা নেই; বিকল্প মানচিত্র দেখানো হচ্ছে।",
      keyFailed: "Google Maps কী কাজ করছে না; বিকল্প মানচিত্র দেখানো হচ্ছে।", started: "সংগ্রহ শুরু হয়েছে",
      busy: "একটি সংগ্রহ ইতিমধ্যে চলছে", failed: "শুরু করা যায়নি", days: "দিন", year: "বছর",
      sourceNote: "সূত্র: প্রথম আলো · শ্রেণিবিন্যাস: Gemma (নিজস্ব সার্ভার) · প্রতিবেদিত ঘটনা, সব অপরাধ নয়",
      gemmaProgress: "Gemma পড়ছে: {done}/{total}টি প্রতিবেদন", fetching: "প্রতিবেদন সংগ্রহ: {done}/{total}",
      spotsWaiting: "নির্দিষ্ট স্থান খোঁজা বাকি {n}টি", truncated: "অনেক ঘটনা; প্রথম {n}টি দেখানো হচ্ছে",
      showing: "{n}/{total}", offline: "সার্ভারে পৌঁছানো যাচ্ছে না; পুরোনো তথ্য দেখানো হচ্ছে", updated: "হালনাগাদ",
      covDone: "এই সময়ের {done}/{total} দিন সম্পূর্ণ প্রক্রিয়া হয়েছে", covMissing: "{n} দিন এখনো সংগ্রহ হয়নি",
      covPartial: "{n} দিন আংশিক", covProcessing: "{n} দিন Gemma পড়ছে", covCollect: "বাকি দিন সংগ্রহ করুন",
      notCollected: "সংগ্রহ হয়নি", processingDay: "Gemma পড়ছে", partialDay: "আংশিক সংগ্রহ",
      covFailed: "{n} দিনে কিছু প্রতিবেদন ব্যর্থ", failedDay: "কিছু ব্যর্থ",
      covTooOld: "{n} দিনের বেশি পুরোনো দিন এখান থেকে সংগ্রহ করা যায় না",
    },
    en: {
      title: "Dhaka Crime Map", runNow: "Collect now", period: "Period", from: "From", to: "To",
      crimeType: "Crime type", all: "All", area: "Thana / area", allDhaka: "All of Dhaka", mapView: "Map",
      heat: "Heatmap", both: "Both", points: "Incidents", hotspots: "Most incidents", timeOfDay: "Time of day",
      daily: "Incidents per day", reports: "Reports", tabFilters: "Filters", tabMap: "Map", tabFeed: "Reports",
      incidents: "Incidents", victims: "Killed / injured", topArea: "Top area", topCrime: "Top crime",
      lastRun: "Last collected", nextRun: "next", running: "Collecting and classifying…", never: "not yet",
      model: "model", read: "Read on Prothom Alo", moreReports: "{n} more reports", noData: "No incidents match these filters",
      exact: "Exact spot", neighbourhood: "Neighbourhood", thana: "Thana level", city: "Location unclear",
      unlocated: "{n} incidents have no clear location and are not on the map", fewer: "fewer", more: "more",
      density: "Incident density", published: "Published", killedInjured: "{n} killed/injured",
      noKey: "No Google Maps key configured; showing the fallback map.",
      keyFailed: "Google Maps key was rejected; showing the fallback map.", started: "Collection started",
      busy: "A collection run is already in progress", failed: "Could not start", days: "days", year: "year",
      sourceNote: "Source: Prothom Alo · classified by Gemma (in-house server) · reported incidents, not all crime",
      gemmaProgress: "Gemma reading: {done}/{total} articles", fetching: "Collecting articles: {done}/{total}",
      spotsWaiting: "{n} exact spots still being looked up", truncated: "Many incidents; showing the first {n}",
      showing: "{n} of {total}", offline: "Server unreachable; showing the last data", updated: "updated",
      covDone: "{done} of {total} days in this period fully processed", covMissing: "{n} days not collected yet",
      covPartial: "{n} days partly collected", covProcessing: "{n} days still being read by Gemma",
      covCollect: "Collect the missing days", notCollected: "not collected", processingDay: "Gemma reading",
      partialDay: "partly collected", covFailed: "{n} days with failed articles", failedDay: "some failed",
      covTooOld: "days older than {n} cannot be collected from here",
    },
  };
  const CAT_ORDER = ["murder", "assault", "robbery", "theft", "sexual_violence", "kidnapping", "drugs_arms", "fraud_extortion", "other"];
  // Transparent at the edge, deep red where incidents pile up: no hard-edged discs.
  const HEAT = [[254, 229, 217, 0], [253, 208, 190, 90], [252, 174, 145, 140], [251, 136, 104, 175], [244, 96, 72, 205],
    [222, 45, 38, 225], [180, 20, 30, 240], [127, 10, 18, 250]];
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
    cats: new Set(CAT_ORDER), thana: "", mode: "both", meta: null, incidents: [], stats: null, selected: null,
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
  const placeName = (i) => (state.lang === "bn" ? i.place_bn || i.thana_bn : i.place_en || i.thana_en) || i.location_text || "—";
  const thanaName = (i) => (state.lang === "bn" ? i.thana_bn : i.thana_en) || "";

  /* ---------- map engines ---------- */
  function jitter(d) {
    // Spread incidents that share a gazetteer centroid so each point stays clickable.
    if (d.geocoded) return [d.lng, d.lat];
    const a = d.id * 2.399963, r = 0.00045 * Math.sqrt(((d.id * 7919) % 97) / 97 + 0.05);
    return [d.lng + Math.cos(a) * r, d.lat + Math.sin(a) * r];
  }

  // Heat scale: "how many incidents pile up in one place", fixed for the current data so the colours mean the
  // same thing at every zoom (deck.gl's automatic scale is re-computed per view, which made the heat fade out).
  function heatScale(pts) {
    const n = {};
    for (const p of pts) { const k = `${p.lat.toFixed(3)},${p.lng.toFixed(3)}`; n[k] = (n[k] || 0) + 1; }
    // compressed: a single incident glows faintly, a quarter of the largest pile-up is already deep red
    return Math.max(1.5, Math.max(0, ...Object.values(n)) / 4);
  }
  // Blobs grow as you zoom in (half as fast as the map), so hotspots stay visible instead of shrinking to dots.
  const heatRadius = (zoom) => Math.max(30, Math.min(150, 42 * 2 ** ((zoom - 11.5) * 0.55)));

  function layers() {
    const pts = state.incidents.filter((i) => i.lat != null);
    const out = [];
    if (state.mode !== "points") {
      const zoom = engine?.zoom ? engine.zoom() : 12;
      out.push(new deck.HeatmapLayer({
        id: "heat", data: pts, getPosition: (d) => [d.lng, d.lat], getWeight: 1,
        radiusPixels: heatRadius(zoom), intensity: 1, threshold: 0.03, colorRange: HEAT, aggregation: "SUM",
        colorDomain: [0, heatScale(pts)], debounceTimeout: 0,
        updateTriggers: { radiusPixels: Math.round(zoom * 2) },
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

  function hover(info) {
    const tip = $("#tooltip");
    if (!info.object) { tip.hidden = true; return; }
    const d = info.object;
    fill(tip, 
      el("div", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(d.category)}` }), catLabel(d.category)),
      el("div", {}, state.lang === "bn" ? d.headline_bn : d.headline_en || d.headline_bn),
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
      center: startView().center, zoom: startView().zoom, minZoom: 9, maxZoom: 18, mapTypeControl: false,
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
      zoomBy(dz) { map.setZoom(Math.max(9, Math.min(18, (map.getZoom() || 12) + dz))); },
      reset() { map.panTo(DHAKA); map.setZoom(12); },
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
    let view = { longitude: sv.center.lng, latitude: sv.center.lat, zoom: sv.zoom, pitch: 0, bearing: 0, minZoom: 9, maxZoom: 18 };
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
      zoomBy(dz) { goTo({ zoom: Math.max(9, Math.min(18, view.zoom + dz)) }); },
      reset() { goTo({ latitude: DHAKA.lat, longitude: DHAKA.lng, zoom: 11.2 }); },
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
    return { zoom: z >= 9 && z <= 18 ? z : 11.2,
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
    if (state.thana) p.set("thana", state.thana);
    return p.toString();
  }

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
    const [inc, stats, all, cov] = await Promise.all([getJSON(`/api/incidents?${q}`), getJSON(`/api/stats?${q}`),
      qc.toString() === q ? null : getJSON(`/api/stats?${qc}`), getJSON(`/api/coverage?${rangeQuery()}`)]);
    if (seq !== refreshSeq) return false;
    state.coverage = cov.data;
    state.incidents = inc.data; state.stats = stats.data; state.catCounts = (all || stats).data.by_category;
    state.truncated = inc.headers.get("X-Truncated") === "true";
    state.totalCount = +(inc.headers.get("X-Total-Count") || inc.data.length);
    // keep the open card, but show the freshly fetched version of it
    if (state.selected) state.selected = inc.data.find((i) => i.id === state.selected.id) || null;
    renderAll();
    if (state.truncated) note(t("truncated", { n: inc.data.length }));
    if (opts.fit) fitToResults(opts.fallback);
    return true;
  }

  async function loadMeta() {
    state.meta = (await getJSON("/api/meta")).data;
    state.offline = false;
    renderStatus();
  }

  /* ---------- rendering ---------- */
  function renderCoverage() {
    const box = $("#coverage"), c = state.coverage;
    if (!c) { box.hidden = true; return; }
    const s = c.summary, total = c.days.length;
    if (s.complete >= total) { box.hidden = true; return; }      // every day, today included, is complete
    const parts = [t("covDone", { done: s.complete, total })];
    if (s.not_collected) parts.push(t("covMissing", { n: s.not_collected }));
    if (s.partial) parts.push(t("covPartial", { n: s.partial }));
    if (s.processing) parts.push(t("covProcessing", { n: s.processing }));
    if (s.failed) parts.push(t("covFailed", { n: s.failed }));
    const busy = state.meta?.collecting;
    const tooOld = c.days_to_collect > c.max_days_back;
    fill(box, el("span", {}, parts.join(" · ")),
      c.days_to_collect > 0 && !busy ? el("button", { class: "btn", type: "button", onclick: async () => {
        const r = await fetch(`/api/scrape?days_back=${Math.min(c.max_days_back, c.days_to_collect)}`, { method: "POST", headers: { "X-DCM-UI": "1" } });
        note(r.status === 202 ? t("started") : r.status === 409 ? t("busy") : `${t("failed")} (${r.status})`);
        tick();
      } }, t("covCollect")) : null,
      tooOld ? el("span", { class: "muted" }, t("covTooOld", { n: c.max_days_back })) : null);
    box.hidden = false;
  }

  // Coverage changes with job progress, not only with the map data: refresh it on every active poll.
  async function refreshCoverage() {
    try {
      state.coverage = (await getJSON(`/api/coverage?${rangeQuery()}`)).data;
      renderCoverage(); renderTrend();
    } catch (e) { console.warn(e); }
  }

  function renderAll() {
    renderCoverage(); renderChips(); renderTiles(); renderRank(); renderTod(); renderTrend(); renderFeed(); renderLegend(); renderSelected();
    engine?.render();
  }

  function renderStatus() {
    const m = state.meta;
    const parts = [];
    if (state.offline) parts.push(t("offline"));
    // Progress of every active batch (a collection run or a reprocess), counted in articles
    const b = (m.batches || []).reduce((a, x) => ({
      jobs: a.jobs + x.jobs, processed: a.processed + x.processed,
      fetch: a.fetch + (x.status === "running" ? Math.max(0, (x.discovered || 0) - (x.fetched || 0)) : 0),
      fetched: a.fetched + (x.status === "running" ? x.fetched || 0 : 0), discovered: a.discovered + (x.status === "running" ? x.discovered || 0 : 0),
    }), { jobs: 0, processed: 0, fetch: 0, fetched: 0, discovered: 0 });
    if (b.fetch) parts.push(t("fetching", { done: b.fetched, total: b.discovered }));
    if (b.jobs && b.processed < b.jobs) parts.push(t("gemmaProgress", { done: b.processed, total: b.jobs }));
    else if (m.running) parts.push(t("running"));
    if (!m.running && !b.jobs) parts.push(`${t("lastRun")}: ${m.last_run ? fmtTime(m.last_run.finished_at || m.last_run.started_at) : t("never")}`);
    if (m.exact_spots_waiting) parts.push(t("spotsWaiting", { n: m.exact_spots_waiting }));
    if (m.next_run) parts.push(`${t("nextRun")}: ${fmtTime(m.next_run)}`);
    parts.push(`${t("model")}: ${m.model_label || m.model}`);
    $("#status-line").textContent = parts.join(" · ");
    $("#run-btn").disabled = m.running;
  }

  function applyI18n() {
    document.documentElement.lang = state.lang;
    document.title = t("title");
    document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
    document.querySelectorAll("#period button").forEach((b) => {
      const d = +b.dataset.days; b.textContent = d === 365 ? `১ ${t("year")}`.replace("১", num(1)) : `${num(d)} ${t("days")}`;
    });
    $("#lang-btn").textContent = state.lang === "bn" ? "EN" : "বাং";
    const sel = $("#thana"); const cur = sel.value;
    fill(sel, el("option", { value: "" }, t("allDhaka")),
      ...state.meta.thanas.slice().sort((a, b) => (state.lang === "bn" ? a.name_bn.localeCompare(b.name_bn, "bn") : a.name_en.localeCompare(b.name_en)))
        .map((p) => el("option", { value: p.id }, state.lang === "bn" ? p.name_bn : p.name_en)));
    sel.value = cur;
    renderStatus();
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
    const topThana = s.by_thana[0];
    const topCat = Object.entries(s.by_category).sort((a, b) => b[1] - a[1])[0];
    const tile = (v, k, txt) => el("div", { class: "tile" }, el("div", { class: txt ? "v txt" : "v", title: v }, v), el("div", { class: "k" }, k));
    fill($("#tiles"), 
      tile(num(s.total), t("incidents")), tile(num(s.victims), t("victims")),
      tile(topThana ? (state.lang === "bn" ? topThana.name_bn : topThana.name_en) : "—", t("topArea"), true),
      tile(topCat ? catLabel(topCat[0]) : "—", t("topCrime"), true));
  }

  function renderRank() {
    const rows = state.stats.by_thana.slice(0, 10);
    const max = Math.max(1, ...rows.map((r) => r.count));
    fill($("#rank"), ...(rows.length ? rows.map((r, i) => el("li", {}, el("button", {
      type: "button", class: state.thana === r.id ? "on" : "",
      onclick: () => { state.thana = state.thana === r.id ? "" : r.id; $("#thana").value = state.thana; refresh({ fit: true, fallback: { lat: r.lat || DHAKA.lat, lng: r.lng || DHAKA.lng, zoom: 14 } }); },
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
    const status = Object.fromEntries((state.coverage?.days || []).map((d) => [d.date, d.status]));
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
      el("h3", {}, state.lang === "bn" ? i.headline_bn : i.headline_en || i.headline_bn),
      el("div", { class: "meta" }, el("span", {}, placeName(i)), el("span", {}, fmtDate(i.event_date)),
        i.time_of_day !== "unknown" ? el("span", {}, todLabel(i.time_of_day)) : null, precisionBadge(i.precision))))) : [el("li", { class: "empty" }, t("noData"))]));
  }

  function renderLegend() {
    const s = state.stats;
    fill($("#legend"), 
      state.mode !== "points" ? el("div", {}, el("div", { class: "muted" }, t("density")), el("div", { class: "ramp" }), el("div", { class: "ends" }, el("span", {}, t("fewer")), el("span", {}, t("more")))) : null,
      state.mode !== "heat" ? el("div", { class: "cats" }, ...CAT_ORDER.filter((k) => state.cats.has(k)).map((k) => el("span", {}, el("i", { style: `background:${cssColor(k)}` }), catLabel(k)))) : null,
      s.unlocated ? el("div", { class: "muted" }, t("unlocated", { n: s.unlocated })) : null,
      el("div", { class: "muted", style: "font-size:11px" }, t("sourceNote")));
  }

  function select(i, fly) {
    state.selected = i;
    if (fly && i.lat != null) engine?.flyTo(i.lat, i.lng, 15);
    if (fly && matchMedia("(max-width: 760px)").matches) setTab("map");
    renderSelected(); renderFeed(); engine?.render();
  }

  function renderSelected() {
    const card = $("#selected"); const i = state.selected;
    if (!i) { card.hidden = true; return; }
    const loc = [i.location_text, thanaName(i) && thanaName(i) !== placeName(i) ? thanaName(i) : null].filter(Boolean).join(" · ");
    fill(card, 
      el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { state.selected = null; renderSelected(); renderFeed(); engine?.render(); } }, "×"),
      el("span", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(i.category)}` }), catLabel(i.category)),
      el("h3", {}, state.lang === "bn" ? i.headline_bn : i.headline_en || i.headline_bn),
      el("div", { class: "meta" }, el("span", {}, loc), precisionBadge(i.precision)),
      el("div", { class: "meta" }, el("span", {}, fmtDate(i.event_date)), i.time_of_day !== "unknown" ? el("span", {}, todLabel(i.time_of_day)) : null,
        i.victims ? el("span", {}, t("killedInjured", { n: i.victims })) : null),
      i.evidence && i.evidence_ok ? el("p", { class: "quote" }, `“${i.evidence}”`) : null,
      el("div", { class: "meta" }, el("a", { href: i.url, target: "_blank", rel: "noopener" }, `${t("read")} ↗`),
        el("span", {}, `${t("published")}: ${fmtTime(i.published_at)}`),
        i.more_reports ? el("span", {}, t("moreReports", { n: i.more_reports })) : null));
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
    $("#thana").addEventListener("change", (e) => {
      state.thana = e.target.value; const p = state.meta.thanas.find((x) => x.id === state.thana);
      refresh({ fit: true, fallback: { lat: p ? p.lat : DHAKA.lat, lng: p ? p.lng : DHAKA.lng, zoom: p ? 14 : 12 } });
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
    $("#run-btn").addEventListener("click", async () => {
      const r = await fetch("/api/scrape", { method: "POST", headers: { "X-DCM-UI": "1" } });
      note(r.status === 202 ? t("started") : r.status === 409 ? t("busy") : `${t("failed")} (${r.status})`);
      tick();
    });
  }

  /* ---------- live updates ----------
     One loop: read /api/meta every 5 s while anything is being collected, classified or geocoded, every 30 s
     otherwise. When data_version (a database counter bumped with every visible change) moves, reload the data;
     the new version counts as seen only after that reload succeeded. */
  let seenVersion = null, ticking = false, timer = null, lastReload = 0;
  async function tick() {
    clearTimeout(timer);
    if (!ticking) {
      ticking = true;
      try {
        await loadMeta();
        const active = state.meta.running || (state.meta.batches || []).length;
        if (active) refreshCoverage();
        // at most one data reload per 15 s, even while exact spots arrive one by one
        if (state.meta.data_version !== seenVersion && Date.now() - lastReload >= 15000) {
          const v = state.meta.data_version;
          lastReload = Date.now();
          if (await refresh()) seenVersion = v;
        }
      } catch (e) {
        console.warn(e); state.offline = true; if (state.meta) renderStatus();
      } finally { ticking = false; }
    }
    const busy = state.meta && (state.meta.running || state.meta.exact_spots_waiting || (state.meta.batches || []).length);
    timer = setTimeout(tick, busy ? 5000 : 30000);
  }

  async function main() {
    applyTheme(); setTab("map");
    const hd = +new URLSearchParams(location.hash.slice(1)).get("d");
    if ([7, 30, 90, 365].includes(hd)) {
      state.days = hd;
      document.querySelectorAll("#period button").forEach((x) => x.classList.toggle("on", +x.dataset.days === hd));
    }
    await loadMeta();
    applyI18n(); wire();
    await initMap();
    await refresh();
    seenVersion = state.meta.data_version;
    tick();
    document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  }
  main().catch((e) => { console.error(e); note(String(e)); });
})();
