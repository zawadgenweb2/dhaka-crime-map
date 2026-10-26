"""Exact-spot geocoding with OpenStreetMap Nominatim, cached in Postgres.

Nominatim's policy for scheduled scripts is at most 4 requests per minute from one machine, single thread.
All containers share one lane: a row in `rate_limits` is locked while a request is made, so lookups are
serialized system-wide and spaced GEOCODE_MIN_INTERVAL_SECONDS apart (default 15 s).

Callers must not hold a database transaction open while calling geocode().
"""
from __future__ import annotations

import logging
import time

import httpx

from . import db
from .config import settings

log = logging.getLogger(__name__)
VIEWBOX = "90.10,24.00,90.60,23.55"  # Dhaka district (lon/lat corners)
LANE = "nominatim"


def _cached(q: str):
    with db.connect() as c:
        return c.execute("SELECT lat, lng FROM geocache WHERE query = %s", (q,)).fetchone()


def geocode(query: str) -> tuple[float, float] | None:
    q = " ".join((query or "").split())[:200]
    if not q or not settings.geocode_enabled:
        return None
    row = _cached(q)
    if row:
        return (row["lat"], row["lng"]) if row["lat"] is not None else None

    with db.tx() as c:
        # Lock the shared lane; other workers wait here instead of calling Nominatim in parallel.
        lane = c.execute("SELECT extract(epoch FROM clock_timestamp() - last_at) AS waited FROM rate_limits "
                         "WHERE name = %s FOR UPDATE", (LANE,)).fetchone()
        # Someone may have resolved the same query while we waited for the lock.
        hit = c.execute("SELECT lat, lng FROM geocache WHERE query = %s", (q,)).fetchone()
        if hit:
            return (hit["lat"], hit["lng"]) if hit["lat"] is not None else None
        wait = settings.geocode_min_interval - float(lane["waited"] if lane else 1e9)
        if wait > 0:
            time.sleep(wait)
        try:
            r = httpx.get(settings.nominatim_url,
                          params={"q": q, "format": "jsonv2", "limit": 1, "viewbox": VIEWBOX, "bounded": 1,
                                  "countrycodes": "bd"},
                          headers={"User-Agent": settings.user_agent}, timeout=20)
            r.raise_for_status()
            hits = r.json()
        except (httpx.HTTPError, ValueError) as e:
            c.execute("UPDATE rate_limits SET last_at = clock_timestamp() WHERE name = %s", (LANE,))
            log.warning("geocode failed for %r: %s", q, e)
            return None  # not cached, so a later attempt can retry
        c.execute("UPDATE rate_limits SET last_at = clock_timestamp() WHERE name = %s", (LANE,))
        top = hits[0] if hits else None
        c.execute("""INSERT INTO geocache (query, lat, lng, display) VALUES (%s, %s, %s, %s)
                     ON CONFLICT (query) DO NOTHING""",
                  (q, float(top["lat"]) if top else None, float(top["lon"]) if top else None,
                   top.get("display_name") if top else None))
    return (float(top["lat"]), float(top["lon"])) if top else None
