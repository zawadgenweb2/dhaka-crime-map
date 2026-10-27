# Public, multi-newspaper, six-district redesign

Status: in progress on branch `public-multisource-redesign`. Design reviewed by a six-role Codex council (27 Oct 2026);
owner decisions below.

## Owner decisions (27 Oct 2026)

| Topic | Decision |
|---|---|
| Newspapers | Prothom Alo + Samakal, Ittefaq, Bangla Tribune, Ajker Patrika, Desh Rupantor (all robots-ok, news sitemaps with titles) |
| Districts | Dhaka, Chattogram, Sylhet, Khulna, Barishal, Rangpur — District filter replaces Thana (thana drill-down kept inside a district) |
| Queue | PostgreSQL job queue with priorities (fresh news before backfills), leases and retries; Redis + RQ dropped on 27 Oct (one source of truth; the GPU, not the queue, is the bottleneck). Revisit only for workers on several machines |
| Collection | twice a day (08:00, 20:00 Asia/Dhaka) per paper; sitemap roll-over measured and flagged |
| GPU | keep 1 llama.cpp slot; benchmark 2 × 12K context before switching |
| History | 30 days where a paper's archive allows; gaps shown |
| Admin | separate admin app, office LAN/VPN only, individual accounts with login |
| Public events | safe summary + source links; no verbatim quotes, no victim counts; sexual-violence / child cases only in area totals |
| Default view | all six districts |
| Crime types on the map | One warm heat ramp for amount; one chosen type tints it; zoomed-in donuts per area show the crime mix (owner, 27 Oct) |
| Heatmap | smooth heat glow, counting events (not articles), scale adapts to the data |

## Work plan (each step tested and deployed before the next)

1. **Safety fixes** — no unauthenticated collect shortcut; rejected backfill has no side effects; worker fencing on
   lease/owner/generation; previews cannot starve jobs; same-sentence "victim's home" guard.
2. **Public / admin split** — two FastAPI apps; admin login (scrypt/argon2 hashes, server-side sessions, CSRF,
   throttling, audit); public read-only API without model/queue/coverage/collect; review, try-an-article, Swagger,
   coverage, collection move to admin.
3. **Districts** — gazetteer for six districts (Wikidata snapshot + curated Dhaka), per-incident district, ambiguity-aware
   namesakes, district-aware prompt, filter and geocoding bounds.
4. **Newspapers** — source registry, per-publisher request lanes, per-site article extractors, provenance per article,
   collect-only mode per source until verified.
5. **Events** — event table; conservative cross-publisher / follow-up matching; counts, map and feed use events; all
   source links per event.
6. **Queue** — done in PostgreSQL: job priority (scheduled/small collect-now 0, backfill/reprocess 2), per-paper download lanes at 1 request/second.
7. **Public UI** — district-first, mobile, map-first loading, compressed and smaller payloads, self-hosted map library,
   adaptive event heat scale.
8. **GPU benchmark** — 1 vs 2 slots on real articles.
