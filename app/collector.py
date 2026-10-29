"""Collector service: the only scheduler. Scrapes the newspapers and queues articles; never calls a model.

Each paper is its own lane (robots.txt, 1 request/second) and the lanes run in parallel, so five papers take about
as long as the slowest one. Gemma's traffic is controlled by the job queue, not here.

Singleton: holds a Postgres session advisory lock for its whole life; a second collector waits.
Schedule: one `schedule_slots` row per 08:00/20:00 Asia/Dhaka slot, so each slot runs once; a slot left
'running' by a crash is retried after restart. Manual "collect now" requests arrive via `run_requests`.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import db
from .config import settings
from .gazetteer import Gazetteer, load as load_gazetteer
from .scheduler import next_run, previous_slot
from .scraper import DHAKA_TZ, Candidate, NewsClient, belongs_to_districts, is_candidate
from .sources import SOURCES, enabled_sources
from .text import crime_signal

log = logging.getLogger(__name__)
COLLECTOR_LOCK = 7_000_003
FRESH, BACKFILL = 0, 2      # job priority: Gemma reads fresh news before history
EXTRACT_FAIL_RUN, EXTRACT_FAIL_SHARE = 8, 0.4   # text-less pages that mean "the paper's layout changed"
TICK_SECONDS = 20
SLOT_ATTEMPTS = 3          # a failed scheduled run is retried this many times in total
SLOT_RETRY_MINUTES = 10


def discover(client, days_back: int, progress: Callable[[str], None],
             by_day: dict | None = None) -> list[Candidate]:
    """News sitemap (~48 h, with titles) plus the archive: one daily sitemap per day, or every monthly sitemap the
    window touches (read whole; such papers have no per-day coverage). `by_day` receives each day's full list
    (for coverage); a URL in both keeps the news-sitemap entry, which has the title."""
    found: dict[str, Candidate] = {}
    try:
        for c in client.news_sitemap():
            found[c.url] = c
    except Exception as e:  # daily sitemaps still give coverage
        progress(f"news sitemap failed: {e}")
    today = datetime.now(DHAKA_TZ).date()
    monthly = getattr(getattr(client, "source", None), "archive", None) == "monthly"
    start = today - timedelta(days=days_back)
    if monthly:
        month = start.replace(day=1)
        while month <= today:
            for c in client.monthly_sitemap(month):
                # lastmod >= publication, so an entry last edited before the window was published before it
                if c.published_at is None or c.published_at.astimezone(DHAKA_TZ).date() >= start:
                    found.setdefault(c.url, c)
            month = (month + timedelta(days=32)).replace(day=1)
    for i in range(days_back + 1) if not monthly else ():
        day = today - timedelta(days=i)
        items = client.daily_sitemap(day)
        if by_day is not None:
            by_day[day] = items
        for c in items:
            found.setdefault(c.url, c)
    if by_day is not None:
        for day, items in by_day.items():
            by_day[day] = [found[c.url] for c in items]
    return list(found.values())


def record_coverage(by_day: dict, gaz: Gazetteer, run_id: int, source: str = "prothomalo") -> None:
    """Remember, per day, every URL the daily sitemap listed and whether it passed stage 1. Candidates are sticky:
    a URL once seen as a candidate (e.g. from a titled news-sitemap entry) stays one. The day's status is computed
    from these URLs' articles at read time (see api /api/coverage)."""
    if not by_day:
        return
    with db.tx() as c:
        for day, items in by_day.items():
            for x in items:
                c.execute("""INSERT INTO coverage_urls (day, url, candidate) VALUES (%s, %s, %s)
                             ON CONFLICT (day, url) DO UPDATE SET candidate = coverage_urls.candidate OR EXCLUDED.candidate""",
                          (day, x.url, is_candidate(x, gaz)))
            c.execute("""INSERT INTO coverage_days (source, day, links, candidates, missing, run_id, checked_at)
                         VALUES (%s, %s, %s, 0, 0, %s, now())
                         ON CONFLICT (source, day) DO UPDATE SET links = GREATEST(coverage_days.links, EXCLUDED.links),
                           run_id = EXCLUDED.run_id, checked_at = now()""", (source, day, len(items), run_id))
        db.bump_revision(c)


