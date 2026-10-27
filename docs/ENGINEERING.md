# Dhaka Crime Map — Engineering Handbook

26 Oct 2026 · repo `github.com/zawadgenweb2/dhaka-crime-map` · for engineers and coding agents

## 0. In five lines

- Scrapes Bangla news (Prothom Alo today), keeps likely crime stories, and has a **local LLM** (Gemma 4 E2B on the in-house GPU) extract incidents: category, exact place, date, time, evidence quote.
- Places resolve against a curated **gazetteer** (163 Dhaka places); exact spots are geocoded later via OpenStreetMap; duplicates across articles are grouped.
- **Live and Gemma-only**: incidents that pass the automatic checks are published at once (`PUBLISH_MODE=auto`); the API serves only rows from a Gemma analysis. `/review` is an optional correction tool.
- Five Docker services + one systemd model server on `genweb2inhouse`; **Postgres is the data store, job queue and lock service**.
- **No external AI APIs**: the only model is the in-house Gemma server. Dhaka is always collected; other districts are planned on demand.

## 1. Architecture

```
 prothomalo.com ◄─ collector ──► Postgres 17 ◄── api (FastAPI, HTTPS :8100) ◄── browsers (LAN)
  (1 req/s)         │  scheduler      ▲  queue/locks        dashboard · /review · /docs
                    ▼                 │
              jobs table ──► classifier (host network) ──► llama-server (systemd, GPU, 127.0.0.1:8090)
                                      └──► OSM Nominatim (≤ 4 req/min, shared lane)
```

| Component | Runs as | Address | Owns |
|---|---|---|---|
| `db` | Docker `postgres:17-alpine`, volume `dhaka-crime-map_pgdata` | 127.0.0.1:55432 | all state, queue, advisory locks (the only copy of the data) |
| `migrate` | Docker, one-shot | – | schema migrations, then exits |
| `api` | Docker | 192.168.1.200:8100 (HTTPS, self-signed) | read API, review API, "collect now" requests, static UI |
| `collector` | Docker, singleton | – | schedule slots, scraping, article + job rows |
| `classifier` | Docker, host network | – | job claims, model calls, analyses, incidents; a second thread geocodes exact spots |
| `dhaka-llm` | systemd `--user` | 127.0.0.1:8090 + API key | llama.cpp b11669 (CUDA 12.2 build), Gemma 4 E2B Q8 |

Host `genweb2inhouse` (192.168.1.200): Ubuntu 20.04, RTX 3080 Ti 12 GB, NVIDIA driver 575.57 (CUDA 12.9). Code: `/home/genslr/dhaka-crime-map`.
All data lives on this server; backups: `~/dhaka-backups/` (nightly 02:30, 14 days, `dhaka-backup.timer`). Laptops hold code only.
One image (`Dockerfile`) for every service; the command picks the role (`python -m app api|collector|classifier|migrate`).

## 2. Pipeline

