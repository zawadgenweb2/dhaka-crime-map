"""Classifier service: claims queued articles, calls the model once, saves the answer, then maps incidents.

Cost and safety rules (from the Codex council review):
- A job is claimed with a lease (FOR UPDATE SKIP LOCKED); no two workers process the same article.
- Every paid call is recorded in llm_calls *before* it is sent and counted against a daily budget.
- The model's answer is saved (analyses) immediately; materializing incidents can be retried from it
  without another model call.
- If a worker dies after sending a call but before saving the answer, the job becomes 'uncertain' for
  review instead of being re-sent (we cannot know whether that call was billed).
- When the prompt cache is cold, only one call is sent first so the others reuse the cached prefix.
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import threading
import time
from datetime import datetime, timedelta

from psycopg.types.json import Jsonb

from . import db
from .classifiers import Classifier, ClassifierError, get_classifier
from .config import settings
from .gazetteer import Gazetteer, load as load_gazetteer
from .schema import ArticleAnalysis
from .scraper import DHAKA_TZ, Article
from .store import materialize, resolve_locations

log = logging.getLogger(__name__)
PAID_BACKENDS = {"claude"}
MAX_MATERIALIZE_ATTEMPTS = 3
RECOVERY_EVERY = 60


class CacheWarmGate:
    """Let one request warm the provider's prompt cache before the rest go out in parallel."""

    def __init__(self, ttl: float = 240):
        self.ttl, self.cv, self.last_ok, self.priming = ttl, threading.Condition(), 0.0, False

    def enter(self) -> bool:
        with self.cv:
            while True:
                if time.monotonic() - self.last_ok < self.ttl:
                    return False                  # cache warm: go ahead in parallel
                if not self.priming:
                    self.priming = True
                    return True                   # this request warms the cache
                self.cv.wait(timeout=30)

    def leave(self, primed: bool, ok: bool):
        with self.cv:
            if ok:
                self.last_ok = time.monotonic()
            if primed:
                self.priming = False
            self.cv.notify_all()


def dhaka_day_start() -> datetime:
    now = datetime.now(DHAKA_TZ)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def article_from_row(row: dict) -> Article:
    return Article(url=row["url"], section=row["section"] or "", title=row["title"] or "", body=row["body"] or "",
                   published_at=row["published_at"], keywords=row["keywords"] or "")


