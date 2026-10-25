"""Schedule arithmetic for the collector: fixed Asia/Dhaka wall-clock slots (SCRAPE_TIMES)."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from .config import settings
from .scraper import DHAKA_TZ


def _times(times: list[str] | None = None) -> list[time]:
    out = []
    for t in times or settings.scrape_times:
        h, m = t.split(":")
        out.append(time(int(h), int(m)))
    return sorted(out)


def next_run(after: datetime, times: list[str] | None = None) -> datetime:
    after = after.astimezone(DHAKA_TZ)
    for day in range(2):
        d = after.date() + timedelta(days=day)
        for t in _times(times):
            candidate = datetime.combine(d, t, DHAKA_TZ)
            if candidate > after:
                return candidate
    raise RuntimeError("no scrape times configured")


def previous_slot(now: datetime, times: list[str] | None = None) -> datetime:
    now = now.astimezone(DHAKA_TZ)
    slots = [datetime.combine(now.date() - timedelta(days=d), t, DHAKA_TZ) for d in (0, 1) for t in _times(times)]
    return max(s for s in slots if s <= now)
