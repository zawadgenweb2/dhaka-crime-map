"""One collection run: discover -> filter -> fetch -> classify -> locate -> store."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import db
from .classifiers import Classifier, ClassifierError, get_classifier
from .config import settings
from .gazetteer import Gazetteer, distance_km, load as load_gazetteer
from .geocode import geocode
from .schema import CATEGORIES, ArticleAnalysis
from .scraper import DHAKA_TZ, Article, Candidate, ProthomAloClient, is_candidate
from .text import crime_signal, normalize

log = logging.getLogger(__name__)
RUN_LOCK = threading.Lock()
MAX_ATTEMPTS = 3
GEOCODE_MAX_KM = 2.5  # how far an exact geocode may sit from the chosen gazetteer place


class RunInProgress(RuntimeError):
    pass


def is_running() -> bool:
    """True if a run is active in this process or (per the runs table) in another one."""
    if RUN_LOCK.locked():
        return True
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    return bool(db.connect().execute("SELECT 1 FROM runs WHERE status='running' AND started_at > ?",
                                     (cutoff,)).fetchone())


def _row_to_article(row) -> Article:
    pub = datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
    return Article(url=row["url"], section=row["section"] or "", title=row["title"] or "", body=row["body"] or "",
                   published_at=pub, keywords=row["keywords"] or "")


def locate(inc, gaz: Gazetteer, use_geocoder: bool = True) -> dict:
    """Resolve an incident to coordinates. Gazetteer first; exact geocode only if it agrees."""
    place = gaz.get(inc.place_id) or gaz.best_match(inc.location_text or "")
    out = {"place_id": None, "thana_id": None, "lat": None, "lng": None, "geocoded": 0,
           "precision": inc.precision}
    if place is not None:
        thana = gaz.thana_of(place)
        out.update(place_id=place.id, thana_id=thana.id, lat=place.lat, lng=place.lng)
        # Precision describes the point we actually plot, not what the article named.
        out["precision"] = {"landmark": "exact", "area": "neighbourhood"}.get(place.kind, "thana")
    elif inc.precision != "city":
        out["precision"] = "city"
    if use_geocoder and inc.geocode_query and place is not None:
        hit = geocode(inc.geocode_query)
        if hit and distance_km(hit, (place.lat, place.lng)) <= GEOCODE_MAX_KM:
            out.update(lat=hit[0], lng=hit[1], geocoded=1, precision="exact")
    return out


def _find_duplicate(conn, article_id: int, category: str, thana_id: str | None, event_date: str | None):
    """Same category, same thana, event dates within a day, from another article = same event."""
    if not thana_id or not event_date:
        return None
    day = datetime.fromisoformat(event_date).date()
    row = conn.execute(
        """SELECT id FROM incidents WHERE article_id != ? AND category = ? AND thana_id = ?
           AND event_date BETWEEN ? AND ? AND duplicate_of IS NULL ORDER BY id LIMIT 1""",
        (article_id, category, thana_id, (day - timedelta(days=1)).isoformat(), (day + timedelta(days=1)).isoformat()),
    ).fetchone()
    return row["id"] if row else None


def store_analysis(conn, article_id: int, article: Article, analysis: ArticleAnalysis, classifier: str,
                   gaz: Gazetteer, use_geocoder: bool = True) -> int:
    conn.execute("""UPDATE incidents SET duplicate_of = NULL WHERE duplicate_of IN
                    (SELECT id FROM incidents WHERE article_id = ?)""", (article_id,))
    conn.execute("DELETE FROM incidents WHERE article_id = ?", (article_id,))
    body_norm = normalize(f"{article.title} {article.body}")
    pub_day = article.published_at.astimezone(DHAKA_TZ).date() if article.published_at else None
    stored = 0
    if analysis.in_dhaka:
        for inc in analysis.incidents:
            if inc.category not in CATEGORIES:
                continue
            loc = locate(inc, gaz, use_geocoder)
            incident_date = inc.incident_date
            try:
                d = datetime.fromisoformat(incident_date).date() if incident_date else None
                if d and pub_day and (d > pub_day + timedelta(days=1)):
                    d = None  # a date after publication is a model error
            except ValueError:
                d = None
            incident_date = d.isoformat() if d else None
            event_date = incident_date or (pub_day.isoformat() if pub_day else None)
            ev = normalize(inc.evidence or "")
            evidence_ok = int(len(ev) >= 8 and ev in body_norm)
            dup = _find_duplicate(conn, article_id, inc.category, loc["thana_id"], event_date)
            conn.execute(
                """INSERT INTO incidents (article_id, category, headline_bn, headline_en, location_text, place_id,
                   thana_id, lat, lng, precision, geocoded, incident_date, event_date, time_of_day, victims,
                   evidence, evidence_ok, duplicate_of, classifier, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (article_id, inc.category, inc.headline_bn, inc.headline_en, inc.location_text, loc["place_id"],
                 loc["thana_id"], loc["lat"], loc["lng"], loc["precision"], loc["geocoded"], incident_date,
                 event_date, inc.time_of_day, max(0, inc.victims), inc.evidence, evidence_ok, dup, classifier,
                 db.now()))
            stored += 1
    conn.execute("""UPDATE articles SET status='classified', classifier=?, note=?, error=NULL, classified_at=?
                    WHERE id=?""", (classifier, analysis.note[:500], db.now(), article_id))
    return stored