class Worker:
    def __init__(self, classifier: Classifier | None = None, gaz: Gazetteer | None = None,
                 use_geocoder: bool = True, owner: str | None = None):
        self._classifier = classifier
        self.gaz = gaz or load_gazetteer()
        self.use_geocoder = use_geocoder
        self.owner = owner or f"{socket.gethostname()}:{os.getpid()}"
        self.gate = CacheWarmGate()
        self.stop = threading.Event()
        self.paused_until = 0.0

    @property
    def classifier(self) -> Classifier:
        if self._classifier is None:
            self._classifier = get_classifier()
        return self._classifier

    # ---- queue -----------------------------------------------------------------------------
    def recover_expired(self) -> int:
        """Jobs whose lease ran out: requeue, unless a model call may have been billed without a saved answer."""
        n = 0
        with db.tx() as c:
            for job in c.execute("""SELECT id, article_id FROM jobs WHERE state = 'running' AND lease_until < now()
                                    FOR UPDATE SKIP LOCKED""").fetchall():
                in_flight = c.execute("""SELECT 1 FROM llm_calls WHERE job_id = %s AND outcome = 'sent'""",
                                      (job["id"],)).fetchone()
                saved = c.execute("SELECT 1 FROM analyses WHERE job_id = %s", (job["id"],)).fetchone()
                if in_flight and not saved:
                    c.execute("""UPDATE jobs SET state = 'uncertain', owner = NULL, updated_at = now(),
                                 last_error = 'worker stopped after sending a paid call; review before retrying'
                                 WHERE id = %s""", (job["id"],))
                    c.execute("UPDATE articles SET status = 'uncertain' WHERE id = %s", (job["article_id"],))
                else:
                    c.execute("""UPDATE jobs SET state = 'queued', owner = NULL, updated_at = now()
                                 WHERE id = %s""", (job["id"],))
                n += 1
        return n

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

    def calls_today(self, backend: str) -> int:
        with db.connect() as c:
            return c.execute("SELECT count(*) AS n FROM llm_calls WHERE backend = %s AND sent_at >= %s",
                             (backend, dhaka_day_start())).fetchone()["n"]

    # ---- one job ---------------------------------------------------------------------------
    def process(self, job: dict) -> str:
        with db.connect() as c:
            article = c.execute("SELECT * FROM articles WHERE id = %s", (job["article_id"],)).fetchone()
            saved = c.execute("""SELECT id, result FROM analyses WHERE job_id = %s ORDER BY id DESC LIMIT 1""",
                              (job["id"],)).fetchone()
        if article is None:
            self._release(job, "failed", "article missing")
            return "failed"

        if saved is None:
            backend = self.classifier.name.split(":", 1)[0]
            if job["dispatches"] >= job["max_dispatches"]:
                self._release(job, "failed", job["last_error"] or "model call limit reached")
                return "failed"
            limit = settings.max_llm_calls_per_day
            if backend in PAID_BACKENDS and limit and self.calls_today(backend) >= limit:
                tomorrow = dhaka_day_start() + timedelta(days=1)
                wait = (tomorrow - datetime.now(DHAKA_TZ)).total_seconds() / 60
                self._release(job, "queued", f"daily budget of {limit} calls reached", wait)
                log.warning("daily budget reached; job %s waits until %s", job["id"], tomorrow.isoformat())
                return "budget"
            with db.tx() as c:
                ok = c.execute("""UPDATE jobs SET dispatches = dispatches + 1, backend = %s
                                  WHERE id = %s AND generation = %s RETURNING id""",
                               (backend, job["id"], job["generation"])).fetchone()
                if not ok:
                    return "lost"  # lease expired and someone else owns it now
                call_id = c.execute("INSERT INTO llm_calls (job_id, backend) VALUES (%s, %s) RETURNING id",
                                    (job["id"], backend)).fetchone()["id"]
            primed = self.gate.enter() if backend in PAID_BACKENDS else False
            success = False
            try:
                analysis, meta = self.classifier.classify_with_meta(article_from_row(article))
                success = True
            except ClassifierError as e:
                self._call_failed(call_id, str(e))
                if e.permanent:  # bad key, bad config: stop spending attempts on every article
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
            finally:
                self.gate.leave(primed, success)
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

        return self._materialize(job, article, analysis_id, analysis)

    def _call_failed(self, call_id: int, error: str):
        with db.tx() as c:
            c.execute("UPDATE llm_calls SET outcome = 'error', error = %s, finished_at = now() WHERE id = %s",
                      (error[:500], call_id))

    def _materialize(self, job: dict, article: dict, analysis_id: int, analysis: ArticleAnalysis) -> str:
        try:
            geocoded = resolve_locations(analysis, self.gaz, self.use_geocoder)  # network, outside any transaction
            with db.tx() as c:
                owned = c.execute("SELECT 1 FROM jobs WHERE id = %s AND generation = %s FOR UPDATE",
                                  (job["id"], job["generation"])).fetchone()
                if not owned:
                    return "lost"
                materialize(c, article, analysis_id, analysis, self.classifier.name, self.gaz, geocoded)
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
                if self.run_once() is None:
                    self.stop.wait(5)
            except Exception:
                log.exception("worker iteration failed")
                self.stop.wait(10)

    def serve(self):
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        log.info("classifier worker %s using %s, %d threads", self.owner, self.classifier.name,
                 settings.classify_concurrency)
        threads = [threading.Thread(target=self._loop, name=f"classify-{i}", daemon=True)
                   for i in range(max(1, settings.classify_concurrency))]
        for t in threads:
            t.start()
        last_recovery = 0.0
        while not self.stop.is_set():
            if time.monotonic() - last_recovery > RECOVERY_EVERY:
                try:
                    if n := self.recover_expired():
                        log.warning("recovered %d expired jobs", n)
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
