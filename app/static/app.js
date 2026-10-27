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
      unlocated: "{n}টি ঘটনার স্থান অস্পষ্ট, মানচিত্রে নেই", fewer: "কম", more: "বেশি", density: "ঘটনার ঘনত্ব", blendNote: "প্রতিটি অপরাধের নিজস্ব রং; একাধিক ধরন মিশলে রংও মেশে। গাঢ় রং = বেশি প্রতিবেদিত ঘটনা (এই দৃশ্যের তুলনায়)। মানচিত্রে ট্যাপ করে মিশ্রণ দেখুন।",
      localMix: "এখানকার আনুমানিক মিশ্রণ", localMixNote: "কাছের ম্যাপকৃত ঘটনা থেকে রঙের ভাগ; এই রাস্তার ঘটনার সংখ্যা নয়।",
      totalsOnlyNote: "এই ধরন শুধু মোট সংখ্যায় গোনা হয়; স্থান ও প্রতিবেদনের লিংক দেখানো হয় না।", areaTotal: "{n}টি ঘটনা", crimeMix: "অপরাধের ধরন",
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
      density: "Incident density", blendNote: "Each crime type has its own colour; where types overlap, the colours blend. Deeper colour = more reported incidents (relative to this view). Tap the map to see the mix.",
      localMix: "Approximate local mix", localMixNote: "Shares of the glow from nearby mapped incidents, not counts for this street.",
      totalsOnlyNote: "This type is counted in totals only; locations and report links are not shown.", areaTotal: "{n} incidents", crimeMix: "Crime mix", published: "Published", killedInjured: "{n} killed/injured",
      noKey: "No Google Maps key configured; showing the fallback map.",
      keyFailed: "Google Maps key was rejected; showing the fallback map.", failed: "Could not start", days: "days", year: "year",
      sourceNote: "Source: newspaper reports · automatically extracted, may contain errors · reported incidents, not all crime", truncated: "Many incidents; showing the first {n}",
      showing: "{n} of {total}", offline: "Server unreachable; showing the last data",
    },
  };
  // Replaced by the server's category list on start (loadConfig): order, labels, visibility and permanent hues.
  let CAT_ORDER = ["murder", "assault", "robbery", "theft", "sexual_violence", "kidnapping", "drugs_arms", "fraud_extortion", "other"];
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
    lang: store.get("dcm.lang", "bn"), days: 7, start: "", end: "",
    cats: new Set(CAT_ORDER), district: "", thana: "", mode: "heat", meta: null, incidents: [], stats: null, selected: null, mix: null, heat: null,
  };
  let engine = null;

  const t = (k, vars = {}) => (I18N[state.lang][k] || k).replace(/\{(\w+)\}/g, (_, v) => num(vars[v]));
  const num = (n) => state.lang === "bn" ? String(n).replace(/\d/g, (d) => "০১২৩৪৫৬৭৮৯"[d]) : String(n);
  const locale = () => (state.lang === "bn" ? "bn-BD" : "en-GB");
  const fmtDate = (s) => s ? new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", year: "numeric" }).format(new Date(s + "T00:00:00")) : "";
  const fmtTime = (s) => s ? new Intl.DateTimeFormat(locale(), { day: "numeric", month: "short", hour: "numeric", minute: "2-digit", timeZone: "Asia/Dhaka" }).format(new Date(s)) : "";
  const catLabel = (k) => { const c = state.meta?.categories.find((x) => x.key === k); return c ? c[state.lang] : k; };
  const todLabel = (k) => { const c = state.meta?.time_of_day.find((x) => x.key === k); return c ? c[state.lang] : k; };
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

  function layers() {
    const pts = state.incidents.filter((i) => i.lat != null);
    const out = [];
    if (state.mode !== "points" && state.heat) {
      out.push(new deck.BitmapLayer({ id: "heat", image: state.heat.image, bounds: state.heat.bounds,
                                      textureParameters: { minFilter: "linear", magFilter: "linear" } }));
    }
    if (state.mode !== "heat") {
      const ring = [252, 252, 251];
      const colors = Object.fromEntries(CAT_ORDER.map((k) => [k, rgb(cssColor(k))]));
      const sel = state.selected?.id;
      out.push(new deck.ScatterplotLayer({
        id: "points", data: pts, pickable: true, stroked: true, radiusUnits: "pixels", lineWidthUnits: "pixels",
        getPosition: jitter, getRadius: (d) => (d.id === sel ? 10 : 6), getLineWidth: (d) => (d.id === sel ? 3 : 2),
        getFillColor: (d) => [...(colors[d.category] || colors.other), 235], getLineColor: ring,
        radiusMinPixels: 4, updateTriggers: { getRadius: sel, getLineWidth: sel },
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

  async function googleEngine(key, mapId) {
    await loadGoogle(key);
    const { Map } = await google.maps.importLibrary("maps");
    const opts = {
      center: startView().center, zoom: startView().zoom, minZoom: 6, maxZoom: 18, mapTypeControl: false,
      streetViewControl: false, fullscreenControl: false, zoomControl: false, rotateControl: false, tilt: 0, heading: 0,
      clickableIcons: false, gestureHandling: "greedy", backgroundColor: "#f2f1ed",
    };
    if (mapId) { opts.mapId = mapId; opts.colorScheme = "LIGHT"; } else { opts.styles = MAP_STYLE_LIGHT; }
    const map = new Map($("#map"), opts);
    const overlay = new deck.GoogleMapsOverlay({ interleaved: Boolean(mapId), layers: [] });
    overlay.setMap(map);
    map.addListener("click", (e) => {
      const r = $("#map").getBoundingClientRect(), de = e.domEvent;
      if (de && "clientX" in de) inspectHeat(de.clientX - r.left, de.clientY - r.top);
    });
    map.addListener("bounds_changed", () => paintHeat(true));
    let lastZoom = map.getZoom();
    map.addListener("zoom_changed", () => { if (Math.abs(map.getZoom() - lastZoom) >= 0.5) { lastZoom = map.getZoom(); engine?.render(); } });
    return {
      name: "google",
      render() { overlay.setProps({ layers: layers() }); },
      zoom() { return map.getZoom() || 12; },
      view() {
        const proj = map.getProjection(), b = map.getBounds();
        if (!proj || !b) return null;
        const nw = proj.fromLatLngToPoint(new google.maps.LatLng(b.getNorthEast().lat(), b.getSouthWest().lng()));
        const scale = 2 ** map.getZoom();
        return { zoom: map.getZoom(), project: (lng, lat) => {
          const p = proj.fromLatLngToPoint(new google.maps.LatLng(lat, lng));
          return [(p.x - nw.x) * scale, (p.y - nw.y) * scale];
        }, unproject: (x, y) => {
          const ll = proj.fromPointToLatLng(new google.maps.Point(nw.x + x / scale, nw.y + y / scale));
          return [ll.lng(), ll.lat()];
        } };
      },
      zoomBy(dz) { map.setZoom(Math.max(6, Math.min(18, (map.getZoom() || 12) + dz))); },
      reset() { fitArea(); },
      flyTo(lat, lng, zoom) { map.panTo({ lat, lng }); if (zoom) map.setZoom(zoom); },
      fitTo(b) {
        if (b.single) { this.flyTo(b.lat, b.lng, 15); return; }
        map.fitBounds({ south: b.s, west: b.w, north: b.n, east: b.e }, FIT_PADDING);
        google.maps.event.addListenerOnce(map, "idle", () => { if (map.getZoom() > 16) map.setZoom(16); });
      },
      destroy() { try { overlay.setMap(null); overlay.finalize(); } catch (e) { /* map never initialised */ } fill($("#map")); },
    };
  }

  function tileEngine() {
    const tiles = () => "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
    const base = () => new deck.TileLayer({
      id: "base", data: tiles(), minZoom: 0, maxZoom: 19, tileSize: 256,
      renderSubLayers: (props) => {
        const [[w, s], [e, n]] = props.tile.boundingBox;
        return new deck.BitmapLayer(props, {
          data: null, image: props.data, bounds: [w, s, e, n],
          desaturate: 0.55, tintColor: [255, 255, 255],
        });
      },
    });
    const sv = startView();
    let view = { longitude: sv.center.lng, latitude: sv.center.lat, zoom: sv.zoom, pitch: 0, bearing: 0, minZoom: 6, maxZoom: 18 };
    let heatZoom = Math.round(view.zoom * 2);
    const d = new deck.Deck({
      parent: $("#map"), initialViewState: view, layers: [],
      controller: { dragRotate: false, touchRotate: false, keyboard: { rotateSpeedX: 0, rotateSpeedY: 0 } },   // north-up only
      onViewStateChange: ({ viewState }) => {
        view = viewState;
        if (Math.round(view.zoom * 2) !== heatZoom) { heatZoom = Math.round(view.zoom * 2); engine?.render(); }
        paintHeat(true);
      },
      onClick: (info) => { if (!info.object) inspectHeat(info.x, info.y); },
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
      view() {
        const el = $("#map");
        const vp = new deck.WebMercatorViewport({ ...view, width: el.clientWidth || 800, height: el.clientHeight || 600 });
        return { zoom: view.zoom, project: (lng, lat) => vp.project([lng, lat]), unproject: (x, y) => vp.unproject([x, y]) };
      },
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
    if (state.version?.data_version) p.set("v", state.version.data_version);    // never reuse a cached old answer
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
    const [inc, stats, all] = await Promise.all([getJSON(`/api/incidents?${qc}&limit=20000`), getJSON(`/api/stats?${q}`),
      qc.toString() === q ? null : getJSON(`/api/stats?${qc}`)]);
    if (seq !== refreshSeq) return false;
    // the heat gets every type (hidden ones masked) so its scale stays put when chips change; lists use the filter
    state.allIncidents = inc.data;
    state.incidents = inc.data.filter((i) => state.cats.has(i.category));
    HeatPaint.setData(inc.data);
    state.mix = null;
    state.stats = stats.data; state.catCounts = (all || stats).data.by_category;
    state.truncated = inc.headers.get("X-Truncated") === "true";
    state.totalCount = +(inc.headers.get("X-Total-Count") || inc.data.length);
    // keep the open card, but show the freshly fetched version of it
    if (state.selected) state.selected = state.incidents.find((i) => i.id === state.selected.id) || null;
    renderAll();
    if (state.truncated) note(t("truncated", { n: inc.data.length }));
    if (opts.fit) fitToResults(opts.fallback);
    return true;
  }

  // Public page: labels once (/api/config), then only the small data-version check (/api/version).
  async function loadConfig() {
    state.meta = (await getJSON("/api/config")).data;
    CAT_ORDER = state.meta.categories.map((c) => c.key);
    state.cats = new Set(CAT_ORDER);
    const mapped = state.meta.categories.filter((c) => c.visibility === "mapped" && c.hue != null);
    HeatPaint.configure(mapped.map((c) => ({ key: c.key, hue: c.hue })));
    // chips, dots and legend take the heat's own colour for each mapped type
    for (const c of mapped) document.documentElement.style.setProperty(`--c-${c.key}`, HeatPaint.swatch(c.key));
  }

  async function loadVersion() {
    state.version = (await getJSON("/api/version")).data;
    state.offline = false;
    renderStatus();
  }

  /* ---------- rendering ---------- */
  function renderAll() {
    renderChips(); renderTiles(); renderRank(); renderTod(); renderTrend(); renderFeed(); renderLegend(); renderSelected();
    engine?.render(); paintHeat();
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
    $("#feed-count").textContent = list.length < state.incidents.length
      ? t("showing", { n: list.length, total: state.incidents.length }) : num(state.incidents.length);
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
    if (!s) return;                                         // a mode click before the first data arrives
    const mapped = CAT_ORDER.filter((k) => state.cats.has(k) && !(state.meta?.area_totals_only || []).includes(k));
    const totalsOnly = CAT_ORDER.filter((k) => state.cats.has(k) && (state.meta?.area_totals_only || []).includes(k));
    fill($("#legend"),
      state.mode !== "points" ? el("div", {},
        el("div", { class: "cats" }, ...mapped.map((k) => el("span", {}, el("i", { style: `background:${HeatPaint.swatch(k)}` }), catLabel(k)))),
        el("div", { class: "muted" }, t("blendNote"))) : null,
      state.mode !== "heat" ? el("div", { class: "cats" }, ...mapped.map((k) => el("span", {}, el("i", { style: `background:${cssColor(k)}` }), catLabel(k)))) : null,
      !mapped.length && totalsOnly.length ? el("div", { class: "muted" }, t("totalsOnlyNote")) : null,
      s.unlocated ? el("div", { class: "muted" }, t("unlocated", { n: s.unlocated })) : null,
      el("div", { class: "muted", style: "font-size:11px" }, t("sourceNote")));
  }

  function select(i, fly) {
    state.selected = i; state.mix = null;
    if (fly && i.lat != null) engine?.flyTo(i.lat, i.lng, 15);
    if (fly && matchMedia("(max-width: 760px)").matches) setTab("map");
    renderSelected(); renderFeed(); engine?.render();
  }

  function renderSelected() {
    const card = $("#selected"); const i = state.selected;
    if (!i && state.mix) { renderMixCard(card, state.mix); return; }
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

  // Tap on the heat: the approximate mix of crime types that makes up the glow there (shares, not counts)
  function renderMixCard(card, rows) {
    fill(card,
      el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { state.mix = null; renderSelected(); } }, "×"),
      el("h3", {}, t("localMix")),
      el("div", { class: "muted", style: "font-size:12px;margin-bottom:6px" }, t("localMixNote")),
      el("ul", { class: "mix" }, ...rows.map(([k, v]) => el("li", {},
        el("span", { class: "name" }, el("span", { class: "dot", style: `background:${HeatPaint.swatch(k)}` }), catLabel(k)),
        el("span", { class: "bar" }, el("i", { style: `width:${v * 100}%;background:${HeatPaint.swatch(k)}` })),
        el("span", { class: "cnt" }, `${num(Math.round(v * 100))}%`)))));
    card.hidden = false;
  }

  /* ---------- multi-colour heat (HeatPaint on its own canvas over the map) ---------- */
  let paintReq = null, paintRaf = 0, settleTimer = 0;
  function paintHeat(moving) {
    if (!engine?.view) return;
    if (state.mode === "points") {
      cancelAnimationFrame(paintRaf); paintRaf = 0; paintReq = null; clearTimeout(settleTimer);
      HeatPaint.clear(); if (state.heat) { state.heat = null; engine.render(); }
      return;
    }
    paintReq = { moving: Boolean(moving) };                 // the latest request wins
    if (!paintRaf) paintRaf = requestAnimationFrame(doPaint);
    clearTimeout(settleTimer);
    if (moving) settleTimer = setTimeout(() => paintHeat(false), 160);   // full detail once the map settles
  }
  function doPaint() {
    paintRaf = 0;
    const req = paintReq; paintReq = null;
    if (!req || state.mode === "points" || !engine?.view) return;
    const v = engine.view(), box = $("#map"); if (!v) return;
    const w = box.clientWidth, h = box.clientHeight;
    if (!w || !h) return;                                   // map hidden (phone tab): repainted when shown
    HeatPaint.setHidden(CAT_ORDER.filter((k) => !state.cats.has(k)));
    const image = HeatPaint.paint(w, h, v.zoom, v.project, req.moving);
    if (!image) { state.heat = null; engine.render(); return; }
    // the image covers whole grid cells, so its bottom-right corner can sit slightly past the view
    const [west, north] = v.unproject(0, 0), [east, south] = v.unproject(image.width, image.height);
    state.heat = { image, bounds: [west, south, east, north] };
    engine.render();
  }
  const mercY = (lat) => { const s = Math.sin(lat * Math.PI / 180); return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI); };

  function inspectHeat(x, y) {
    if (state.mode === "points" || !state.heat || !engine?.view) return;
    const v = engine.view(); if (!v) return;
    const [lng, lat] = v.unproject(x, y), [w0, s0, e0, n0] = state.heat.bounds;
    const fx = (lng - w0) / (e0 - w0), fy = (mercY(lat) - mercY(n0)) / (mercY(s0) - mercY(n0));
    const rows = HeatPaint.sample(fx * state.heat.image.width, fy * state.heat.image.height);
    state.selected = null; state.mix = rows && rows.length ? rows : null;
    renderSelected(); renderFeed(); engine?.render();
  }

  function setTab(tab) {
    document.body.dataset.tab = tab;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === tab));
    if (tab === "map") requestAnimationFrame(() => { engine?.render(); paintHeat(); });
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
      renderLegend(); engine?.render(); paintHeat();
    }));
    window.addEventListener("resize", () => paintHeat());
    $("#zoom-in").addEventListener("click", () => engine?.zoomBy(1));
    $("#zoom-out").addEventListener("click", () => engine?.zoomBy(-1));
    $("#zoom-reset").addEventListener("click", () => engine?.reset());
    $("#lang-btn").addEventListener("click", () => { state.lang = state.lang === "bn" ? "en" : "bn"; store.set("dcm.lang", state.lang); applyI18n(); renderAll(); });
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
    setTab("map");
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
