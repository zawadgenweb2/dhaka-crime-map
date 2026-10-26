# Dhaka Crime Map — API guide

Base URL (in-house LAN): `https://192.168.1.200:8100` · Swagger UI: `https://192.168.1.200:8100/docs`

The certificate is self-signed, so `curl` needs `-k`. Set these once in your terminal:

```bash
BASE=https://192.168.1.200:8100
TOKEN='paste-admin-token-here'      # on the server: grep ADMIN_TOKEN ~/dhaka-crime-map/.env
```

| # | Method | Path | Token | What it does |
|---|---|---|---|---|
| 1 | GET | `/api/health` | – | Is the API up and the database reachable |
| 2 | GET | `/api/meta` | – | Status: model, schedule, progress, data version, categories, thanas |
| 3 | GET | `/api/incidents` | – | The incidents on the map (filters) |
| 4 | GET | `/api/stats` | – | Counts for the same filters (totals, by category, thana, time of day, day) |
| 5 | GET | `/api/runs` | – | Collection run history |
| 6 | POST | `/api/scrape` | ✔ | Ask the collector to scrape now |
| 7 | POST | `/api/classify` | ✔ | Try a pasted article: Gemma's answer + checks, **nothing saved** |
| 8 | GET | `/api/classify/{id}` | ✔ | Result of an earlier try |
| 9 | GET | `/api/review/queue` | ✔ | Incidents by review status, for corrections |
| 10 | POST | `/api/review/incidents/{id}` | ✔ | Approve / reject / fix category or place of one incident |
| 11 | POST | `/api/review/articles/{id}` | ✔ | Verdict on a whole article: note, retry with Gemma, or dismiss (hide) |
| – | GET | `/`, `/review`, `/docs` | – | Dashboard, review page, Swagger |

"✔" = send the header `X-Admin-Token: $TOKEN` (in Swagger: **Authorize** button, once).

Common filters for `/api/incidents` and `/api/stats`:

| Parameter | Example | Meaning |
|---|---|---|
| `days` | `7` | last N days (default 30) — ignored when `start`/`end` are given |
| `start`, `end` | `2026-10-20`, `2026-10-26` | date range (YYYY-MM-DD, Asia/Dhaka) |
| `categories` | `murder,robbery` | comma list of: `murder` `assault` `robbery` `theft` `sexual_violence` `kidnapping` `drugs_arms` `fraud_extortion` `other` (unknown key → 400) |
| `thana` | `mohammadpur` | one thana/upazila id (list in `/api/meta` → `thanas`) |

---

## 1. Health

```bash
curl -sk $BASE/api/health
```
Returns `{"ok": true}`. Anything else (or no answer) means the API or the database is down.



## 2. Meta — what is going on

```bash
curl -sk $BASE/api/meta | python3 -m json.tool
```
Key fields:
- `model_label` — the model in use (Gemma 4 E2B, in-house); `publish_mode` — `auto`
- `schedule`, `next_run`, `last_run` — the 08:00 / 20:00 Asia/Dhaka collections
- `batches` — active work: `fetched`/`discovered` articles, Gemma `processed`/`jobs`, `failed`
- `exact_spots_waiting` — incidents still waiting for a street-level geocode
- `data_version` — a counter that changes whenever the map data changes (the dashboard reloads on it)
- `incident_count`, `data_span` — how much is on the map
- `categories`, `time_of_day`, `thanas` — the lists used by filters
Real response (26 Oct 2026, lists shortened):
```json
{
 "model_label": "Gemma 4 E2B (in-house)", "publish_mode": "auto",
 "schedule": ["08:00", "20:00"], "next_run": "2026-10-26T20:00:00+06:00", "running": false,
 "batches": [], "exact_spots_waiting": 0,
 "data_version": "170", "data_changed_at": "2026-10-26T06:21:21.434736+00:00",
 "incident_count": 108, "data_span": {"first": "2018-03-15", "last": "2026-10-25"},
 "queue": {"cancelled": 237, "done": 237}, "model_calls_today": 166,
 "last_run": {"id": 11, "trigger": "manual", "status": "interrupted", "discovered": 964, "fetched": 439,
              "queued": 322, "errors": 0, "message": "stopped: scope reduced to 7 days"},
 "categories": [{"key": "murder", "bn": "হত্যা", "en": "Murder"}, "… 9 in total"],
 "thanas": [{"id": "adabor", "name_en": "Adabor", "name_bn": "আদাবর", "kind": "thana", "lat": 23.7745, "lng": 90.356}, "… 56 in total"]
}
```
(`data_span.first` is 2018 because some articles report court cases about old crimes, dated to the original event.)


## 3. Incidents — what the map shows