class Pipeline:
    def __init__(self, client: ProthomAloClient | None = None, classifier: Classifier | None = None,
                 gazetteer: Gazetteer | None = None, use_geocoder: bool = True,
                 progress: Callable[[str], None] | None = None):
        self.client = client or ProthomAloClient()
        self._classifier = classifier
        self.gaz = gazetteer or load_gazetteer()
        self.use_geocoder = use_geocoder
        self.progress = progress or (lambda msg: log.info(msg))

    @property
    def classifier(self) -> Classifier:
        if self._classifier is None:
            self._classifier = get_classifier()
        return self._classifier

    # -- discovery ---------------------------------------------------------------------------
    def discover(self, days_back: int = 1) -> list[Candidate]:
        found: dict[str, Candidate] = {}
        try:
            for c in self.client.news_sitemap():
                found[c.url] = c
        except Exception as e:  # keep going with the daily sitemaps
            self.progress(f"news sitemap failed: {e}")
        today = datetime.now(DHAKA_TZ).date()
        for i in range(days_back + 1):
            for c in self.client.daily_sitemap(today - timedelta(days=i)):
                found.setdefault(c.url, c)
        return list(found.values())

    # -- the run ------------------------------------------------------------------------------
    def run(self, trigger: str = "manual", days_back: int = 1, max_articles: int | None = None) -> dict:
        if not RUN_LOCK.acquire(blocking=False):
            raise RunInProgress("A collection run is already in progress")
        conn = db.connect()
        # Another process (CLI vs server) may be running; rows older than 3h are treated as crashed.
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
        if conn.execute("SELECT 1 FROM runs WHERE status='running' AND started_at > ?", (cutoff,)).fetchone():
            RUN_LOCK.release()
            raise RunInProgress("A collection run is already in progress in another process")
        stats = {"discovered": 0, "fetched": 0, "classified": 0, "incidents": 0, "errors": 0}
        with db.tx() as c:
            run_id = c.execute("INSERT INTO runs (trigger, started_at, status) VALUES (?,?,?)",
                               (trigger, db.now(), "running")).lastrowid
        status, message = "ok", ""
        try:
            candidates = [c for c in self.discover(days_back) if is_candidate(c, self.gaz)]
            known = {r[0] for r in conn.execute("SELECT url FROM articles")}
            new = [c for c in candidates if c.url not in known]
            new.sort(key=lambda c: c.published_at.timestamp() if c.published_at else 0, reverse=True)
            new = new[: max_articles or settings.max_articles_per_run]
            stats["discovered"] = len(new)
            self.progress(f"{len(candidates)} candidate links, {len(new)} new")

            for i, c in enumerate(new, 1):
                try:
                    art = self.client.article(c.url)
                except Exception as e:
                    stats["errors"] += 1
                    self.progress(f"fetch failed {c.url}: {e}")
                    continue
                stats["fetched"] += 1
                art.published_at = art.published_at or c.published_at
                art.keywords = art.keywords or c.keywords
                text = f"{art.title}\n{art.keywords}\n{art.body}"
                relevant = crime_signal(text) > 0 and self.gaz.mentions_dhaka(text)
                with db.tx() as tc:
                    tc.execute("""INSERT OR IGNORE INTO articles (url, section, title, keywords, body, published_at,
                                  fetched_at, status, note) VALUES (?,?,?,?,?,?,?,?,?)""",
                               (c.url, art.section, art.title, art.keywords, art.body,
                                art.published_at.isoformat() if art.published_at else None, db.now(),
                                "pending" if relevant else "skipped",
                                None if relevant else "pre-filter: no Dhaka crime signal"))
                if i % 10 == 0:
                    self.progress(f"fetched {i}/{len(new)}")

            done, found, errors = self.classify_pending()
            stats["classified"], stats["incidents"] = done, found
            stats["errors"] += errors
            message = f"{done} articles classified, {found} incidents"
        except Exception as e:
            status, message = "failed", f"{type(e).__name__}: {e}"
            log.exception("run failed")
        finally:
            with db.tx() as c:
                c.execute("""UPDATE runs SET finished_at=?, status=?, discovered=?, fetched=?, classified=?,
                             incidents=?, errors=?, message=? WHERE id=?""",
                          (db.now(), status, stats["discovered"], stats["fetched"], stats["classified"],
                           stats["incidents"], stats["errors"], message[:500], run_id))
            RUN_LOCK.release()
        self.progress(f"run {run_id} {status}: {message}")
        return {"run_id": run_id, "status": status, "message": message, **stats}

    def classify_pending(self, limit: int = 500, reclassify: bool = False) -> tuple[int, int, int]:
        conn = db.connect()
        where = "status IN ('pending','error','classified')" if reclassify else \
                "status = 'pending' OR (status = 'error' AND attempts < ?)"
        params = () if reclassify else (MAX_ATTEMPTS,)
        rows = conn.execute(f"SELECT * FROM articles WHERE {where} ORDER BY published_at DESC LIMIT ?",
                            (*params, limit)).fetchall()
        if not rows:
            return 0, 0, 0
        classifier = self.classifier
        self.progress(f"classifying {len(rows)} articles with {classifier.name}")
        done = found = errors = 0

        def work(row):
            return row, classifier.classify(_row_to_article(row))

        with ThreadPoolExecutor(max_workers=max(1, settings.classify_workers)) as pool:
            futures = [pool.submit(work, r) for r in rows]
            for f in as_completed(futures):
                try:
                    row, analysis = f.result()
                except Exception as e:  # ClassifierError, or anything unexpected from a backend
                    errors += 1
                    row = rows[futures.index(f)]
                    with db.tx() as c:
                        c.execute("UPDATE articles SET status='error', error=?, attempts=attempts+1 WHERE id=?",
                                  (str(e)[:500], row["id"]))
                    self.progress(f"classify failed: {e}")
                    continue
                with db.tx() as c:
                    n = store_analysis(c, row["id"], _row_to_article(row), analysis, classifier.name, self.gaz,
                                       self.use_geocoder)
                done += 1
                found += n
                if done % 5 == 0:
                    self.progress(f"classified {done}/{len(rows)} ({found} incidents)")
        return done, found, errors
