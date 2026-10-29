/* Dhaka Crime Map - dashboard. Google Maps + deck.gl when a key is configured, otherwise a deck.gl tile basemap. */
(() => {
  "use strict";

  const I18N = {
    bn: {
      title: "বাংলাদেশ অপরাধ মানচিত্র", place: "বিভাগ ও জেলা", allDivisions: "সব বিভাগ (৮টি)", allDistricts: "বিভাগের সব জেলা", period: "সময়কাল", from: "শুরু", to: "শেষ",
      crimeType: "অপরাধের ধরন", all: "সব", area: "থানা / এলাকা", allDhaka: "সমগ্র ঢাকা", mapView: "মানচিত্র",
      heat: "হিটম্যাপ", both: "দুটোই", points: "ঘটনা", hotspots: "সবচেয়ে বেশি ঘটনা", timeOfDay: "দিনের কোন সময়ে",
      daily: "প্রতিদিনের ঘটনা", reports: "প্রতিবেদন", tabFilters: "ফিল্টার", tabMap: "মানচিত্র", tabFeed: "প্রতিবেদন",
      incidents: "ঘটনা", victims: "হতাহত", topArea: "শীর্ষ এলাকা", topCrime: "প্রধান অপরাধ",
      updated: "হালনাগাদ", topTime: "বেশি ঘটনার সময়", read: "পড়ুন:", moreReports: "আরও {n}টি প্রতিবেদন", noData: "এই ফিল্টারে কোনো ঘটনা নেই",
      exact: "নির্দিষ্ট স্থান", neighbourhood: "এলাকা", thana: "থানা পর্যায়", city: "জেলা পর্যায়",
      unlocated: "{n}টি ঘটনার শুধু জেলা জানা: জেলার বৃত্তে গোনা, হিটম্যাপে নেই", fewer: "কম", more: "বেশি", density: "ঘটনার ঘনত্ব", blendNote: "প্রতিটি অপরাধের নিজস্ব রং; একাধিক ধরন মিশলে রংও মেশে (মিশ্র রং আনুমানিক, সঠিক সংখ্যা ট্যাপ করে দেখুন)। গাঢ় = এই জুমে বেশি প্রতিবেদিত ঘটনা।",
      howToRead: "কীভাবে পড়বেন", districtHint: "মানচিত্রে ট্যাপ: সেই জেলার প্রতিবেদন · জুম করে এলাকা দেখুন", heatHint: "মানচিত্রে ট্যাপ: সেখানকার প্রতিবেদন",
      pointsNote: "প্রতিটি বিন্দু একটি প্রতিবেদিত ঘটনা; রং = অপরাধের ধরন।",
      districtReports: "{place} জেলায় {n}টি প্রতিবেদন", reportsWord: "প্রতিবেদন",
      areaReports: "{place}: {n}টি প্রতিবেদন", showAreaReports: "এখানকার {n}টি প্রতিবেদন দেখুন", thisArea: "এই এলাকা",
      areaCount: "বৃত্তের ভেতরে {n}টি প্রতিবেদন", localMix: "এখানকার আনুমানিক মিশ্রণ", mixAt: "{place}: আনুমানিক মিশ্রণ", nearCount: "এখানে আশপাশে মানচিত্রে প্রায় {n}টি ঘটনা",
      totalsOnlyFeed: "{cat}: {n}টি ঘটনা। ভুক্তভোগীর গোপনীয়তার জন্য এই ধরনের ঘটনা শুধু মোট সংখ্যায় দেখানো হয়; মানচিত্রে স্থান ও প্রতিবেদনের লিংক দেখানো হয় না।",
      byDistrict: "জেলা অনুযায়ী:", localMixNote: "কাছের ম্যাপকৃত ঘটনা থেকে রঙের ভাগ; এই রাস্তার ঘটনার সংখ্যা নয়।",
      totalsOnlyNote: "এই ধরন শুধু মোট সংখ্যায় গোনা হয়; স্থান ও প্রতিবেদনের লিংক দেখানো হয় না।", areaTotal: "{n}টি ঘটনা", crimeMix: "অপরাধের ধরন",
      published: "প্রকাশ", killedInjured: "হতাহত {n}", noKey: "Google Maps কী সেট করা নেই; বিকল্প মানচিত্র দেখানো হচ্ছে।",
      keyFailed: "Google Maps কী কাজ করছে না; বিকল্প মানচিত্র দেখানো হচ্ছে।", failed: "শুরু করা যায়নি", days: "দিন", year: "বছর",
      sourceNote: "সূত্র: সংবাদপত্রের প্রতিবেদন · স্বয়ংক্রিয় বিশ্লেষণ, ভুল থাকতে পারে · প্রতিবেদিত ঘটনা, সব অপরাধ নয়", truncated: "অনেক ঘটনা; প্রথম {n}টি দেখানো হচ্ছে",
      showing: "{n}/{total}", offline: "সার্ভারে পৌঁছানো যাচ্ছে না; পুরোনো তথ্য দেখানো হচ্ছে",
    },
    en: {
      title: "Bangladesh Crime Map", place: "Division & district", allDivisions: "All 8 divisions", allDistricts: "All districts of the division", period: "Period", from: "From", to: "To",
      crimeType: "Crime type", all: "All", area: "Thana / area", allDhaka: "All of Dhaka", mapView: "Map",
      heat: "Heatmap", both: "Both", points: "Incidents", hotspots: "Most incidents", timeOfDay: "Time of day",
      daily: "Incidents per day", reports: "Reports", tabFilters: "Filters", tabMap: "Map", tabFeed: "Reports",
      incidents: "Incidents", victims: "Killed / injured", topArea: "Top area", topCrime: "Top crime",
      updated: "Updated", topTime: "Most common time", read: "Read on", moreReports: "{n} more reports", noData: "No incidents match these filters",
      exact: "Exact spot", neighbourhood: "Neighbourhood", thana: "Thana level", city: "District level",
      unlocated: "{n} incidents are known only to their district: counted in its circle, not in the heatmap", fewer: "fewer", more: "more",
      density: "Incident density", blendNote: "Each crime type has its own colour; where types overlap the colours blend (a mixed colour is approximate: tap for exact counts). Deeper = more reported incidents at this zoom.",
      howToRead: "How to read", districtHint: "Tap the map: that district's reports · zoom in for areas", heatHint: "Tap the map: the reports there",
      pointsNote: "Each dot is one reported incident; colour = crime type.",
      districtReports: "{n} reports in {place} district", reportsWord: "reports",
      areaReports: "{place}: {n} reports", showAreaReports: "Show the {n} reports here", thisArea: "This area",
      areaCount: "{n} reports inside the circle", localMix: "Approximate local mix", mixAt: "{place}: approximate mix", nearCount: "About {n} mapped incidents around here",
      totalsOnlyFeed: "{cat}: {n} incidents. To protect victims, this type is counted in totals only; locations and report links are not shown on the map.",
      byDistrict: "By district:", localMixNote: "Shares of the glow from nearby mapped incidents, not counts for this street.",
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
    cats: new Set(CAT_ORDER), division: "", district: "", thana: "", area: null, mode: "heat", meta: null, incidents: [], stats: null, selected: null, mix: null, heat: null,
  };
  let engine = null;

  /* One colour-blended heat at every zoom (owner, 29 Oct: district circles made a mixed colour look like another
     crime type; the heat shows the real overlap). Below DISTRICT_ZOOM a tap opens the reports of the district under
     the finger; closer in, the reports around the tap. #base=tiles forces the raster fallback (for testing). */
  const STYLE = { base: new URLSearchParams(location.hash.slice(1)).get("base") === "tiles" ? "osm" : "vector", veil: 0.5 };
  const DISTRICT_ZOOM = 9;
  // re-render on half-zoom steps, and at once when the zoom crosses the district-tap threshold
  const zoomStep = (z0, z1) => Math.abs(z1 - z0) >= 0.5 || (z0 < DISTRICT_ZOOM) !== (z1 < DISTRICT_ZOOM);
  const overview = () => !state.district && !!engine && engine.zoom() < DISTRICT_ZOOM;
  const districtMeta = (id) => state.meta.districts.find((x) => x.id === id);
  function districtCentre(d) {
    if (d.lat != null) return { lat: d.lat, lng: d.lng };
    const b = d.bounds; return b ? { lat: (b.s + b.n) / 2, lng: (b.w + b.e) / 2 } : null;
  }

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
  // place, else thana, else (district-level reports) the district
  const placeName = (i) => (state.lang === "bn" ? i.place_bn || i.thana_bn : i.place_en || i.thana_en) || i.location_text
    || (i.district_id && districtMeta(i.district_id) ? label(districtMeta(i.district_id)) : "—");
  const thanaName = (i) => (state.lang === "bn" ? i.thana_bn : i.thana_en) || "";

  /* ---------- map engines ---------- */
  function jitter(d) {
    // Spread incidents that share a gazetteer centroid so each point stays clickable.
    if (d.geocoded) return [d.lng, d.lat];
    const a = d.id * 2.399963, r = 0.00045 * Math.sqrt(((d.id * 7919) % 97) / 97 + 0.05);
    return [d.lng + Math.cos(a) * r, d.lat + Math.sin(a) * r];
  }

  let ptsCache = { src: null, rows: [] };
  const mappedPoints = () => (ptsCache.src === state.incidents ? ptsCache.rows
    : (ptsCache = { src: state.incidents, rows: state.incidents.filter((i) => i.lat != null) }).rows);
  function layers() {
    const out = [];
    if (state.mode !== "points" && state.heat && !engine?.drawsHeat) {
      out.push(new deck.BitmapLayer({ id: "heat", image: state.heat.image, bounds: state.heat.bounds,
                                      textureParameters: { minFilter: "linear", magFilter: "linear" } }));
    }
    if (state.mode !== "heat") {
      const pts = mappedPoints();
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

  // Called on every render: crossing the district-tap threshold changes the legend hint
  let lastOverview = null;
  function syncView() {
    const o = overview();
    if (o !== lastOverview) { lastOverview = o; queueMicrotask(renderLegend); }
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
    map.addListener("zoom_changed", () => { if (zoomStep(lastZoom, map.getZoom())) { lastZoom = map.getZoom(); engine?.render(); } });
    return {
      name: "google",
      render() { syncView(); overlay.setProps({ layers: layers() }); },
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

  /* Clean vector basemap (no key, no signup): OpenFreeMap's Positron style drawn by MapLibre, calmed further so only
     what helps to find a place stays - no parks, land cover or icons, faint water, near-white land, quiet labels in
     the page's language. The heat is a raster layer inside the map, under every label (place, road and river names
     stay readable); deck.gl draws points on top. Falls back to the OSM tiles if it cannot load. */
  const VECTOR_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
  const labelField = (lang) => (lang === "bn"
    ? ["coalesce", ["get", "name:bn"], ["get", "name:nonlatin"], ["get", "name"]]
    : ["coalesce", ["get", "name_en"], ["get", "name:latin"], ["get", "name"]]);
  function calmStyle(style, lang) {
    // no coloured areas (parks, land cover, land use, buildings, road surfaces); lines and names stay
    const drop = /^(park|landcover|landuse|aeroway|airport|building|highway-shield|road_shield|highway_path|railway_transit|railway_service|road_area)/;
    style.layers = style.layers.filter((l) => !drop.test(l.id));
    // Bangla labels: MapLibre's glyph files cannot join Bangla letters (conjuncts like ন্দ, vowel signs like ি that go
    // before the consonant). font-faces gives it the real Noto Sans Bengali font for the Bengali block, which the
    // browser shapes cluster by cluster; other scripts keep using the style's glyph files.
    const bengali = [{ url: new URL("/static/fonts/noto-sans-bengali-bengali-wght-normal.woff2", location.href).href,
                       "unicode-range": ["U+0980-09FF", "U+200C-200D", "U+25CC"] }];
    const fonts = new Set(["Noto Sans Regular", ...style.layers.flatMap((l) => {
      const f = l.layout?.["text-font"]; return Array.isArray(f) && f.every((x) => typeof x === "string") ? f : [];
    })]);
    style["font-faces"] = Object.fromEntries([...fonts].map((f) => [f, bengali]));
    for (const l of style.layers) {
      l.paint = l.paint || {};
      if (l.id === "background") l.paint["background-color"] = "#fcfcfb";
      if (l.type === "fill" && l.id !== "water") l.paint["fill-color"] = "#fcfcfb";   // any other area: as the land
      if (l.id === "water") l.paint["fill-color"] = "#eeefef";                         // rivers: a neutral hint, no blue
      if (l.id === "waterway") l.paint["line-color"] = "#e6e7e7";
      if (l.type === "symbol") {
        l.layout = { ...(l.layout || {}), "text-field": labelField(lang) };
        l.paint["text-color"] = /country|state/.test(l.id) ? "#9a9a96" : /water/.test(l.id) ? "#6f8a99" : "#45453f";
        l.paint["text-halo-color"] = "#fcfcfb";
        l.paint["text-halo-width"] = 1.4;
        l.layout["text-letter-spacing"] = 0;                 // spacing pulls Bangla letter clusters apart
        // main roads named from zoom 11.5, other streets from 14 (landmarks people navigate by); rivers stay named
        if (l.id === "highway-name-major") l.minzoom = 11.5;
        if (l.id === "highway-name-minor") l.minzoom = 14;
        // towns and cities from zoom 9: below that our district names (one per district, on top) label the map
        if (/^label_(city|town)/.test(l.id)) l.minzoom = Math.max(l.minzoom || 0, 9);
      }
    }
    return style;
  }
  const maplibreReady = () => (window.maplibregl ? Promise.resolve()
    : new Promise((res) => { addEventListener("maplibre-ready", res, { once: true }); setTimeout(res, 8000); }));

  async function vectorEngine() {
    await maplibreReady();
    if (!window.maplibregl || !deck.MapboxOverlay) throw new Error("vector map library not available");
    const r = await fetch(VECTOR_STYLE_URL);
    if (!r.ok) throw new Error(`basemap style: HTTP ${r.status}`);
    const style = calmStyle(await r.json(), state.lang);
    const sv = startView();
    const map = new maplibregl.Map({   // eslint-disable-line no-undef
      container: $("#map"), style, center: [sv.center.lng, sv.center.lat], zoom: sv.zoom, minZoom: 5.5, maxZoom: 18,
      dragRotate: false, pitchWithRotate: false, touchPitch: false, attributionControl: { compact: true },
    });
    try {
      map.touchZoomRotate.disableRotation();
      // the style must load; slow tiles may follow (a timeout with the style loaded is fine)
      await new Promise((res, rej) => {
        map.once("load", res);
        map.once("error", (e) => { if (!map.isStyleLoaded()) rej(e.error || new Error("basemap error")); });
        setTimeout(() => (map.isStyleLoaded() ? res() : rej(new Error("basemap timeout"))), 12000);
      });
    } catch (e) { try { map.remove(); } catch (_) { /* never created */ } throw e; }
    const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
    const overlay = new deck.MapboxOverlay({ interleaved: false, layers: [],
      onClick: (info) => { if (!info.object) inspectHeat(info.x, info.y); } });
    map.addControl(overlay);
    // the heat: one canvas the painter's image is copied into, shown as a raster layer under the first label
    const heatCanvas = document.createElement("canvas"); heatCanvas.width = heatCanvas.height = 1;
    let heatSource = null;
    function setHeat(image, b) {
      if (!image) { if (heatSource) map.setLayoutProperty("heat", "visibility", "none"); return; }
      if (heatCanvas.width !== image.width || heatCanvas.height !== image.height) {
        heatCanvas.width = image.width; heatCanvas.height = image.height;
      }
      const ctx = heatCanvas.getContext("2d");
      ctx.clearRect(0, 0, heatCanvas.width, heatCanvas.height); ctx.drawImage(image, 0, 0);
      const [w, s, e, n] = b, coords = [[w, n], [e, n], [e, s], [w, s]];
      if (!heatSource) {
        map.addSource("heat", { type: "canvas", canvas: heatCanvas, coordinates: coords, animate: false });
        map.addLayer({ id: "heat", type: "raster", source: "heat",
                       paint: { "raster-fade-duration": 0, "raster-resampling": "linear" } }, firstLabel);
        heatSource = map.getSource("heat");
      } else {
        heatSource.setCoordinates(coords);
        map.setLayoutProperty("heat", "visibility", "visible");
      }
      heatSource.play(); map.once("render", () => heatSource.pause()); map.triggerRepaint();   // upload the new pixels once
    }
    // every district's name at country and division zoom (the bird's-eye view), above the heat
    const districtName = (lang) => ["get", lang === "bn" ? "bn" : "en"];
    map.addSource("district-names", { type: "geojson", data: { type: "FeatureCollection",
      features: state.meta.districts.filter((d) => districtCentre(d)).map((d) => {
        const c = districtCentre(d);
        return { type: "Feature", properties: { bn: d.bn, en: d.en }, geometry: { type: "Point", coordinates: [c.lng, c.lat] } };
      }) } });
    map.addLayer({ id: "district-names", type: "symbol", source: "district-names", maxzoom: DISTRICT_ZOOM + 0.6,
      layout: { "text-field": districtName(state.lang), "text-font": ["Noto Sans Regular"], "text-padding": 1,
                "text-size": ["interpolate", ["linear"], ["zoom"], 6, 10.5, 9, 13.5], "text-optional": true },
      paint: { "text-color": "#2b2b28", "text-halo-color": "#fcfcfb", "text-halo-width": 1.6 } });
    let lastZ = map.getZoom();
    map.on("move", () => paintHeat(true));
    map.on("zoom", () => { if (zoomStep(lastZ, map.getZoom())) { lastZ = map.getZoom(); engine?.render(); } });
    return {
      name: "vector",
      drawsHeat: true, setHeat,
      render() { syncView(); overlay.setProps({ layers: layers() }); },
      zoom() { return map.getZoom(); },
      view() {
        return { zoom: map.getZoom(), project: (lng, lat) => { const p = map.project([lng, lat]); return [p.x, p.y]; },
                 unproject: (x, y) => { const l = map.unproject([x, y]); return [l.lng, l.lat]; } };
      },
      zoomBy(dz) { map.easeTo({ zoom: Math.max(5.5, Math.min(18, map.getZoom() + dz)), duration: 300 }); },
      reset() { fitArea(); },
      flyTo(lat, lng, zoom) { map.flyTo({ center: [lng, lat], zoom: zoom || map.getZoom(), duration: 700 }); },
      fitTo(b) {
        if (b.single) { this.flyTo(b.lat, b.lng, 15); return; }
        map.fitBounds([[b.w, b.s], [b.e, b.n]], { padding: FIT_PADDING, maxZoom: 16, duration: 600 });
      },
      setLang(lang) {
        for (const l of map.getStyle().layers) {
          if (l.type === "symbol") map.setLayoutProperty(l.id, "text-field", l.id === "district-names" ? districtName(lang) : labelField(lang));
        }
      },
      destroy() { try { map.remove(); } catch (e) { /* already gone */ } fill($("#map")); },
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
          desaturate: 1,
        });
      },
    });
    const sv = startView();
    let view = { longitude: sv.center.lng, latitude: sv.center.lat, zoom: sv.zoom, pitch: 0, bearing: 0, minZoom: 6, maxZoom: 18 };
    let heatZoom = Math.round(view.zoom * 2), prevZoom = view.zoom;
    const d = new deck.Deck({
      parent: $("#map"), initialViewState: view, layers: [],
      controller: { dragRotate: false, touchRotate: false, keyboard: { rotateSpeedX: 0, rotateSpeedY: 0 } },   // north-up only
      onViewStateChange: ({ viewState }) => {
        view = viewState;
        if (Math.round(view.zoom * 2) !== heatZoom || zoomStep(prevZoom, view.zoom)) {
          heatZoom = Math.round(view.zoom * 2); engine?.render();
        }
        prevZoom = view.zoom;
        paintHeat(true);
      },
      onClick: (info) => { if (!info.object) inspectHeat(info.x, info.y); },
    });
    const goTo = (v) => d.setProps({ initialViewState: { ...view, ...v, transitionDuration: 300, transitionInterpolator: new deck.FlyToInterpolator() } });
    const attribution = el("div", { class: "muted", style: "position:absolute;right:6px;bottom:4px;z-index:4;font-size:11px;background:var(--surface);padding:0 6px;border-radius:4px" },
      "© OpenStreetMap contributors");
    $("#map").append(attribution);
    let baseLayer = base();
    // a white veil over the grey tiles: near-white background, place names still readable, data stays punchy
    const veil = new deck.SolidPolygonLayer({ id: "veil", data: [{ p: [[-180, -85], [180, -85], [180, 85], [-180, 85]] }],
      getPolygon: (d) => d.p, getFillColor: [255, 255, 255, Math.round(255 * STYLE.veil)], pickable: false });
    return {
      name: "tiles",
      render() { syncView(); d.setProps({ layers: [baseLayer, veil, ...layers()] }); },
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

  async function googleFailed() {
    if (engine?.name !== "google") return;
    engine.destroy(); engine = null; note(t("keyFailed"));
    try { engine = await vectorEngine(); } catch (e) { console.warn(e); fill($("#map")); engine = tileEngine(); }
    engine.render(); fitArea(); refresh().catch(console.warn);
  }

  async function initMap() {
    const key = state.meta.google_maps_api_key;
    if (key) {
      try { engine = await googleEngine(key, state.meta.google_maps_map_id); return; } catch (e) { console.warn(e); note(t("keyFailed")); }
    }
    if (STYLE.base === "vector") {
      try { engine = await vectorEngine(); return; } catch (e) { console.warn("vector basemap unavailable, using tiles", e); fill($("#map")); }
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
    if (state.division) p.set("division", state.division);
    if (state.district) p.set("district", state.district);
    if (state.thana) p.set("thana", state.thana);
    if (state.version?.data_version) p.set("v", state.version.data_version);    // never reuse a cached old answer
    return p.toString();
  }

  // Map view for the current selection: a district, a division, or the whole country
  function areaBounds() {
    const d = state.meta.districts.find((x) => x.id === state.district);
    const dv = state.meta.divisions.find((x) => x.id === state.division);
    const b = d ? d.bounds : dv ? dv.bounds : state.meta.all_bounds;
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
  // Never throws: a failed request keeps the last data on screen and says so (the next tick retries)
  async function refresh(opts = {}) {
    try { return await refreshData(opts); } catch (e) {
      console.warn("refresh failed", e); state.offline = true; renderStatus(); return false;
    }
  }
  async function refreshData(opts) {
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
    if (state.area) areaCard();                        // a live update keeps the chosen area, with fresh counts
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
    const mapped = state.meta.categories.filter((c) => c.visibility === "mapped" && c.color);
    HeatPaint.configure(mapped.map((c) => ({ key: c.key, color: c.color })));
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
    fill($("#division"), el("option", { value: "" }, t("allDivisions")),
      ...state.meta.divisions.map((d) => el("option", { value: d.id }, label(d))));
    $("#division").value = state.division;
    renderDistrictSelect();
    renderStatus();
  }

  const label = (x) => (state.lang === "bn" ? x.bn : x.en);
  // District drill-down inside the selected division (alphabetical in the page's language)
  function renderDistrictSelect() {
    const sel = $("#district");
    sel.hidden = !state.division;
    if (!state.division) { fill(sel); return; }
    const byName = (a, b) => label(a).localeCompare(label(b), state.lang === "bn" ? "bn" : "en");
    fill(sel, el("option", { value: "" }, t("allDistricts")),
      ...state.meta.districts.filter((d) => d.division === state.division).sort(byName)
        .map((d) => el("option", { value: d.id }, label(d))));
    sel.value = state.district;
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
    const top = state.district ? s.by_thana[0] : (state.division ? s.by_district : s.by_division)[0];
    const topThana = top && { name_bn: top.name_bn || top.bn, name_en: top.name_en || top.en };
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
    if (!state.district) {   // whole country: rank the divisions; one division: rank its districts
      const ds = (state.division ? state.stats.by_district : state.stats.by_division || []).slice(0, 10);
      const mx = Math.max(1, ...ds.map((r) => r.count));
      fill($("#rank"), ...(ds.length ? ds.map((r, i) => el("li", {}, el("button", {
        type: "button", onclick: () => (state.division ? selectDistrict(r.id) : selectDivision(r.id)),
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
      onclick: () => { state.thana = state.thana === r.id ? "" : r.id; if (!state.thana) { refresh(); fitArea(); return; }
                       refresh({ fit: true, fallback: r.lat ? { lat: r.lat, lng: r.lng, zoom: 13 } : null }); },
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

  /* Tapped area: the reports whose point lies inside the circle that feeds the glow at the tap (same radius as the
     painter's kernel), kept in metres so it survives panning, zooming and live data updates. */
  function areaIncidents() {
    const a = state.area; if (!a) return state.incidents;
    if (a.district) return state.incidents.filter((i) => i.district_id === a.district);
    const r = Math.PI / 180, k = Math.cos(a.lat * r) * 6371000 * r, m2 = a.m * a.m;
    return state.incidents.filter((i) => i.lat != null
      && ((i.lng - a.lng) * k) ** 2 + ((i.lat - a.lat) * 6371000 * r) ** 2 <= m2);
  }
  function setArea(area) { state.area = area; if (!area) state.mix = null; renderFeed(); engine?.render(); }
  // Name of the selected area in the current language (derived at render, so a language switch updates it)
  function areaPlace(a) {
    if (!a) return "";
    if (a.district) { const m = districtMeta(a.district); return m ? label(m) : ""; }
    return placeAt(a.lng, a.lat, a.zoom) || t("thisArea");
  }
  // The card for the selected area: exact counts per type of the same reports the Reports list shows
  function areaCard() {
    const here = areaIncidents(), cats = {};
    for (const i of here) cats[i.category] = (cats[i.category] || 0) + 1;
    state.mix = CAT_ORDER.filter((k) => cats[k]).map((k) => [k, cats[k] / Math.max(1, here.length)])
      .sort((a, b) => b[1] - a[1]);
    state.mixAt = { n: here.length, cats, district: Boolean(state.area?.district) };
    return here.length;
  }

  function renderAreaChip(n) {
    const box = $("#feed-area"); if (!box) return;
    if (!state.area) { box.hidden = true; fill(box); return; }
    fill(box, el("span", { class: "area-pin", "aria-hidden": "true" }), el("span", { class: "area-txt" },
      t("areaReports", { place: areaPlace(state.area), n })));
    box.hidden = false;
  }

  function renderFeed() {
    const all = areaIncidents(), list = all.slice(0, 400);
    renderAreaChip(all.length);
    const hiddenTypes = CAT_ORDER.filter((k) => state.cats.has(k) && (state.meta?.area_totals_only || []).includes(k)
                                         && state.stats?.by_category?.[k]);
    const totalsNote = hiddenTypes.length ? el("li", { class: "empty totals-only" },
      ...hiddenTypes.map((k) => el("p", {}, t("totalsOnlyFeed", { cat: catLabel(k), n: state.stats.by_category[k] }))),
      // per-district numbers are totals too (same as the hotspot list); no places below district level
      list.length ? null : el("p", { class: "muted" }, t("byDistrict"), " ",
        (state.stats.by_district || []).slice(0, 12).map((d) => `${label(d)} ${num(d.count)}`).join(" · "))) : null;
    $("#feed-count").textContent = list.length < all.length ? t("showing", { n: list.length, total: all.length }) : num(all.length);
    fill($("#feed"), ...(list.length ? list.map((i) => el("li", {}, el("button", {
      type: "button", class: `item${state.selected?.id === i.id ? " on" : ""}`, onclick: () => select(i, true),
    },
      el("span", { class: "tag" }, el("span", { class: "dot", style: `background:${cssColor(i.category)}` }), catLabel(i.category)),
      el("h3", {}, summary(i)),
      el("div", { class: "meta" }, el("span", {}, placeName(i)), el("span", {}, fmtDate(i.event_date)),
        i.time_of_day !== "unknown" ? el("span", {}, todLabel(i.time_of_day)) : null, precisionBadge(i.precision))))) : [totalsNote || el("li", { class: "empty" }, t("noData"))]),
      ...(list.length && totalsNote ? [totalsNote] : []));
  }

  // Legend: colour key, one short hint; the longer explanation folds away so the map stays visible
  function renderLegend() {
    const s = state.stats;
    if (!s) return;                                         // a mode click before the first data arrives
    const mapped = CAT_ORDER.filter((k) => state.cats.has(k) && !(state.meta?.area_totals_only || []).includes(k));
    const totalsOnly = CAT_ORDER.filter((k) => state.cats.has(k) && (state.meta?.area_totals_only || []).includes(k));
    const more = el("details", { class: "more" }, el("summary", {}, t("howToRead")),
      el("div", { class: "muted" }, state.mode === "points" ? t("pointsNote") : t("blendNote")),
      !mapped.length && totalsOnly.length ? el("div", { class: "muted" }, t("totalsOnlyNote")) : null,
      s.unlocated ? el("div", { class: "muted" }, t("unlocated", { n: s.unlocated })) : null,
      el("div", { class: "muted", style: "font-size:11px" }, t("sourceNote")));
    if (state.legendOpen) more.open = true;
    more.addEventListener("toggle", () => { state.legendOpen = more.open; });
    fill($("#legend"),
      el("div", { class: "cats" }, ...mapped.map((k) => el("span", {}, el("i", { style: `background:${HeatPaint.swatch(k)}` }), catLabel(k)))),
      el("div", { class: "hint" }, t(overview() ? "districtHint" : "heatHint")),
      more);
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
    const at = state.mixAt;
    fill(card,
      el("button", { class: "close", type: "button", "aria-label": "Close", onclick: () => { state.mix = null; setArea(null); renderSelected(); } }, "×"),
      el("h3", {}, state.area ? areaPlace(state.area) : t("thisArea")),
      at && at.n ? el("div", { style: "font-size:13px;margin-bottom:2px" },
        at.district ? t("districtReports", { place: areaPlace(state.area), n: at.n }) : t("areaCount", { n: at.n })) : null,
      el("ul", { class: "mix" }, ...rows.map(([k, v]) => el("li", {},
        el("span", { class: "name" }, el("span", { class: "dot", style: `background:${HeatPaint.swatch(k)}` }), catLabel(k)),
        el("span", { class: "bar" }, el("i", { style: `width:${v * 100}%;background:${HeatPaint.swatch(k)}` })),
        el("span", { class: "cnt" }, at && at.cats ? num(at.cats[k]) : `${num(Math.round(v * 100))}%`)))),
      state.area && at && at.n ? el("button", { type: "button", class: "link area-open", onclick: () => setTab("feed") },
        t("showAreaReports", { n: at.n })) : null);
    card.hidden = false;
  }

  /* ---------- multi-colour heat (HeatPaint on its own canvas over the map) ---------- */
  let paintReq = null, paintRaf = 0, settleTimer = 0;
  function paintHeat(moving) {
    if (!engine?.view) return;
    if (state.mode === "points") {
      cancelAnimationFrame(paintRaf); paintRaf = 0; paintReq = null; clearTimeout(settleTimer);
      HeatPaint.clear(); if (state.heat) { state.heat = null; engine.setHeat?.(null); engine.render(); }
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
    if (!image) { state.heat = null; engine.setHeat?.(null); engine.render(); return; }
    // the image covers whole grid cells, so its bottom-right corner can sit slightly past the view
    const [west, north] = v.unproject(0, 0), [east, south] = v.unproject(image.width, image.height);
    state.heat = { image, bounds: [west, south, east, north] };
    if (engine.drawsHeat) engine.setHeat(image, state.heat.bounds); else engine.render();
  }
  // District of the nearest thana/upazila (within 25 km); districts have no outlines here
  function districtAt(lng, lat) {
    const k = Math.cos(lat * Math.PI / 180);
    let best = null, bd = Infinity;
    for (const p of state.meta.thanas) {
      if (p.lat == null) continue;
      const d = ((p.lng - lng) * k) ** 2 + (p.lat - lat) ** 2;
      if (d < bd) { bd = d; best = p; }
    }
    return best && Math.sqrt(bd) * 111 <= 25 ? best.district : null;
  }

  // Name for a spot: nearest thana/upazila (with its district) when zoomed in, the district when zoomed out
  function placeAt(lng, lat, zoom) {
    const km = (a, b) => { const r = Math.PI / 180, x = (b.lng - a.lng) * r * Math.cos(((a.lat + b.lat) / 2) * r), y = (b.lat - a.lat) * r;
                           return 6371 * Math.hypot(x, y); };
    const here = { lng, lat };
    const dname = (id) => { const d = state.meta.districts.find((x) => x.id === id); return d ? (state.lang === "bn" ? d.bn : d.en) : ""; };
    const near = state.meta.thanas.filter((p) => p.lat != null).map((p) => [km(here, p), p]).sort((a, b) => a[0] - b[0])[0];
    if (!near || near[0] > 25) return "";
    if (zoom < 9) return dname(near[1].district);
    const name = state.lang === "bn" ? near[1].name_bn : near[1].name_en;
    return `${name}, ${dname(near[1].district)}`;
  }


  // Tap on the map (not on a point): the local mix of the glow (heat views) and the reports of that area in the feed
  function inspectHeat(x, y) {
    if (!engine?.view) return;
    const v = engine.view(); if (!v) return;
    const [lng, lat] = v.unproject(x, y);
    if (overview()) {                                       // country/division view: the district under the finger
      const d = districtAt(lng, lat);
      state.selected = null; state.area = d ? { district: d } : null;
      if (!state.area || !areaCard()) { state.area = null; state.mix = null; }
      renderSelected(); renderFeed(); engine?.render();
      return;
    }
    // the circle that feeds the glow here (kernel radius), in metres; points view: a finger-sized circle
    const px = state.mode === "points" ? 28 : HeatPaint.radius(v.zoom);
    const mPerPx = 156543.03392 * Math.cos(lat * Math.PI / 180) / 2 ** v.zoom;
    state.selected = null; state.area = { lng, lat, m: px * mPerPx, zoom: v.zoom };
    // the card and the Reports list show the same reports: exact counts per type inside the ring
    if (!areaCard()) { state.area = null; state.mix = null; }   // nothing reported here: back to the full list
    renderSelected(); renderFeed(); engine?.render();
  }

  function setTab(tab) {
    // medium screens (761-1100 px) have no tabs: the Reports list opens as a drawer over the map
    if (tab === "feed" && matchMedia("(min-width: 761px) and (max-width: 1100px)").matches) {
      document.body.classList.add("feed-open"); return;
    }
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
    $("#feed-close").addEventListener("click", () => document.body.classList.remove("feed-open"));
    $("#division").addEventListener("change", (e) => selectDivision(e.target.value));
    $("#district").addEventListener("change", (e) => selectDistrict(e.target.value));
    document.querySelectorAll("#mode button").forEach((b) => b.addEventListener("click", () => {
      state.mode = b.dataset.mode; document.querySelectorAll("#mode button").forEach((x) => x.classList.toggle("on", x === b));
      renderLegend(); engine?.render(); paintHeat();
    }));
    window.addEventListener("resize", () => paintHeat());
    $("#zoom-in").addEventListener("click", () => engine?.zoomBy(1));
    $("#zoom-out").addEventListener("click", () => engine?.zoomBy(-1));
    $("#zoom-reset").addEventListener("click", () => engine?.reset());
    $("#lang-btn").addEventListener("click", () => { state.lang = state.lang === "bn" ? "en" : "bn"; store.set("dcm.lang", state.lang); $("#tooltip").hidden = true; applyI18n(); engine?.setLang?.(state.lang); renderAll(); });
    document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  }

  function selectDivision(id) {
    state.division = id || ""; state.district = ""; state.thana = ""; state.area = null; state.mix = null;
    $("#division").value = state.division; renderDistrictSelect();
    refresh(); fitArea();
  }
  function selectDistrict(id) {
    const d = state.meta.districts.find((x) => x.id === id);
    if (d && d.division !== state.division) { state.division = d.division; $("#division").value = d.division; }
    state.district = id || ""; state.thana = ""; state.area = null; state.mix = null;
    renderDistrictSelect();
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
