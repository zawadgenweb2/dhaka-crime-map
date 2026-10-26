"""Offline evaluation: run a candidate classifier on articles that already have reference results.

The reference set is the 71 articles labelled during the prototype phase (stored as backend 'claude'; no Claude
API is used any more). It is a strong baseline, not ground truth: a Bangla reviewer should check disagreements.
Nothing here writes to `incidents`; answers go to `eval_results` under a run label.
"""
from __future__ import annotations

import json
import statistics
import time
from datetime import datetime

from psycopg.types.json import Jsonb

from . import db
from .classifiers import get_classifier
from .gazetteer import load as load_gazetteer
from .schema import ArticleAnalysis
from .store import build_rows
from .worker import article_from_row

# Switch gates (precision first, from the council review). Recall is reported but gated lower.
GATES = {"valid_json": 0.98, "article_precision": 0.98, "article_recall": 0.90,
         "incident_precision": 0.95, "incident_recall": 0.85,
         "category": 0.95, "thana": 0.95, "date": 0.95}


def _reference(c, article_id: int) -> list[dict]:
    return c.execute("""SELECT category, place_id, thana_id, incident_date, time_of_day FROM incidents
                        WHERE article_id = %s AND (published OR review_status = 'approved')
                        AND review_status <> 'rejected'""", (article_id,)).fetchall()


def _match(ref: list[dict], pred: list[dict]) -> list[tuple[dict, dict]]:
    """Pair predicted with reference incidents: same thana first, then same category."""
    pairs, left = [], list(pred)
    for r in ref:
        best = next((p for p in left if p["thana_id"] == r["thana_id"] and p["category"] == r["category"]), None) \
            or next((p for p in left if p["thana_id"] == r["thana_id"]), None) \
            or next((p for p in left if p["category"] == r["category"]), None)
        if best is not None:
            pairs.append((r, best))
            left.remove(best)
    return pairs


def compare(other: str, limit: int = 1000, out: str | None = None) -> int:
    clf = get_classifier(other)
    gaz = load_gazetteer()
    label = f"{clf.name}@{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    with db.connect() as c:
        # Frozen reference set: the prototype-phase labels (historical backend 'claude'); local output never becomes reference.
        arts = c.execute("""SELECT a.* FROM articles a WHERE a.status = 'classified' AND EXISTS
                              (SELECT 1 FROM analyses x WHERE x.article_id = a.id AND x.backend = 'claude')
                            ORDER BY a.published_at DESC NULLS LAST LIMIT %s""", (limit,)).fetchall()
    print(f"evaluating {clf.name} on {len(arts)} reference articles (run {label})")
    tp = fp = fn = tn = valid = 0
    inc_tp = inc_fp = inc_fn = 0
    cat_ok = thana_ok = place_ok = date_ok = date_n = matched = 0
    latencies, disagreements = [], []
    for i, a in enumerate(arts, 1):
        with db.connect() as c:
            ref = _reference(c, a["id"])
        started = time.monotonic()
        try:
            analysis, meta = clf.classify_with_meta(article_from_row(a))
            ok, err = True, None
        except Exception as e:  # count failures in the denominator
            analysis, meta, ok, err = None, {}, False, f"{type(e).__name__}: {e}"
        latency = meta.get("latency_s") or round(time.monotonic() - started, 2)
        latencies.append(latency)
        with db.tx() as c:
            c.execute("""INSERT INTO eval_results (run_label, article_id, backend, model, ok, error, result, latency_s,
                           input_tokens, output_tokens) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (label, a["id"], other, meta.get("model"), ok, err,
                       Jsonb(analysis.model_dump()) if analysis else None, latency,
                       meta.get("input_tokens"), meta.get("output_tokens")))
        pred = [r for r in build_rows(a, analysis, gaz, {}, "auto") if r["passes"]] if ok else []
        valid += ok
        has_ref, has_pred = bool(ref), bool(pred)
        tp += has_ref and has_pred; fp += has_pred and not has_ref
        fn += has_ref and not has_pred; tn += not has_ref and not has_pred
        pairs = _match(ref, pred)
        differs = len(pairs) != len(ref) or len(pairs) != len(pred)   # unmatched on either side
        inc_tp += len(pairs)
        inc_fp += len(pred) - len(pairs)                                # invented / extra incidents
        inc_fn += len(ref) - len(pairs)                                 # missed incidents
        for r, p in pairs:
            matched += 1
            cat_ok += r["category"] == p["category"]
            thana_ok += r["thana_id"] == p["thana_id"]
            place_ok += r["place_id"] == p["place_id"]
            if r["incident_date"]:
                date_n += 1
                date_ok += r["incident_date"] == p["incident_date"]
            differs |= (r["category"], r["thana_id"], r["place_id"]) != (p["category"], p["thana_id"], p["place_id"])
            differs |= bool(r["incident_date"]) and r["incident_date"] != p["incident_date"]
        if differs:
            disagreements.append({"article_id": a["id"], "url": a["url"], "title": a["title"],
                                  "reference": [f"{x['category']}@{x['place_id']}/{x['incident_date']}" for x in ref],
                                  "candidate": [f"{x['category']}@{x['place_id']}/{x['incident_date']}" for x in pred],
                                  "error": err})
        print(f"  {i:>3}/{len(arts)} {'ok ' if ok else 'ERR'} {latency:6.1f}s ref={len(ref)} pred={len(pred)}"
              f"{'' if ok else '  ' + (err or '')[:80]}")

    n = len(arts) or 1
    rate = lambda a, b: round(a / b, 3) if b else None  # noqa: E731
    report = {
        "run": label, "articles": len(arts), "valid_json": rate(valid, n),
        "article_precision": rate(tp, tp + fp), "article_recall": rate(tp, tp + fn),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn}, "matched_incidents": matched,
        "incident_precision": rate(inc_tp, inc_tp + inc_fp), "incident_recall": rate(inc_tp, inc_tp + inc_fn),
        "incident_counts": {"matched": inc_tp, "extra": inc_fp, "missed": inc_fn},
        "category": rate(cat_ok, matched), "thana": rate(thana_ok, matched), "place": rate(place_ok, matched),
        "date": rate(date_ok, date_n),
        "latency_p50_s": round(statistics.median(latencies), 1) if latencies else None,
        "latency_p95_s": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1) if latencies else None,
        "disagreements": disagreements,
    }
    report["gates"] = {k: (report[k] is not None and report[k] >= v) for k, v in GATES.items()}
    report["passes_all_gates"] = all(report["gates"].values())
    print(json.dumps({k: v for k, v in report.items() if k != "disagreements"}, indent=1))
    print(f"{len(disagreements)} articles disagree with the reference; review them before switching.")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1, default=str)
    return 0