| # | Step | Where | Output | On failure |
|---|---|---|---|---|
| 1 | Schedule 08:00/20:00 Dhaka (+ "collect now") | `collector.py`, `scheduler.py` | `schedule_slots`, `run_requests` | slot retried 3× / 10 min |
| 2 | Discover: news sitemap (48 h, titles+keywords) + daily sitemaps | `scraper.py` | candidate URLs (new only) | robots 5xx/unreachable → crawl nothing |
| 3 | URL pre-filter (no download): crime/capital sections; else crime term + Dhaka mention | `scraper.is_candidate` | ≈10 of 260/day | misses are not measured yet |
| 4 | Fetch (8 MB cap, per-hop robots+host check) + full-text check | `scraper.py`, `collector.py` | `articles` (`queued`/`skipped`) + `jobs` | fetch errors counted, run continues |
| 5 | Classify: one call per article, JSON schema, compact prompt; place ids outside the article's shortlist → null | `worker.py`, `classifiers/gemma.py`, `classifiers/base.py`, `schema.py` | `llm_calls`, `analyses` | 2 dispatches max; then `failed` |
| 6 | Validate + locate on the gazetteer place: dates, evidence quote, fallback phrase must be in the article | `store.py`, `gazetteer.py` | `incidents` (`auto` published / `failed` hidden) | failed checks are never shown |
| 7 | Group duplicates (fallback until the event store is live): same category + place, dates ±1, compatible time, corroborated | `store.rebuild_groups` | `incidents.duplicate_of` | rule-based |
| 7b | **Event store** (one row per real crime across papers): filter → EmbeddingGemma 2 rank → Gemma judge (≥2 quote-proven shared facts, both orders) → link / new event; reports matching two events trigger a direct check of the two main reports | `events.py`, `deploy/inhouse-llm/dhaka-embed.service` | `events`, `event_reports`, `match_decisions` (append-only), `event_exclusions`, `match_queue` | errors never merge: the report shows on its own, retried later |
| 8 | Exact spot (later): Nominatim, kept only ≤2.5 km from the place | `store.enrich_next`, `geocode.py` | `geocode_state` `todo`→`done`/`miss`/`far` | network error: retried later |
| 9 | Serve + map: published Gemma canonical incidents; live refresh on `data_revision` | `api.py`, `static/app.js` | heat + points + feed + progress | – |
| – | Optional corrections: fix category/place, reject, retry, dismiss (hides the article) | `api.py`, `static/review.html` | `review_status` | – |

## 3. Data model (Postgres, `migrations/00*.sql`)

| Table | Purpose | Key states |
|---|---|---|
| `articles` | one row per URL (body kept for re-analysis); `analysis_version` = the only version allowed to write incidents | `queued` · `skipped` · `classified` · `failed` · `uncertain` · `dismissed` |
| `jobs` | work queue, one per article + analysis version; `run_id` = batch | `queued` · `running`(lease) · `done` · `failed` · `uncertain` · `cancelled` · `superseded` |
| `llm_calls` | every model dispatch, written **before** sending | `sent` · `ok` · `error` |
| `analyses` | the model's full JSON answer + tokens/cost | `materialized_at` |
| `incidents` | map rows | `review_status`: `auto` · `failed` · `approved` · `rejected` (`pending` only in review mode); `published`; `duplicate_of`; `geocode_state` |
| `data_revision` | one counter, bumped with every visible change | the dashboard reloads when it moves |
| `eval_reference_articles`, `eval_reference_incidents` | frozen prototype-phase labels (71 articles, 58 incidents) for offline evaluation only | never served |
| `runs`, `schedule_slots`, `run_requests` | collection history, one row per slot, manual triggers | slot: `pending` · `running` · `done` · `failed` · `skipped` |
| `geocache`, `rate_limits` | Nominatim cache and the shared request lane | – |
| `heartbeats` | service liveness for `/api/meta` | – |
| `article_reviews`, `eval_results` | reviewer verdicts, offline model evaluations | – |

## 4. Invariants (do not break)

1. **One collector.** It holds Postgres advisory lock `7000003`; a second one waits.
2. **Claim before work.** Jobs are claimed with `FOR UPDATE SKIP LOCKED` + lease; every write checks the job `generation`.
3. **Record before calling, save before using.** `llm_calls` row before the request; `analyses` row before incidents, so a later failure never needs a second model call. A worker that dies mid-call has its job requeued when the lease expires.
4. **No network inside a DB transaction.** One short transaction replaces an article's incidents (lock `7000002`) only if the job's `analysis_version` is the article's current one; geocoding happens afterwards with conditional updates.
5. **Served = published Gemma output.** Every read path uses `db.GEMMA_PROVENANCE` (a non-legacy `gemma` analysis of the same article) plus `published`; Claude-era, imported and rules output can never be served. Every visible change calls `db.bump_revision()` in its transaction.
6. **Politeness.** robots.txt per RFC 9309 (`RobotsPolicy`), 1 req/s per publisher, Nominatim ≤ 4/min via `rate_limits`.
7. **Secrets stay out of git and images.** `.env` (0600), `deploy/tls/`, model key file; `.dockerignore` allow-lists sources only.
8. **Schema changes are new migrations**, never edits to applied ones. Saved analyses are re-read with today's schema: version breaking changes.

## 5. Code map

