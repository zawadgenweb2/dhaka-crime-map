"""Collector service: the only scheduler. Scrapes Prothom Alo and queues articles; never calls a model.

Singleton: holds a Postgres session advisory lock for its whole life; a second collector waits.
Schedule: one `schedule_slots` row per 08:00/20:00 Asia/Dhaka slot, so each slot runs once; a slot left
'running' by a crash is retried after restart. Manual "collect now" requests arrive via `run_requests`.
"""
from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import db
from .config import settings
from .gazetteer import Gazetteer, load as load_gazetteer
from .scheduler import next_run, previous_slot
from .scraper import CRIME_SECTIONS, DHAKA_TZ, Candidate, ProthomAloClient, belongs_to_dhaka, is_candidate
from .text import crime_signal

log = logging.getLogger(__name__)
COLLECTOR_LOCK = 7_000_003
TICK_SECONDS = 20
SLOT_ATTEMPTS = 3          # a failed scheduled run is retried this many times in total
SLOT_RETRY_MINUTES = 10


def discover(client, days_back: int, progress: Callable[[str], None]) -> list[Candidate]:
    found: dict[str, Candidate] = {}
    try:
        for c in client.news_sitemap():
            found[c.url] = c
    except Exception as e:  # daily sitemaps still give coverage
        progress(f"news sitemap failed: {e}")
    today = datetime.now(DHAKA_TZ).date()
    for i in range(days_back + 1):
        for c in client.daily_sitemap(today - timedelta(days=i)):
            found.setdefault(c.url, c)
    return list(found.values())


def collect(trigger: str, days_back: int = 1, client=None, gaz: Gazetteer | None = None,
            max_articles: int | None = None, progress: Callable[[str], None] | None = None) -> dict:
    """One scrape: discover → filter → fetch → store article → queue a classification job."""
    progress = progress or log.info
    client = client or ProthomAloClient()
    gaz = gaz or load_gazetteer()
    with db.tx() as c:
        run_id = c.execute("INSERT INTO runs (trigger, days_back) VALUES (%s, %s) RETURNING id",
                           (trigger, days_back)).fetchone()["id"]
    stats = {"discovered": 0, "fetched": 0, "queued": 0, "errors": 0}
    status, message = "ok", ""
    try:
        candidates = [c for c in discover(client, days_back, progress) if is_candidate(c, gaz)]
        with db.connect() as c:
            known = {r["url"] for r in c.execute("SELECT url FROM articles")}
        new = sorted((c for c in candidates if c.url not in known),
                     key=lambda c: c.published_at.timestamp() if c.published_at else 0, reverse=True)
        new = new[: max_articles or settings.max_articles_per_run]
        stats["discovered"] = len(new)
        with db.tx() as c:
            c.execute("UPDATE runs SET discovered = %s, candidates = %s WHERE id = %s",
                      (len(new), len(candidates), run_id))
        progress(f"run {run_id}: {len(candidates)} candidate links, {len(new)} new")
        for n, cand in enumerate(new, 1):
            if n % 10 == 0:  # progress is visible on the dashboard while a long backfill runs
                with db.tx() as c:
                    c.execute("UPDATE runs SET fetched = %s, queued = %s, errors = %s WHERE id = %s",
                              (stats["fetched"], stats["queued"], stats["errors"], run_id))
                db.heartbeat("collector", {"run_id": run_id, "fetched": stats["fetched"], "of": len(new)})
            try:
                art = client.article(cand.url)
            except Exception as e:
                stats["errors"] += 1
                progress(f"fetch failed {cand.url}: {e}")
                continue
            stats["fetched"] += 1
            art.published_at = art.published_at or cand.published_at
            art.keywords = art.keywords or cand.keywords
            text = f"{art.title}\n{art.keywords}\n{art.body}"
            # Stage 2 (full text). Entries that came without a title (daily sitemaps) get the title rule now.
            title_ok = bool(cand.title) or cand.section in CRIME_SECTIONS or crime_signal(f"{art.title} {art.keywords}") > 0
            in_dhaka = belongs_to_dhaka(cand.section, text, gaz)
            relevant = title_ok and crime_signal(text) > 0 and in_dhaka
            why = None if relevant else ("pre-filter: no crime word in the title" if not title_ok
                                         else "pre-filter: no Dhaka district place in the text" if not in_dhaka
                                         else "pre-filter: no crime word in the text")
            with db.tx() as c:
                row = c.execute(
                    """INSERT INTO articles (url, section, title, keywords, body, published_at, status, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (url) DO NOTHING RETURNING id""",
                    (cand.url, art.section, art.title, art.keywords, art.body, art.published_at,
                     "queued" if relevant else "skipped", why),
                ).fetchone()
                if row and relevant:
                    c.execute("""INSERT INTO jobs (article_id, backend, run_id) VALUES (%s, %s, %s)
                                 ON CONFLICT (article_id, analysis_version) DO NOTHING""",
                              (row["id"], settings.classifier, run_id))
                    stats["queued"] += 1
    except Exception as e:
        status, message = "failed", f"{type(e).__name__}: {e}"
        log.exception("collection run %s failed", run_id)
    message = message or f"{stats['fetched']} fetched, {stats['queued']} queued for classification"
    with db.tx() as c:
        c.execute("""UPDATE runs SET finished_at = now(), status = %s, discovered = %s, fetched = %s, queued = %s,
                     errors = %s, message = %s WHERE id = %s""",
                  (status, stats["discovered"], stats["fetched"], stats["queued"], stats["errors"], message[:500],
                   run_id))
    progress(f"run {run_id} {status}: {message}")
    return {"run_id": run_id, "status": status, "message": message, **stats}


