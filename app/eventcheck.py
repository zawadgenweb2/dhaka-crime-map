"""Checks that the event store does what the map promises: each real crime once, nothing lost, nothing over-merged.

`python -m app events-verify` prints a report with four parts:
  1. invariants      every located published report is in exactly one active event; each event's main report is
                     one of its own; counts consistent; the public API serves one row per event (list and stats
                     agree). Events holding two incidents of one article are reported as information
  2. known stories   multi-paper stories we know (Rangpur 4 killed, Sitakunda blast, ...) and how many events each
                     became (1 = shown once)
  3. residual look-alikes   pairs of separate events that still look alike (same type and place, +-1 day, different
                     papers): how many remain versus the old per-report count, and a sample to review
  4. over-merge flags   events whose reports span more than 7 days or more than one thana (possible wrong chains)
The samples are exported so an independent reviewer (a person, or the Codex council) can label them.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from . import db

KNOWN_STORIES = [   # label, place/thana ids, category, date window, title words (any)
    ("Rangpur: retired teacher's family of 4 killed", ["rangpur:rangpur_kotwali"], "murder", ("2026-08-21", "2026-08-26"),
     ["গণপতি", "চার খুন", "৪ খুন", "শিক্ষক পরিবার", "৪ জনকে", "চারজন"]),
    ("Sitakunda ship-breaking yard blast", ["chattogram:sitakunda"], None, ("2026-08-13", "2026-08-17"),
     ["জাহাজভাঙা", "সীতাকুণ্ড ট্র্যাজেডি", "বিস্ফোরণ"]),
    ("Ashulia blast", ["ashulia"], None, ("2026-09-19", "2026-09-23"), ["বিস্ফোরণ", "বি'স্ফো'রণ"]),
    ("Khulna University student Azmul beaten to death", None, "murder", ("2026-09-17", "2026-09-21"),
     ["আজমুল", "খুলনা বিশ্ববিদ্যালয়", "খুবি", "বিশ্ববিদ্যালয় ছাত্রকে", "বিশ্ববিদ্যালয় শিক্ষার্থী"]),
    ("Shots at singer Asif Akbar's car (Mogbazar)", ["mogbazar"], None, ("2026-10-23", "2026-10-26"), ["আসিফ"]),
    ("Patiya banana-theft killing", ["chattogram:patiya"], None, ("2026-07-25", "2026-10-28"), ["কলা"]),
]


def _q(c, sql, params=()):
    return c.execute(sql, params).fetchall()


def invariants(c) -> dict:
    eligible = """i.published AND i.place_id IS NOT NULL AND i.event_date IS NOT NULL AND i.report_key IS NOT NULL"""
    out = {}
    out["eligible_reports"] = _q(c, f"SELECT count(*) n FROM incidents i WHERE {eligible}")[0]["n"]
    out["not_in_any_event"] = _q(c, f"""SELECT count(*) n FROM incidents i WHERE {eligible} AND NOT EXISTS
                                     (SELECT 1 FROM event_reports er WHERE er.report_key = i.report_key)""")[0]["n"]
    out["in_retired_event"] = _q(c, f"""SELECT count(*) n FROM incidents i JOIN event_reports er ON er.report_key = i.report_key
                                     JOIN events e ON e.id = er.event_id WHERE {eligible} AND e.state <> 'active'""")[0]["n"]
    out["main_report_not_a_member"] = _q(c, """SELECT count(*) n FROM events e WHERE e.state = 'active' AND NOT EXISTS
                                          (SELECT 1 FROM event_reports er JOIN incidents i ON i.report_key = er.report_key
                                           WHERE er.event_id = e.id AND i.id = e.primary_incident_id AND i.published)""")[0]["n"]
    out["count_mismatch"] = _q(c, """SELECT count(*) n FROM events e WHERE e.state = 'active' AND e.report_count <>
                                  (SELECT count(*) FROM event_reports er JOIN incidents i ON i.report_key = er.report_key
                                   WHERE er.event_id = e.id AND i.published)""")[0]["n"]
    # information, not an error: Gemma sometimes splits one crime into two incidents of one article (e.g. "weapon
    # recovered" and "yaba seized" in one shooting story); the event store puts them back together
    out["info_events_holding_one_article_twice"] = _q(c, """SELECT count(*) n FROM (SELECT event_id, article_id
                                            FROM event_reports GROUP BY 1, 2 HAVING count(*) > 1) x""")[0]["n"]
    out["ok"] = not any(out[k] for k in ("not_in_any_event", "in_retired_event", "main_report_not_a_member",
                                         "count_mismatch"))
    return out


def public_consistency(days: int = 90) -> dict:
    """The public API, called in-process: list rows, stats total and active events in the period must agree."""
    from fastapi.testclient import TestClient
    from .public import create_public_app
    api = TestClient(create_public_app(), base_url="https://check")
    items = api.get("/api/incidents", params={"days": days, "limit": 20000}).json()
    stats = api.get("/api/stats", params={"days": days}).json()
    with db.connect() as c:
        live = bool(_q(c, "SELECT 1 FROM app_flags WHERE key = 'events_live' AND value = '1'"))
        start = date.today() - timedelta(days=days - 1)
        events = _q(c, """SELECT count(*) n FROM events e WHERE e.state = 'active' AND e.event_date BETWEEN %s AND %s""",
                    (start, date.today()))[0]["n"]
        hidden = _q(c, """SELECT count(*) n FROM events e WHERE e.state = 'active' AND e.event_date BETWEEN %s AND %s
                          AND e.category IN ('sexual_violence')""", (start, date.today()))[0]["n"]
    ids = [i["id"] for i in items]
    return {"events_live": live, "map_rows": len(items), "stats_total": stats["total"], "active_events": events,
            "of_which_totals_only": hidden, "duplicate_ids_on_map": len(ids) - len(set(ids)),
            "ok": (not live) or (stats["total"] == events and len(items) == events - hidden)}


def known_stories(c) -> list[dict]:
    out = []
    for label, places, cat, (d0, d1), words in KNOWN_STORIES:
        cond, params = ["i.published", "i.event_date BETWEEN %s AND %s"], [d0, d1]
        if places:
            cond.append("(i.place_id = ANY(%s) OR i.thana_id = ANY(%s))")
            params += [places, places]
        if cat:
            cond.append("i.category = %s")
            params.append(cat)
        cond.append("(" + " OR ".join("a.title LIKE %s" for _ in words) + ")")
        params += [f"%{w}%" for w in words]
        rows = _q(c, f"""SELECT i.report_key, a.source, er.event_id FROM incidents i JOIN articles a ON a.id = i.article_id
                         LEFT JOIN event_reports er ON er.report_key = i.report_key WHERE {' AND '.join(cond)}""", params)
        events = sorted({r["event_id"] for r in rows if r["event_id"] is not None})
        out.append({"story": label, "reports": len(rows), "papers": len({r["source"] for r in rows}),
                    "events": len(events), "unmatched_yet": sum(r["event_id"] is None for r in rows), "event_ids": events})
    return out


def residual_lookalikes(c, sample: int = 30) -> dict:
    """Separate events whose main reports still look alike: same category, same place or thana, +-1 day,
    different papers. Some are real separate crimes; the sample is for review."""
    rows = _q(c, """SELECT e1.id e1, e2.id e2, a1.source s1, a2.source s2, a1.title t1, a2.title t2, a1.url u1, a2.url u2,
                           e1.category, e1.place_id, e1.event_date d1, e2.event_date d2
                    FROM events e1 JOIN events e2 ON e1.id < e2.id AND e1.state = 'active' AND e2.state = 'active'
                      AND e1.category = e2.category AND e1.district_id = e2.district_id
                      AND (e1.place_id = e2.place_id OR e1.thana_id = e2.thana_id)
                      AND abs(e1.event_date - e2.event_date) <= 1
                    JOIN incidents i1 ON i1.id = e1.primary_incident_id JOIN articles a1 ON a1.id = i1.article_id
                    JOIN incidents i2 ON i2.id = e2.primary_incident_id JOIN articles a2 ON a2.id = i2.article_id
                    WHERE a1.source <> a2.source AND e1.category <> 'sexual_violence'
                    ORDER BY md5(e1.id::text || e2.id::text)""")
    old = _q(c, """SELECT count(*) n FROM incidents x JOIN incidents y ON x.id < y.id AND x.article_id <> y.article_id
                   AND x.category = y.category AND x.place_id = y.place_id AND abs(x.event_date - y.event_date) <= 1
                   JOIN articles ax ON ax.id = x.article_id JOIN articles ay ON ay.id = y.article_id
                   WHERE x.published AND y.published AND ax.source <> ay.source""")[0]["n"]
    return {"remaining_pairs": len(rows), "report_level_pairs_before": old,
            "sample": [{k: (str(v) if isinstance(v, date) else v) for k, v in r.items()} for r in rows[:sample]]}


def overmerge_flags(c, limit: int = 20) -> dict:
    rows = _q(c, """SELECT e.id, e.report_count, max(i.event_date) - min(i.event_date) AS day_span,
                           count(DISTINCT i.thana_id) AS thanas, count(DISTINCT a.source) AS papers,
                           (array_agg(a.title ORDER BY a.published_at))[1:3] AS titles
                    FROM events e JOIN event_reports er ON er.event_id = e.id
                    JOIN incidents i ON i.report_key = er.report_key AND i.published JOIN articles a ON a.id = i.article_id
                    WHERE e.state = 'active' GROUP BY e.id HAVING count(*) > 1
                    ORDER BY e.report_count DESC""")
    flagged = [r for r in rows if r["day_span"] > 7 or r["thanas"] > 1]
    sizes = {}
    for r in rows:
        b = "2" if r["report_count"] == 2 else "3-5" if r["report_count"] <= 5 else "6-10" if r["report_count"] <= 10 else "11+"
        sizes[b] = sizes.get(b, 0) + 1
    return {"events_with_several_reports": len(rows), "size_buckets": sizes, "flagged": len(flagged),
            "flagged_sample": flagged[:limit], "largest": rows[:5]}


def merged_sample(c, n: int = 40) -> list[dict]:
    """Random automatic links with both titles and the judge's quoted facts (for an independent review)."""
    rows = _q(c, """SELECT d.id, d.event_id, a.source s1, a.title t1, ca.source s2, ca.title t2, d.evidence -> 'facts' AS facts
                    FROM match_decisions d JOIN incidents i ON i.report_key = d.report_key JOIN articles a ON a.id = i.article_id
                    JOIN incidents ci ON ci.report_key = d.candidate_key JOIN articles ca ON ca.id = ci.article_id
                    WHERE d.stage = 'final' AND d.outcome = 'linked' ORDER BY md5(d.id::text) LIMIT %s""", (n,))
    return rows


def verify(sample: int = 30, export: str | None = None) -> dict:
    with db.connect() as c:
        report = {"invariants": invariants(c), "known_stories": known_stories(c),
                  "residual": residual_lookalikes(c, sample), "overmerge": overmerge_flags(c)}
        merged = merged_sample(c)
    report["public"] = public_consistency()
    if export:
        with open(export, "w", encoding="utf-8") as f:
            json.dump({"residual_sample": report["residual"]["sample"], "merged_sample": merged,
                       "overmerge_flagged": report["overmerge"]["flagged_sample"]}, f, ensure_ascii=False, indent=1,
                      default=str)
    return report