| Path | Responsibility |
|---|---|
| `app/__main__.py` | CLI: services + `collect-now [--days N --max M]`, `reprocess-all --yes`, `stats`, `compare`, `rebuild-duplicates` |
| `app/reprocess.py` | re-run every collected article through Gemma (after a prompt change) |
| `app/config.py` | every setting (env) with defaults |
| `app/db.py` | connections, transactions, migrations, heartbeats |
| `app/scraper.py` | Prothom Alo client, sitemaps, pre-filter, article parse, robots |
| `app/collector.py` | collector service and `collect()` |
| `app/worker.py` | classifier service: claim → call → save → materialize → recover |
| `app/store.py` | locate, date/evidence checks, publish status, duplicate grouping, exact-spot enrichment |
| `app/classifiers/` | `base.py` prompts (full + compact), `gemma.py` in-house model client, `rules.py` offline baseline |
| `app/gazetteer.py`, `data/dhaka_places.json` | Bangla place matching (suffixes, namesake guard) |
| `app/api.py`, `app/static/` | REST + Swagger (incl. `POST /api/classify`: try a pasted article, nothing saved), dashboard, review page |
| `app/evaluate.py`, `scripts/eval_table.py` | offline model evaluation vs the frozen 71-article reference set |
| `deploy/inhouse-llm/` | llama.cpp build, model download, start scripts, systemd units, vLLM setup |
| `compose.yaml`, `compose.inhouse.yaml` | services; server overrides (HTTPS, loopback DB, host-network classifier) |

## 6. Configuration (`.env`, see `.env.example`)

`POSTGRES_PASSWORD` · `ADMIN_TOKEN` (review + token-triggered runs) · `API_BIND` (server LAN IP) · `CLASSIFIER` (`gemma`|`rules`) ·
`GEMMA_API_KEY`, `GEMMA_BASE_URL`, `GEMMA_MODEL`, `GEMMA_PROMPT` (`compact`|`full`) · `MODEL_LABEL` · `PUBLISH_MODE` (`auto` default | `review`) ·
`SCRAPE_TIMES` · `USER_AGENT` · `MAX_ARTICLES_PER_RUN` · `GEOCODE_*` ·
`ALLOW_UI_TRIGGER` · `GOOGLE_MAPS_API_KEY` (browser key; empty = OpenStreetMap tiles).

## 7. Runbook

```bash
ssh genweb2inhouse && cd ~/dhaka-crime-map
C="docker compose -f compose.yaml -f compose.inhouse.yaml"
git pull && $C up -d --build            # deploy (migrations run automatically)
$C ps ; $C logs -f collector classifier # health and logs
$C exec classifier python -m app collect-now      # scrape now
$C run --rm migrate collect-now --days 90 --max 3000   # backfill 90 days (progress shows on the dashboard)
$C stop classifier && $C run --rm migrate reprocess-all --yes && $C up -d   # re-run all articles after a prompt change
$C exec classifier python -m app stats
$C exec db psql -U dcm -d dcm           # SQL shell
systemctl --user status|restart dhaka-llm ; journalctl --user -u dhaka-llm -f   # model server
$C --profile test build test && $C --profile test run --rm test   # 66 tests, separate dcm_test database
deploy/backup-db.sh                     # backup now; restore: pg_restore -U dcm -d dcm --clean <file>
```

| Symptom | Check | Fix |
|---|---|---|
| Run `failed: robots.txt disallows …` | publisher reachable? | transient: slot retries; persistent: network or publisher block |
| Jobs stay `queued` | `curl -s 127.0.0.1:8090/health`; classifier logs | `systemctl --user restart dhaka-llm` |
| Classifier log "pausing 10 min" | 401/404 from model server | key in `.env` vs `~/.config/dhaka-llm/api-key`; model alias `dhaka-gemma` |
| Map not updating | `/api/meta` `data_version`, `batches`, classifier logs | open pages poll every 5 s while work runs, 30 s otherwise |
| Browser "Not secure" | self-signed LAN cert | Tailscale HTTPS (needs tailnet admin) or a domain + Let's Encrypt |
| GPU errors after kernel update | `nvidia-smi`, `dkms status` | DKMS must rebuild driver 575 for the new kernel |

