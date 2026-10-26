# Dhaka Crime Map — Engineering Handbook

Commit `b4f1209` · 26 Oct 2026 · repo `github.com/zawadgenweb2/dhaka-crime-map` · for engineers and coding agents

## 0. In five lines

- Scrapes Bangla news (Prothom Alo today), keeps likely crime stories, and has a **local LLM** (Gemma 4 E2B on the in-house GPU) extract incidents: category, exact place, date, time, evidence quote.
- Places resolve against a curated **gazetteer** (163 Dhaka places) and optional OpenStreetMap geocoding; duplicates across articles are grouped.
- A **human reviews** every new incident (`PUBLISH_MODE=review`); only published incidents reach the API and map.
- Five Docker services + one systemd model server on `genweb2inhouse`; **Postgres is the data store, job queue and lock service**.
- Precision over recall. No paid model calls in production. Dhaka is always collected; other districts are planned on demand.

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
| `classifier` | Docker, host network | – | job claims, model calls, analyses, incidents, geocoding |
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
| 5 | Classify: one call per article, JSON schema, compact prompt | `worker.py`, `classifiers/gemma.py`, `classifiers/base.py`, `schema.py` | `llm_calls`, `analyses` | 2 dispatches max; then `failed` |
| 6 | Validate + locate: place shortlist, geocode ≤2.5 km, dates, evidence quote | `store.py`, `geocode.py`, `gazetteer.py` | `incidents` (`pending`/`failed`) | failed checks stay hidden, reviewable |
| 7 | Group duplicates: same category + place, dates ±1, compatible time | `store.rebuild_groups` | `incidents.duplicate_of` | rule-based; can merge repeated raids |
| 8 | Review: approve/reject, fix category/place, retry/dismiss | `api.py`, `static/review.html` | `published`, `review_status` | nothing new is shown unreviewed |
| 9 | Serve + map: published canonical incidents; refresh on `data_version` | `api.py`, `static/app.js` | heat + points + feed | – |

## 3. Data model (Postgres, `migrations/00*.sql`)

| Table | Purpose | Key states |
|---|---|---|
| `articles` | one row per URL (body kept for re-analysis) | `queued` · `skipped` · `classified` · `failed` · `uncertain` · `dismissed` |
| `jobs` | work queue, one per article + analysis version | `queued` · `running`(lease) · `done` · `failed` · `uncertain` · `cancelled` |
| `llm_calls` | every model dispatch, written **before** sending | `sent` · `ok` · `error` |
| `analyses` | the model's full JSON answer + tokens/cost | `materialized_at` |
| `incidents` | map rows | `review_status`: `auto` · `pending` · `failed` · `approved` · `rejected`; `published`; `duplicate_of` |
| `runs`, `schedule_slots`, `run_requests` | collection history, one row per slot, manual triggers | slot: `pending` · `running` · `done` · `failed` · `skipped` |
| `geocache`, `rate_limits` | Nominatim cache and the shared request lane | – |
| `heartbeats` | service liveness for `/api/meta` | – |
| `article_reviews`, `eval_results` | reviewer verdicts, offline model evaluations | – |

## 4. Invariants (do not break)

1. **One collector.** It holds Postgres advisory lock `7000003`; a second one waits.
2. **Claim before work.** Jobs are claimed with `FOR UPDATE SKIP LOCKED` + lease; every write checks the job `generation`.
3. **Record before paying, save before using.** `llm_calls` row before the request; `analyses` row before geocoding or incidents. A crash after a *paid* call → `uncertain`, never auto-resent.
4. **No network inside a DB transaction.** Geocode first, then one short transaction replaces an article's incidents (lock `7000002`).
5. **Public = published.** `/api/incidents` and `/api/stats` return only `published AND duplicate_of IS NULL`.
6. **Politeness.** robots.txt per RFC 9309 (`RobotsPolicy`), 1 req/s per publisher, Nominatim ≤ 4/min via `rate_limits`.
7. **Secrets stay out of git and images.** `.env` (0600), `deploy/tls/`, model key file; `.dockerignore` allow-lists sources only.
8. **Schema changes are new migrations**, never edits to applied ones. Saved analyses are re-read with today's schema: version breaking changes.

## 5. Code map

| Path | Responsibility |
|---|---|
| `app/__main__.py` | CLI: services + `collect-now`, `stats`, `compare`, `rebuild-duplicates` |
| `app/config.py` | every setting (env) with defaults |
| `app/db.py` | connections, transactions, migrations, heartbeats |
| `app/scraper.py` | Prothom Alo client, sitemaps, pre-filter, article parse, robots |
| `app/collector.py` | collector service and `collect()` |
| `app/worker.py` | classifier service: claim → call → save → materialize → recover |
| `app/store.py` | locate, date/evidence checks, publish status, duplicate grouping |
| `app/classifiers/` | `base.py` prompts (full + compact), `gemma.py` local, `claude.py` reference, `rules.py` tests |
| `app/gazetteer.py`, `data/dhaka_places.json` | Bangla place matching (suffixes, namesake guard) |
| `app/api.py`, `app/static/` | REST + Swagger, dashboard, review page |
| `app/evaluate.py`, `scripts/eval_table.py` | offline model evaluation vs the Claude reference set |
| `deploy/inhouse-llm/` | llama.cpp build, model download, start scripts, systemd units, vLLM setup |
| `compose.yaml`, `compose.inhouse.yaml` | services; server overrides (HTTPS, loopback DB, host-network classifier) |

## 6. Configuration (`.env`, see `.env.example`)

