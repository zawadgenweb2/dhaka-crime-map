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
