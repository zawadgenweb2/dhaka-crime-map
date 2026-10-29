"""Public site: the map and read-only data. No admin routes, no API docs, no operational or model metadata.

Each incident is a safe summary: crime type, date, time of day, area-level place, and the newspaper link. No verbatim
quotes, no model headlines, no victim counts. Sexual-violence cases appear only in totals (never as a point or a link).
Responses are compressed and briefly cacheable; /api/version tells the page when the data changed.
"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from fastapi import FastAPI, Query, Response
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .api import STATIC, _filters, _iso
from .config import settings
from .gazetteer import load as load_gazetteer
from .schema import CATEGORIES, DISTRICTS, DIVISIONS, TIME_OF_DAY, TOTALS_ONLY
from .scraper import DHAKA_TZ
from .sources import source_for_url

# Never a point, feed item or link on the public site; still counted in totals.
AREA_TOTALS_ONLY = TOTALS_ONLY               # from the category list: never a point, link or heat
CACHE = "public, max-age=30"


def _publisher(url: str | None) -> tuple[str | None, str | None, str | None]:
    if not url:
        return None, None, None
    src = source_for_url(url)       # only links to the registered papers are ever returned
    if urlsplit(url).scheme != "https" or src is None:
        return None, None, None
    return url, src.name_bn, src.name_en


def create_public_app() -> FastAPI:
    app = FastAPI(title="Bangladesh Crime Map", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def headers(request, call_next):
        r = await call_next(request)
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")   # tile servers need the origin
        r.headers.setdefault("X-Frame-Options", "DENY")
        return r

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/health")
    def health():
        with db.connect() as c:
            c.execute("SELECT 1")
        return {"ok": True, "version": settings.version}

    @app.get("/api/config")
    def config(response: Response):
        """Labels and lists for the page (categories, times of day, areas, map key)."""
        gaz = load_gazetteer()
        response.headers["Cache-Control"] = "public, max-age=300"
        return {
            "categories": [{"key": k, **v} for k, v in CATEGORIES.items()],
            "time_of_day": [{"key": k, **v} for k, v in TIME_OF_DAY.items()],
            "divisions": [{"id": k, **v, "bounds": gaz.bounds(division=k)} for k, v in DIVISIONS.items()],
            "districts": [{"id": k, **v, "bounds": gaz.bounds(k)} for k, v in DISTRICTS.items()],
            "all_bounds": gaz.bounds(),
            "thanas": [p.to_dict() for p in gaz.places if p.kind in ("thana", "upazila")],
            "area_totals_only": sorted(AREA_TOTALS_ONLY),
            "google_maps_api_key": settings.google_maps_api_key,
            "google_maps_map_id": settings.google_maps_map_id,
        }

    @app.get("/api/version")
    def version(response: Response):
        """Changes whenever the published data changes; the page reloads data only then."""
        with db.connect() as c:
            rev = c.execute("SELECT rev, changed_at FROM data_revision").fetchone()
        response.headers["Cache-Control"] = "public, max-age=10"
        return {"data_version": str(rev["rev"]), "updated_at": _iso(rev["changed_at"]),
                "today": datetime.now(DHAKA_TZ).date().isoformat()}

    @app.get("/api/incidents")
    def incidents(response: Response, start: str | None = None, end: str | None = None,
                  days: int | None = Query(None, ge=1, le=366), categories: str | None = None,
                  thana: str | None = None, district: str | None = None, division: str | None = None,
                  limit: int = Query(10000, ge=1, le=20000)):
        """Published incidents as safe summaries (no quotes, headlines or victim counts)."""
        where, params, _, _ = _filters(start, end, days, categories, thana, district, division)
        where += " AND NOT (i.category = ANY(%s))"
        params = [*params, sorted(AREA_TOTALS_ONLY)]
        with db.connect() as c:
            total = c.execute(f"SELECT count(*) n FROM incidents i WHERE {where}", params).fetchone()["n"]
            rows = c.execute(
                f"""SELECT i.id, i.category, i.district_id, i.place_id, i.thana_id, i.lat, i.lng, i.precision, i.geocoded,
                           i.event_date, i.time_of_day, a.url, a.published_at,
                           (CASE WHEN EXISTS (SELECT 1 FROM app_flags f WHERE f.key = 'events_live' AND f.value = '1')
                            THEN coalesce((SELECT e.report_count - 1 FROM events e WHERE e.primary_incident_id = i.id
                                           AND e.state = 'active'), 0)
                            ELSE (SELECT count(*) FROM incidents d WHERE d.duplicate_of = i.id AND d.published) END)
                           AS more_reports
                    FROM incidents i JOIN articles a ON a.id = i.article_id
                    WHERE {where} ORDER BY i.event_date DESC, i.id DESC LIMIT %s""", (*params, limit)).fetchall()
        response.headers.update({"X-Total-Count": str(total), "X-Truncated": "true" if total > limit else "false",
                                 "Cache-Control": CACHE})
        gaz = load_gazetteer()
        out = []
        for d in rows:
            p, t = gaz.get(d["place_id"]), gaz.get(d["thana_id"])
            url, pub_bn, pub_en = _publisher(d.pop("url"))
            out.append({**{k: _iso(v) for k, v in d.items()},
                        "place_bn": p.name_bn if p else None, "place_en": p.name_en if p else None,
                        "thana_bn": t.name_bn if t else None, "thana_en": t.name_en if t else None,
                        "url": url, "publisher_bn": pub_bn, "publisher_en": pub_en})
        return out

    @app.get("/api/stats")
    def stats(response: Response, start: str | None = None, end: str | None = None,
              days: int | None = Query(None, ge=1, le=366), categories: str | None = None, thana: str | None = None,
              district: str | None = None, division: str | None = None):
        """Totals for the same filters (all categories, including those shown only as totals)."""
        where, params, start_d, end_d = _filters(start, end, days, categories, thana, district, division)
        gaz = load_gazetteer()
        with db.connect() as c:
            def q(sql):
                return c.execute(sql.format(w=where), params).fetchall()
            total = q("SELECT count(*) n, count(*) FILTER (WHERE lat IS NULL) unloc FROM incidents i WHERE {w}")[0]
            by_thana_rows = q("""SELECT thana_id, category, count(*) n FROM incidents i WHERE {w} AND thana_id IS NOT NULL
                                 GROUP BY thana_id, category""")
        thanas: dict[str, dict] = {}
        for r in by_thana_rows:
            t = thanas.setdefault(r["thana_id"], {"count": 0, "categories": {}})
            t["count"] += r["n"]
            t["categories"][r["category"]] = r["n"]
        by_thana = []
        for tid, t in sorted(thanas.items(), key=lambda kv: -kv[1]["count"])[:15]:
            p = gaz.get(tid)
            by_thana.append({"id": tid, "name_bn": p.name_bn if p else tid, "name_en": p.name_en if p else tid,
                             "lat": p.lat if p else None, "lng": p.lng if p else None, **t})
        with db.connect() as c:
            by_category = {r["category"]: r["n"] for r in c.execute(
                f"SELECT category, count(*) n FROM incidents i WHERE {where} GROUP BY category", params)}
            by_tod = {r["time_of_day"]: r["n"] for r in c.execute(
                f"SELECT time_of_day, count(*) n FROM incidents i WHERE {where} GROUP BY time_of_day", params)}
            by_day = [{"date": r["event_date"].isoformat(), "count": r["n"]} for r in c.execute(
                f"SELECT event_date, count(*) n FROM incidents i WHERE {where} GROUP BY event_date ORDER BY 1", params)]
            by_district = {r["district_id"]: r["n"] for r in c.execute(
                f"""SELECT district_id, count(*) n FROM incidents i WHERE {where} AND district_id IS NOT NULL
                    GROUP BY district_id""", params)}
        by_division: dict[str, int] = {}
        for k, n in by_district.items():
            if k in DISTRICTS:
                dv = DISTRICTS[k]["division"]
                by_division[dv] = by_division.get(dv, 0) + n
        response.headers["Cache-Control"] = CACHE
        return {"total": total["n"], "unlocated": total["unloc"], "by_category": by_category, "by_time_of_day": by_tod,
                "by_day": by_day, "by_thana": by_thana,
                "by_district": [{"id": k, **DISTRICTS[k], "count": n} for k, n in
                                sorted(by_district.items(), key=lambda kv: -kv[1]) if k in DISTRICTS],
                "by_division": [{"id": k, **DIVISIONS[k], "count": n} for k, n in
                                sorted(by_division.items(), key=lambda kv: -kv[1])], "range": {"start": start_d.isoformat(), "end": end_d.isoformat()}}

    return app


app = create_public_app()
