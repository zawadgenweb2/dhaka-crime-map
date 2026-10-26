"""Classifier service: claims queued articles, calls the model once, saves the answer, then maps incidents.

Safety rules (from the Codex council reviews). The model is the in-house Gemma server; there are no paid calls.
- A job is claimed with a lease (FOR UPDATE SKIP LOCKED); no two workers process the same job.
- Only the article's current analysis version may write incidents (articles.analysis_version), so an older
  job finishing late can never replace newer output; a dismissed article is never re-published.
- A saved answer is reused only if it came from the same model family and is not legacy data.
- Exact-spot geocoding runs in its own thread after publication, so the 15 s Nominatim lane never stalls the GPU.
- Every model call is recorded in llm_calls *before* it is sent (audit trail, at most max_dispatches per job).
- The model's answer is saved (analyses) immediately; materializing incidents can be retried from it
  without another model call.
- A job whose worker died mid-call is simply requeued once its lease expires.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from psycopg.types.json import Jsonb

from . import db
from .classifiers import Classifier, ClassifierError, get_classifier
from .config import settings
from .gazetteer import Gazetteer, load as load_gazetteer
from .schema import ArticleAnalysis
from .scraper import Article
from .store import build_rows, enrich_next, materialize

log = logging.getLogger(__name__)
MAX_MATERIALIZE_ATTEMPTS = 3
RECOVERY_EVERY = 60


def article_from_row(row: dict) -> Article:
    return Article(url=row["url"], section=row["section"] or "", title=row["title"] or "", body=row["body"] or "",
                   published_at=row["published_at"], keywords=row["keywords"] or "")


class Worker:
    def __init__(self, classifier: Classifier | None = None, gaz: Gazetteer | None = None,
                 use_geocoder: bool = True, owner: str | None = None):
        self._classifier = classifier
        self.gaz = gaz or load_gazetteer()
        self.use_geocoder = use_geocoder  # run the exact-spot geocoding thread in serve()
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"
        self.stop = threading.Event()
        self.paused_until = 0.0

    @property
    def classifier(self) -> Classifier:
        if self._classifier is None:
            self._classifier = get_classifier()
        return self._classifier

    # ---- queue -----------------------------------------------------------------------------
    def recover_expired(self) -> int:
        """Jobs whose lease ran out (worker died or hung): requeue them; a saved answer is reused, not recomputed."""
        with db.tx() as c:
            rows = c.execute("""UPDATE jobs SET state = 'queued', owner = NULL, updated_at = now()
                                WHERE id IN (SELECT id FROM jobs WHERE state = 'running' AND lease_until < now()
                                             FOR UPDATE SKIP LOCKED) RETURNING id""").fetchall()
            c.execute("""UPDATE llm_calls SET outcome = 'error', error = 'worker stopped', finished_at = now()
                         WHERE outcome = 'sent' AND job_id = ANY(%s)""", ([r["id"] for r in rows],))
        return len(rows)

    def claim(self) -> dict | None:
        with db.tx() as c:
            return c.execute(
                """WITH next AS (SELECT id FROM jobs WHERE state = 'queued' AND available_at <= now()
                                 ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT 1)
                   UPDATE jobs j SET state = 'running', owner = %s, generation = j.generation + 1,
                          lease_until = now() + make_interval(mins => %s), updated_at = now()
                   FROM next WHERE j.id = next.id RETURNING j.*""",
                (self.owner, settings.job_lease_minutes)).fetchone()

    def _release(self, job: dict, state: str, error: str | None = None, delay_minutes: float = 0):
        with db.tx() as c:
            c.execute("""UPDATE jobs SET state = %s, owner = NULL, last_error = %s, updated_at = now(),
                         available_at = now() + make_interval(secs => %s)
                         WHERE id = %s AND generation = %s""",
                      (state, (error or "")[:500] or None, delay_minutes * 60, job["id"], job["generation"]))
            if state in ("failed", "uncertain"):
                c.execute("UPDATE articles SET status = %s, error = %s WHERE id = %s",
                          (state, (error or "")[:500], job["article_id"]))

    # ---- one job ---------------------------------------------------------------------------
    def process(self, job: dict) -> str:
        with db.connect() as c:
            article = c.execute("SELECT * FROM articles WHERE id = %s", (job["article_id"],)).fetchone()
            saved = c.execute("""SELECT id, result, backend, model, legacy FROM analyses WHERE job_id = %s
                                 ORDER BY id DESC LIMIT 1""", (job["id"],)).fetchone()
        if article is None:
            self._release(job, "failed", "article missing")
            return "failed"
        if article["status"] == "dismissed" or job["analysis_version"] != article["analysis_version"]:
            self._release(job, "superseded", "article dismissed or a newer analysis version exists")
            return "superseded"
        backend = self.classifier.name.split(":", 1)[0]
        if saved is not None and (saved["legacy"] or saved["backend"] != backend):
            self._release(job, "failed", f"saved answer is from {saved['backend']}, not {backend}; not reused")
            return "failed"

        if saved is None:
            label = self.classifier.name
            if job["dispatches"] >= job["max_dispatches"]:
                self._release(job, "failed", job["last_error"] or "model call limit reached")
                return "failed"
            with db.tx() as c:
                ok = c.execute("""UPDATE jobs SET dispatches = dispatches + 1, backend = %s
                                  WHERE id = %s AND generation = %s RETURNING id""",
                               (backend, job["id"], job["generation"])).fetchone()
                if not ok:
                    return "lost"  # lease expired and someone else owns it now
                call_id = c.execute("INSERT INTO llm_calls (job_id, backend) VALUES (%s, %s) RETURNING id",
                                    (job["id"], backend)).fetchone()["id"]
            try:
                analysis, meta = self.classifier.classify_with_meta(article_from_row(article))
            except ClassifierError as e:
                self._call_failed(call_id, str(e))
                if e.permanent:  # bad key or model alias: pause instead of failing every article
                    self.paused_until = time.monotonic() + 600
                    self._release(job, "queued", str(e), 10)
                    log.error("classifier misconfigured, pausing 10 min: %s", e)
                    return "paused"
                done = job["dispatches"] + 1 >= job["max_dispatches"]
                self._release(job, "failed" if done else "queued", str(e), 0 if done else 2 ** job["dispatches"])
                return "failed" if done else "retry"
            except Exception as e:  # unexpected backend bug
                self._call_failed(call_id, f"{type(e).__name__}: {e}")
                self._release(job, "failed", f"{type(e).__name__}: {e}")
                return "failed"
            with db.tx() as c:
                c.execute("UPDATE llm_calls SET outcome = 'ok', finished_at = now() WHERE id = %s", (call_id,))
                analysis_id = c.execute(
                    """INSERT INTO analyses (article_id, job_id, llm_call_id, backend, model, result, input_tokens,
                         cache_read_tokens, cache_write_tokens, output_tokens, cost_usd)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (article["id"], job["id"], call_id, backend, meta.get("model"), Jsonb(analysis.model_dump()),
                     meta.get("input_tokens"), meta.get("cache_read_tokens"), meta.get("cache_write_tokens"),
                     meta.get("output_tokens"), meta.get("cost_usd"))).fetchone()["id"]
        else:
            analysis_id = saved["id"]
            analysis = ArticleAnalysis.model_validate(saved["result"])
            label = f"{saved['backend']}:{saved['model']}" if saved["model"] else saved["backend"]

        return self._materialize(job, article, analysis_id, analysis, label)

    def _call_failed(self, call_id: int, error: str):
        with db.tx() as c:
            c.execute("UPDATE llm_calls SET outcome = 'error', error = %s, finished_at = now() WHERE id = %s",
                      (error[:500], call_id))

    def _materialize(self, job: dict, article: dict, analysis_id: int, analysis: ArticleAnalysis,
                     label: str) -> str:
        try:
            with db.tx() as c:
                owned = c.execute("""SELECT 1 FROM jobs WHERE id = %s AND generation = %s AND state = 'running'
                                     AND owner = %s FOR UPDATE""",
                                  (job["id"], job["generation"], self.owner)).fetchone()
                if not owned:
                    return "lost"
                current = c.execute("SELECT status, analysis_version FROM articles WHERE id = %s FOR UPDATE",
                                    (article["id"],)).fetchone()
                if current["status"] == "dismissed" or current["analysis_version"] != job["analysis_version"]:
                    c.execute("""UPDATE jobs SET state = 'superseded', owner = NULL, updated_at = now()
                                 WHERE id = %s""", (job["id"],))
                    return "superseded"
                materialize(c, article, analysis_id, analysis, label, self.gaz)
                c.execute("""UPDATE jobs SET state = 'done', owner = NULL, last_error = NULL, updated_at = now()
                             WHERE id = %s""", (job["id"],))
            return "done"
        except Exception as e:
            log.exception("materialize failed for job %s", job["id"])
            with db.tx() as c:
                row = c.execute("""UPDATE jobs SET materialize_attempts = materialize_attempts + 1
                                   WHERE id = %s AND generation = %s RETURNING materialize_attempts""",
                                (job["id"], job["generation"])).fetchone()
            attempts = row["materialize_attempts"] if row else MAX_MATERIALIZE_ATTEMPTS
            done = attempts >= MAX_MATERIALIZE_ATTEMPTS
            # The saved analysis stays; a retry never calls the model again.
            self._release(job, "failed" if done else "queued", f"materialize: {type(e).__name__}: {e}",
                          0 if done else 2)
            return "failed" if done else "retry"

    # ---- "try an article" previews (POST /api/classify) -------------------------------------
    def run_preview(self) -> bool:
        """Answer one pasted article. Nothing is written to articles, analyses or incidents."""
        with db.tx() as c:
            p = c.execute("""UPDATE previews SET status = 'running', started_at = now()
                             WHERE id = (SELECT id FROM previews WHERE status = 'queued' ORDER BY id
                                         FOR UPDATE SKIP LOCKED LIMIT 1)
                             RETURNING id, input""").fetchone()
        if p is None:
            return False
        try:
            result, status, error = preview_result(self.classifier, p["input"], self.gaz), "done", None
        except Exception as e:
            result, status, error = None, "failed", f"{type(e).__name__}: {e}"[:500]
        with db.tx() as c:
            c.execute("UPDATE previews SET status = %s, result = %s, error = %s, finished_at = now() WHERE id = %s",
                      (status, Jsonb(result) if result is not None else None, error, p["id"]))
        return True

    # ---- service loop ------------------------------------------------------------------------
    def run_once(self) -> str | None:
        job = self.claim()
        if job is None:
            return None
        return self.process(job)

    def drain(self, max_jobs: int = 1000) -> dict:
        """Process queued jobs until none are left (used by tests and the CLI)."""
        counts: dict[str, int] = {}
        for _ in range(max_jobs):
            outcome = self.run_once()
            if outcome is None:
                break
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    def _loop(self):
        while not self.stop.is_set():
            if time.monotonic() < self.paused_until:
                self.stop.wait(15)
                continue
            try:
                if self.run_preview():      # someone is waiting in Swagger: answer first
                    continue
                if self.run_once() is None:
                    self.stop.wait(2)
            except Exception:
                log.exception("worker iteration failed")
                self.stop.wait(10)

    def _geocode_loop(self):
        """Exact spots for published incidents, one at a time through the shared Nominatim lane."""
        while not self.stop.is_set():
            try:
                state = enrich_next(self.gaz)
                if state is None:
                    self.stop.wait(20)
                elif state == "error":
                    self.stop.wait(60)
            except Exception:
                log.exception("geocode enrichment failed")
                self.stop.wait(60)

    def serve(self):
        if not self.classifier.name.startswith("gemma"):
            # The rules classifier exists for tests and offline comparison only; it never feeds the live map.
            raise SystemExit(f"the live classifier must be the in-house Gemma model, not {self.classifier.name}")
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        log.info("classifier worker %s using %s, %d threads", self.owner, self.classifier.name,
                 settings.classify_concurrency)
        threads = [threading.Thread(target=self._loop, name=f"classify-{i}", daemon=True)
                   for i in range(max(1, settings.classify_concurrency))]
        if self.use_geocoder and settings.geocode_enabled:
            threads.append(threading.Thread(target=self._geocode_loop, name="geocode", daemon=True))
        for t in threads:
            t.start()
        last_recovery = 0.0
        while not self.stop.is_set():
            if time.monotonic() - last_recovery > RECOVERY_EVERY:
                try:
                    if n := self.recover_expired():
                        log.warning("recovered %d expired jobs", n)
                    with db.tx() as c:  # previews: give up on stuck ones, keep a week of history
                        c.execute("""UPDATE previews SET status = 'failed', error = 'worker stopped',
                                     finished_at = now() WHERE status = 'running'
                                     AND started_at < now() - interval '10 minutes'""")
                        c.execute("DELETE FROM previews WHERE created_at < now() - interval '7 days'")
                    with db.connect() as c:
                        q = {r["state"]: r["n"] for r in
                             c.execute("SELECT state, count(*) AS n FROM jobs GROUP BY state")}
                    db.heartbeat("classifier", {"backend": self.classifier.name, "queue": q})
                except Exception:
                    log.exception("recovery/heartbeat failed")
                last_recovery = time.monotonic()
            self.stop.wait(5)
        for t in threads:
            t.join(timeout=30)


