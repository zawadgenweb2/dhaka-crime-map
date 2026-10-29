"""Build data/places.json: all 64 districts of Bangladesh in their 8 divisions, with thanas and upazilas.

Sources, in order of authority:
  1. data/sources/bdgov-admin-2026-10-29.json - Bangladesh National Portal (bangladesh.gov.bd/views/upazila-list,
     read 29 Oct 2026): 8 divisions, 64 districts, 500 upazilas. Decides which upazilas exist and where they belong.
  2. data/sources/wikidata-bd-admin-2026-10-26.json (CC0) - points, English names, city police thanas.
  3. data/dhaka_places.json - curated Dhaka catalogue (ids kept unchanged); data/sources/metro-thanas.json -
     city police thanas Wikidata lacks, plus extra spellings; NEW_UPAZILAS below - notified after the portal list.
District ids: the six used since 27 Oct stay (dhaka, chattogram, sylhet, khulna, barishal, rangpur); the others are
the English name as a slug (coxs_bazar, chapai_nawabganj, ...). Place ids are "<district>:<slug>" outside Dhaka.
A Wikidata point is a representative point, not an area centre. Places without a point are kept (they still give a
district for counts) but get no map point.

Run: python scripts/build_places.py
"""
from __future__ import annotations

import json
import re
import unicodedata
from urllib.parse import urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "sources" / "wikidata-bd-admin-2026-10-26.json"
BDGOV = ROOT / "data" / "sources" / "bdgov-admin-2026-10-29.json"
DIVISION_BY_BN = {"ঢাকা বিভাগ": "dhaka", "চট্টগ্রাম বিভাগ": "chattogram", "রাজশাহী বিভাগ": "rajshahi",
                  "খুলনা বিভাগ": "khulna", "বরিশাল বিভাগ": "barishal", "সিলেট বিভাগ": "sylhet", "রংপুর বিভাগ": "rangpur",
                  "ময়মনসিংহ বিভাগ": "mymensingh"}
# Notified by the Cabinet Division (NICAR-1 branch, 8 Jul 2026) but not yet on the portal list: (district, bn, en)
NEW_UPAZILAS = [("cumilla", "বাঙ্গরা", "Bangra"), ("chattogram", "ফটিকছড়ি উত্তর", "Fatikchhari North")]
# Official spelling -> Wikidata spelling where the two differ beyond loose() (both are kept as names)
WD_SPELLING = {"মোরেলগঞ্জ": "মোড়েলগঞ্জ", "দুপচাচিঁয়া": "দুপচাঁচিয়া", "আদর্শ সদর": "কুমিল্লা আদর্শ সদর",
               "সদর দক্ষিণ": "কুমিল্লা সদর দক্ষিণ", "লক্ষীছড়ি": "লক্ষ্মীছড়ি", "সোনারগাঁ": "সোনারগাঁও",
               "খালিয়াজুরী": "খালিয়াজুড়ি"}
# English names for upazilas Wikidata does not have yet (new since 2021)
NEW_EN = {"মোকামতলা": "Mokamtala", "চন্দ্রগঞ্জ": "Chandraganj", "ডাসার": "Dasar", "ঈদগাঁও": "Eidgaon",
          "শান্তিগঞ্জ": "Shantiganj", "মধ্যনগর": "Madhyanagar", "লালমাই": "Lalmai", "গুইমারা": "Guimara",
          "রুহিয়া": "Ruhiya", "দক্ষিণ গফরগাঁও": "Dakshin Gafargaon", "জিয়ানগর": "Zianagar", "বাঙ্গরা": "Bangra",
          "ফটিকছড়ি উত্তর": "Fatikchhari North", "সদর দক্ষিণ": "Sadar Dakshin", "আদর্শ সদর": "Adarsha Sadar"}
METRO = ROOT / "data" / "sources" / "metro-thanas.json"
OSM_POINTS = ROOT / "data" / "sources" / "osm-points-2026-10-29.json"   # scripts/fill_points.py
COMMON_WORDS = ROOT / "data" / "sources" / "common-word-places-2026-10-29.json"   # scripts/find_common_word_places.py

DIVISIONS = {  # id: (Bangla, English); ids are their own namespace (a division id may equal a district id)
    "dhaka": ("ঢাকা", "Dhaka"), "chattogram": ("চট্টগ্রাম", "Chattogram"), "rajshahi": ("রাজশাহী", "Rajshahi"),
    "khulna": ("খুলনা", "Khulna"), "barishal": ("বরিশাল", "Barishal"), "sylhet": ("সিলেট", "Sylhet"),
    "rangpur": ("রংপুর", "Rangpur"), "mymensingh": ("ময়মনসিংহ", "Mymensingh"),
}
DIVISION_BY_EN = {"Dhaka Division": "dhaka", "Chattogram Division": "chattogram", "Rajshahi Division": "rajshahi",
                  "Khulna Division": "khulna", "Barisal Division": "barishal", "Sylhet Division": "sylhet",
                  "Rangpur Division": "rangpur", "Mymensingh Division": "mymensingh"}