def collect(trigger: str, days_back: int = 1, client=None, gaz: Gazetteer | None = None,
            max_articles: int | None = None, progress: Callable[[str], None] | None = None,
            sources: list[str] | None = None) -> dict:
    """One scrape of every enabled paper (or `sources`), one lane per paper in parallel:
    discover → filter → fetch → store article → queue a classification job.

    Window: Asia/Dhaka publication dates from today minus `days_back` to today (the dashboard's "N days" view is
    days_back = N - 1). Archive sitemaps list updated old articles too; anything published before the window is
    stored as skipped ('outside the window') and not sent to Gemma. `max_articles` caps each paper's downloads.
    `client` (tests) replaces the lanes with one client for one paper."""
    progress = progress or log.info
    gaz = gaz or load_gazetteer()
    with db.tx() as c:
        run_id = c.execute("INSERT INTO runs (trigger, days_back) VALUES (%s, %s) RETURNING id",
                           (trigger, days_back)).fetchone()["id"]
    stats = {"discovered": 0, "candidates": 0, "fetched": 0, "queued": 0, "errors": 0}
    lock = threading.Lock()
    window_start = datetime.now(DHAKA_TZ).date() - timedelta(days=days_back)   # fixed for the whole run
    if client is not None:
        lanes = [(getattr(getattr(client, "source", None), "key", "prothomalo"), client)]
    else:
        keys = [s.key for s in enabled_sources() if sources is None or s.key in sources]
        with db.connect() as c:                 # papers that refused us recently are left alone
            resting = {r["source"]: r for r in c.execute(
                "SELECT source, not_before, reason FROM source_state WHERE not_before > now()")}
        for k in keys:
            if k in resting:
                progress(f"[{k}] skipped: cooling down until {resting[k]['not_before']:%Y-%m-%d %H:%M} UTC "
                         f"({resting[k]['reason']})")
        lanes = [(k, NewsClient(SOURCES[k])) for k in keys if k not in resting]

    def flush():
        with lock, db.tx() as c:
            c.execute("""UPDATE runs SET discovered = %s, candidates = %s, fetched = %s, queued = %s, errors = %s
                         WHERE id = %s""", (stats["discovered"], stats["candidates"], stats["fetched"],
                                            stats["queued"], stats["errors"], run_id))

    def lane(key: str, cl) -> str | None:
        """One paper; returns an error message, or None."""
        say = lambda m: progress(f"[{key}] {m}")                                       # noqa: E731
        by_day: dict = {}
        error = None
        try:
            _collect_source(key, cl, days_back, gaz, window_start, run_id, by_day, stats, lock, flush,
                            max_articles or settings.max_articles_per_run, say,
                            FRESH if trigger == "schedule" or days_back <= 1 else BACKFILL)
        except Exception as e:
            error = f"{key}: {type(e).__name__}: {e}"
            log.exception("collection run %s failed for %s", run_id, key)
        refused = getattr(cl, "blocked", None)
        if refused is not None and getattr(refused, "cooldown_until", None):
            with db.tx() as c:
                c.execute("""INSERT INTO source_state (source, not_before, reason) VALUES (%s, %s, %s)
                             ON CONFLICT (source) DO UPDATE SET not_before = EXCLUDED.not_before,
                               reason = EXCLUDED.reason, updated_at = now()""",
                          (key, refused.cooldown_until, str(refused)[:300]))
        try:
            record_coverage(by_day, gaz, run_id, key)
        except Exception as e:  # never leave stale "complete" days behind a silent failure
            log.exception("coverage bookkeeping failed for run %s (%s)", run_id, key)
            error = error or f"{key}: coverage bookkeeping failed: {type(e).__name__}: {e}"
        return error

    with ThreadPoolExecutor(max_workers=max(1, len(lanes)), thread_name_prefix="lane") as pool:
        errors = [e for e in pool.map(lambda kc: lane(*kc), lanes) if e]
    status = "failed" if errors else "ok"      # a slot with a failed paper is retried; done papers' URLs are skipped
    message = (f"{stats['fetched']} fetched, {stats['queued']} queued for classification"
               + (f"; failed: {'; '.join(errors)}" if errors else ""))
    with db.tx() as c:
        c.execute("""UPDATE runs SET finished_at = now(), status = %s, discovered = %s, candidates = %s, fetched = %s,
                     queued = %s, errors = %s, message = %s WHERE id = %s""",
                  (status, stats["discovered"], stats["candidates"], stats["fetched"], stats["queued"],
                   stats["errors"] + len(errors), message[:500], run_id))
    progress(f"run {run_id} {status}: {message}")
    return {"run_id": run_id, "status": status, "message": message, **stats}


