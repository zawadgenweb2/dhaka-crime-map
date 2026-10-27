"""Build data/places.json: the curated Dhaka catalogue plus thanas/upazilas of the other supported districts.

Sources: data/dhaka_places.json (curated, ids kept unchanged) and the CC0 Wikidata snapshot
data/sources/wikidata-bd-admin-2026-10-26.json (district -> thana/upazila links, Bangla/English names, points).
New ids are "<district>:<slug>"; a Wikidata point is a representative point, not an area centre. Places without a
coordinate are kept (they still give a district and an area for counts) but get no map point.

Run: python scripts/build_places.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "sources" / "wikidata-bd-admin-2026-10-26.json"
DISTRICT_QIDS = {"Q1074991": "chattogram", "Q2093352": "sylhet", "Q2093344": "khulna", "Q1763301": "barishal",
                 "Q2344570": "rangpur"}
DISTRICTS = {  # key: (Bangla, English, representative point)
    "dhaka": ("ঢাকা", "Dhaka", (23.785, 90.395)),
    "chattogram": ("চট্টগ্রাম", "Chattogram", (22.3475, 91.8123)),
    "sylhet": ("সিলেট", "Sylhet", (24.8949, 91.8687)),
    "khulna": ("খুলনা", "Khulna", (22.8456, 89.5403)),
    "barishal": ("বরিশাল", "Barishal", (22.7010, 90.3535)),
    "rangpur": ("রংপুর", "Rangpur", (25.7439, 89.2752)),
}
# English names Wikidata lacks (used for ids and the English interface)
EN_FIX = {"সাতকানিয়া উত্তর": "Satkania North", "দক্ষিণ রাঙ্গুনিয়া": "Rangunia South", "কোতোয়ালী": "Kotwali",
          "শাহপরাণ": "Shahporan", "খুলনা সদর": "Khulna Sadar", "কাউনিয়া": "Kaunia", "বন্দর": "Bandar", "কাজিরহাট": "Kazirhat"}
# Words removed from names: "কোতোয়ালী থানা, বরিশাল" -> "কোতোয়ালী"
STRIP_BN = re.compile(r"\s*(থানা|উপজেলা|পৌরসভা)\s*(,.*)?$")
STRIP_EN = re.compile(r"\s*(Thana|thana|Upazila|upazila)\s*$")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def point(r: dict):
    m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", (r.get("coord") or {}).get("value", ""))
    return (round(float(m.group(2)), 5), round(float(m.group(1)), 5)) if m else (None, None)


def main() -> None:
    dhaka = json.loads((ROOT / "data" / "dhaka_places.json").read_text(encoding="utf-8"))
    places = [{**p, "district": "dhaka"} for p in dhaka]
    rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["results"]["bindings"]
    children: dict[str, list[dict]] = {}
    for r in rows:
        if "parent" in r:
            children.setdefault(qid(r["parent"]["value"]), []).append(r)

    for dq, district in DISTRICT_QIDS.items():
        level1 = children.get(dq, [])
        level2 = [c for r in level1 for c in children.get(qid(r["item"]["value"]), [])]
        seen: dict[str, dict] = {}            # base Bangla name -> place (a thana and its upazila share one name)
        for r in level1 + level2:
            bn = STRIP_BN.sub("", r.get("bn", {}).get("value", "")).strip()
            en = STRIP_EN.sub("", r.get("en", {}).get("value", "") or "").strip() or EN_FIX.get(bn, bn)
            if not bn:
                continue
            lat, lng = point(r)
            if bn in seen:                     # keep the first (level 1 = the upazila / city thana); fill a missing point
                if seen[bn]["lat"] is None and lat is not None:
                    seen[bn].update(lat=lat, lng=lng)
                continue
            pid = f"{district}:{slug(en) or slug(qid(r['item']['value']))}"
            while any(p["id"] == pid for p in seen.values()):
                pid += "_2"
            seen[bn] = {"id": pid, "name_en": en, "name_bn": bn, "aliases": [], "kind": r["kind"]["value"],
                        "parent": None, "lat": lat, "lng": lng, "district": district,
                        "wikidata": qid(r["item"]["value"])}
        places.extend(seen.values())

    # Spelling variants: final ী/ি (কোতোয়ালী/কোতোয়ালি) and য়/য় forms are both common in news text.
    for p in places:
        if p["district"] == "dhaka":
            continue
        variants = {p["name_bn"][:-1] + {"ী": "ি", "ি": "ী"}[p["name_bn"][-1]]} if p["name_bn"][-1:] in ("ী", "ি") else set()
        p["aliases"] = sorted(set(p["aliases"]) | variants - {p["name_bn"]})

    out = {"districts": [{"id": k, "name_bn": v[0], "name_en": v[1], "lat": v[2][0], "lng": v[2][1]}
                         for k, v in DISTRICTS.items()],
           "places": places,
           "sources": ["data/dhaka_places.json (curated)", SNAPSHOT.name + " (Wikidata, CC0)"]}
    (ROOT / "data" / "places.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    by = {}
    for p in places:
        by[p["district"]] = by.get(p["district"], 0) + 1
    print(f"wrote data/places.json: {len(places)} places", by,
          "without coordinates:", sum(1 for p in places if p["lat"] is None))


if __name__ == "__main__":
    main()