KEEP_IDS = {"Q1850485": "dhaka", "Q1074991": "chattogram", "Q2093352": "sylhet", "Q2093344": "khulna",
            "Q1763301": "barishal", "Q2344570": "rangpur"}
# Other spellings used by the papers (and the English-letter police units that name a city)
DISTRICT_ALIASES = {
    "dhaka": ["রাজধানী", "ডিএমপি", "ঢাকা মহানগর"], "chattogram": ["চট্রগ্রাম", "চাটগাঁ", "সিএমপি"],
    "sylhet": ["এসএমপি"], "khulna": ["কেএমপি"], "barishal": ["বিএমপি", "বরিশাল"], "rangpur": ["আরপিএমপি"],
    "rajshahi": ["আরএমপি"], "gazipur": ["জিএমপি"], "cumilla": ["কুমিল্লা"], "coxs_bazar": ["কক্সবাজার"],
    "chapai_nawabganj": ["চাঁপাই নবাবগঞ্জ", "চাঁপাই"], "netrokona": ["নেত্রকোনা", "নেত্রকোণা"],
    "munshiganj": ["মুন্সিগঞ্জ", "মুন্সীগঞ্জ"], "rangamati": ["রাঙামাটি", "রাঙ্গামাটি"], "jhalokati": ["ঝালকাঠী", "ঝালকাঠি"],
    "narayanganj": ["নারায়নগঞ্জ"], "tangail": ["টাঙাইল"], "shariatpur": ["শরিয়তপুর"], "brahmanbaria": ["বি-বাড়িয়া"],
    "bogura": ["বগুড়া"], "jashore": ["যশোর"], "khagrachari": ["খাগড়াছড়ি", "খাগড়াছড়ী"], "moulvibazar": ["মৌলভীবাজার"],
    "panchagarh": ["পঞ্চগড়"], "thakurgaon": ["ঠাকুরগাঁও"], "kishoreganj": ["কিশোরগঞ্জ"], "lakshmipur": ["লক্ষীপুর"],
}
# English names Wikidata lacks (used for ids and the English interface)
EN_FIX = {"সাতকানিয়া উত্তর": "Satkania North", "দক্ষিণ রাঙ্গুনিয়া": "Rangunia South", "কোতোয়ালী": "Kotwali",
          "শাহপরাণ": "Shahporan", "খুলনা সদর": "Khulna Sadar", "কাউনিয়া": "Kaunia", "বন্দর": "Bandar", "কাজিরহাট": "Kazirhat"}
# Words removed from names: "কোতোয়ালী থানা, বরিশাল" -> "কোতোয়ালী"
STRIP_BN = re.compile(r"\s*(থানা|উপজেলা|পৌরসভা|জেলা)\s*(,.*)?$")
STRIP_EN = re.compile(r"\s*(Thana|thana|Upazila|upazila|District|district)\s*$")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower().replace("'", "")).strip("_")


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def point(r: dict):
    m = re.match(r"Point\(([-\d.]+) ([-\d.]+)\)", (r.get("coord") or {}).get("value", ""))
    return (round(float(m.group(2)), 5), round(float(m.group(1)), 5)) if m else (None, None)


def loose(name: str) -> str:
    """Matching key that ignores common spelling differences: composed vs decomposed য়/ড়/ঢ়, ণ/ন, ী/ি, ূ/ু,
    hasanta, anusvara/ঙ, chandrabindu, spaces, hyphens, zero-width joiners."""
    t = unicodedata.normalize("NFC", name)
    for a, b in (("\u09af\u09bc", "\u09df"), ("\u09a1\u09bc", "\u09dc"), ("\u09a2\u09bc", "\u09dd"),
                 ("\u09a3", "\u09a8"), ("\u09c0", "\u09bf"), ("\u09c2", "\u09c1"), ("\u09cd", ""),
                 ("\u0982", "\u0999"), ("\u0981", ""), (" ", ""), ("-", ""), ("\u200c", ""), ("\u200d", "")):
        t = t.replace(a, b)
    return t


def official_name(name: str) -> str:
    """'নবাবগঞ্জ উপজেলা, ঢাকা' -> 'নবাবগঞ্জ'; 'উপজেলা মতলব দক্ষিণ,চাঁদপুর' -> 'মতলব দক্ষিণ'; 'শেরপুর উপজেলা, বগুড়া' -> 'শেরপুর'."""
    t = name.split(",")[0].strip()
    t = re.sub(r"^উপজেলা\s+", "", t)
    return re.sub(r"\s*(উপজেলা|পার্বত্য জেলা|জেলা)$", "", t).strip()


