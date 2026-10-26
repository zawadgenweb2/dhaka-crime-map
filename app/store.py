"""Turning a saved model analysis into map incidents, and grouping duplicate reports.

Order of work (no network call happens inside a database transaction):
  1. materialize():  one short transaction that replaces the article's incidents (located on the gazetteer place)
                     and rebuilds the affected duplicate groups, serialized by an advisory lock.
  2. enrich_next():  later, one incident at a time, an exact-spot geocode through the shared Nominatim lane
                     (1 request / 15 s) moves the point to the named street/building if it agrees with the place.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import db
from .config import settings
from .gazetteer import Gazetteer, distance_km
from .geocode import geocode, is_cached
from .schema import CATEGORIES, ArticleAnalysis, Incident
from .scraper import DHAKA_TZ
from .text import normalize

GEOCODE_MAX_KM = 2.5            # an exact geocode must sit this close to the chosen gazetteer place
MATERIALIZE_LOCK = 7_000_002    # serializes duplicate grouping across workers
EARLIEST = date(2000, 1, 1)


# ---- locations ---------------------------------------------------------------------------------
def _fallback_place(inc: Incident, gaz: Gazetteer, source_text: str | None):
    """No usable place_id: match the location phrase, but only if that phrase really is in the article."""
    phrase = inc.location_text or ""
    if source_text is not None and normalize(phrase) not in normalize(source_text):
        return None
    return gaz.best_match(phrase)


def locate(inc: Incident, gaz: Gazetteer, geocoded: dict[str, tuple[float, float] | None] | None = None,
           source_text: str | None = None) -> dict:
    """Gazetteer first; an exact geocode is used only if it agrees with the chosen place."""
    place = gaz.get(inc.place_id) or _fallback_place(inc, gaz, source_text)
    out = {"place_id": None, "thana_id": None, "lat": None, "lng": None, "geocoded": False, "precision": "city"}
    if place is None:
        return out
    thana = gaz.thana_of(place)
    out.update(place_id=place.id, thana_id=thana.id, lat=place.lat, lng=place.lng,
               precision={"landmark": "exact", "area": "neighbourhood"}.get(place.kind, "thana"))
    hit = (geocoded or {}).get(inc.geocode_query or "")
    if hit and distance_km(hit, (place.lat, place.lng)) <= GEOCODE_MAX_KM:
        out.update(lat=hit[0], lng=hit[1], geocoded=True, precision="exact")
    return out


# ---- dates & evidence --------------------------------------------------------------------------
def publication_day(published_at: datetime | None) -> date | None:
    return published_at.astimezone(DHAKA_TZ).date() if published_at else None


def clean_incident_date(value: str | None, pub_day: date | None) -> date | None:
    """Drop impossible dates: unparseable, before 2000, or after the publication day (Asia/Dhaka)."""
    if not value:
        return None
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return None
    if d < EARLIEST or (pub_day and d > pub_day):
        return None
    return d


def evidence_ok(evidence: str | None, title: str, body: str) -> bool:
    ev = normalize(evidence or "")
    return len(ev) >= 8 and ev in normalize(f"{title} {body}")


# ---- duplicate grouping ------------------------------------------------------------------------
def _same_event(a: dict, b: dict) -> bool:
    """Two reports describe one event: same category and specific place, dates ±1 day, compatible time."""
    if a["article_id"] == b["article_id"]:
        return False
    if a["category"] != b["category"] or not a["place_id"] or a["place_id"] != b["place_id"]:
        return False
    if not a["event_date"] or not b["event_date"] or abs((a["event_date"] - b["event_date"]).days) > 1:
        return False
    ta, tb = a["time_of_day"] or "unknown", b["time_of_day"] or "unknown"
    return ta == tb or "unknown" in (ta, tb)


def rebuild_groups(conn, keys: set[tuple]) -> int:
    """Recompute duplicate_of for the whole (category, place) partition of each key.

    Whole partitions, not date windows: a window can cut a chain (A <- B) and wrongly make B canonical.
    Unpublished incidents never take part in grouping."""
    changed = 0
    for category, place_id in {(k[0], k[1]) for k in keys}:
        conn.execute("""UPDATE incidents SET duplicate_of = NULL WHERE NOT published AND category = %s
                        AND place_id = %s AND duplicate_of IS NOT NULL""", (category, place_id))
        rows = conn.execute(
            """SELECT id, article_id, category, place_id, event_date, time_of_day, duplicate_of FROM incidents
               WHERE published AND category = %s AND place_id = %s ORDER BY event_date, id""",
            (category, place_id)).fetchall()
        canon: list[dict] = []
        for r in rows:
            target = next((c["id"] for c in canon if _same_event(c, r)), None)
            if target is None:
                canon.append(r)
            if r["duplicate_of"] != target:
                conn.execute("UPDATE incidents SET duplicate_of = %s WHERE id = %s", (target, r["id"]))
                changed += 1
    return changed


# ---- materialize -------------------------------------------------------------------------------
def build_rows(article: dict, analysis: ArticleAnalysis, gaz: Gazetteer,
               geocoded: dict[str, tuple[float, float] | None], publish_mode: str | None = None) -> list[dict]:
    publish_mode = publish_mode or settings.publish_mode
    pub_day = publication_day(article["published_at"])
    fetched_day = publication_day(article.get("fetched_at"))
    upper = pub_day or fetched_day or datetime.now(DHAKA_TZ).date()   # never accept dates in the future
    consistent = analysis.is_crime_report and analysis.in_dhaka
    rows = []
    if not consistent:
        return rows
    source = f"{article['title'] or ''}\n{article.get('keywords') or ''}\n{article['body'] or ''}"
    grounded = gaz.grounded_places(source)                   # Dhaka places the article really names
    elsewhere = gaz.lead_in_other_district(article["body"] or "")
    seen = set()
    for inc in analysis.incidents:
        if inc.category not in CATEGORIES:
            continue
        same = tuple(" ".join(str(v).split()) for v in inc.model_dump().values())
        if same in seen:  # the model repeated an identical incident; distinct events are never merged here
            continue
        seen.add(same)
        loc = locate(inc, gaz, geocoded, source)
        inc_date = clean_incident_date(inc.incident_date, upper)
        quoted = evidence_ok(inc.evidence, article["title"] or "", article["body"] or "")
        # Auto-publishing also needs a located incident whose place (or its thana) the article itself names, and a
        # lead that does not put the story in another district. Gemma's in_dhaka alone is not enough.
        # Where the article describes this incident (location phrase + the quote's sentence and its neighbours)
        # must name the place or say রাজধানী/ঢাকা, and the quote's own sentence must not put it in another
        # district. A place named only elsewhere in the article (e.g. a victim's home) is not enough.
        local, capital, conflict = gaz.incident_support(article["body"] or "", inc.location_text, inc.evidence)
        in_dhaka = bool(loc["place_id"]) and (loc["place_id"] in grounded or loc["thana_id"] in grounded) \
            and (loc["place_id"] in local or loc["thana_id"] in local or capital) and not conflict and not elsewhere
        ok = quoted and in_dhaka
        rows.append({
            **loc, "category": inc.category, "headline_bn": inc.headline_bn, "headline_en": inc.headline_en,
            "location_text": inc.location_text, "incident_date": inc_date, "event_date": inc_date or pub_day or fetched_day or upper,
            "time_of_day": inc.time_of_day, "victims": max(0, inc.victims), "evidence": inc.evidence,
            # passes = automatic checks OK. Published now only in auto mode; review mode waits for a human.
            "evidence_ok": quoted, "located_in_dhaka": in_dhaka, "passes": ok,
            "published": ok and publish_mode == "auto",
            "review_status": ("auto" if publish_mode == "auto" else "pending") if ok else "failed",
            "geocode_query": inc.geocode_query if inc.geocode_query and loc["place_id"] else None,
            "geocode_state": "todo" if inc.geocode_query and loc["place_id"] and not loc["geocoded"] else "none",
        })
    return rows


def materialize(conn, article: dict, analysis_id: int | None, analysis: ArticleAnalysis, classifier: str,
                gaz: Gazetteer, geocoded: dict | None = None) -> int:
    """Replace the article's incidents atomically. Caller owns the transaction (conn.transaction())."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
    old = conn.execute("SELECT category, place_id, event_date FROM incidents WHERE article_id = %s",
                       (article["id"],)).fetchall()
    keys = {(r["category"], r["place_id"], r["event_date"]) for r in old if r["place_id"] and r["event_date"]}
    conn.execute("DELETE FROM incidents WHERE article_id = %s", (article["id"],))
    rows = build_rows(article, analysis, gaz, geocoded or {})
    for r in rows:
        conn.execute(
            """INSERT INTO incidents (article_id, analysis_id, category, headline_bn, headline_en, location_text,
                 place_id, thana_id, lat, lng, precision, geocoded, incident_date, event_date, time_of_day, victims,
                 evidence, evidence_ok, published, review_status, classifier, geocode_query, geocode_state)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (article["id"], analysis_id, r["category"], r["headline_bn"], r["headline_en"], r["location_text"],
             r["place_id"], r["thana_id"], r["lat"], r["lng"], r["precision"], r["geocoded"], r["incident_date"],
             r["event_date"], r["time_of_day"], r["victims"], r["evidence"], r["evidence_ok"], r["published"],
             r["review_status"], classifier, r["geocode_query"], r["geocode_state"]))
        if r["place_id"] and r["event_date"]:
            keys.add((r["category"], r["place_id"], r["event_date"]))
    rebuild_groups(conn, keys)
    conn.execute("""UPDATE articles SET status = 'classified', classifier = %s, note = %s, error = NULL,
                    classified_at = now() WHERE id = %s""", (classifier, (analysis.note or "")[:500], article["id"]))
    if analysis_id:
        conn.execute("UPDATE analyses SET materialized_at = now() WHERE id = %s", (analysis_id,))
    db.bump_revision(conn)
    return len(rows)


# ---- exact-spot geocoding after publication --------------------------------------------------------
def enrich_next(gaz: Gazetteer) -> str | None:
    """Geocode the newest waiting incident. Returns its new state, 'error' (try later) or None (nothing waiting).

    The update is conditional: if the incident was replaced, re-located by a reviewer or already handled
    meanwhile, nothing is overwritten."""
    with db.connect() as c:
        row = c.execute("""SELECT id, analysis_id, place_id, geocode_query FROM incidents
                           WHERE geocode_state = 'todo' ORDER BY id DESC LIMIT 1""").fetchone()
    if row is None:
        return None
    place = gaz.get(row["place_id"])
    if place is None or not settings.geocode_enabled:
        state, hit = "miss", None
    else:
        hit = geocode(row["geocode_query"])                       # may wait on the shared lane; no transaction open
        if hit is None and not is_cached(row["geocode_query"]):
            return "error"                                        # network problem: leave it waiting
        state = "miss" if hit is None else (
            "done" if distance_km(hit, (place.lat, place.lng)) <= GEOCODE_MAX_KM else "far")
    with db.tx() as c:
        if state == "done":
            n = c.execute("""UPDATE incidents SET lat = %s, lng = %s, geocoded = true, precision = 'exact',
                             geocode_state = 'done' WHERE id = %s AND geocode_state = 'todo' AND place_id = %s
                             AND analysis_id IS NOT DISTINCT FROM %s""",
                          (hit[0], hit[1], row["id"], row["place_id"], row["analysis_id"])).rowcount
            if n:
                db.bump_revision(c)
        else:
            c.execute("UPDATE incidents SET geocode_state = %s WHERE id = %s AND geocode_state = 'todo'",
                      (state, row["id"]))
    return state
