"""API service: dashboard + read API. Writes only one thing: 'collect now' requests for the collector."""
from __future__ import annotations

import hmac
import logging
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request, Response, Security
from fastapi.security import APIKeyHeader
from fastapi.responses import FileResponse, JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from . import db
from .config import ROOT, settings
from .gazetteer import load as load_gazetteer
from .scheduler import next_run
from .schema import CATEGORIES, TIME_OF_DAY
from .scraper import DHAKA_TZ

log = logging.getLogger(__name__)
STATIC = ROOT / "app" / "static"
MIN_DATE, MAX_DATE = date(2000, 1, 1), date(2100, 1, 1)
UI_HEADER = "x-dcm-ui"
# Declared in OpenAPI so Swagger's "Authorize" button can send it.
ADMIN_KEY = APIKeyHeader(name="X-Admin-Token", auto_error=False, description="Team admin token (from the server .env)")


class ArticleIn(BaseModel):
    """A Prothom Alo-style article to try. Nothing is saved."""
    title: str = Field(min_length=1, max_length=500, examples=["ব্যবসায়ীকে আটকে ১০ লাখ টাকা চাঁদা দাবি, গ্রেপ্তার ৬"])
    body: str = Field(min_length=20, max_length=30000,
                      examples=["রাজধানীর মোহাম্মদপুরের চন্দ্রিমা মডেল টাউনের একটি বাসায় এক ব্যবসায়ীকে আটকে রেখে ১০ লাখ টাকা "
                                "চাঁদা দাবির অভিযোগে ছয়জনকে গ্রেপ্তার করেছে পুলিশ। গত শুক্রবার রাতে এ ঘটনা ঘটে।"])
    published_at: datetime | None = Field(None, description="When it was published; default now (Asia/Dhaka). "
                                                             "Used to resolve 'গতকাল', weekday names, etc.")
    section: str = Field("bangladesh/crime", max_length=100)
    keywords: str = Field("", max_length=1000)
    url: str | None = Field(None, max_length=500, description="Optional, for your own reference")


MAX_WAITING_PREVIEWS = 5


def _filters(start: str | None, end: str | None, days: int | None, categories: str | None,
             thana: str | None) -> tuple[str, list, date, date]:
    today = datetime.now(DHAKA_TZ).date()
    try:
        end_d = date.fromisoformat(end) if end else today
        start_d = date.fromisoformat(start) if start else end_d - timedelta(days=(days or 30) - 1)
    except (ValueError, OverflowError):
        raise HTTPException(400, "dates must be YYYY-MM-DD")
    if not (MIN_DATE <= start_d <= end_d <= MAX_DATE):
        raise HTTPException(400, "date range must be ordered and within 2000-01-01..2100-01-01")
    # A duplicate is hidden only if the report it points to is itself in the period, so an event never
    # vanishes from a period because its first report fell just outside it.
    where = ["i.published", db.GEMMA_PROVENANCE, "i.event_date BETWEEN %s AND %s",
             """(i.duplicate_of IS NULL OR NOT EXISTS (SELECT 1 FROM incidents c WHERE c.id = i.duplicate_of
                 AND c.published AND c.event_date BETWEEN %s AND %s))"""]
    params: list = [start_d, end_d, start_d, end_d]
    if categories:
        cats = [c for c in categories.split(",") if c]
        unknown = [c for c in cats if c not in CATEGORIES]
        if unknown:  # never silently widen to "all categories"
            raise HTTPException(400, f"unknown categories: {', '.join(unknown)}")
        if cats:
            where.append("i.category = ANY(%s)")
            params.append(cats)
    if thana:
        where.append("i.thana_id = %s")
        params.append(thana)
    return " AND ".join(where), params, start_d, end_d


