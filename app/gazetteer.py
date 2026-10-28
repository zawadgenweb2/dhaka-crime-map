"""Place catalogue for the supported districts: thanas, upazilas, neighbourhoods and landmarks with coordinates.

data/places.json (built by scripts/build_places.py) holds the curated Dhaka catalogue plus thanas/upazilas of the other
supported districts. Every place has a district. Some names exist in several districts (Kotwali, Chawkbazar, Bandar,
Sadarghat, Airport, Kaunia) or in unsupported districts (Mirpur in Kushtia): a mention is resolved by a district word
right before it ("চট্টগ্রাম নগরের চকবাজারে"), otherwise by the other places and district names in the same text; if it
stays ambiguous it is not used (precision first).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache

from .config import ROOT
from .text import normalize

KIND_RANK = {"landmark": 3, "area": 2, "thana": 1, "upazila": 1, "district": 0}

# Supported districts and the words that name them in Bangla news text.
DISTRICT_TERMS = {
    "dhaka": ["ঢাকা", "রাজধানী", "ডিএমপি", "ঢাকা মহানগর"],
    "chattogram": ["চট্টগ্রাম", "চট্রগ্রাম", "চাটগাঁ", "সিএমপি"],
    "sylhet": ["সিলেট", "এসএমপি"],
    "khulna": ["খুলনা", "কেএমপি"],
    "barishal": ["বরিশাল", "বিএমপি"],
    "rangpur": ["রংপুর", "আরপিএমপি"],
}
SUPPORTED = tuple(DISTRICT_TERMS)
DHAKA_TERMS = DISTRICT_TERMS["dhaka"]
# Bangla case endings allowed right after a place name ("মিরপুরে", "গুলশানের", "বাড্ডায়")
SUFFIXES = {normalize(s) for s in ["", "র", "এর", "ের", "য়", "য়ে", "য়ের", "তে", "তেই", "ে", "েই", "এ", "কে",
                                  "বাসী", "স্থ", "ও", "ই", "গামী", "মুখী"]}
# Districts we do not cover. "কুষ্টিয়ার মিরপুরে" or "দিনাজপুরের নবাবগঞ্জে" names a namesake outside our area.
OTHER_DISTRICTS = {normalize(d) for d in """
বাগেরহাট বান্দরবান বরগুনা ভোলা বগুড়া ব্রাহ্মণবাড়িয়া চাঁদপুর চাঁপাইনবাবগঞ্জ চুয়াডাঙ্গা কুমিল্লা
কক্সবাজার দিনাজপুর ফরিদপুর ফেনী গাইবান্ধা গাজীপুর গোপালগঞ্জ হবিগঞ্জ জামালপুর যশোর ঝালকাঠি ঝিনাইদহ জয়পুরহাট
খাগড়াছড়ি কিশোরগঞ্জ কুড়িগ্রাম কুষ্টিয়া লক্ষ্মীপুর লালমনিরহাট মাদারীপুর মাগুরা মানিকগঞ্জ মেহেরপুর মৌলভীবাজার
মুন্সিগঞ্জ মুন্সীগঞ্জ ময়মনসিংহ নওগাঁ নড়াইল নারায়ণগঞ্জ নরসিংদী নাটোর নেত্রকোনা নীলফামারী নোয়াখালী পাবনা পঞ্চগড়
পটুয়াখালী পিরোজপুর রাজবাড়ী রাজশাহী রাঙামাটি সাতক্ষীরা শরীয়তপুর শেরপুর সিরাজগঞ্জ সুনামগঞ্জ টাঙ্গাইল
ঠাকুরগাঁও""".split()}
_DISTRICT_WORDS = {normalize(w): k for k, words in DISTRICT_TERMS.items() for w in words if " " not in w}
_GENITIVE = [normalize(x) for x in ("ের", "এর", "য়ের", "র")]
_LOCATIVE = [normalize(x) for x in ("ে", "য়", "য়ে", "তে", "এ")]
_ENDINGS = sorted({*_GENITIVE, *SUFFIXES} - {""}, key=len, reverse=True)
# Words that can sit between a district and a place: "চট্টগ্রাম নগরের চকবাজারে", "কুষ্টিয়া সদর উপজেলার মিরপুরে"
_CONNECTORS = {normalize(x) for x in ("নগরের", "নগর", "নগরীর", "মহানগরের", "মহানগর", "শহরের", "শহর", "জেলার", "জেলা",
                                      "উপজেলার", "উপজেলা", "পৌরসভার", "পৌর", "সদরের", "সদর", "থানার", "এলাকার")}
# Victims from anywhere are taken to the big medical colleges: naming one says nothing about where a crime happened.
REFERRAL_PLACES = {"dmch"}
REFERRAL_PHRASES = [normalize(x) for x in ("ঢাকা মেডিকেল কলেজ হাসপাতাল", "ঢাকা মেডিকেল কলেজ", "ঢাকা মেডিকেল",
                                           "চট্টগ্রাম মেডিকেল কলেজ হাসপাতাল", "চট্টগ্রাম মেডিকেল",
                                           "সিলেট এম এ জি ওসমানী মেডিকেল", "ওসমানী মেডিকেল", "খুলনা মেডিকেল",
                                           "শেরেবাংলা মেডিকেল", "রংপুর মেডিকেল")]


def district_word(word: str) -> str | None:
    """'chattogram' for চট্টগ্রাম/চট্টগ্রামের/চট্টগ্রামে…, 'other' for an unsupported district, else None."""
    for base in (word, *(word[: -len(e)] for e in _ENDINGS if word.endswith(e))):
        if base in _DISTRICT_WORDS:
            return _DISTRICT_WORDS[base]
        if base in OTHER_DISTRICTS:
            return "other"
    return None


def _locative_district(word: str) -> str | None:
    """The district named in the locative case ("in X"): চট্টগ্রামে, ফেনীতে, কুমিল্লায়."""
    for suf in _LOCATIVE:
        if word.endswith(suf):
            base = word[: -len(suf)]
            if base in _DISTRICT_WORDS:
                return _DISTRICT_WORDS[base]
            if base in OTHER_DISTRICTS:
                return "other"
    return None


def _qualifier(before: str) -> str | None:
    """The district named right before a place (up to 4 words back, through connector words like নগরের/উপজেলার)."""
    for word in reversed(before.rstrip().split(" ")[-4:]):
        d = district_word(word)
        if d:
            return d
        if word not in _CONNECTORS:
            return None
    return None


def _strip_referrals(n: str) -> str:
    for phrase in REFERRAL_PHRASES:
        n = n.replace(phrase, " ")
    return n


@dataclass(frozen=True)
class Place:
    id: str
    name_en: str
    name_bn: str
    aliases: tuple[str, ...]
    kind: str
    parent: str | None
    lat: float | None
    lng: float | None
    district: str = "dhaka"

    def to_dict(self) -> dict:
        return {"id": self.id, "name_en": self.name_en, "name_bn": self.name_bn, "kind": self.kind,
                "parent": self.parent, "lat": self.lat, "lng": self.lng, "district": self.district}


class Gazetteer:
    def __init__(self, places: list[Place], districts: list[dict] | None = None):
        self.places = places
        self.districts = districts or []
        self.by_id = {p.id: p for p in places}
        terms: dict[str, list[Place]] = {}
        for p in places:
            for name in {p.name_bn, *p.aliases}:
                key = normalize(name)
                if p not in terms.setdefault(key, []):
                    terms[key].append(p)
        # Longest names first so "মিরপুর 10" wins over "মিরপুর"
        self._terms = sorted(terms.items(), key=lambda t: len(t[0]), reverse=True)

    def get(self, place_id: str | None) -> Place | None:
        return self.by_id.get(place_id or "")

    def thana_of(self, place: Place) -> Place:
        return self.by_id[place.parent] if place.parent in self.by_id else place

    def district_mentions(self, text: str) -> set[str]:
        """Supported districts named by a district word (referral hospitals excluded)."""
        n = _strip_referrals(f" {normalize(text)} ")
        out = {d for w in n.split(" ") if (d := district_word(w)) and d != "other"}
        out |= {k for k, words in DISTRICT_TERMS.items() for w in words if " " in w and f" {normalize(w)} " in n}
        return out

    def find_all(self, text: str) -> list[Place]:
        """Places mentioned in the text, most specific first, without overlapping matches. A name shared by several
        districts is kept only when a district word before it, or the rest of the text, settles which one."""
        n = f" {normalize(text)} "
        taken: list[tuple[int, int]] = []
        hits: list[list[Place]] = []
        for term, candidates in self._terms:
            start = n.find(term)
            while start != -1:
                end = start + len(term)
                word_end = n.find(" ", end)
                if (n[start - 1] == " " and n[end:word_end] in SUFFIXES
                        and not any(s < end and start < e for s, e in taken)):
                    q = _qualifier(n[:start])
                    options = [] if q == "other" else [p for p in candidates if q is None or p.district == q]
                    taken.append((start, end))           # the words are used up even when no candidate fits
                    if options:
                        hits.append(options)
                start = n.find(term, end)
        settled = {opts[0].district for opts in hits if len({p.district for p in opts}) == 1}
        context = settled | self.district_mentions(text)
        found: list[Place] = []
        for opts in hits:
            districts = {p.district for p in opts}
            if len(districts) > 1:
                fitting = [p for p in opts if p.district in context]
                if len({p.district for p in fitting}) != 1:
                    continue                             # still ambiguous: not used
                opts = fitting
            for p in opts:
                if p not in found:
                    found.append(p)
        return sorted(found, key=lambda p: -KIND_RANK.get(p.kind, 0))

    def best_match(self, text: str) -> Place | None:
        hits = self.find_all(text)
        return hits[0] if hits else None

    def grounded_places(self, text: str) -> set[str]:
        """Ids of places the text really names (namesakes and referral hospitals excluded), plus their thanas."""
        out = set()
        for p in self.find_all(_strip_referrals(normalize(text or ""))):
            if p.id not in REFERRAL_PLACES:
                out |= {p.id, self.thana_of(p).id}
        return out

    def names_other_district(self, text: str, district: str = "dhaka") -> bool:
        """The text puts things in a district other than `district` and does not name `district` (as a word or by
        one of its places). "চট্টগ্রামে ছিনতাই, বাড়ি মিরপুরে": a crime *in* another district (locative form) is not
        rescued by a place of `district` in the same sentence (often the victim's home); a genitive ("মাদারীপুরের
        যুবক") only says where someone is from. Referral hospitals ("ঢাকা মেডিকেলে নেওয়া হয়") never count."""
        n = _strip_referrals(normalize(text or ""))
        words = n.split(" ")
        others = {d for w in words if (d := district_word(w)) and d != district}
        if not others:
            return False
        if district in self.district_mentions(n):
            return False
        if any((d := _locative_district(w)) and d != district for w in words):
            return True
        return not any(self.get(pid) and self.get(pid).district == district for pid in self.grounded_places(n))

    def lead_in_other_district(self, body: str, district: str = "dhaka") -> bool:
        """News leads say where it happened: "চট্টগ্রাম নগরের ..." vs "রাজধানীর মিরপুরে ..."."""
        return self.names_other_district((body or "").split("।", 1)[0][:300], district)

    @staticmethod
    def quote_sentence(body: str, evidence: str) -> str:
        """The article sentence that contains the start of the evidence quote ("" if not found)."""
        head = normalize(evidence or "")[:40]
        if not head:
            return ""
        return next((x for x in (body or "").split("।") if head in normalize(x)), "")

    def mentions_supported(self, text: str) -> bool:
        """Any supported district named by a word or by one of its places."""
        return bool(self.district_mentions(text)) or bool(self.find_all(text))

    mentions_dhaka = mentions_supported          # old name, still used by a few callers

    def district_name(self, key: str | None, lang: str = "bn") -> str | None:
        d = next((x for x in self.districts if x["id"] == key), None)
        return d and d["name_bn" if lang == "bn" else "name_en"]

    def bounds(self, district: str | None = None) -> dict | None:
        """Bounding box of the places of one district (or all), for map views and geocoding."""
        pts = [(p.lat, p.lng) for p in self.places if p.lat is not None and (district is None or p.district == district)]
        if not pts:
            return None
        lats, lngs = [a for a, _ in pts], [b for _, b in pts]
        return {"s": min(lats), "n": max(lats), "w": min(lngs), "e": max(lngs)}

    def prompt_table(self) -> str:
        """Compact catalogue for the model prompt: id | Bangla | English | kind | parent | district."""
        lines = ["id | name_bn | name_en | kind | parent_thana | district"]
        for p in self.places:
            lines.append(f"{p.id} | {p.name_bn} | {p.name_en} | {p.kind} | {p.parent or '-'} | {p.district}")
        return "\n".join(lines)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


@lru_cache(maxsize=1)
def load() -> Gazetteer:
    raw = json.loads((ROOT / "data" / "places.json").read_text(encoding="utf-8"))
    return Gazetteer([Place(r["id"], r["name_en"], r["name_bn"], tuple(r.get("aliases") or ()), r["kind"],
                            r.get("parent"), r.get("lat"), r.get("lng"), r.get("district", "dhaka"))
                      for r in raw["places"]], raw.get("districts"))
