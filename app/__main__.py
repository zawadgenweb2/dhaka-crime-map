"""Command line: python -m app <command>

  serve                 dashboard + API + twice-daily scheduler (http://127.0.0.1:8100)
  scrape [--days N]     one collection run now (N = also scan daily sitemaps N days back)
  classify [--all]      classify pending articles (or re-classify everything with --all)
  compare --with gemma  run another classifier on stored articles and compare with saved results
  stats                 quick counts in the terminal
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
    sp = sub.add_parser("serve"); sp.add_argument("--no-scheduler", action="store_true")
    sc = sub.add_parser("scrape"); sc.add_argument("--days", type=int, default=1)
    sc.add_argument("--max", type=int, default=None, help="max new articles to fetch")
    cl = sub.add_parser("classify"); cl.add_argument("--all", action="store_true")
    cl.add_argument("--limit", type=int, default=500)
    cp = sub.add_parser("compare"); cp.add_argument("--with", dest="other", default="gemma")
    cp.add_argument("--limit", type=int, default=30)
    sub.add_parser("stats")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)

    if args.cmd == "serve":
        import uvicorn
        from .api import create_app
        uvicorn.run(create_app(enable_scheduler=not args.no_scheduler), host=settings.host, port=settings.port)
        return 0

    from .pipeline import Pipeline
    if args.cmd == "scrape":
        result = Pipeline(progress=print).run(trigger="cli", days_back=args.days, max_articles=args.max)
        print(result)
        return 0 if result["status"] == "ok" else 1
    if args.cmd == "classify":
        done, found, errors = Pipeline(progress=print).classify_pending(limit=args.limit, reclassify=args.all)
        print(f"classified={done} incidents={found} errors={errors}")
        return 0
    if args.cmd == "compare":
        return compare(args.other, args.limit)
    if args.cmd == "stats":
        conn = db.connect()
        for r in conn.execute("SELECT status, count(*) n FROM articles GROUP BY status"):
            print(f"articles {r['status']:<11} {r['n']}")
        for r in conn.execute("""SELECT category, count(*) n FROM incidents WHERE duplicate_of IS NULL
                                 GROUP BY category ORDER BY n DESC"""):
            print(f"incidents {r['category']:<16} {r['n']}")
        return 0
    return 1


def compare(other: str, limit: int) -> int:
    """Agreement between the saved classifier output and another backend (e.g. Gemma vs Claude)."""
    from .classifiers import get_classifier
    from .pipeline import _row_to_article
    clf = get_classifier(other)
    conn = db.connect()
    rows = conn.execute("""SELECT * FROM articles WHERE status='classified' ORDER BY published_at DESC LIMIT ?""",
                        (limit,)).fetchall()
    same_crime = same_cat = same_thana = n = 0
    from .gazetteer import load
    gaz = load()
    for row in rows:
        saved = conn.execute("SELECT category, thana_id FROM incidents WHERE article_id=? ORDER BY id LIMIT 1",
                             (row["id"],)).fetchone()
        try:
            a = clf.classify(_row_to_article(row))
        except Exception as e:
            print(f"! {row['url']}: {e}")
            continue
        n += 1
        first = a.incidents[0] if (a.in_dhaka and a.incidents) else None
        same_crime += int(bool(saved) == bool(first))
        if saved and first:
            same_cat += int(saved["category"] == first.category)
            p = gaz.get(first.place_id) or gaz.best_match(first.location_text)
            same_thana += int(bool(p) and gaz.thana_of(p).id == saved["thana_id"])
    print(f"{other} vs saved on {n} articles: has-incident agreement {same_crime}/{n}, "
          f"category {same_cat}, thana {same_thana}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