```bash
# last 7 days
curl -sk "$BASE/api/incidents?days=7" | python3 -m json.tool

# murders and robberies in Mohammadpur, a date range, only 5 rows, with the count headers
curl -sk -D - "$BASE/api/incidents?start=2026-10-20&end=2026-10-26&categories=murder,robbery&thana=mohammadpur&limit=5"
```
Each item: `category`, `headline_bn/en`, `location_text` (as written in the article), `place_*`, `thana_*`, `lat`/`lng`,
`precision` (`exact` · `neighbourhood` · `thana` · `city`), `incident_date`/`event_date`, `time_of_day`, `victims`,
`evidence` (verbatim quote), `url` (Prothom Alo article), `more_reports` (other articles about the same event).
Headers: `X-Total-Count` (matches) and `X-Truncated: true` if `limit` (default 10000) cut the list.
Only published Gemma incidents are returned; duplicates of the same event appear once.
Real response to `?days=7&limit=2` — headers `x-total-count: 32`, `x-truncated: true`:
```json
[
 {"id": 120, "category": "assault",
  "headline_bn": "ব্যবসায়ীকে আটকে ১০ লাখ টাকা চাঁদা দাবি, গ্রেপ্তার ৬",
  "headline_en": "Businessperson held, demanded 10 lakh taka extortion, 6 arrested",
  "location_text": "মোহাম্মদপুর থানা এলাকা", "place_id": "mohammadpur", "thana_id": "mohammadpur",
  "lat": 23.765, "lng": 90.358, "precision": "thana", "geocoded": false,
  "incident_date": "2026-10-25", "event_date": "2026-10-25", "time_of_day": "night", "victims": 0,
  "evidence": "ঘটনাটি মোহাম্মদপুর থানা এলাকায় হওয়া আটক ব্যক্তিদের ওই থানায় হস্তান্তর করা হয়।", "evidence_ok": true,
  "url": "https://www.prothomalo.com/bangladesh/crime/kdnsdsnuw6", "published_at": "2026-10-25T20:48:14+00:00",
  "more_reports": 0, "place_bn": "মোহাম্মদপুর", "place_en": "Mohammadpur", "thana_bn": "মোহাম্মদপুর", "thana_en": "Mohammadpur"},
 {"id": 119, "category": "kidnapping", "location_text": "শ্যামলী", "place_id": "adabor", "…": "same article"}
]
```
Known weakness visible here: the live E2B model still splits this one extortion episode into several incidents.


## 4. Stats — numbers for the same filters

```bash
curl -sk "$BASE/api/stats?days=7" | python3 -m json.tool
```
`total`, `victims`, `unlocated` (no clear place, not on the map), `by_category`, `by_time_of_day`, `by_day`,
`by_thana` (top 15 with per-category counts), `range`.
Real response to `?days=7` (by_thana shortened):
```json
{"total": 32, "victims": 275, "unlocated": 2,
 "by_category": {"assault": 6, "drugs_arms": 7, "fraud_extortion": 6, "kidnapping": 3, "murder": 6, "robbery": 1,
                 "sexual_violence": 2, "theft": 1},
 "by_time_of_day": {"afternoon": 5, "evening": 2, "morning": 8, "night": 13, "unknown": 4},
 "by_day": [{"date": "2026-10-20", "count": 7}, {"date": "2026-10-21", "count": 2}, {"date": "2026-10-22", "count": 4},
            {"date": "2026-10-23", "count": 7}, {"date": "2026-10-24", "count": 6}, {"date": "2026-10-25", "count": 6}],
 "by_thana": [{"id": "adabor", "name_en": "Adabor", "count": 6,
               "categories": {"fraud_extortion": 3, "assault": 1, "kidnapping": 1, "theft": 1}},
              {"id": "vatara", "name_en": "Vatara", "count": 5, "categories": {"drugs_arms": 3, "murder": 2}}],
 "range": {"start": "2026-10-20", "end": "2026-10-26"}}
```


## 5. Runs — collection history

```bash
curl -sk "$BASE/api/runs?limit=5" | python3 -m json.tool
```
Per run: `trigger` (`schedule` · `manual` · `reprocess`), `status`, `discovered`, `fetched`, `queued`, `errors`, `message`.
Real response:
```json
[{"id": 11, "trigger": "manual", "status": "interrupted", "days_back": 90, "candidates": 1041, "discovered": 964,
  "fetched": 439, "queued": 322, "errors": 0, "message": "stopped: scope reduced to 7 days",
  "started_at": "2026-10-26T06:12:13.675053+00:00", "finished_at": "2026-10-26T06:21:20.388793+00:00"},
 {"id": 10, "trigger": "reprocess", "status": "ok", "discovered": 73, "fetched": 73, "queued": 73, "errors": 0,
  "message": "re-run collected articles through Gemma"}]
```


