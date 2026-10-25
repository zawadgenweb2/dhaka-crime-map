# ঢাকা অপরাধ মানচিত্র · Dhaka Crime Map

Collects crime reports from **Prothom Alo** (Bangla), uses an AI model to classify each article and pinpoint
where in **Dhaka district** it happened, and shows the result as a heat map with filters, hotspots and a news feed.

```
Prothom Alo sitemaps ──► pre-filter ──► fetch article ──► classifier ──► locate ──► SQLite ──► API ──► map
 (08:00 & 20:00 Dhaka)   (free, rules)   (JSON-LD text)   Claude Opus 5.5   gazetteer      (dedup)        Google Maps
                                                          → Gemma 4 E2B     + OSM geocode                 + deck.gl
```

## Quick start

```bash
cd dhaka-crime-map
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt
cp .env.example .env            # add ANTHROPIC_API_KEY (and GOOGLE_MAPS_API_KEY)
.venv/bin/python -m app scrape --days 7    # one-off backfill of the last week
.venv/bin/python -m app serve              # http://127.0.0.1:8100, scheduler included
```

Run as a service (keeps the 08:00/20:00 schedule after reboot): see `deploy/dhaka-crime-map.service`.

## How an article becomes a point on the map

1. **Discover.** Prothom Alo's `news_sitemap.xml` (last ~48 h, with title and keywords) plus the daily sitemaps
   for today and yesterday. Both are advertised in the site's robots.txt, which is respected; requests are spaced
   1 s apart.
2. **Pre-filter (no model, no cost).** Keep the অপরাধ and রাজধানী sections. From other news sections keep a
   story only if its title or Prothom Alo keywords contain a crime term (হত্যা, ছিনতাই, ধর্ষণ, মাদক, …) **and** a
   Dhaka place from the gazetteer. Sports, entertainment, opinion, video and the like are never fetched.
   After download, the full text must pass the same check before it reaches the model.
3. **Classify.** The model reads the full Bangla article and returns structured JSON (`app/schema.py`): whether it
   is a crime report, whether it happened inside Dhaka district, and for every incident its category, the exact
   location phrase, a place id from the catalogue, date, time of day, victim count and a verbatim evidence quote.
4. **Validate and locate.**
   * the place id must exist in `data/dhaka_places.json`, otherwise the location text is matched again locally;
   * when the article names a precise spot (station, market, road), it is geocoded on OpenStreetMap and kept
     **only** if it lands within 2.5 km of the chosen area;
   * the evidence quote must appear in the article (`evidence_ok`);
   * dates after publication are discarded;
   * the same category in the same thana within ±1 day from another article is marked as a duplicate report.

Precision shown in the UI: **নির্দিষ্ট স্থান** (exact spot) · **এলাকা** (neighbourhood centre) · **থানা পর্যায়**
(thana centre) · **স্থান অস্পষ্ট** (only "রাজধানী", listed but not mapped).

### Scope and categories

* **Dhaka district**: the 50 DMP thanas plus Savar, Ashulia, Dhamrai, Keraniganj, Dohar, Nawabganj.
  Gazipur/Tongi and Narayanganj are excluded.
* **Categories**: হত্যা, হামলা ও সংঘর্ষ, ছিনতাই ও ডাকাতি, চুরি, যৌন সহিংসতা, অপহরণ, মাদক ও অস্ত্র (arrests and
  seizures, placed where they happened), প্রতারণা ও চাঁদাবাজি, অন্যান্য. Road accidents, fires and suicides are
  not crimes here.

### The gazetteer

`data/dhaka_places.json` has 163 places (50 thanas, 6 upazilas, neighbourhoods and landmarks) with Bangla names,
spelling variants and coordinates. Edit `scripts/build_gazetteer.py`, rebuild, and re-check against OpenStreetMap:

```bash
.venv/bin/python scripts/build_gazetteer.py
.venv/bin/python scripts/verify_gazetteer.py      # lists places > 1.2 km from their OSM match
```

Matching understands Bangla digits, "১০ নম্বর", hyphens and case endings (মিরপুরে, গুলশানের, বাড্ডায়), and will
not match inside other words (উত্তরাঞ্চল is not উত্তরা).

## Models

| `CLASSIFIER` | What | Where it runs |
|---|---|---|
| `claude` (default) | Claude Opus 5.5, adaptive thinking, structured output, prompt caching, server-side refusal fallback | Anthropic API, ~US$0.01–0.02 per article |
| `gemma` | Gemma 4 E2B via any OpenAI-compatible server, same prompt and schema | Local CPU/GPU (Ollama: `ollama pull gemma4:e2b`) |
| `rules` | Keyword baseline | Offline, free; used in tests |

Before switching to the local model, measure it against Claude's saved results:

```bash
.venv/bin/python -m app compare --with gemma --limit 50
```

## Map

With `GOOGLE_MAPS_API_KEY` set, the dashboard uses the **Google Maps JavaScript API** (`v=weekly`, async loader)
and draws the heat map and incident points with **deck.gl 9.4** `GoogleMapsOverlay`. Google retired its own
`HeatmapLayer` in May 2026 and recommends deck.gl. Without a key, the same layers are drawn on OpenStreetMap tiles.

Creating the key: Google Cloud Console → enable **Maps JavaScript API** → Credentials → Create API key →
restrict it to *HTTP referrers* `http://localhost:8100/*` and to *Maps JavaScript API*. A billing account is
required by Google; normal personal use stays inside the free monthly allowance.

## CLI

```
python -m app serve [--no-scheduler]   dashboard + API + scheduler
python -m app scrape [--days N] [--max M]
python -m app classify [--all]         classify pending (or re-classify everything)
python -m app compare --with gemma
python -m app stats
```

API: `GET /api/meta`, `/api/incidents`, `/api/stats` (filters: `days` or `start`/`end`, `categories`, `thana`),
`/api/runs`, `POST /api/scrape` (localhost, or `X-Admin-Token`).

## Limits

These are **reported** incidents in one newspaper, not all crime, and AI extraction can be wrong; every point
links to its source article. Area centroids are approximate. Check Prothom Alo's terms before any public or
commercial use.

## Tests

```bash
.venv/bin/python -m pytest -q
```
