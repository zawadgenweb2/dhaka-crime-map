"""Side-by-side table of evaluation runs (logs written by `python -m app compare ... && cat report.json`).
Usage: python3 scripts/eval_table.py data/eval/*.log [--disagreements N]"""
import json
import sys

KEYS = ["valid_json", "article_precision", "article_recall", "incident_precision", "incident_recall",
        "category", "thana", "place", "date", "latency_p50_s", "latency_p95_s"]


def load(path):
    text = open(path, encoding="utf-8").read()
    i = text.rfind('\n{\n "run"')
    return json.loads(text[i + 1:]) if i >= 0 else None


def main(argv):
    n = 0
    if "--disagreements" in argv:
        n = int(argv[argv.index("--disagreements") + 1])
        argv = argv[:argv.index("--disagreements")]
    runs = [(p, load(p)) for p in argv]
    print("metric".ljust(20) + "".join(p.split("/")[-1][:18].ljust(20) for p, _ in runs))
    for k in KEYS + ["disagreements", "passes_all_gates"]:
        row = []
        for _, r in runs:
            v = (len(r["disagreements"]) if k == "disagreements" else r.get(k)) if r else "-"
            row.append(str(v).ljust(20))
        print(k.ljust(20) + "".join(row))
    for p, r in runs[-1:]:
        for d in (r or {}).get("disagreements", [])[:n]:
            print("-", d["article_id"], (d["title"] or "")[:45], "| ref", d["reference"], "| cand", d["candidate"])


if __name__ == "__main__":
    main(sys.argv[1:])
