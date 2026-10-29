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
from .events import in_text
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
    out = {"place_id": None, "thana_id": None, "lat": None, "lng": None, "geocoded": False, "precision": "city",
           "district": None}
    if place is None:
        return out
    thana = gaz.thana_of(place)
    out.update(place_id=place.id, thana_id=thana.id, lat=place.lat, lng=place.lng, district=place.district,
               precision={"landmark": "exact", "area": "neighbourhood"}.get(place.kind, "thana"))
    hit = (geocoded or {}).get(inc.geocode_query or "")
    if hit and place.lat is not None and distance_km(hit, (place.lat, place.lng)) <= GEOCODE_MAX_KM:
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
    """The quote is in the article, word for word or as a near-copy (one unbroken run of >= 60% of it, >= 15
    characters): the model often adds or drops a word. Invented quotes still fail (same rule as the event matcher)."""
    ev = normalize(evidence or "")
    return len(ev) >= 8 and (ev in normalize(f"{title} {body}") or in_text(evidence or "", f"{title}\n{body}"))


# ---- duplicate grouping ------------------------------------------------------------------------
# Words too common in crime reports to tell two events apart
_COMMON = {normalize(w) for w in (
    "করা হয় হয়েছে হয়েছেন করে করেন এলাকায় এলাকার থানার থানায় পুলিশ পুলিশের জানান বলেন জানিয়েছেন একটি নামে এক "
    "গ্রেপ্তার আটক হত্যা খুন নিহত আহত মামলা অভিযোগ গতকাল সোমবার মঙ্গলবার বুধবার বৃহস্পতিবার শুক্রবার শনিবার "
    "রবিবার রাতে সকালে দুপুরে বিকেলে সন্ধ্যায় তাঁকে তাকে তিনি তাঁর তার তাদের এ ঘটনায় ঘটনার পরে পর থেকে দিয়ে "
    "সঙ্গে সাথে জন্য কাছে মধ্যে বয়স বছর ওসি উপজেলার উপজেলায় জেলার নগরের").split()}


def _tokens(text: str | None) -> set[str]:
    """Distinctive words of a quote (3+ characters, not common crime-report words). Numbers are not counted on their
    own: a shared age or amount alone is weak evidence (the old second pass here never ran; removed, 28 Oct)."""
    words = (w.strip("()[]{}.,;:!?'\"‘’“”-–—।") for w in normalize(text or "").split())
    return {w for w in words if len(w) >= 3 and w not in _COMMON}


def _corroboration(a: dict, b: dict) -> int:
    """Event-specific facts two reports share: the same explicit incident date, the same victim count, and
    names/ages/amounts (three or more distinctive words in common between their quotes)."""
    n = 0
    if a.get("incident_date") and a.get("incident_date") == b.get("incident_date"):
        n += 1
    if (a.get("victims") or 0) > 0 and a.get("victims") == b.get("victims"):
        n += 1
    if len(_tokens(a.get("evidence")) & _tokens(b.get("evidence"))) >= 3:
        n += 1
    return n


def _same_event(a: dict, b: dict) -> bool:
    """Two reports (any papers) describe one event: same category and place, dates ±1 day, compatible time, AND
    corroborated: one shared event-specific fact for a neighbourhood/spot, two for a whole thana or upazila.
    A wrong merge hides a real crime from the public map, so uncorroborated look-alikes stay separate."""
    if a["article_id"] == b["article_id"]:
        return False
    if a["category"] != b["category"] or not a["place_id"] or a["place_id"] != b["place_id"]:
        return False
    if not a["event_date"] or not b["event_date"] or abs((a["event_date"] - b["event_date"]).days) > 1:
        return False
    ta, tb = a["time_of_day"] or "unknown", b["time_of_day"] or "unknown"
    if not (ta == tb or "unknown" in (ta, tb)):
        return False
    specific = bool(a.get("thana_id")) and a["place_id"] != a.get("thana_id")
    return _corroboration(a, b) >= (1 if specific else 2)


