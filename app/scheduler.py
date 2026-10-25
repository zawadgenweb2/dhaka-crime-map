"""Runs collection at fixed Asia/Dhaka times (SCRAPE_TIMES, default 08:00 and 20:00)."""
from __future__ import annotations

import logging
import threading
from datetime import datetime, time, timedelta

from . import db
from .config import settings
from .scraper import DHAKA_TZ

log = logging.getLogger(__name__)


def _times() -> list[time]:
    out = []
    for t in settings.scrape_times:
        h, m = t.split(":")
        out.append(time(int(h), int(m)))
    return sorted(out)


def next_run(after: datetime) -> datetime:
    after = after.astimezone(DHAKA_TZ)
    for day in range(2):
        d = after.date() + timedelta(days=day)
        for t in _times():
            candidate = datetime.combine(d, t, DHAKA_TZ)
            if candidate > after:
                return candidate
    raise RuntimeError("no scrape times configured")


def previous_slot(now: datetime) -> datetime:
    now = now.astimezone(DHAKA_TZ)
    slots = [datetime.combine(now.date() - timedelta(days=d), t, DHAKA_TZ) for d in (0, 1) for t in _times()]
    return max(s for s in slots if s <= now)


class Scheduler:
    def __init__(self, run_fn):
        self.run_fn = run_fn
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self.next_at: datetime | None = None

    def start(self):
        self.thread.start()

    def _missed(self) -> bool:
        row = db.connect().execute("SELECT max(started_at) AS t FROM runs WHERE status != 'failed'").fetchone()
        if not row["t"]:
            return True
        return datetime.fromisoformat(row["t"]) < previous_slot(datetime.now(DHAKA_TZ))

    def _loop(self):
        if self._missed():
            log.info("scheduler: last slot was missed, running catch-up in 30s")
            if self.stop.wait(30):
                return
            self._run("catch-up")
        while not self.stop.is_set():
            self.next_at = next_run(datetime.now(DHAKA_TZ))
            log.info("scheduler: next run at %s", self.next_at.isoformat())
            while not self.stop.is_set():
                remaining = (self.next_at - datetime.now(DHAKA_TZ)).total_seconds()
                if remaining <= 0:
                    break
                self.stop.wait(min(remaining, 60))
            if not self.stop.is_set():
                self._run("schedule")

    def _run(self, trigger: str):
        try:
            self.run_fn(trigger)
        except Exception:
            log.exception("scheduled run failed")
