"""Re-run every collected article through the in-house Gemma model (python -m app reprocess-all --yes).

Used once to replace the prototype-phase (Claude) output, and again whenever the prompt changes. In one transaction:
  1. refuse while any job is running (stop the classifier first: no half-finished calls);
  2. delete every incident that does not come from a Gemma analysis, so nothing else can be served;
  3. give each collected article a new analysis version and one fresh job, grouped under one `runs` row
     (trigger 'reprocess') so the dashboard can show progress; older jobs can no longer write incidents.
The frozen evaluation reference (migration 005) is untouched.
"""
from __future__ import annotations

from . import db
from .config import settings
from .store import MATERIALIZE_LOCK


def reprocess_all() -> dict:
    with db.tx() as c:
        c.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
        running = c.execute("SELECT count(*) n FROM jobs WHERE state = 'running'").fetchone()["n"]
        if running:
            raise SystemExit(f"{running} job(s) are running; stop the classifier first")
        superseded = c.execute("""UPDATE jobs SET state = 'superseded', owner = NULL, updated_at = now()
                                  WHERE state = 'queued'""").rowcount
        removed = c.execute(f"DELETE FROM incidents i WHERE NOT ({db.GEMMA_PROVENANCE})").rowcount
        run_id = c.execute("""INSERT INTO runs (trigger, status, finished_at, message)
                              VALUES ('reprocess', 'ok', now(), 're-run collected articles through Gemma')
                              RETURNING id""").fetchone()["id"]
        arts = c.execute("""UPDATE articles a SET analysis_version = v.nv, status = 'queued', error = NULL
                            FROM (SELECT a2.id, greatest(a2.analysis_version,
                                                         coalesce(max(j.analysis_version), 0)) + 1 AS nv
                                  FROM articles a2 LEFT JOIN jobs j ON j.article_id = a2.id
                                  WHERE a2.status IN ('classified', 'failed', 'uncertain', 'queued')
                                  GROUP BY a2.id) v
                            WHERE a.id = v.id RETURNING a.id, a.analysis_version""").fetchall()
        for a in arts:
            c.execute("""INSERT INTO jobs (article_id, analysis_version, backend, run_id) VALUES (%s, %s, %s, %s)""",
                      (a["id"], a["analysis_version"], settings.classifier, run_id))
        c.execute("UPDATE runs SET discovered = %s, fetched = %s, queued = %s WHERE id = %s",
                  (len(arts), len(arts), len(arts), run_id))
        db.bump_revision(c)
    return {"run_id": run_id, "articles_queued": len(arts), "non_gemma_incidents_removed": removed,
            "old_queued_jobs_superseded": superseded}


def requeue_set_aside(days: int) -> dict:
    """Give articles that were set aside as outside the window a fresh Gemma job if they were published on or after
    today minus `days` (Asia/Dhaka dates; the dashboard's 30-day view is days = 29). Same versioning as reprocess_all, so older jobs can never write."""
    with db.tx() as c:
        c.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
        run_id = c.execute("""INSERT INTO runs (trigger, status, finished_at, message, days_back)
                              VALUES ('reprocess', 'ok', now(), 're-queue articles set aside outside the 7-day window', %s)
                              RETURNING id""", (days,)).fetchone()["id"]
        arts = c.execute("""UPDATE articles a SET analysis_version = v.nv, status = 'queued', error = NULL, note = NULL
                            FROM (SELECT a2.id, greatest(a2.analysis_version,
                                                         coalesce(max(j.analysis_version), 0)) + 1 AS nv
                                  FROM articles a2 LEFT JOIN jobs j ON j.article_id = a2.id
                                  WHERE a2.status = 'skipped'
                                    AND a2.note IN ('outside the 7-day window', 'outside the window')
                                    AND (a2.published_at AT TIME ZONE 'Asia/Dhaka')::date
                                        >= (now() AT TIME ZONE 'Asia/Dhaka')::date - %s
                                    AND NOT EXISTS (SELECT 1 FROM jobs q WHERE q.article_id = a2.id
                                                    AND q.state IN ('queued', 'running'))
                                  GROUP BY a2.id) v
                            WHERE a.id = v.id RETURNING a.id, a.analysis_version""", (days,)).fetchall()
        for a in arts:
            c.execute("INSERT INTO jobs (article_id, analysis_version, backend, run_id) VALUES (%s, %s, %s, %s)",
                      (a["id"], a["analysis_version"], settings.classifier, run_id))
        c.execute("UPDATE runs SET discovered = %s, fetched = %s, queued = %s WHERE id = %s",
                  (len(arts), len(arts), len(arts), run_id))
        if not arts:
            c.execute("DELETE FROM runs WHERE id = %s", (run_id,))   # nothing to do: leave no empty batch behind
        db.bump_revision(c)
    return {"run_id": run_id if arts else None, "articles_queued": len(arts)}


def rematerialize() -> dict:
    """Re-apply today's checks (place grounding, dates, duplicates) to every article's saved Gemma answer.
    No model calls. Only the article's current analysis version is used."""
    from .gazetteer import load as load_gazetteer
    from .schema import ArticleAnalysis
    from .store import materialize
    gaz = load_gazetteer()
    n = rows = 0
    with db.connect() as c:
        todo = c.execute("""SELECT a.id AS article_id, x.id AS analysis_id, x.backend, x.model, x.result
                            FROM articles a
                            JOIN jobs j ON j.article_id = a.id AND j.analysis_version = a.analysis_version
                            JOIN LATERAL (SELECT * FROM analyses y WHERE y.job_id = j.id ORDER BY y.id DESC LIMIT 1) x ON true
                            WHERE a.status = 'classified' AND x.backend = 'gemma' AND NOT x.legacy""").fetchall()
    for t in todo:
        with db.tx() as c:
            art = c.execute("SELECT * FROM articles WHERE id = %s FOR UPDATE", (t["article_id"],)).fetchone()
            if art["status"] != "classified":
                continue
            rows += materialize(c, art, t["analysis_id"], ArticleAnalysis.model_validate(t["result"]),
                                f"{t['backend']}:{t['model']}", gaz)
            n += 1
    return {"articles": n, "incidents_published_or_held": rows}