def vowel_variant(name: str) -> set[str]:
    """Final ী/ি spellings are both common in news text (কোতোয়ালী / কোতোয়ালি)."""
    return {name[:-1] + {"ী": "ি", "ি": "ী"}[name[-1]]} if name[-1:] in ("ী", "ি") else set()


def main() -> None:
    rows = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["results"]["bindings"]
    children: dict[str, list[dict]] = {}
    for r in rows:
        if "parent" in r:
            children.setdefault(qid(r["parent"]["value"]), []).append(r)

    districts: dict[str, dict] = {}                 # wikidata id -> district record
    for r in rows:
        if r["kind"]["value"] != "district" or qid(r["item"]["value"]) in districts:
            continue
        q = qid(r["item"]["value"])
        bn = STRIP_BN.sub("", r.get("bn", {}).get("value", "")).strip()
        en = STRIP_EN.sub("", r.get("en", {}).get("value", "")).strip()
        did = KEEP_IDS.get(q) or slug(en)
        lat, lng = point(r)
        districts[q] = {"id": did, "name_bn": bn, "name_en": en, "lat": lat, "lng": lng,
                        "division": DIVISION_BY_EN[r["parentEn"]["value"]],
                        "aliases": sorted((set(DISTRICT_ALIASES.get(did, [])) | vowel_variant(bn)) - {bn}),
                        "wikidata": q}
    assert len(districts) == 64, len(districts)

    official = json.loads(BDGOV.read_text(encoding="utf-8"))["districts"]
    by_loose = {loose(d["name_bn"]): d for d in districts.values()}
    for o in official:                                  # the portal decides the division of every district
        d = by_loose[loose(official_name(o["district"]))]
        div = {loose(k): v for k, v in DIVISION_BY_BN.items()}[loose(o["division"])]
        assert d["division"] == div, (d["id"], o["division"])
        # (Bangla name, English from the upazila's official web address: dupchanchia.bogura.gov.bd -> Dupchanchia)
        d["official_upazilas"] = [(official_name(u["name"]), urlparse(u["url"]).hostname.split(".")[0])
                                  for u in o["upazilas"]]
        d["website"] = o["url"]
    assert all("official_upazilas" in d for d in districts.values())

    dhaka = json.loads((ROOT / "data" / "dhaka_places.json").read_text(encoding="utf-8"))
    places = [{**p, "district": "dhaka"} for p in dhaka]
    unmatched = []
    district_names = {loose(x) for d in districts.values() for x in [d["name_bn"], *d["aliases"]]}
    for q, d in sorted(districts.items(), key=lambda kv: kv[1]["id"]):
        level1 = children.get(q, [])
        level2 = [c for r in level1 for c in children.get(qid(r["item"]["value"]), [])]
        wd = {}                                         # loose Bangla name -> wikidata row (first wins: level 1)
        for r in level1 + level2:
            if r["kind"]["value"] in ("upazila", "thana"):
                wd.setdefault(loose(STRIP_BN.sub("", r.get("bn", {}).get("value", "")).strip()), r)
        have = {loose(p["name_bn"]) for p in places if p["district"] == d["id"]}
        for k in [x for x in have]:                     # Dhaka: the curated catalogue already has these
            have.add(k)
        new = [(bn, sub) for bn, sub in d["official_upazilas"]] + \
              [(bn, en) for dist, bn, en in NEW_UPAZILAS if dist == d["id"]]
        spelling = {loose(k): v for k, v in WD_SPELLING.items()}
        for bn, en_hint in new:                         # every official upazila
            if loose(bn) in have:
                continue
            r = wd.get(loose(bn)) or wd.get(loose(spelling.get(loose(bn), bn)))
            wbn = STRIP_BN.sub("", r.get("bn", {}).get("value", "")).strip() if r else bn
            en = (STRIP_EN.sub("", (r.get("en", {}) or {}).get("value", "") or "").strip() if r else "") \
                or NEW_EN.get(bn) or EN_FIX.get(bn) or (en_hint or "").replace("sadar", " Sadar").strip().title() or bn
            lat, lng = point(r) if r else (None, None)
            if r is None:
                unmatched.append(f"{d['id']}:{bn}")
            pid = f"{d['id']}:{slug(en) or slug(bn)}"
            while any(p["id"] == pid for p in places):
                pid += "_2"
            places.append({"id": pid, "name_en": en, "name_bn": bn,
                           "aliases": sorted(({wbn} | vowel_variant(bn) | vowel_variant(wbn)) - {bn}),
                           "kind": "upazila", "parent": None, "lat": lat, "lng": lng, "district": d["id"],
                           **({"wikidata": qid(r["item"]["value"])} if r else {})})
            have.add(loose(bn))
        if d["id"] == "dhaka":
            continue                                    # Dhaka's thanas and neighbourhoods are curated
        for r in level1 + level2:                       # city police thanas (and any thana not named as an upazila)
            if r["kind"]["value"] != "thana":
                continue
            bn = STRIP_BN.sub("", r.get("bn", {}).get("value", "")).strip()
            if not bn or loose(bn) in have or loose(bn) in district_names:
                continue                                # a "Kurigram" thana is the district's own Sadar thana
            en = STRIP_EN.sub("", r.get("en", {}).get("value", "") or "").strip() or EN_FIX.get(bn, "")
            if not en:
                continue                                # a Wikidata stub with no English name and no point
            lat, lng = point(r)
            pid = f"{d['id']}:{slug(en) or slug(qid(r['item']['value']))}"
            while any(p["id"] == pid for p in places):
                pid += "_2"
            places.append({"id": pid, "name_en": en, "name_bn": bn, "aliases": sorted(vowel_variant(bn)),
                           "kind": "thana", "parent": None, "lat": lat, "lng": lng, "district": d["id"],
                           "wikidata": qid(r["item"]["value"])})
            have.add(loose(bn))

    metro = json.loads(METRO.read_text(encoding="utf-8"))
    for t in metro["thanas"]:
        pid = f"{t['district']}:{slug(t['name_en'])}"
        assert not any(p["id"] == pid for p in places), pid
        places.append({"id": pid, "name_en": t["name_en"], "name_bn": t["name_bn"], "aliases": [], "kind": "thana",
                       "parent": None, "lat": t["lat"], "lng": t["lng"], "district": t["district"]})
    for pid, extra in metro["aliases"].items():
        p = next(p for p in places if p["id"] == pid)
        p["aliases"] = sorted(set(p["aliases"]) | set(extra))

    if OSM_POINTS.exists():                             # points Wikidata lacks, looked up once (ODbL)
        osm = json.loads(OSM_POINTS.read_text(encoding="utf-8"))["points"]
        for p in places:
            if p["lat"] is None and p["id"] in osm:
                p["lat"], p["lng"] = osm[p["id"]]["lat"], osm[p["id"]]["lng"]

    if COMMON_WORDS.exists():                           # names that are mostly words, people or other districts
        common = {loose(n) for n in json.loads(COMMON_WORDS.read_text(encoding="utf-8"))["names"]}
        for p in places:
            if p["district"] != "dhaka" and any(loose(n) in common for n in [p["name_bn"], *p.get("aliases", [])]):
                p["needs_context"] = True               # counts only when its district is in the text

    # a district without its own point takes the middle of its places
    by_district: dict[str, list[dict]] = {}
    for p in places:
        by_district.setdefault(p["district"], []).append(p)
    for d in districts.values():
        if d["lat"] is None:
            pts = [(p["lat"], p["lng"]) for p in by_district.get(d["id"], []) if p["lat"] is not None]
            if pts:
                d["lat"], d["lng"] = (round(sum(a for a, _ in pts) / len(pts), 5),
                                      round(sum(b for _, b in pts) / len(pts), 5))

    for d in districts.values():
        d.pop("official_upazilas", None)
    out = {"divisions": [{"id": k, "name_bn": v[0], "name_en": v[1]} for k, v in DIVISIONS.items()],
           "districts": sorted(districts.values(), key=lambda d: (list(DIVISIONS).index(d["division"]), d["name_en"])),
           "places": places,
           "sources": [BDGOV.name + " (Bangladesh National Portal, read 29 Oct 2026: divisions, districts, upazilas)",
                       "data/dhaka_places.json (curated)", SNAPSHOT.name + " (Wikidata, CC0: points, English names, thanas)",
                       METRO.name + " (curated; points from OpenStreetMap, ODbL)",
                       "Cabinet Division NICAR-1 notifications of 8 Jul 2026 (Bangra, Fatikchhari North)"]}
    (ROOT / "data" / "places.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    per_div: dict[str, int] = {}
    for d in districts.values():
        per_div[d["division"]] = per_div.get(d["division"], 0) + 1
    kinds: dict[str, int] = {}
    for p in places:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"wrote data/places.json: {len(out['districts'])} districts {per_div}, {len(places)} places {kinds},",
          "without coordinates:", sum(1 for p in places if p["lat"] is None))
    print("official upazilas not found in Wikidata (no point yet):", unmatched)


if __name__ == "__main__":
    main()