## 6. Collect now

```bash
curl -sk -X POST "$BASE/api/scrape?days_back=1" -H "X-Admin-Token: $TOKEN"
```
`202 {"queued": true, "request_id": N}`; the collector starts within ~20 s, Gemma follows, the map updates by itself
(watch `/api/meta` → `batches`). `409` = a collection is already queued or running. `days_back` 0–30.
Response shape: `{"queued": true, "request_id": 4}` (not run here: it starts a real collection).


## 7. Try an article (nothing is saved)

```bash
curl -sk -X POST "$BASE/api/classify?wait=60" -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" -d '{
  "title": "ব্যবসায়ীকে আটকে ১০ লাখ টাকা চাঁদা দাবি, গ্রেপ্তার ৬",
  "published_at": "2026-10-25T21:00:00+06:00",
  "body": "রাজধানীর মোহাম্মদপুরের চন্দ্রিমা মডেল টাউনের একটি বাসায় এক ব্যবসায়ীকে আটকে রেখে ১০ লাখ টাকা চাঁদা দাবির অভিযোগে ছয়জনকে গ্রেপ্তার করেছে পুলিশ। গত শুক্রবার রাতে এ ঘটনা ঘটে।"
}' | python3 -m json.tool
```
- Body fields: `title` and `body` (required; body 20–30,000 characters), `published_at` (optional, default now —
  used to turn "গতকাল"/weekday names into dates), `section`, `keywords`, `url` (optional).
- JSON strings cannot contain raw line breaks: put the article on one line or write `\n`.
- Answer: `place_candidates_sent` (places found in the text that Gemma may choose from), `gemma_answer` (raw JSON),
  `after_checks` (each incident after the pipeline's checks: place, thana, date, `evidence_in_article`,
  `would_be_published`), `seconds`, `tokens`, `"saved": false`.
- `202` with an `id` if it took longer than `wait` seconds → fetch it with §8. `429` = 5 tries already waiting.
Real responses, with three real Prothom Alo articles pasted in full:

**a) A Dhaka crime** — "এবার হাজারীবাগের কুরিয়ার সার্ভিসের গুদামঘরে আগুন দেওয়ার চেষ্টা, কর্মীকে মারধর" (3,486 characters), 3.6 s:
```json
{"id": 4, "status": "done", "saved": false, "seconds": 3.6, "tokens": {"input": 2338, "output": 429},
 "place_candidates_sent": ["rayer_bazar", "hazaribagh"],
 "gemma_answer": {"is_crime_report": true, "in_dhaka": true, "note": "… The assault on the worker and the van break-in are treated as separate incidents.",
   "incidents": [
     {"category": "assault", "headline_en": "Assault on courier service worker", "place_id": "rayer_bazar",
      "location_text": "এ জে আর পার্সেল অ্যান্ড কুরিয়ার সার্ভিস কার্যালয়ে", "incident_date": "2026-10-25", "time_of_day": "morning",
      "victims": 1, "geocode_query": "Rayer Bazar, Dhaka",
      "evidence": "পরে মারধর করে তাঁর সঙ্গে থাকা একটি স্মার্ট ফোন ও মানিব্যাগ ছিনতাই করে নেওয়া হয়।"},
     {"category": "theft", "headline_en": "Covered van break-in", "place_id": null, "incident_date": "2026-10-24",
      "evidence": "তাঁর ‘লাশ পড়ে থাকবে’ হুমকির পর কুরিয়ার সার্ভিসের কাভার্ড ভ্যান ভাঙচুর।"}]},
 "after_checks": [
   {"category": "assault", "place": "রায়েরবাজার / Rayer Bazar", "thana": "হাজারীবাগ / Hazaribagh", "lat": 23.744, "lng": 90.36,
    "precision": "neighbourhood", "incident_date": "2026-10-25", "evidence_in_article": true, "would_be_published": true,
    "exact_spot_lookup": "Rayer Bazar, Dhaka"},
   {"category": "theft", "place": null, "thana": null, "precision": "city", "incident_date": "2026-10-24",
    "evidence_in_article": false, "would_be_published": false}]}
```
The second incident is dropped by the checks: its "quote" is not in the article (the model paraphrased).

