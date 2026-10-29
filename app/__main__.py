"""Command line: python -m app <command>

Services (one per container):
  api                     public site + read-only API on HOST:PORT
  admin                   admin panel (login) on HOST:ADMIN_PORT — keep it on the LAN/VPN only
  admin-user add NAME     create an admin account or reset its password (asks for the password)
  admin-user disable NAME disable an account and end its sessions
  collector               the only scheduler: scrapes at SCRAPE_TIMES, queues articles
  classifier              claims queued articles and classifies them with the in-house Gemma model
  migrate [--import-sqlite PATH]   apply schema migrations; optionally import the v0.1 SQLite data once

Admin:
  collect-now [--days N] [--max M]   ask the running collector to scrape now; --days 90 --max 3000 = backfill
  reprocess-all --yes     re-run every collected article through Gemma (replaces all current incidents)
  requeue-set-aside [--days N]   queue set-aside articles published on or after today minus N days (30-day view: 29)
  rematerialize           re-apply the current checks to every saved Gemma answer (no model calls)
  refilter-skipped [--days N]   re-check pre-filter-skipped articles (stored text) and queue those that now qualify
  requeue-no-text SOURCE [--days N]   after fixing a paper's extractor: re-download pages that had no article text
  rebuild-duplicates      regroup duplicate reports with the current rule (no model calls)
  events-build            queue every published report for the cross-paper matcher (the map switches when done)
  events-status           matcher queue, events and decisions
  events-verify [--export F]   check the event store: invariants, known stories, residual look-alikes, over-merges
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
    sub.add_parser("admin")
    au = sub.add_parser("admin-user"); au.add_argument("action", choices=["add", "disable"]); au.add_argument("name")
    sub.add_parser("collector")
    sub.add_parser("classifier")
    m = sub.add_parser("migrate"); m.add_argument("--import-sqlite", metavar="PATH")
    cn = sub.add_parser("collect-now"); cn.add_argument("--days", type=int, default=1)
    cn.add_argument("--max", type=int, default=None, help="article cap for this run (default MAX_ARTICLES_PER_RUN)")
    rp = sub.add_parser("reprocess-all"); rp.add_argument("--yes", action="store_true")
    rq = sub.add_parser("requeue-set-aside"); rq.add_argument("--days", type=int, default=29)
    rm = sub.add_parser("rematerialize"); rm.add_argument("--since", default=None, help="ISO time: only articles classified since")
    rf = sub.add_parser("refilter-skipped"); rf.add_argument("--days", type=int, default=29)
    rn = sub.add_parser("requeue-no-text"); rn.add_argument("source"); rn.add_argument("--days", type=int, default=29)
    sub.add_parser("rebuild-duplicates")
    sub.add_parser("events-build")
    sub.add_parser("events-status")
    co = sub.add_parser("events-consolidate"); co.add_argument("--workers", type=int, default=1)
    ev = sub.add_parser("events-verify"); ev.add_argument("--export", default=None); ev.add_argument("--sample", type=int, default=30)
    cp = sub.add_parser("compare"); cp.add_argument("--with", dest="other", default="gemma")
    cp.add_argument("--limit", type=int, default=1000); cp.add_argument("--out", default=None)
    sub.add_parser("stats")
    hc = sub.add_parser("healthcheck", help="exit 0 if the service's heartbeat is recent (Docker HEALTHCHECK)")
    hc.add_argument("service", choices=["collector", "classifier"]); hc.add_argument("--max-age", type=int, default=900)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd in ("api", "admin"):
        import os
        import uvicorn
        if args.cmd == "api":
            from .public import create_public_app as factory
            port = settings.port
        else:
            from .api import create_app as factory
            port = settings.admin_port
        tls = {"ssl_certfile": os.getenv("TLS_CERT_FILE"), "ssl_keyfile": os.getenv("TLS_KEY_FILE")}
        uvicorn.run(factory(), host=settings.host, port=port, proxy_headers=False,
                    **({k: v for k, v in tls.items()} if all(tls.values()) else {}))
    elif args.cmd == "admin-user":
        from . import auth
        if args.action == "disable":
            auth.disable_user(args.name)
            print(f"disabled {args.name}")
        else:
            import getpass
            pw = getpass.getpass("New password (12+ characters): ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
            if sys.stdin.isatty() and pw != getpass.getpass("Repeat: "):
                print("passwords differ"); return 2
            auth.add_user(args.name, pw)
            print(f"account {args.name} ready (existing sessions ended)")
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
    elif args.cmd == "requeue-no-text":
        from . import db as database
        with database.tx() as c:
            n = c.execute("""DELETE FROM articles WHERE source = %s AND status = 'skipped' AND note LIKE 'no article text%%'
                             AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.article_id = articles.id)
                             AND coalesce(published_at, fetched_at) > now() - make_interval(days => %s)""",
                          (args.source, args.days)).rowcount
        print(f"{n} text-less {args.source} pages forgotten; the next run downloads them again")
    elif args.cmd == "refilter-skipped":
        from .reprocess import refilter_skipped
        print(refilter_skipped(args.days))
    elif args.cmd == "rematerialize":
        from .reprocess import rematerialize
        print(rematerialize(args.since))
    elif args.cmd == "requeue-set-aside":
        from .reprocess import requeue_set_aside
        print(requeue_set_aside(args.days))
    elif args.cmd == "events-build":
        from .events import build_all
        print(build_all())
    elif args.cmd == "events-verify":
        import json as _json
        from .eventcheck import verify
        rep_ = verify(args.sample, args.export)
        for part in ("invariants", "public"):
            print(part, _json.dumps(rep_[part], ensure_ascii=False))
        for s_ in rep_["known_stories"]:
            print("story", _json.dumps(s_, ensure_ascii=False))
        r_ = rep_["residual"]
        print("residual", _json.dumps({k: v for k, v in r_.items() if k != "sample"}))
        o_ = rep_["overmerge"]
        print("overmerge", _json.dumps({k: v for k, v in o_.items() if k not in ("flagged_sample", "largest")},
                                       ensure_ascii=False))
        for x in o_["largest"]:
            print("  largest", x["id"], x["report_count"], "reports,", x["papers"], "papers, span", x["day_span"], "days,",
                  x["thanas"], "thanas:", " | ".join(t[:40] for t in x["titles"]))
    elif args.cmd == "events-consolidate":
        from .classifiers.gemma import GemmaClassifier
        from .events import consolidate
        print(consolidate(GemmaClassifier(), workers=args.workers))
    elif args.cmd == "events-status":
        from .events import status
        print(status())
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
    elif args.cmd == "healthcheck":
        with db.connect() as c:
            row = c.execute("""SELECT extract(epoch FROM now() - seen_at) AS age FROM heartbeats WHERE service = %s""",
                            (args.service,)).fetchone()
        age = None if row is None else float(row["age"])
        ok = age is not None and age <= args.max_age
        print(f"{args.service}: {'ok' if ok else 'stale'}, last heartbeat {'never' if age is None else f'{age:.0f} s ago'}")
        return 0 if ok else 1
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
