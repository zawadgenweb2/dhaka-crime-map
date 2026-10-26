# ঢাকা অপরাধ মানচিত্র · Dhaka Crime Map

Collects crime reports from **Prothom Alo** (Bangla), uses an AI model to classify each article and pinpoint
where in **Dhaka district** it happened, and shows the result as a heat map with filters, hotspots and a news feed.

## Architecture (Docker Compose)

```
                      ┌────────────┐  08:00 / 20:00 Asia/Dhaka (one row per slot, runs once)
 prothomalo.com ◄─────┤ collector  │  sitemaps → pre-filter → fetch article → INSERT article + job
  (robots.txt,        └─────┬──────┘  never calls a model; singleton via Postgres advisory lock
   1 req/s, ≤8 MB)          │ jobs (queue)
                      ┌─────▼──────┐  claim job with lease (FOR UPDATE SKIP LOCKED)
 in-house Gemma    ◄─┤ classifier │  record call → call model once → save full answer → geocode → incidents
 model server         └─────┬──────┘  daily budget; crash after sending ⇒ 'uncertain', never re-sent
                            │
 OSM Nominatim ◄────────────┤ shared geocoding lane: ≤ 4 requests/minute across all containers
                      ┌─────▼──────┐
                      │ PostgreSQL │  articles · jobs · llm_calls · analyses · incidents · runs · slots
                      └─────▲──────┘
                      ┌─────┴──────┐
 browser ────────────►│    api     │  dashboard + read API (127.0.0.1:8100); only writes "collect now" requests
                      └────────────┘
```

| Service | Role | Model credentials |
|---|---|---|
| `db` | PostgreSQL 17: data, job queue, locks | – |
| `migrate` | one-shot: schema migrations (and the one-time SQLite import) | – |
| `api` | dashboard and read API, `POST /api/scrape` queues a run request | – |
| `collector` | the only scheduler; scrapes and queues articles | – |
| `classifier` | claims queued articles, classifies, saves, locates, deduplicates | **only here** |

The design was reviewed by an independent Codex council (architecture + code review); its findings are fixed and
covered by tests: atomic job claiming, bounded model calls, results saved before anything else can fail,
no network calls inside database transactions, Nominatim rate limits, a scheduler that cannot double-run,
CSRF-safe "collect now", streamed size limits and RFC 9309 robots handling.

## Run it

```bash
cd dhaka-crime-map
cp .env.example .env          # set POSTGRES_PASSWORD, ADMIN_TOKEN, GEMMA_API_KEY (GOOGLE_MAPS_API_KEY optional)
docker compose up -d --build  # http://127.0.0.1:8100
docker compose --profile test run --rm test      # full test suite against Postgres
```

Admin commands run in the same image:

```bash
docker compose run --rm migrate collect-now --days 1   # ask the collector to scrape now
docker compose run --rm migrate stats
docker compose run --rm migrate rebuild-duplicates     # regroup duplicate reports (no model calls)
docker compose run --rm migrate compare --with gemma   # model vs the frozen reference articles
docker compose logs -f collector classifier
```

## How an article becomes a point on the map

1. **Discover.** Prothom Alo's `news_sitemap.xml` (last ~48 h, with title and keywords) plus the daily sitemaps for
   today and yesterday. robots.txt is honoured (5xx or unreachable = crawl nothing this run), redirects are
   re-checked hop by hop, responses are streamed with an 8 MB cap.
2. **Pre-filter (no model, no cost).** Keep the অপরাধ and রাজধানী sections. From other news sections keep a
   story only if its title or keywords contain a crime term **and** a Dhaka place from the gazetteer.
3. **Classify.** The model reads the full Bangla article and returns structured JSON (`app/schema.py`): whether it
   is a crime report inside Dhaka district, and per incident the category, verbatim location phrase, a place id
   from the catalogue, date, time of day, victims and a verbatim evidence quote.
4. **Validate and locate.** Unknown place ids are re-matched locally; exact spots are geocoded and kept only within
   2.5 km of the chosen place; dates after publication or before 2000 are dropped; an incident is **published**
   only if its evidence quote is in the article and the article was judged a Dhaka crime report.
5. **Group duplicates.** Reports are the same event only with the same category, the same specific place, dates
   within a day and compatible time of day (so Mirpur 11 and Mirpur 12 stay separate).

Scope: **Dhaka district** (50 DMP thanas + Savar, Ashulia, Dhamrai, Keraniganj, Dohar, Nawabganj). A place name
right after another district's name ("কুষ্টিয়ার মিরপুরে") is not treated as Dhaka.

## Model

The only model is **Gemma 4** served from the in-house GPU server (`genweb2inhouse`) by llama.cpp on 127.0.0.1:8090
(OpenAI-compatible API with an API key); no external AI API is used. `CLASSIFIER=rules` is an offline keyword baseline
for tests. Every model call is recorded in `llm_calls` and every answer saved in `analyses`. Model setup, evaluation and
switching are described in `docs/ENGINEERING.md`.

## Map

With `GOOGLE_MAPS_API_KEY` set, the dashboard uses the Google Maps JavaScript API and draws the heat map and points
with deck.gl 9.4 (`GoogleMapsOverlay`; Google retired its own HeatmapLayer in May 2026). Without a key the same
layers are drawn on OpenStreetMap tiles. Filters zoom the map to the matching incidents.

## The gazetteer

`data/dhaka_places.json`: 163 places (50 thanas, 6 upazilas, neighbourhoods, landmarks) with Bangla names,
spelling variants and coordinates checked against OpenStreetMap. Edit `scripts/build_gazetteer.py`, then run it
and `scripts/verify_gazetteer.py`.

## Limits

These are **reported** incidents in one newspaper, not all crime, and AI extraction can be wrong; every point links
to its source article. Area centroids are approximate. Check Prothom Alo's terms before public or commercial use.
