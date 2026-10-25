"""One-time import of the old SQLite database (v0.1) into Postgres, without calling any model again.

- Reads a consistent snapshot through SQLite's backup API (includes the WAL; copying crime.db alone loses data).
- Preserves ids, statuses, notes, coordinates, evidence flags and duplicate links.
- Every classified article gets a 'done' job and a legacy analysis row, so nothing is re-sent to a model.
- Refuses to run twice (it records itself in schema_migrations as 'import_sqlite_v01').
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from . import db

log = logging.getLogger(__name__)
MARKER = "import_sqlite_v01"


def _ts(v):
    if not v:
        return None
    d = datetime.fromisoformat(v)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def snapshot(path: str) -> sqlite3.Connection:
    """Open a quiesced backup file (make one with sqlite3's .backup; journal_mode=DELETE)."""
    from pathlib import Path
    if Path(f"{path}-wal").exists():
        raise RuntimeError("database has a live -wal file; import a backup made with SQLite's backup API instead")
    src = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    mem = sqlite3.connect(":memory:")
    src.backup(mem)
    src.close()
    mem.row_factory = sqlite3.Row
    if mem.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity check failed")
    return mem


def import_sqlite(path: str) -> dict:
    s = snapshot(path)
    counts = {}
    with db.tx() as c:
        if c.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (MARKER,)).fetchone():
            raise RuntimeError("SQLite data was already imported")
        if c.execute("SELECT 1 FROM articles LIMIT 1").fetchone():
            raise RuntimeError("target database already has articles; refusing to merge")

        arts = s.execute("SELECT * FROM articles ORDER BY id").fetchall()
        for a in arts:
            status = {"pending": "queued", "error": "failed"}.get(a["status"], a["status"])
            c.execute("""INSERT INTO articles (id, url, section, title, keywords, body, published_at, fetched_at, status,
                           classifier, note, error, classified_at)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (a["id"], a["url"], a["section"], a["title"], a["keywords"], a["body"], _ts(a["published_at"]),
                       _ts(a["fetched_at"]) or datetime.now(timezone.utc), status, a["classifier"], a["note"],
                       a["error"], _ts(a["classified_at"])))
            if a["status"] == "classified":
                job = c.execute("""INSERT INTO jobs (article_id, state, backend, dispatches, created_at, updated_at)
                                   VALUES (%s, 'done', %s, 1, %s, %s) RETURNING id""",
                                (a["id"], (a["classifier"] or "").split(":", 1)[0] or None,
                                 _ts(a["classified_at"]) or datetime.now(timezone.utc),
                                 _ts(a["classified_at"]) or datetime.now(timezone.utc))).fetchone()["id"]
                # The v0.1 schema did not keep the full model answer; record what we have.
                c.execute("""INSERT INTO analyses (article_id, job_id, backend, model, result, legacy, created_at,
                               materialized_at) VALUES (%s,%s,%s,%s,%s,true,%s,%s)""",
                          (a["id"], job, (a["classifier"] or "unknown").split(":", 1)[0],
                           (a["classifier"] or "").split(":", 1)[-1] or None,
                           Jsonb({"legacy_v01": True, "note": a["note"]}),
                           _ts(a["classified_at"]) or datetime.now(timezone.utc), _ts(a["classified_at"])))
            elif a["status"] in ("pending", "error"):
                c.execute("INSERT INTO jobs (article_id) VALUES (%s)", (a["id"],))
        counts["articles"] = len(arts)

        incs = s.execute("SELECT * FROM incidents ORDER BY id").fetchall()
        for i in incs:
            c.execute("""INSERT INTO incidents (id, article_id, category, headline_bn, headline_en, location_text,
                           place_id, thana_id, lat, lng, precision, geocoded, incident_date, event_date, time_of_day,
                           victims, evidence, evidence_ok, published, classifier, created_at)
                         VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (i["id"], i["article_id"], i["category"], i["headline_bn"], i["headline_en"], i["location_text"],
                       i["place_id"], i["thana_id"], i["lat"], i["lng"], i["precision"], bool(i["geocoded"]),
                       i["incident_date"], i["event_date"], i["time_of_day"], i["victims"], i["evidence"],
                       bool(i["evidence_ok"]), bool(i["evidence_ok"]), i["classifier"],
                       _ts(i["created_at"]) or datetime.now(timezone.utc)))
        for i in incs:  # second pass: self-references
            if i["duplicate_of"]:
                c.execute("UPDATE incidents SET duplicate_of = %s WHERE id = %s", (i["duplicate_of"], i["id"]))
        counts["incidents"] = len(incs)

        for g in s.execute("SELECT * FROM geocache").fetchall():
            c.execute("""INSERT INTO geocache (query, lat, lng, display, created_at) VALUES (%s,%s,%s,%s,%s)
                         ON CONFLICT (query) DO NOTHING""",
                      (g["query"], g["lat"], g["lng"], g["display"], _ts(g["created_at"]) or datetime.now(timezone.utc)))
        for r in s.execute("SELECT * FROM runs ORDER BY id").fetchall():
            c.execute("""INSERT INTO runs (id, trigger, started_at, finished_at, status, discovered, fetched, queued,
                           errors, message) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (r["id"], r["trigger"], _ts(r["started_at"]), _ts(r["finished_at"]),
                       "interrupted" if r["status"] == "running" else r["status"], r["discovered"], r["fetched"],
                       r["classified"], r["errors"], r["message"]))
        for table in ("articles", "incidents", "runs"):
            c.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                      f"coalesce((SELECT max(id) FROM {table}), 1))")
        c.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (MARKER,))

        counts["queued_jobs"] = c.execute("SELECT count(*) n FROM jobs WHERE state = 'queued'").fetchone()["n"]
        counts["classified"] = c.execute("SELECT count(*) n FROM articles WHERE status = 'classified'").fetchone()["n"]
        counts["canonical"] = c.execute("""SELECT count(*) n FROM incidents
                                           WHERE published AND duplicate_of IS NULL""").fetchone()["n"]
    log.info("imported %s", counts)
    return counts