**b) Not a crime** — "ঢাকার এই ঐতিহাসিক ভবনে সেদিন প্রথম জ্বলেছিল বৈদ্যুতিক বাতি" (6,095 characters), 1.0 s:
```json
{"id": 2, "status": "done", "saved": false, "seconds": 1.0, "tokens": {"input": 3149, "output": 83},
 "place_candidates_sent": ["babubazar", "kotwali", "sadarghat", "islampur", "demra", "dhanmondi", "chawkbazar"],
 "gemma_answer": {"is_crime_report": false, "in_dhaka": true, "incidents": [],
   "note": "প্রদত্ত সংবাদটি ঢাকার আহসান মঞ্জিলে বৈদ্যুতিক বাতি স্থাপনের ঐতিহাসিক ঘটনা নিয়ে, কোনো অপরাধমূলক কার্যকলাপের বিবরণ দেয় না। …"},
 "after_checks": []}
```

**c) A crime outside Dhaka** — "সীমান্তে অপরাধ খুঁজতে গিয়েই সন্ত্রাসীদের নিশানা হন সাংবাদিক আলিফ" (16,894 characters), 1.3 s:
```json
{"id": 3, "status": "done", "saved": false, "seconds": 1.3, "tokens": {"input": 5825, "output": 73},
 "place_candidates_sent": ["darussalam"],
 "gemma_answer": {"is_crime_report": false, "in_dhaka": false, "incidents": [],
   "note": "The provided article details a murder in Netrokona district, not Dhaka district. …"},
 "after_checks": []}
```


## 8. Result of an earlier try

```bash
curl -sk "$BASE/api/classify/12" -H "X-Admin-Token: $TOKEN" | python3 -m json.tool
```
`status`: `queued` · `running` · `done` · `failed`. Tries are kept for 7 days.
Real response (`GET /api/classify/2`, shortened): `{"id": 2, "status": "done", "error": null, "seconds": 1.0, …same fields as §7}`


## 9. Review queue

```bash
curl -sk "$BASE/api/review/queue?status=auto&limit=20" -H "X-Admin-Token: $TOKEN" | python3 -m json.tool
```
`status`: `auto` (published automatically) · `failed` (failed the checks, hidden) · `approved` · `rejected` ·
`pending` (only if PUBLISH_MODE=review). Also returns `counts`, `stuck_articles` (failed model calls), and the
`places`/`categories` lists for corrections. The page `$BASE/review` does the same with buttons.
Real response (`?status=auto&limit=1`, article body shortened):
```json
{"counts": {"auto": 108, "failed": 12},
 "items": [{"id": 120, "article_id": 80, "analysis_id": 146, "category": "assault", "place_id": "mohammadpur",
            "thana_id": "mohammadpur", "evidence_ok": true, "published": true, "duplicate_of": null,
            "review_status": "auto", "classifier": "gemma:dhaka-gemma", "geocode_state": "none",
            "url": "https://www.prothomalo.com/bangladesh/crime/kdnsdsnuw6",
            "body": "রাজধানীর মোহাম্মদপুর এলাকায় এক ব্যবসায়ীকে আটকে ১০ লাখ টাকা চাঁদা দাবির অভিযোগে ছয়জনকে গ্রেপ্তার করেছে পুলিশ। …"}],
 "stuck_articles": [], "places": "[163 places]", "categories": "[9 categories]"}
```


## 10. Fix one incident

```bash
# change the category and place, keep it published
curl -sk -X POST "$BASE/api/review/incidents/123" -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "approve", "category": "kidnapping", "place_id": "mohammadpur"}'

# remove it from the map
curl -sk -X POST "$BASE/api/review/incidents/123" -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"action": "reject"}'
```
`action`: `approve` | `reject`; `category` and `place_id` optional. Approving an incident whose quote is not in the
article is refused (`409`). Duplicate groups and the map update immediately.
Response: `{"ok": true}` (not run against live data here, because it changes the map).


## 11. Verdict on a whole article

```bash
# run the article through Gemma again (e.g. after a prompt change)
curl -sk -X POST "$BASE/api/review/articles/45" -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"verdict": "retry"}'

# hide everything from this article
curl -sk -X POST "$BASE/api/review/articles/45" -H "X-Admin-Token: $TOKEN" -H "Content-Type: application/json" \
  -d '{"verdict": "dismiss", "note": "opinion piece, not a crime report"}'
```
`verdict`: `ok` · `missed_incident` · `not_crime` · `outside_dhaka` · `other` (notes only) · `retry` (new Gemma run;
`409` if one is already queued) · `dismiss` (hides its incidents, cancels waiting work). The article id is the
`article_id` field in the review queue.
Response: `{"ok": true}` (not run against live data here).


---

Errors: `400` bad filter or body · `401` admin token missing/wrong · `403` "collect now" without token or UI header ·
`404` unknown id · `409` conflict (already running / failed evidence) · `422` invalid parameter · `429` too many tries
waiting · `502` the model call failed.
