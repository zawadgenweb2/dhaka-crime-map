"""Find place names that are mostly ordinary words or person names in our news text (তালা = lock, পলাশ = a name,
তিতাস = a gas company) and write data/sources/common-word-places-<date>.json for scripts/build_places.py.

For every place outside the curated Dhaka catalogue: in how many articles does its name appear, and in how many of
those is its district also named? A real upazila is usually reported with its district; a common word is not. Names
seen in >= 30 articles with their district in < 30% of them must have their district in the text to count as the
place. Places named like another district (Faridpur upazila in Pabna) are always on the list.

Needs the article database:  docker compose run --rm migrate python scripts/find_common_word_places.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db                       # noqa: E402
from app.text import normalize           # noqa: E402

MIN_ARTICLES, MAX_WITH_DISTRICT = 30, 0.30
SUFFIXES = ["", "র", "এর", "ের", "য়", "য়ে", "য়ের", "তে", "তেই", "ে", "েই", "এ", "কে", "বাসী", "ও", "ই"]


def main() -> None:
    data = json.loads((ROOT / "data" / "places.json").read_text(encoding="utf-8"))
    dist = {d["id"]: [normalize(x) for x in [d["name_bn"], *d["aliases"]]] for d in data["districts"]}
    district_names = {n for names in dist.values() for n in names}
    names: dict[str, set[str]] = {}
    for p in data["places"]:
        if p["district"] != "dhaka":
            for nm in {p["name_bn"], *p.get("aliases", [])}:
                names.setdefault(normalize(nm), set()).add(p["district"])
    alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    suf = "|".join(re.escape(normalize(s)) for s in sorted(SUFFIXES, key=len, reverse=True) if s)
    rx = re.compile(rf"(?<!\S)({alt})(?:{suf})?(?!\S)")
    hits: dict[str, int] = {}
    with_d: dict[str, int] = {}
    with db.connect() as c:
        for r in c.execute("SELECT title, body FROM articles WHERE body IS NOT NULL"):
            t = f" {normalize((r['title'] or '') + ' ' + (r['body'] or ''))} "
            for n in set(rx.findall(t)):
                hits[n] = hits.get(n, 0) + 1
                if any(any(f" {a}" in t for a in dist[d]) for d in names[n]):
                    with_d[n] = with_d.get(n, 0) + 1
    out = {}
    for n, h in sorted(hits.items()):
        share = with_d.get(n, 0) / h
        if (h >= MIN_ARTICLES and share < MAX_WITH_DISTRICT) or n in district_names:
            out[n] = {"articles": h, "with_its_district": round(share, 2)}
    for n in names:                                  # named like a district, even if rare in the corpus
        if n in district_names and n not in out:
            out[n] = {"articles": hits.get(n, 0), "with_its_district": None}
    path = ROOT / "data" / "sources" / f"common-word-places-{date.today().isoformat()}.json"
    path.write_text(json.dumps({"note": __doc__.split("\n\n")[1].replace("\n", " "), "rule":
                                {"min_articles": MIN_ARTICLES, "max_share_with_district": MAX_WITH_DISTRICT},
                                "names": out}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(out)} names need their district in the text:", ", ".join(out))


if __name__ == "__main__":
    main()
