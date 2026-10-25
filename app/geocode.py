"""Exact-spot geocoding with OpenStreetMap Nominatim, cached in SQLite.

A geocode is only trusted when it lands close to the gazetteer place the model chose,
which guards against namesakes elsewhere in Bangladesh.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from . import db
from .config import settings

log = logging.getLogger(__name__)
URL = "https://nominatim.openstreetmap.org/search"
VIEWBOX = "90.10,24.00,90.60,23.55"  # Dhaka district (lon/lat corners)
_lock = threading.Lock()
_last = [0.0]


def geocode(query: str) -> tuple[float, float] | None:
    q = " ".join(query.split())[:200]
    if not q or not settings.geocode_enabled:
        return None
    conn = db.connect()
    row = conn.execute("SELECT lat, lng FROM geocache WHERE query = ?", (q,)).fetchone()
    if row:
        return (row["lat"], row["lng"]) if row["lat"] is not None else None
    with _lock:  # Nominatim policy: at most 1 request per second
        wait = 1.1 - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
        try:
            r = httpx.get(URL, params={"q": q, "format": "jsonv2", "limit": 1, "viewbox": VIEWBOX, "bounded": 1,
                                       "countrycodes": "bd"},
                          headers={"User-Agent": settings.user_agent}, timeout=20)
            r.raise_for_status()
            hits = r.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("geocode failed for %r: %s", q, e)
            return None  # not cached, so it is retried next time
    hit = hits[0] if hits else None
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?,?,?)",
                  (q, float(hit["lat"]) if hit else None, float(hit["lon"]) if hit else None,
                   hit.get("display_name") if hit else None, db.now()))
    return (float(hit["lat"]), float(hit["lon"])) if hit else None