## 8. Adding features (recipes)

- **New model:** download a GGUF into `~/.local/share/dhaka-llm`, set `DHAKA_LLM_MODEL` via `systemctl --user edit dhaka-llm`, restart, then
  `$C exec classifier python -m app compare --with gemma --limit 71 --out /tmp/r.json`; compare with the table in §9, then `reprocess-all`.
- **New newspaper (planned design):** source registry + per-source config (sitemaps, article URL pattern, crime/capital sections, body selector);
  probe robots, bot challenges and extraction before enabling. Samakal fits (same sitemap format, body in `#contentDetails`);
  Bangladesh Pratidin returns a Cloudflare challenge (needs publisher allowlisting).
- **Other districts (planned):** national gazetteer from `data/sources/wikidata-bd-admin-*.json` (CC0); ambiguity-aware matching;
  coverage table + token-protected activation + resumable 30-day backfill; schema v2 replaces `in_dhaka`.
- **New category:** `schema.py` (enum + labels), prompt rules in `classifiers/base.py`, colours in `static/styles.css`/`app.js`; re-evaluate.
- **Schema change:** add `migrations/00N_*.sql`; never edit applied ones; add a service test in `tests/test_services.py`.
- **API endpoint:** in `create_app()`; work-triggering or private endpoints use `Security(ADMIN_KEY)`; add a test; check `/docs`.

## 9. Tests and evaluation

Tests: 66 (pure + the separate `dcm_test` database, never `dcm`). Evaluation reference: 71 articles labelled during the prototype phase, frozen in
`eval_reference_*` (a strong baseline, not ground truth). E2B, compact prompt + calendar: JSON 100%, article P/R 0.86/0.88, incident P/R 0.76/0.71,
category 0.78, thana 0.93, date 0.53, 2.4 s/article. The gates in `evaluate.GATES` are a yardstick, not a publishing switch.

Model/engine benchmark, 26 Oct (71 articles, same prompt, RTX 3080 Ti; `GEMMA_STREAM=1 ... compare` measures speed; ±0.03 run-to-run):

| Setup | Incident P / R | Article P / R | Time/article p50 | Prefill | Decode | GPU mem |
|---|---|---|---|---|---|---|
| **E2B Q8, llama.cpp (live)** | 0.80–0.83 / 0.64–0.66 | 0.87–0.90 / 0.81 | 2.4 s | ~4,400 tok/s | ~120 tok/s | 2.9 GB |
| E4B QAT Q4_0, llama.cpp | 0.71 / 0.69 | 0.78 / 0.83 | 2.8 s | ~3,100 tok/s | ~113 tok/s | 3.5 GB |
| E4B QAT w4a16, vLLM 0.32 | stopped (see below) | | ~13 s (long pretty JSON) | | ~120 tok/s | 11.7 of 12 GB |

vLLM lessons on 12 GB (kept in `deploy/inhouse-llm/start-vllm.sh`, not in use): the w4a16 checkpoints keep the per-layer
embeddings in bf16 (E4B 11.5 GB, E2B 8.35 GB on disk; E4B uses 10.1 GB loaded); torch.compile autotuning runs out of memory,
eager mode decodes at ~15 tok/s, decode-only CUDA graphs (`-cc mode 0, FULL_DECODE_ONLY`) restore ~120 tok/s; xgrammar's
unbounded whitespace makes the model loop on newlines and its no-whitespace mode breaks answers (recall 0.02), so use the
`guidance` backend with `GEMMA_JSON_WHITESPACE=bounded`. Decision: stay on llama.cpp E2B.

## 9b. The event store and how it is verified (28 Oct)

**Flow.** `store.materialize` gives every report a stable `report_key` (article + quote + type) and queues it. The
worker, when idle, runs `events.run_queue_item`: block candidate events (district, compatible type, same place or
thana, dates ±3, not the same article, not excluded by an admin split) → rank by EmbeddingGemma 2 cosine against each
event's main report (top 3 ≥ 0.80) → `events.judge`: Gemma must answer "same" with ≥ 2 distinctive shared facts whose
quotes are verbatim in BOTH articles, and again with the reports swapped. Police round-ups match only the same arrest
count (rule). One passing event → link; two → the two main reports are judged directly and merged if same, else
the report stays apart; none → new event. The event's main report = its earliest-published one. The public map,
feed and stats switch to one row per event automatically once the full history has been matched (`app_flags`).