def preview_result(classifier: Classifier, inp: dict, gaz: Gazetteer) -> dict:
    """What the pipeline would do with one pasted article: Gemma's raw answer, then the same automatic checks."""
    from datetime import datetime
    from .classifiers.base import candidate_places
    from .scraper import DHAKA_TZ
    pub = datetime.fromisoformat(inp["published_at"]) if inp.get("published_at") else datetime.now(DHAKA_TZ)
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=DHAKA_TZ)
    art = Article(url=inp.get("url") or "preview", section=inp.get("section") or "", title=inp["title"],
                  body=inp["body"], published_at=pub, keywords=inp.get("keywords") or "")
    started = time.monotonic()
    analysis, meta = classifier.classify_with_meta(art)
    row = {"id": 0, "title": art.title, "body": art.body, "keywords": art.keywords, "published_at": pub,
           "fetched_at": pub}
    checked = []
    for r in build_rows(row, analysis, gaz, {}, settings.publish_mode):
        place, thana = gaz.get(r["place_id"]), gaz.get(r["thana_id"])
        checked.append({
            "category": r["category"], "headline_en": r["headline_en"], "location_text": r["location_text"],
            "place_id": r["place_id"], "place": f"{place.name_bn} / {place.name_en}" if place else None,
            "thana": f"{thana.name_bn} / {thana.name_en}" if thana else None, "lat": r["lat"], "lng": r["lng"],
            "precision": r["precision"], "incident_date": r["incident_date"].isoformat() if r["incident_date"] else None,
            "time_of_day": r["time_of_day"], "victims": r["victims"], "evidence_in_article": r["evidence_ok"],
            "place_named_in_article": r["located_in_dhaka"],
            "would_be_published": r["published"], "exact_spot_lookup": r["geocode_query"]})
    return {
        "classifier": classifier.name, "model": meta.get("model"), "seconds": round(time.monotonic() - started, 2),
        "tokens": {"input": meta.get("input_tokens"), "output": meta.get("output_tokens")},
        "place_candidates_sent": [p.id for p in candidate_places(art)],
        "gemma_answer": analysis.model_dump(),
        "after_checks": checked,
        "saved": False,
    }
