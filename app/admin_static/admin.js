/* Admin dashboard: status, collection, coverage, runs, try-an-article. Uses the login session; changes send its CSRF token. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const when = (s) => (s ? new Date(s).toLocaleString("en-GB", { timeZone: "Asia/Dhaka", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—");
  let csrf = "";

  async function api(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, ...(opts.headers || {}) } });
    if (r.status === 401) { location.href = "/login"; throw new Error("login required"); }
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `HTTP ${r.status}`);
    return body;
  }

  async function status() {
    const m = await api("/api/meta");
    const b = (m.batches || []).map((x) => `${x.trigger} #${x.id}: fetched ${x.fetched ?? "?"}/${x.discovered ?? "?"}, Gemma ${x.processed}/${x.jobs}, failed ${x.failed}`).join("<br>") || "none";
    const svc = Object.entries(m.services || {}).map(([k, v]) => `${k} ${v.alive ? "✓" : "✗"}`).join(" · ");
    $("#status").innerHTML = [
      ["Model", esc(m.model_label || m.model)], ["Publishing", esc(m.publish_mode)], ["Schedule", esc((m.schedule || []).join(", "))],
      ["Next run", when(m.next_run)], ["Last run", m.last_run ? `${when(m.last_run.finished_at || m.last_run.started_at)} — ${esc(m.last_run.status)}: ${esc(m.last_run.message || "")}` : "—"],
      ["Active work", b], ["Queue", esc(JSON.stringify(m.queue))], ["Exact spots waiting", m.exact_spots_waiting], ["Incidents", m.incident_count],
      ["Model calls today", m.model_calls_today], ["Services", svc],
    ].map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  }

  async function coverage() {
    const c = await api(`/api/coverage?days=${$("#cov-days").value}`);
    const s = c.summary;
    $("#cov-summary").innerHTML = `${s.complete} complete · ${s.processing} processing · ${s.partial} partial · ${s.failed} failed · ${s.not_collected} not collected` +
      (c.days_to_collect ? ` <button class="btn" id="fill" type="button">Collect missing days (${Math.min(90, c.days_to_collect)} back)</button>` : "");
    if (c.days_to_collect) $("#fill").onclick = () => collect(Math.min(90, c.days_to_collect), 5000);
    $("#coverage").innerHTML = "<tr><th>Date</th><th>Status</th><th>Listed</th><th>Candidates</th><th>Missing</th><th>Set aside</th><th>Gemma pending</th><th>Failed</th></tr>" +
      c.days.slice().reverse().map((d) => `<tr><td>${d.date}${d.is_today ? " (today)" : ""}</td><td class="st-${d.status}">${d.status}</td><td>${d.links ?? "—"}</td><td>${d.candidates}</td><td>${d.missing}</td><td>${d.set_aside}</td><td>${d.gemma_pending}</td><td>${d.failed}</td></tr>`).join("");
  }

  async function runs() {
    const rs = await api("/api/runs?limit=15");
    $("#runs").innerHTML = "<tr><th>#</th><th>Trigger</th><th>Started</th><th>Status</th><th>Fetched</th><th>Queued</th><th>Errors</th><th>Message</th></tr>" +
      rs.map((r) => `<tr><td>${r.id}</td><td>${esc(r.trigger)}</td><td>${when(r.started_at)}</td><td>${esc(r.status)}</td><td>${r.fetched}/${r.discovered}</td><td>${r.queued}</td><td>${r.errors}</td><td>${esc(r.message || "")}</td></tr>`).join("");
  }

  async function collect(days, max) {
    const q = new URLSearchParams({ days_back: days });
    if (max) q.set("max_articles", max);
    try {
      const r = await api(`/api/scrape?${q}`, { method: "POST" });
      $("#collect-msg").textContent = `Queued request #${r.request_id}; the collector starts within ~20 s.`;
    } catch (e) { $("#collect-msg").textContent = e.message; }
    refresh();
  }

  async function tryArticle() {
    const out = $("#t-out"); out.hidden = false; out.textContent = "Asking Gemma…";
    const body = { title: $("#t-title").value, body: $("#t-body").value };
    if ($("#t-date").value) body.published_at = new Date($("#t-date").value).toISOString();
    try { out.textContent = JSON.stringify(await api("/api/classify?wait=120", { method: "POST", body: JSON.stringify(body) }), null, 1); }
    catch (e) { out.textContent = e.message; }
  }

  async function eventsCard() {
    const s = await api("/api/events/status");
    $("#ev-status").textContent = `${s.events} events (${s.events_with_several_reports} with several papers) · queue ${s.queue}` +
      ` (${s.retried} retried) · public map ${s.live ? "uses events" : "not switched yet (matching the history)"} · ` +
      Object.entries(s.decisions).map(([k, v]) => `${k} ${v}`).join(", ");
    const rows = await api(`/api/events/decisions?outcome=${$("#ev-outcome").value}&limit=60`);
    const facts = (d) => ((d.evidence && d.evidence.facts) || []).map((f) => `${esc(f.kind)}: ${esc(f.quote_a)} ⟷ ${esc(f.quote_b)}`).join("<br>");
    $("#ev-list").innerHTML = "<tr><th>Event</th><th>Report</th><th>Matched with</th><th>Proof (quotes from both)</th><th>When</th><th></th></tr>" +
      rows.map((d) => `<tr><td>${d.event_id ?? "—"}</td>` +
        `<td><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.source)}: ${esc(d.title)}</a></td>` +
        `<td>${d.cand_url ? `<a href="${esc(d.cand_url)}" target="_blank" rel="noopener">${esc(d.cand_source)}: ${esc(d.cand_title)}</a>` : "—"}</td>` +
        `<td style="font-size:12px">${facts(d) || (d.score != null ? `similarity ${d.score.toFixed(2)}` : "")}</td><td>${when(d.created_at)}</td>` +
        `<td>${d.outcome === "linked" ? `<button class="btn ghost" data-split="${esc(d.report_key)}" type="button">Split</button>` : ""}</td></tr>`).join("");
    document.querySelectorAll("[data-split]").forEach((b) => b.onclick = async () => {
      try { const r = await api("/api/events/split", { method: "POST", body: JSON.stringify({ report_key: b.dataset.split }) });
        $("#ev-msg").textContent = `Split into event #${r.new_event}.`; } catch (e) { $("#ev-msg").textContent = e.message; }
      eventsCard().catch(console.warn);
    });
  }

  function refresh() { status().catch(console.warn); coverage().catch(console.warn); runs().catch(console.warn); eventsCard().catch(console.warn); }

  $("#collect").onclick = () => collect(+$("#days").value || 0, +$("#max").value || null);
  $("#cov-days").onchange = () => coverage().catch(console.warn);
  $("#ev-outcome").onchange = () => eventsCard().catch(console.warn);
  $("#ev-merge").onclick = async () => {
    try { await api("/api/events/merge", { method: "POST", body: JSON.stringify({ keep: +$("#ev-keep").value, other: +$("#ev-other").value }) });
      $("#ev-msg").textContent = "Merged."; } catch (e) { $("#ev-msg").textContent = e.message; }
    eventsCard().catch(console.warn);
  };
  $("#try").onclick = tryArticle;
  $("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); location.href = "/login"; };

  api("/api/session").then((s) => { csrf = s.csrf || ""; $("#who").textContent = s.user; refresh(); setInterval(refresh, 15000); });
})();