def rebuild_groups(conn, keys: set[tuple]) -> int:
    """Recompute duplicate_of for the whole (category, place) partition of each key.

    Whole partitions, not date windows: a window can cut a chain (A <- B) and wrongly make B canonical.
    Unpublished incidents never take part in grouping."""
    changed = 0
    for category, place_id in {(k[0], k[1]) for k in keys}:
        conn.execute("""UPDATE incidents SET duplicate_of = NULL WHERE NOT published AND category = %s
                        AND place_id = %s AND duplicate_of IS NOT NULL""", (category, place_id))
        rows = conn.execute(
            """SELECT id, article_id, category, place_id, thana_id, event_date, incident_date, time_of_day, victims,
                      evidence, duplicate_of FROM incidents
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
    consistent = analysis.is_crime_report and analysis.in_scope
    rows = []
    if not consistent:
        return rows
    source = f"{article['title'] or ''}\n{article.get('keywords') or ''}\n{article['body'] or ''}"
    grounded = gaz.grounded_places(source)                   # places the article really names
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
        # Located (a point on the map) only if the place is one the article names (the shortlist), its district
        # agrees with the model's district or with the district the text itself names for this incident, and
        # neither the first sentence, the quote's own sentence, nor the location phrase puts the incident in
        # another district. The model's district alone is never enough.
        d = loc["district"]
        quote_sentence = gaz.quote_sentence(article["body"] or "", inc.evidence)
        # The district the text names for this incident by a district word: in the location phrase itself, or in the
        # quote's sentence when the model agrees (a district there can be someone's home: "মাদারীপুরের যুবক").
        loc_d, quote_d = gaz.sole_district(inc.location_text), gaz.sole_district(quote_sentence)
        text_d = loc_d or (quote_d if quote_d and inc.district == quote_d else None)
        located = bool(loc["place_id"]) and (loc["place_id"] in grounded or loc["thana_id"] in grounded) \
            and (inc.district is None or d in (inc.district, loc_d, quote_d)) \
            and not gaz.lead_in_other_district(article["body"] or "", d) \
            and not gaz.names_other_district(quote_sentence, d) \
            and not gaz.names_other_district(inc.location_text, d)
        if not located and text_d and not gaz.lead_in_other_district(article["body"] or "", text_d):
            # No reliable point, but the text names the district: counted at district level (district bubble,
            # totals and reports list; no heat point), so a crime is not lost for want of a catalogued place.
            loc = {**loc, "place_id": None, "thana_id": None, "lat": None, "lng": None, "geocoded": False,
                   "precision": "city", "district": text_d}
        ok = quoted and (located or bool(loc["district"] and not loc["place_id"]))
        rows.append({
            **loc, "category": inc.category, "headline_bn": inc.headline_bn, "headline_en": inc.headline_en,
            "location_text": inc.location_text, "incident_date": inc_date, "event_date": inc_date or pub_day or fetched_day or upper,
            "time_of_day": inc.time_of_day, "victims": max(0, inc.victims), "evidence": inc.evidence,
            # passes = automatic checks OK. Published now only in auto mode; review mode waits for a human.
            "evidence_ok": quoted, "located": located, "passes": ok,
            "published": ok and publish_mode == "auto",
            "review_status": ("auto" if publish_mode == "auto" else "pending") if ok else "failed",
            "geocode_query": inc.geocode_query if inc.geocode_query and loc["place_id"] and located else None,
            "geocode_state": "todo" if inc.geocode_query and loc["place_id"] and located and not loc["geocoded"] else "none",
        })
    return rows


def materialize(conn, article: dict, analysis_id: int | None, analysis: ArticleAnalysis, classifier: str,
                gaz: Gazetteer, geocoded: dict | None = None) -> int:
    """Replace the article's incidents atomically. Caller owns the transaction (conn.transaction())."""
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
    old = conn.execute("SELECT category, place_id, event_date, report_key FROM incidents WHERE article_id = %s",
                       (article["id"],)).fetchall()
    keys = {(r["category"], r["place_id"], r["event_date"]) for r in old if r["place_id"] and r["event_date"]}
    conn.execute("DELETE FROM incidents WHERE article_id = %s", (article["id"],))
    rows = build_rows(article, analysis, gaz, geocoded or {})
    for r in rows:
        conn.execute(
            """INSERT INTO incidents (article_id, analysis_id, category, headline_bn, headline_en, location_text,
                 place_id, thana_id, lat, lng, precision, geocoded, incident_date, event_date, time_of_day, victims,
                 evidence, evidence_ok, published, review_status, classifier, geocode_query, geocode_state, district_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (article["id"], analysis_id, r["category"], r["headline_bn"], r["headline_en"], r["location_text"],
             r["place_id"], r["thana_id"], r["lat"], r["lng"], r["precision"], r["geocoded"], r["incident_date"],
             r["event_date"], r["time_of_day"], r["victims"], r["evidence"], r["evidence_ok"], r["published"],
             r["review_status"], classifier, r["geocode_query"], r["geocode_state"], r["district"]))
        if r["place_id"] and r["event_date"]:
            keys.add((r["category"], r["place_id"], r["event_date"]))
    rebuild_groups(conn, keys)
    # the event store: every report of this article (new, changed or vanished) goes through the matcher again
    from .events import assign_keys, enqueue
    assign_keys(conn, article["id"])
    new_keys = {r["report_key"] for r in conn.execute(
        "SELECT report_key FROM incidents WHERE article_id = %s", (article["id"],))}
    fresh = article.get("published_at") is None or (datetime.now(DHAKA_TZ) - article["published_at"]).days <= 3
    enqueue(conn, sorted(new_keys | {r["report_key"] for r in old if r["report_key"]}), priority=0 if fresh else 2)
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
        from .geocode import viewbox_for
        hit = geocode(row["geocode_query"], viewbox_for(gaz.bounds(place.district)))   # shared lane; no transaction
        if hit is None and not is_cached(row["geocode_query"]):
            return "error"                                        # network problem: leave it waiting
        state = "miss" if hit is None or place.lat is None else (
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
