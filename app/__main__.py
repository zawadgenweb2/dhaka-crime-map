"""Command line: python -m app <command>

Services (one per container):
  api                     dashboard + read API on HOST:PORT
  collector               the only scheduler: scrapes at SCRAPE_TIMES, queues articles
  classifier              claims queued articles and classifies them with the in-house Gemma model
  migrate [--import-sqlite PATH]   apply schema migrations; optionally import the v0.1 SQLite data once

Admin:
  collect-now [--days N] [--max M]   ask the running collector to scrape now; --days 90 --max 3000 = backfill
  reprocess-all --yes     re-run every collected article through Gemma (replaces all current incidents)
  rebuild-duplicates      regroup duplicate reports with the current rule (no model calls)
  compare --with gemma    run the model on the frozen reference articles and report agreement (offline only)
  stats                   counts in the terminal
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import db
from .config import settings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("api")
    sub.add_parser("collector")
    sub.add_parser("classifier")
    m = sub.add_parser("migrate"); m.add_argument("--import-sqlite", metavar="PATH")
    cn = sub.add_parser("collect-now"); cn.add_argument("--days", type=int, default=1)
    cn.add_argument("--max", type=int, default=None, help="article cap for this run (default MAX_ARTICLES_PER_RUN)")
    rp = sub.add_parser("reprocess-all"); rp.add_argument("--yes", action="store_true")
    sub.add_parser("rebuild-duplicates")
    cp = sub.add_parser("compare"); cp.add_argument("--with", dest="other", default="gemma")
    cp.add_argument("--limit", type=int, default=1000); cp.add_argument("--out", default=None)
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "api":
        import uvicorn
        from .api import create_app
        import os
        tls = {"ssl_certfile": os.getenv("TLS_CERT_FILE"), "ssl_keyfile": os.getenv("TLS_KEY_FILE")}
        uvicorn.run(create_app(), host=settings.host, port=settings.port, proxy_headers=False,
                    **({k: v for k, v in tls.items()} if all(tls.values()) else {}))
    elif args.cmd == "collector":
        from .collector import Collector
        Collector().serve()
    elif args.cmd == "classifier":
        from .worker import Worker
        Worker().serve()
    elif args.cmd == "migrate":
        print("applied:", db.migrate() or "nothing new")
        if args.import_sqlite:
            from .importer import import_sqlite
            print("imported:", import_sqlite(args.import_sqlite))
    elif args.cmd == "collect-now":
        with db.tx() as c:
            rid = c.execute("""INSERT INTO run_requests (source, days_back, max_articles) VALUES ('cli', %s, %s)
                               RETURNING id""", (args.days, args.max)).fetchone()["id"]
        print(f"queued run request {rid}; the collector picks it up within ~20 s")
    elif args.cmd == "reprocess-all":
        if not args.yes:
            print("re-runs every collected article through Gemma and replaces all incidents; add --yes")
            return 2
        from .reprocess import reprocess_all
        print(reprocess_all())
    elif args.cmd == "rebuild-duplicates":
        from .store import MATERIALIZE_LOCK, rebuild_groups
        with db.tx() as c:
            c.execute("SELECT pg_advisory_xact_lock(%s)", (MATERIALIZE_LOCK,))
            keys = {(r["category"], r["place_id"], r["event_date"]) for r in c.execute(
                "SELECT DISTINCT category, place_id, event_date FROM incidents "
                "WHERE published AND place_id IS NOT NULL AND event_date IS NOT NULL")}
            c.execute("UPDATE incidents SET duplicate_of = NULL WHERE NOT published")
            print(f"regrouped; {rebuild_groups(c, keys)} links changed")
            db.bump_revision(c)
    elif args.cmd == "compare":
        from .evaluate import compare
        return compare(args.other, args.limit, args.out)
    elif args.cmd == "stats":
        with db.connect() as c:
            for r in c.execute("SELECT status, count(*) n FROM articles GROUP BY 1 ORDER BY 1"):
                print(f"articles  {r['status']:<11} {r['n']}")
            for r in c.execute("SELECT state, count(*) n FROM jobs GROUP BY 1 ORDER BY 1"):
                print(f"jobs      {r['state']:<11} {r['n']}")
            for r in c.execute("""SELECT category, count(*) n FROM incidents WHERE published AND duplicate_of IS NULL
                                  GROUP BY 1 ORDER BY 2 DESC"""):
                print(f"incidents {r['category']:<16} {r['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