**Verification, layer by layer.**
1. Unit/service tests (`tests/test_services.py`): same crime → one event shown once; "different", missing proof or
   a failed judge never merge; sexual-violence reports never judged; admin split sticks; fragments reunite;
   round-up counts; the verification report itself. Mechanics only — they use a fake judge.
2. Judge accuracy on real pairs: 48 hand-labelled cross-paper look-alike pairs (`scratchpad` eval, labels by reading
   the Bangla titles and quotes): 39/42 same merged, 0/6 different merged. Small sample, one labeller.
3. Embedding model choice on the same pairs: EmbeddingGemma 2 AUC 0.73 vs multilingual-e5-large-instruct 0.68 —
   embeddings alone cannot decide, so they only rank candidates.
4. `python -m app events-verify [--export F]` on the live data: invariants (each located published report in
   exactly one active event, main report is a member, counts consistent, no event with two reports of one article),
   public API rows = events (list and stats agree), known multi-paper stories → number of events, residual
   look-alike pairs between separate events vs the old report-level count, over-merge flags (events spanning > 7
   days or > 1 thana), and exported samples of merges and residual pairs for independent review.
5. Independent review: a Codex council (GPT-6.1 Terra) labels the exported samples without seeing the judge's
   verdicts; disagreements are fixed in the rules/prompt and the samples re-run.

## 10. Decisions

| Decision | Why |
|---|---|
| Postgres as queue/locks, no broker | small volume; one fewer service; transactional claims |
| llama.cpp built for CUDA 12.2, outside Docker | no NVIDIA container toolkit on the shared host; driver-compatible |
| vLLM installed (cu129 wheel) but not serving | default PyPI wheel needs CUDA 13; speed benchmark pending |
| Compact prompt + grammar-constrained `place_id` | thana accuracy 71% → 93–98% for the small model |
| Auto-publish, review optional (26 Oct) | product decision: articles state crimes plainly; live map over a review backlog. Evidence check proves a quote exists, not that it supports the claim |
| llama.cpp, not vLLM (26 Oct) | same speed for one-at-a-time requests; vLLM's QAT checkpoints need most of the 12 GB card and long JSON output |
| Geocode after publishing | Nominatim allows 1 request / 15 s; inline geocoding would stall the GPU for hours in a backfill |
| Driver 535 → 575, no OS upgrade | enough for current vLLM/llama.cpp; OS upgrade unsafe without console access |
| Event store with an LLM judge, no agent framework (27–28 Oct) | owner's design ("redux-like store", automatic, live); a fixed pipeline with one schema-constrained judge is testable and auditable; embeddings only rank (they cannot tell same crime from same kind of crime) |
| EmbeddingGemma 2 over e5-large-instruct | better separation on our labelled pairs (AUC 0.73 vs 0.68), 310 MB vs 1.1 GB |

## 11. Known gaps

Backups stay on the same machine (copy off-site) · event judge recall/precision measured on 48 pairs only · re-classifying an
article drops its review corrections · daily sitemaps have no titles, so backfill covers only the crime/capital sections (older Savar/Keraniganj
district news is missed) · Gemma can still split one episode into several incidents · pre-filter recall unmeasured · `/api/meta` exposes operational data (fine on LAN, not public) ·
Tailscale HTTPS needs the tailnet admin · server: Redis on all interfaces, NTP unsynchronised, `sign2text` restart loop (not ours).

## 12. Notes for coding agents

- Commit as **zawadgenweb2** (repo-local git config); **never add AI co-author or "generated by" lines**.
- Never print or commit secrets (`.env`, `deploy/tls/key.pem`, `~/.config/dhaka-llm/api-key`).
- Run the test suite in Docker before pushing; deploy with the runbook commands; keep invariants in §4.
- Design changes get an independent Codex council review first (model `gpt-6.1-sol`, effort `medium`).
