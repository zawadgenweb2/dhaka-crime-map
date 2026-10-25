"""HTTP API + static dashboard."""
from __future__ import annotations

import hmac
import logging
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import ROOT, settings
from .gazetteer import load as load_gazetteer
from .pipeline import Pipeline, RunInProgress, is_running
from .schema import CATEGORIES, TIME_OF_DAY
from .scraper import DHAKA_TZ

log = logging.getLogger(__name__)
STATIC = ROOT / "app" / "static"
state: dict = {"scheduler": None, "last_error": None}


def start_run(trigger: str, days_back: int = 1) -> bool:
    """Start a run in a background thread. False if one is already running."""
    if is_running():
        return False

    def target():
        try:
            Pipeline().run(trigger=trigger, days_back=days_back)
            state["last_error"] = None
        except RunInProgress:
            pass
        except Exception as e:
            state["last_error"] = f"{type(e).__name__}: {e}"
            log.exception("run failed")

    threading.Thread(target=target, name=f"run-{trigger}", daemon=True).start()
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.connect()
    if settings.scheduler_enabled and app.state.enable_scheduler:
        from .scheduler import Scheduler
        state["scheduler"] = Scheduler(lambda trigger: Pipeline().run(trigger=trigger, days_back=1))
        state["scheduler"].start()
    yield
    if state["scheduler"]:
        state["scheduler"].stop.set()