def _authorize_trigger(request: Request, token: str | None = None) -> None:
    token = token or request.headers.get("x-admin-token", "")
    if settings.admin_token and token and hmac.compare_digest(token, settings.admin_token):
        return
    if settings.allow_ui_trigger and request.headers.get(UI_HEADER) == "1":
        # A custom header forces a CORS preflight for cross-site requests, which this API never approves.
        # Origin, when sent, must also match the host the dashboard was loaded from.
        origin = request.headers.get("origin")
        if origin is None or urlsplit(origin).netloc == request.headers.get("host"):
            return
    raise HTTPException(403, "not allowed: use the dashboard button or X-Admin-Token")


def _iso(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


def create_app() -> FastAPI:
    app = FastAPI(title="Dhaka Crime Map", version="0.2.0")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        with db.connect() as c:
            c.execute("SELECT 1")
        return {"ok": True}

    @app.get("/api/meta")
    def meta():
        gaz = load_gazetteer()
        with db.connect() as c:
            counts = {r["status"]: r["n"] for r in c.execute("SELECT status, count(*) n FROM articles GROUP BY status")}
            queue = {r["state"]: r["n"] for r in c.execute("SELECT state, count(*) n FROM jobs GROUP BY state")}
            span = c.execute(f"""SELECT min(event_date) a, max(event_date) b, count(*) n
                                 FROM incidents i WHERE published AND {db.GEMMA_PROVENANCE}""").fetchone()
            rev = c.execute("SELECT rev, changed_at FROM data_revision").fetchone()
            batches = c.execute("""
                SELECT r.id, r.trigger, r.status, r.days_back, r.candidates, r.discovered, r.fetched, r.started_at,
                       count(j.id) AS jobs,
                       count(j.id) FILTER (WHERE j.state IN ('done', 'failed', 'uncertain', 'superseded',
                                                             'cancelled')) AS processed,
                       count(j.id) FILTER (WHERE j.state = 'failed') AS failed,
                       count(j.id) FILTER (WHERE j.state = 'running') AS in_progress
                FROM runs r LEFT JOIN jobs j ON j.run_id = r.id
                WHERE r.status = 'running' OR EXISTS (SELECT 1 FROM jobs q WHERE q.run_id = r.id
                                                      AND q.state IN ('queued', 'running'))
                GROUP BY r.id ORDER BY r.id""").fetchall()
            spots = c.execute("SELECT count(*) n FROM incidents WHERE geocode_state = 'todo'").fetchone()["n"]
            last = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            beats = {r["service"]: r for r in c.execute("SELECT service, seen_at, detail FROM heartbeats")}
            pending = c.execute("SELECT count(*) n FROM run_requests WHERE status IN ('pending','running')").fetchone()["n"]
            collecting = c.execute("SELECT count(*) n FROM runs WHERE status = 'running'").fetchone()["n"]
            day0 = datetime.now(DHAKA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            calls = c.execute("SELECT count(*) n FROM llm_calls WHERE sent_at >= %s", (day0,)).fetchone()["n"]
        now = datetime.now(timezone.utc)
        clf = (beats.get("classifier") or {}).get("detail") or {}
        return {
            "categories": [{"key": k, **v} for k, v in CATEGORIES.items()],
            "time_of_day": [{"key": k, **v} for k, v in TIME_OF_DAY.items()],
            "thanas": [p.to_dict() for p in gaz.places if p.kind in ("thana", "upazila")],
            "classifier": settings.classifier, "model": clf.get("backend") or settings.classifier,
            "schedule": settings.scrape_times, "next_run": next_run(now).isoformat(),
            "running": bool(pending or collecting or queue.get("queued") or queue.get("running")),
            "collecting": bool(pending or collecting), "queue": queue,
            "services": {s: {"alive": (now - b["seen_at"]).total_seconds() < 180, "seen_at": b["seen_at"].isoformat()}
                         for s, b in beats.items()},
            "last_run": {k: _iso(v) for k, v in last.items()} if last else None,
            "articles": counts, "data_span": {"first": _iso(span["a"]), "last": _iso(span["b"])},
            # data_revision: bumped in the same transaction as every change the map can see
            "data_version": str(rev["rev"]), "data_changed_at": _iso(rev["changed_at"]), "incident_count": span["n"],
            "publish_mode": settings.publish_mode, "model_label": settings.model_label,
            # active batches (a collection run or a reprocess) and their Gemma progress, in articles
            "batches": [{k: _iso(v) for k, v in b.items()} for b in batches],
            "exact_spots_waiting": spots,
            "model_calls_today": calls,
            "google_maps_api_key": settings.google_maps_api_key,
            "google_maps_map_id": settings.google_maps_map_id,
        }

    @app.get("/api/incidents")
    def incidents(response: Response, start: str | None = None, end: str | None = None,
                  days: int | None = Query(None, ge=1, le=3650), categories: str | None = None,
                  thana: str | None = None, limit: int = Query(10000, ge=1, le=20000)):
        """Published, non-duplicate Gemma incidents. X-Total-Count / X-Truncated tell clients when `limit` cut it."""
        where, params, _, _ = _filters(start, end, days, categories, thana)
        with db.connect() as c:
            total = c.execute(f"SELECT count(*) n FROM incidents i WHERE {where}", params).fetchone()["n"]
            response.headers["X-Total-Count"] = str(total)
            response.headers["X-Truncated"] = "true" if total > limit else "false"
            rows = c.execute(
                f"""SELECT i.id, i.category, i.headline_bn, i.headline_en, i.location_text, i.place_id, i.thana_id,
                           i.lat, i.lng, i.precision, i.geocoded, i.incident_date, i.event_date, i.time_of_day,
                           i.victims, i.evidence, i.evidence_ok, a.url, a.title, a.published_at,
                           (SELECT count(*) FROM incidents d WHERE d.duplicate_of = i.id AND d.published) AS more_reports
                    FROM incidents i JOIN articles a ON a.id = i.article_id
                    WHERE {where} ORDER BY i.event_date DESC, i.id DESC LIMIT %s""", (*params, limit)).fetchall()
        gaz = load_gazetteer()
        out = []
        for d in rows:
            p, t = gaz.get(d["place_id"]), gaz.get(d["thana_id"])
            d["place_bn"], d["place_en"] = (p.name_bn, p.name_en) if p else (None, None)
            d["thana_bn"], d["thana_en"] = (t.name_bn, t.name_en) if t else (None, None)
            out.append({k: _iso(v) for k, v in d.items()})
        return out

    @app.get("/api/stats")
    def stats(start: str | None = None, end: str | None = None, days: int | None = Query(None, ge=1, le=3650),
              categories: str | None = None, thana: str | None = None):
        where, params, start_d, end_d = _filters(start, end, days, categories, thana)
        gaz = load_gazetteer()
        with db.connect() as c:
            def q(sql):
                return c.execute(sql.format(w=where), params).fetchall()
            total = q("""SELECT count(*) n, coalesce(sum(victims), 0) v, count(*) FILTER (WHERE lat IS NULL) unloc
                         FROM incidents i WHERE {w}""")[0]
            by_thana = []
            for r in q("""SELECT thana_id, count(*) n FROM incidents i WHERE {w} AND thana_id IS NOT NULL
                          GROUP BY thana_id ORDER BY n DESC LIMIT 15"""):
                p = gaz.get(r["thana_id"])
                cats = c.execute(f"""SELECT category, count(*) n FROM incidents i WHERE {where} AND thana_id = %s
                                     GROUP BY category ORDER BY n DESC""", (*params, r["thana_id"])).fetchall()
                by_thana.append({"id": r["thana_id"], "name_bn": p.name_bn if p else r["thana_id"],
                                 "name_en": p.name_en if p else r["thana_id"], "lat": p.lat if p else None,
                                 "lng": p.lng if p else None, "count": r["n"],
                                 "categories": {x["category"]: x["n"] for x in cats}})
            return {
                "total": total["n"], "victims": total["v"], "unlocated": total["unloc"],
                "by_category": {r["category"]: r["n"] for r in
                                q("SELECT category, count(*) n FROM incidents i WHERE {w} GROUP BY category")},
                "by_time_of_day": {r["time_of_day"]: r["n"] for r in
                                   q("SELECT time_of_day, count(*) n FROM incidents i WHERE {w} GROUP BY time_of_day")},
                "by_day": [{"date": r["event_date"].isoformat(), "count": r["n"]} for r in
                           q("SELECT event_date, count(*) n FROM incidents i WHERE {w} GROUP BY event_date ORDER BY 1")],
                "by_thana": by_thana,
                "range": {"start": start_d.isoformat(), "end": end_d.isoformat()},
            }

    @app.get("/api/runs")
    def runs(limit: int = Query(20, ge=1, le=200)):
        with db.connect() as c:
            return [{k: _iso(v) for k, v in r.items()}
                    for r in c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT %s", (limit,))]

    @app.post("/api/scrape", status_code=202)
    def scrape(request: Request, days_back: int = Query(1, ge=0, le=30), token: str | None = Security(ADMIN_KEY)):
        """Queue a "collect now" request for the collector (it never scrapes inside the API)."""
        _authorize_trigger(request, token)
        try:
            with db.tx() as c:
                rid = c.execute("INSERT INTO run_requests (source, days_back) VALUES (%s, %s) RETURNING id",
                                ("token" if token else "ui", days_back)).fetchone()["id"]
        except psycopg.errors.UniqueViolation:  # one active request at a time (migration 004)
            raise HTTPException(409, "a collection is already queued or running")
        return {"queued": True, "request_id": rid}

    # ---- human review (always requires ADMIN_TOKEN) -------------------------------------------
    def _reviewer(request: Request, token: str | None = None) -> str:
        token = token or request.headers.get("x-admin-token", "")
        if not settings.admin_token or not hmac.compare_digest(token, settings.admin_token):
            raise HTTPException(401, "admin token required")
        return (request.headers.get("x-reviewer") or "reviewer")[:60]

    @app.get("/review", include_in_schema=False)
    def review_page():
        return FileResponse(STATIC / "review.html")

    @app.get("/api/review/queue")
    def review_queue(request: Request, status: str = Query("pending", pattern="^(pending|failed|approved|rejected|auto)$"),
                     limit: int = Query(50, ge=1, le=200), token: str | None = Security(ADMIN_KEY)):
        _reviewer(request, token)
        gaz = load_gazetteer()
        with db.connect() as c:
            rows = c.execute(
                f"""SELECT i.*, a.url, a.title, a.body, a.published_at, a.classifier AS article_classifier
                    FROM incidents i JOIN articles a ON a.id = i.article_id
                    WHERE i.review_status = %s AND {db.GEMMA_PROVENANCE}
                    ORDER BY i.event_date DESC NULLS LAST, i.id DESC LIMIT %s""", (status, limit)).fetchall()
            counts = {r["review_status"]: r["n"] for r in
                      c.execute(f"SELECT review_status, count(*) n FROM incidents i WHERE {db.GEMMA_PROVENANCE} GROUP BY 1")}
            stuck = c.execute("""SELECT a.id, a.url, a.title, a.status, j.last_error FROM articles a
                                 LEFT JOIN jobs j ON j.article_id = a.id
                                 WHERE a.status IN ('uncertain','failed') ORDER BY a.id DESC LIMIT 50""").fetchall()
        items = []
        for r in rows:
            p = gaz.get(r["place_id"])
            items.append({**{k: _iso(v) for k, v in r.items()}, "place_bn": p.name_bn if p else None,
                          "place_en": p.name_en if p else None})
        return {"counts": counts, "items": items, "stuck_articles": stuck,
                "places": [{"id": p.id, "name_bn": p.name_bn, "name_en": p.name_en} for p in gaz.places],
                "categories": [{"key": k, **v} for k, v in CATEGORIES.items()]}

    # ---- try an article (admin token: it uses the GPU) ----------------------------------------
    @app.post("/api/classify", tags=["try"], summary="Try an article: Gemma's answer and the automatic checks")
    def classify_preview(item: ArticleIn, request: Request, wait: int = Query(120, ge=5, le=300),
                         token: str | None = Security(ADMIN_KEY)):
        """Paste a title and body; returns the place shortlist sent to Gemma, Gemma's raw JSON answer, and each
        incident after the same automatic checks the pipeline uses (place, thana, date, evidence quote, whether it
        would be published). **Nothing is saved.** If the model takes longer than `wait` seconds, the answer is 202
        with an id to fetch from `GET /api/classify/{id}`."""
        who = _reviewer(request, token)
        with db.tx() as c:
            waiting = c.execute("SELECT count(*) n FROM previews WHERE status IN ('queued','running')").fetchone()["n"]
            if waiting >= MAX_WAITING_PREVIEWS:
                raise HTTPException(429, "too many previews waiting; try again in a minute")
            pid = c.execute("INSERT INTO previews (input, requested_by) VALUES (%s, %s) RETURNING id",
                            (Jsonb(item.model_dump(mode="json")), who)).fetchone()["id"]
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            time.sleep(0.5)
            out = _preview(pid)
            if out["status"] in ("done", "failed"):
                if out["status"] == "failed":
                    raise HTTPException(502, f"model call failed: {out['error']}")
                return out
        return JSONResponse(_preview(pid), status_code=202)

    @app.get("/api/classify/{preview_id}", tags=["try"], summary="Result of an earlier try")
    def classify_preview_result(preview_id: int, request: Request, token: str | None = Security(ADMIN_KEY)):
        _reviewer(request, token)
        return _preview(preview_id)

    def _preview(pid: int) -> dict:
        with db.connect() as c:
            row = c.execute("SELECT id, status, result, error, created_at, finished_at FROM previews WHERE id = %s",
                            (pid,)).fetchone()
        if row is None:
            raise HTTPException(404, "preview not found")
        return {"id": row["id"], "status": row["status"], "error": row["error"], **(row["result"] or {})}

    @app.post("/api/review/incidents/{incident_id}")
    def review_incident(incident_id: int, request: Request, payload: dict, token: str | None = Security(ADMIN_KEY)):
        who = _reviewer(request, token)
        action = payload.get("action")
        if action not in ("approve", "reject"):
            raise HTTPException(400, "action must be approve or reject")
        category, place_id = payload.get("category"), payload.get("place_id")
        if category is not None and category not in CATEGORIES:
            raise HTTPException(400, "unknown category")
        gaz = load_gazetteer()
        place = gaz.get(place_id) if place_id else None
        if place_id and place is None:
            raise HTTPException(400, "unknown place_id")
        from .store import MATERIALIZE_LOCK, rebuild_groups
        with db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
            old = c.execute(f"""SELECT category, place_id, event_date, evidence_ok FROM incidents i
                                 WHERE id = %s AND {db.GEMMA_PROVENANCE} FOR UPDATE""", (incident_id,)).fetchone()
            if not old:
                raise HTTPException(404, "incident not found")
            if action == "approve" and not old["evidence_ok"]:
                # failed the automatic checks: its quote is not in the article, so it is never shown
                raise HTTPException(409, "this incident failed the evidence check and cannot be published")
            if category:
                c.execute("UPDATE incidents SET category = %s WHERE id = %s", (category, incident_id))
            if place and place.id != old["place_id"]:  # keep exact geocodes unless the place really changes
                thana = gaz.thana_of(place)
                c.execute("""UPDATE incidents SET place_id = %s, thana_id = %s, lat = %s, lng = %s, geocoded = false,
                             geocode_state = 'none', precision = %s WHERE id = %s""",
                          (place.id, thana.id, place.lat, place.lng,
                           {"landmark": "exact", "area": "neighbourhood"}.get(place.kind, "thana"), incident_id))
            c.execute("""UPDATE incidents SET review_status = %s, published = %s, reviewed_by = %s, reviewed_at = now(),
                         duplicate_of = CASE WHEN %s THEN duplicate_of ELSE NULL END WHERE id = %s""",
                      ("approved" if action == "approve" else "rejected", action == "approve", who,
                       action == "approve", incident_id))
            c.execute("UPDATE incidents SET duplicate_of = NULL WHERE duplicate_of = %s AND %s",
                      (incident_id, action == "reject"))
            new = c.execute("SELECT category, place_id, event_date FROM incidents WHERE id = %s",
                            (incident_id,)).fetchone()
            keys = {(r["category"], r["place_id"], r["event_date"]) for r in (old, new)
                    if r["place_id"] and r["event_date"]}
            rebuild_groups(c, keys)
            db.bump_revision(c)
        return {"ok": True}

    @app.post("/api/review/articles/{article_id}")
    def review_article(article_id: int, request: Request, payload: dict, token: str | None = Security(ADMIN_KEY)):
        who = _reviewer(request, token)
        verdict = payload.get("verdict")
        if verdict not in ("ok", "missed_incident", "not_crime", "outside_dhaka", "other", "retry", "dismiss"):
            raise HTTPException(400, "bad verdict")
        with db.tx() as c:
            art = c.execute("SELECT id, status FROM articles WHERE id = %s FOR UPDATE", (article_id,)).fetchone()
            if not art:
                raise HTTPException(404, "article not found")
            c.execute("INSERT INTO article_reviews (article_id, verdict, note, reviewed_by) VALUES (%s,%s,%s,%s)",
                      (article_id, verdict, (payload.get("note") or "")[:1000], who))
            active = c.execute("""SELECT 1 FROM jobs WHERE article_id = %s AND state IN ('queued','running')""",
                               (article_id,)).fetchone()
            if verdict == "retry" and active:
                raise HTTPException(409, "this article is already queued for the model")
            if verdict == "retry":
                # New analysis version = a fresh job for the (local) model; old attempts stay on record.
                version = c.execute("SELECT coalesce(max(analysis_version), 0) + 1 v FROM jobs WHERE article_id = %s",
                                    (article_id,)).fetchone()["v"]
                c.execute("INSERT INTO jobs (article_id, analysis_version, backend) VALUES (%s, %s, %s)",
                          (article_id, version, settings.classifier))
                c.execute("UPDATE articles SET status = 'queued', error = NULL, analysis_version = %s WHERE id = %s",
                          (version, article_id))
            elif verdict == "dismiss":
                # Hide the article's incidents now; a worker still running on it cannot re-publish
                # (it checks the article status before writing).
                from .store import MATERIALIZE_LOCK, rebuild_groups
                c.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
                c.execute("UPDATE articles SET status = 'dismissed' WHERE id = %s", (article_id,))
                c.execute("""UPDATE jobs SET state = 'cancelled', updated_at = now()
                             WHERE article_id = %s AND state = 'queued'""", (article_id,))
                hidden = c.execute("""UPDATE incidents SET published = false, review_status = 'rejected',
                                      reviewed_by = %s, reviewed_at = now(), duplicate_of = NULL
                                      WHERE article_id = %s RETURNING id, category, place_id, event_date""",
                                   (who, article_id)).fetchall()
                ids = [r["id"] for r in hidden]
                c.execute("UPDATE incidents SET duplicate_of = NULL WHERE duplicate_of = ANY(%s)", (ids,))
                rebuild_groups(c, {(r["category"], r["place_id"], r["event_date"]) for r in hidden
                                   if r["place_id"] and r["event_date"]})
                db.bump_revision(c)
        return {"ok": True}

    return app


app = create_app()