class Collector:
    def __init__(self):
        self.stop = False

    def _acquire_singleton(self):
        conn = db.connect(autocommit=True)
        while not self.stop:
            if conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (COLLECTOR_LOCK,)).fetchone()["ok"]:
                log.info("collector lock acquired")
                return conn
            log.info("another collector is active; waiting")
            time.sleep(15)
        return None

    def _plan_slots(self):
        now = datetime.now(timezone.utc)
        prev, nxt = previous_slot(now), next_run(now)
        with db.tx() as c:
            for slot in (prev, nxt):
                c.execute("INSERT INTO schedule_slots (scheduled_for) VALUES (%s) ON CONFLICT DO NOTHING", (slot,))
            # Never backfill a pile of old slots: the news sitemap covers ~48 h anyway.
            c.execute("""UPDATE schedule_slots SET status = 'skipped', updated_at = now()
                         WHERE status = 'pending' AND scheduled_for < now() - interval '13 hours'""")
        return nxt

    def _run_slot(self):
        with db.tx() as c:
            slot = c.execute("""SELECT scheduled_for, attempts FROM schedule_slots WHERE status = 'pending'
                                AND scheduled_for <= now() AND (next_try_at IS NULL OR next_try_at <= now())
                                ORDER BY scheduled_for DESC LIMIT 1""").fetchone()
            if not slot:
                return False
            c.execute("""UPDATE schedule_slots SET status = 'running', attempts = attempts + 1, updated_at = now()
                         WHERE scheduled_for = %s""", (slot["scheduled_for"],))
        result = collect("schedule", days_back=1)
        ok = result["status"] == "ok"
        retry = not ok and slot["attempts"] + 1 < SLOT_ATTEMPTS
        with db.tx() as c:
            c.execute("""UPDATE schedule_slots SET status = %s, run_id = %s, updated_at = now(),
                         next_try_at = CASE WHEN %s THEN now() + make_interval(mins => %s) END
                         WHERE scheduled_for = %s""",
                      ("done" if ok else ("pending" if retry else "failed"), result["run_id"], retry,
                       SLOT_RETRY_MINUTES, slot["scheduled_for"]))
        if retry:
            log.warning("scheduled run failed; retrying in %d minutes", SLOT_RETRY_MINUTES)
        return True

    def _run_request(self):
        with db.tx() as c:
            req = c.execute("""SELECT id, days_back, max_articles FROM run_requests WHERE status = 'pending'
                               ORDER BY id LIMIT 1""").fetchone()
            if not req:
                return False
            c.execute("UPDATE run_requests SET status = 'running' WHERE id = %s", (req["id"],))
        result = collect("manual", days_back=req["days_back"], max_articles=req["max_articles"])
        with db.tx() as c:
            c.execute("UPDATE run_requests SET status = %s, run_id = %s WHERE id = %s",
                      ("done" if result["status"] == "ok" else "failed", result["run_id"], req["id"]))
        return True

    def serve(self):
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "stop", True))
        lock_conn = self._acquire_singleton()
        if lock_conn is None:
            return
        with db.tx() as c:  # we are the only collector, so anything 'running' was interrupted by a crash
            c.execute("UPDATE schedule_slots SET status = 'pending' WHERE status = 'running'")
            c.execute("UPDATE run_requests SET status = 'pending' WHERE status = 'running'")
            c.execute("""UPDATE runs SET status = 'interrupted', finished_at = now()
                         WHERE status = 'running'""")
        while not self.stop:
            try:
                lock_conn.execute("SELECT 1")  # lost connection = lost lock → exit and let Docker restart us
            except Exception:
                log.error("lost the collector lock connection; exiting")
                raise SystemExit(1)
            try:
                nxt = self._plan_slots()
                db.heartbeat("collector", {"next_run": nxt.isoformat()})
                while not self.stop and (self._run_request() or self._run_slot()):
                    db.heartbeat("collector", {"next_run": nxt.isoformat()})
            except Exception:
                log.exception("collector tick failed")
            for _ in range(TICK_SECONDS):
                if self.stop:
                    break
                time.sleep(1)
        lock_conn.close()