def _collect_source(key, client, days_back, gaz, window_start, run_id, by_day, stats, lock, flush, cap, progress,
                    priority=FRESH):
    candidates = [c for c in discover(client, days_back, progress, by_day) if is_candidate(c, gaz)]
    with db.connect() as c:
        known = {r["url"] for r in c.execute("SELECT url FROM articles WHERE url = ANY(%s)",
                                             ([x.url for x in candidates],))}
    new = sorted((c for c in candidates if c.url not in known),
                 key=lambda c: c.published_at.timestamp() if c.published_at else 0, reverse=True)[:cap]
    with lock:
        stats["discovered"] += len(new)
        stats["candidates"] += len(candidates)
    flush()
    progress(f"run {run_id}: {len(candidates)} candidate links, {len(new)} new")
    src = SOURCES.get(key)
    crime_sections = src.crime_sections if src else frozenset()
    no_text = no_text_in_a_row = downloads = 0
    for n, cand in enumerate(new, 1):
        if n % 10 == 0:  # progress is visible on the dashboard while a long backfill runs
            flush()
            db.heartbeat("collector", {"run_id": run_id, "fetched": stats["fetched"]})
        if getattr(client, "blocked", False):     # the paper refused us repeatedly: stop asking it this run
            raise RuntimeError(f"{key} refused our requests (HTTP 403); stopped for this run")
        try:
            art = client.article(cand.url)
        except ValueError as e:   # the page downloaded but has no article text (gallery, style page)
            downloads += 1; no_text += 1; no_text_in_a_row += 1
            with db.tx() as c:
                c.execute("""INSERT INTO articles (url, section, source, status, note) VALUES (%s, %s, %s, 'skipped', %s)
                             ON CONFLICT (url) DO NOTHING""", (cand.url, cand.section, key, f"no article text: {e}"[:200]))
            progress(f"no article text {cand.url}: {e}")
            # Many text-less pages in a row usually means the paper changed its page layout: stop, so the failure is
            # visible instead of quietly marking every article skipped (fix sources.py, then requeue-no-text).
            if no_text_in_a_row >= EXTRACT_FAIL_RUN or (downloads >= 25 and no_text / downloads > EXTRACT_FAIL_SHARE):
                raise RuntimeError(f"{key}: {no_text} of {downloads} pages had no article text; "
                                   "page layout probably changed (check body_selectors in sources.py)")
            continue
        except Exception as e:    # network or server problem: try again next run
            with lock:
                stats["errors"] += 1
            progress(f"fetch failed {cand.url}: {e}")
            continue
        downloads += 1; no_text_in_a_row = 0
        with lock:
            stats["fetched"] += 1
        art.published_at = art.published_at or cand.published_at
        outside = bool(art.published_at) and art.published_at.astimezone(DHAKA_TZ).date() < window_start
        art.keywords = art.keywords or cand.keywords
        text = f"{art.title}\n{art.keywords}\n{art.body}"
        # Stage 2 (full text). Entries that came without a title (archive sitemaps) get the title rule now.
        title_ok = (cand.section in crime_sections or crime_signal(f"{cand.title} {cand.keywords}") > 0
                    or crime_signal(f"{art.title} {art.keywords}") > 0)
        in_scope = belongs_to_districts(cand.section, text, gaz)
        relevant = not outside and title_ok and crime_signal(text) > 0 and in_scope
        why = None if relevant else ("outside the window" if outside
                                     else "pre-filter: no crime word in the title" if not title_ok
                                     else "pre-filter: no place in Bangladesh in the text" if not in_scope
                                     else "pre-filter: no crime word in the text")
        with db.tx() as c:
            row = c.execute(
                """INSERT INTO articles (url, section, source, title, keywords, body, published_at, status, note)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (url) DO NOTHING RETURNING id""",
                (cand.url, art.section, key, art.title, art.keywords, art.body, art.published_at,
                 "queued" if relevant else "skipped", why),
            ).fetchone()
            if row and relevant:
                c.execute("""INSERT INTO jobs (article_id, backend, run_id, priority) VALUES (%s, %s, %s, %s)
                             ON CONFLICT (article_id, analysis_version) DO NOTHING""",
                          (row["id"], settings.classifier, run_id, priority))
                with lock:
                    stats["queued"] += 1


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
