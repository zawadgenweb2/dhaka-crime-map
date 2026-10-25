"""API service: dashboard + read API. Writes only one thing: 'collect now' requests for the collector."""
from __future__ import annotations

import hmac
import logging
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
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
    where = ["i.published", "i.duplicate_of IS NULL", "i.event_date BETWEEN %s AND %s"]
    params: list = [start_d, end_d]
    if categories:
        cats = [c for c in categories.split(",") if c in CATEGORIES]
        if cats:
            where.append("i.category = ANY(%s)")
            params.append(cats)
    if thana:
        where.append("i.thana_id = %s")
        params.append(thana)
    return " AND ".join(where), params, start_d, end_d


def _authorize_trigger(request: Request) -> None:
    token = request.headers.get("x-admin-token", "")
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
            span = c.execute("SELECT min(event_date) a, max(event_date) b FROM incidents WHERE published").fetchone()
            last = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            beats = {r["service"]: r for r in c.execute("SELECT service, seen_at, detail FROM heartbeats")}
            pending = c.execute("SELECT count(*) n FROM run_requests WHERE status IN ('pending','running')").fetchone()["n"]
            collecting = c.execute("SELECT count(*) n FROM runs WHERE status = 'running'").fetchone()["n"]
            day0 = datetime.now(DHAKA_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
            spend = c.execute("""SELECT count(*) calls, coalesce(sum(cost_usd), 0) usd FROM analyses
                                 WHERE created_at >= %s AND NOT legacy""", (day0,)).fetchone()
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
            "spend_today": {"calls": spend["calls"], "usd": float(spend["usd"])},
            "google_maps_api_key": settings.google_maps_api_key,
            "google_maps_map_id": settings.google_maps_map_id,
        }

    @app.get("/api/incidents")
    def incidents(start: str | None = None, end: str | None = None, days: int | None = Query(None, ge=1, le=3650),
                  categories: str | None = None, thana: str | None = None,
                  limit: int = Query(3000, ge=1, le=10000)):
        where, params, _, _ = _filters(start, end, days, categories, thana)
        with db.connect() as c:
            rows = c.execute(
                f"""SELECT i.id, i.category, i.headline_bn, i.headline_en, i.location_text, i.place_id, i.thana_id,
                           i.lat, i.lng, i.precision, i.geocoded, i.incident_date, i.event_date, i.time_of_day,
                           i.victims, i.evidence, i.evidence_ok, a.url, a.title, a.published_at,
                           (SELECT count(*) FROM incidents d WHERE d.duplicate_of = i.id) AS more_reports
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
    def scrape(request: Request, days_back: int = Query(1, ge=0, le=30)):
        _authorize_trigger(request)
        with db.tx() as c:
            busy = c.execute("SELECT id FROM run_requests WHERE status IN ('pending','running') LIMIT 1").fetchone()
            if busy:
                raise HTTPException(409, "a collection is already queued or running")
            rid = c.execute("INSERT INTO run_requests (source, days_back) VALUES (%s, %s) RETURNING id",
                            ("ui" if request.headers.get(UI_HEADER) else "token", days_back)).fetchone()["id"]
        return {"queued": True, "request_id": rid}

    return app


app = create_app()