`POSTGRES_PASSWORD` · `ADMIN_TOKEN` (review + token-triggered runs) · `API_BIND` (server LAN IP) · `CLASSIFIER` (`gemma`|`claude`|`rules`) ·
`GEMMA_API_KEY`, `GEMMA_BASE_URL`, `GEMMA_MODEL`, `GEMMA_PROMPT` (`compact`|`full`) · `PUBLISH_MODE` (`review`|`auto`) ·
`SCRAPE_TIMES` · `USER_AGENT` · `MAX_ARTICLES_PER_RUN` · `MAX_LLM_CALLS_PER_DAY` (paid backends only) · `GEOCODE_*` ·
`ALLOW_UI_TRIGGER` · `GOOGLE_MAPS_API_KEY` (browser key; empty = OpenStreetMap tiles).

## 7. Runbook

```bash
ssh genweb2inhouse && cd ~/dhaka-crime-map
C="docker compose -f compose.yaml -f compose.inhouse.yaml"
git pull && $C up -d --build            # deploy (migrations run automatically)
$C ps ; $C logs -f collector classifier # health and logs
$C exec classifier python -m app collect-now      # scrape now
$C exec classifier python -m app stats
$C exec db psql -U dcm -d dcm           # SQL shell
systemctl --user status|restart dhaka-llm ; journalctl --user -u dhaka-llm -f   # model server
$C --profile test run --rm test         # 54 tests, separate dcm_test database
deploy/backup-db.sh                     # backup now; restore: pg_restore -U dcm -d dcm --clean <file>
```

| Symptom | Check | Fix |
|---|---|---|
| Run `failed: robots.txt disallows …` | publisher reachable? | transient: slot retries; persistent: network or publisher block |
| Jobs stay `queued` | `curl -s 127.0.0.1:8090/health`; classifier logs | `systemctl --user restart dhaka-llm` |
| Classifier log "pausing 10 min" | 401/404 from model server | key in `.env` vs `~/.config/dhaka-llm/api-key`; model alias `dhaka-gemma` |
| Articles `uncertain` | paid call may have been billed | review in `/review`; "retry with model" |
| Map not updating | `/api/meta` `data_version`, review queue | approve pending incidents; open pages refresh within 60 s |
| Browser "Not secure" | self-signed LAN cert | Tailscale HTTPS (needs tailnet admin) or a domain + Let's Encrypt |
| GPU errors after kernel update | `nvidia-smi`, `dkms status` | DKMS must rebuild driver 575 for the new kernel |

## 8. Adding features (recipes)

- **New model:** download a GGUF into `~/.local/share/dhaka-llm`, set `DHAKA_LLM_MODEL` via `systemctl --user edit dhaka-llm`, restart, then
  `$C exec classifier python -m app compare --with gemma --limit 100 --out /tmp/r.json`. Switch only if gates pass (`evaluate.GATES`).
- **New newspaper (planned design):** source registry + per-source config (sitemaps, article URL pattern, crime/capital sections, body selector);
  probe robots, bot challenges and extraction before enabling. Samakal fits (same sitemap format, body in `#contentDetails`);
  Bangladesh Pratidin returns a Cloudflare challenge (needs publisher allowlisting).
- **Other districts (planned):** national gazetteer from `data/sources/wikidata-bd-admin-*.json` (CC0); ambiguity-aware matching;
  coverage table + token-protected activation + resumable 30-day backfill; schema v2 replaces `in_dhaka`.
- **New category:** `schema.py` (enum + labels), prompt rules in `classifiers/base.py`, colours in `static/styles.css`/`app.js`; re-evaluate.
- **Schema change:** add `migrations/00N_*.sql`; never edit applied ones; add a service test in `tests/test_services.py`.
- **API endpoint:** in `create_app()`; work-triggering or private endpoints use `Security(ADMIN_KEY)`; add a test; check `/docs`.

## 9. Tests and evaluation

`$C --profile test run --rm test` on the server (54 tests; pure + the separate `dcm_test` database, never `dcm`). Evaluation reference: 71 Claude-classified articles (a strong
baseline, not ground truth). Best local run (E2B, compact prompt + calendar): JSON 100%, article P/R 0.86/0.88, incident P/R 0.76/0.71,
category 0.78, thana 0.93, date 0.53, 2.4 s/article; **below gates**, hence review mode. Gemma 4 E4B Q8 is next.

## 10. Decisions

| Decision | Why |
|---|---|
| Postgres as queue/locks, no broker | small volume; one fewer service; transactional claims |
| llama.cpp built for CUDA 12.2, outside Docker | no NVIDIA container toolkit on the shared host; driver-compatible |
| vLLM installed (cu129 wheel) but not serving | default PyPI wheel needs CUDA 13; speed benchmark pending |
| Compact prompt + grammar-constrained `place_id` | thana accuracy 71% → 93–98% for the small model |
| Review before publish | precision first; evidence check proves a quote exists, not that it supports the claim |
| Driver 535 → 575, no OS upgrade | enough for current vLLM/llama.cpp; OS upgrade unsafe without console access |

## 11. Known gaps

Backups stay on the same machine (copy off-site) · duplicate rule can merge repeated raids at one place (Dayaganj 19/20 Oct) · re-classifying an
article drops its review decisions · pre-filter recall unmeasured · `/api/meta` exposes operational data (fine on LAN, not public) ·
Tailscale HTTPS needs the tailnet admin · server: Redis on all interfaces, NTP unsynchronised, `sign2text` restart loop (not ours).

## 12. Notes for coding agents

- Commit as **zawadgenweb2** (repo-local git config); **never add AI co-author or "generated by" lines**.
- Never print or commit secrets (`.env`, `deploy/tls/key.pem`, `~/.config/dhaka-llm/api-key`).
- Run the test suite in Docker before pushing; deploy with the runbook commands; keep invariants in §4.
- Design changes get an independent Codex council review first (model `gpt-6.1-sol`, effort `medium`).