def create_app(enable_scheduler: bool = True) -> FastAPI:
    app = FastAPI(title="Dhaka Crime Map", version="0.1.0", lifespan=lifespan)
    app.state.enable_scheduler = enable_scheduler
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    def filters(start: str | None, end: str | None, days: int | None, categories: str | None,
                thana: str | None) -> tuple[str, list]:
        today = datetime.now(DHAKA_TZ).date()
        try:
            end_d = date.fromisoformat(end) if end else today
            start_d = date.fromisoformat(start) if start else end_d - timedelta(days=(days or 30) - 1)
        except ValueError:
            raise HTTPException(400, "dates must be YYYY-MM-DD")
        where = ["i.duplicate_of IS NULL", "i.event_date BETWEEN ? AND ?"]
        params: list = [start_d.isoformat(), end_d.isoformat()]
        if categories:
            cats = [c for c in categories.split(",") if c in CATEGORIES]
            if cats:
                where.append(f"i.category IN ({','.join('?' * len(cats))})")
                params += cats
        if thana:
            where.append("i.thana_id = ?")
            params.append(thana)
        return " AND ".join(where), params

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health")
    def health():
        return {"ok": True, "running": is_running()}

    @app.get("/api/meta")
    def meta():
        conn = db.connect()
        gaz = load_gazetteer()
        sched = state["scheduler"]
        counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) n FROM articles GROUP BY status")}
        span = conn.execute("SELECT min(event_date) a, max(event_date) b FROM incidents").fetchone()
        last = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "categories": [{"key": k, **v} for k, v in CATEGORIES.items()],
            "time_of_day": [{"key": k, **v} for k, v in TIME_OF_DAY.items()],
            "thanas": [p.to_dict() for p in gaz.places if p.kind in ("thana", "upazila")],
            "classifier": settings.classifier, "model": settings.claude_model if settings.classifier == "claude"
            else settings.gemma_model if settings.classifier == "gemma" else "keyword rules",
            "schedule": settings.scrape_times,
            "next_run": sched.next_at.isoformat() if sched and sched.next_at else None,
            "running": is_running(), "last_run": dict(last) if last else None,
            "last_error": state["last_error"],
            "articles": counts, "data_span": {"first": span["a"], "last": span["b"]},
            "google_maps_api_key": settings.google_maps_api_key,
            "google_maps_map_id": settings.google_maps_map_id,
        }

    @app.get("/api/incidents")
    def incidents(start: str | None = None, end: str | None = None, days: int | None = Query(None, ge=1, le=3650),
                  categories: str | None = None, thana: str | None = None, limit: int = Query(3000, le=10000)):
        where, params = filters(start, end, days, categories, thana)
        rows = db.connect().execute(
            f"""SELECT i.id, i.category, i.headline_bn, i.headline_en, i.location_text, i.place_id, i.thana_id,
                       i.lat, i.lng, i.precision, i.geocoded, i.incident_date, i.event_date, i.time_of_day,
                       i.victims, i.evidence, i.evidence_ok, a.url, a.title, a.published_at,
                       (SELECT count(*) FROM incidents d WHERE d.duplicate_of = i.id) AS more_reports
                FROM incidents i JOIN articles a ON a.id = i.article_id
                WHERE {where} ORDER BY i.event_date DESC, i.id DESC LIMIT ?""", (*params, limit)).fetchall()
        gaz = load_gazetteer()
        out = []
        for r in rows:
            d = dict(r)
            p, t = gaz.get(d["place_id"]), gaz.get(d["thana_id"])
            d["place_bn"], d["place_en"] = (p.name_bn, p.name_en) if p else (None, None)
            d["thana_bn"], d["thana_en"] = (t.name_bn, t.name_en) if t else (None, None)
            out.append(d)
        return out

    @app.get("/api/stats")
    def stats(start: str | None = None, end: str | None = None, days: int | None = Query(None, ge=1, le=3650),
              categories: str | None = None, thana: str | None = None):
        where, params = filters(start, end, days, categories, thana)
        conn = db.connect()
        q = lambda sql: conn.execute(sql.format(w=where), params).fetchall()  # noqa: E731
        gaz = load_gazetteer()
        total = q("SELECT count(*) n, sum(victims) v, sum(lat IS NULL) unloc FROM incidents i WHERE {w}")[0]
        by_thana = []
        for r in q("""SELECT thana_id, count(*) n FROM incidents i WHERE {w} AND thana_id IS NOT NULL
                      GROUP BY thana_id ORDER BY n DESC LIMIT 15"""):
            p = gaz.get(r["thana_id"])
            cats = conn.execute(f"""SELECT category, count(*) n FROM incidents i WHERE {where} AND thana_id = ?
                                    GROUP BY category ORDER BY n DESC""", (*params, r["thana_id"])).fetchall()
            by_thana.append({"id": r["thana_id"], "name_bn": p.name_bn if p else r["thana_id"],
                             "name_en": p.name_en if p else r["thana_id"], "lat": p.lat if p else None,
                             "lng": p.lng if p else None, "count": r["n"],
                             "categories": {c["category"]: c["n"] for c in cats}})
        return {
            "total": total["n"], "victims": total["v"] or 0, "unlocated": total["unloc"] or 0,
            "by_category": {r["category"]: r["n"] for r in
                            q("SELECT category, count(*) n FROM incidents i WHERE {w} GROUP BY category")},
            "by_time_of_day": {r["time_of_day"]: r["n"] for r in
                               q("SELECT time_of_day, count(*) n FROM incidents i WHERE {w} GROUP BY time_of_day")},
            "by_day": [{"date": r["event_date"], "count": r["n"]} for r in
                       q("SELECT event_date, count(*) n FROM incidents i WHERE {w} GROUP BY event_date ORDER BY 1")],
            "by_thana": by_thana,
            "range": {"start": params[0], "end": params[1]},
        }

    @app.get("/api/runs")
    def runs(limit: int = Query(20, le=200)):
        return [dict(r) for r in db.connect().execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    @app.post("/api/scrape", status_code=202)
    def scrape(request: Request, days_back: int = Query(1, ge=0, le=30)):
        token = request.headers.get("x-admin-token", "")
        if settings.admin_token:
            if not hmac.compare_digest(token, settings.admin_token):
                raise HTTPException(401, "admin token required")
        elif request.client is None or request.client.host not in ("127.0.0.1", "::1", "localhost"):
            raise HTTPException(403, "set ADMIN_TOKEN to allow remote runs")
        if not start_run("manual", days_back):
            raise HTTPException(409, "a run is already in progress")
        return {"started": True}

    return app


app = create_app()
