"""Dhaka place catalogue: thanas, upazilas, neighbourhoods and landmarks with coordinates."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache

from .config import ROOT
from .text import normalize

KIND_RANK = {"landmark": 3, "area": 2, "thana": 1, "upazila": 1}
DHAKA_TERMS = ["ঢাকা", "রাজধানী", "ডিএমপি", "ঢাকা মহানগর"]
# Bangla case endings allowed right after a place name ("মিরপুরে", "গুলশানের", "বাড্ডায়")
SUFFIXES = {normalize(s) for s in ["", "র", "এর", "ের", "য়", "য়ে", "য়ের", "তে", "তেই", "ে", "েই", "এ", "কে",
                                  "বাসী", "স্থ", "ও", "ই", "গামী", "মুখী"]}
# Other districts. "কুষ্টিয়ার মিরপুরে" or "দিনাজপুরের নবাবগঞ্জে" names a namesake outside Dhaka.
OTHER_DISTRICTS = {normalize(d) for d in """
বাগেরহাট বান্দরবান বরগুনা বরিশাল ভোলা বগুড়া ব্রাহ্মণবাড়িয়া চাঁদপুর চাঁপাইনবাবগঞ্জ চট্টগ্রাম চুয়াডাঙ্গা কুমিল্লা
কক্সবাজার দিনাজপুর ফরিদপুর ফেনী গাইবান্ধা গাজীপুর গোপালগঞ্জ হবিগঞ্জ জামালপুর যশোর ঝালকাঠি ঝিনাইদহ জয়পুরহাট
খাগড়াছড়ি খুলনা কিশোরগঞ্জ কুড়িগ্রাম কুষ্টিয়া লক্ষ্মীপুর লালমনিরহাট মাদারীপুর মাগুরা মানিকগঞ্জ মেহেরপুর মৌলভীবাজার
মুন্সিগঞ্জ মুন্সীগঞ্জ ময়মনসিংহ নওগাঁ নড়াইল নারায়ণগঞ্জ নরসিংদী নাটোর নেত্রকোনা নীলফামারী নোয়াখালী পাবনা পঞ্চগড়
পটুয়াখালী পিরোজপুর রাজবাড়ী রাজশাহী রাঙামাটি রংপুর সাতক্ষীরা শরীয়তপুর শেরপুর সিরাজগঞ্জ সুনামগঞ্জ সিলেট টাঙ্গাইল
ঠাকুরগাঁও""".split()}
_GENITIVE = [normalize(x) for x in ("ের", "এর", "য়ের", "র")]


def _other_district(word: str) -> bool:
    for suffix in _GENITIVE:
        if word.endswith(suffix) and word[: -len(suffix)] in OTHER_DISTRICTS:
            return True
    return word in OTHER_DISTRICTS


@dataclass(frozen=True)
class Place:
    id: str
    name_en: str
    name_bn: str
    aliases: tuple[str, ...]
    kind: str
    parent: str | None
    lat: float
    lng: float

    def to_dict(self) -> dict:
        return {"id": self.id, "name_en": self.name_en, "name_bn": self.name_bn, "kind": self.kind,
                "parent": self.parent, "lat": self.lat, "lng": self.lng}


class Gazetteer:
    def __init__(self, places: list[Place]):
        self.places = places
        self.by_id = {p.id: p for p in places}
        self._terms: list[tuple[str, Place]] = []
        for p in places:
            for name in (p.name_bn, *p.aliases):
                self._terms.append((normalize(name), p))
        # Longest names first so "মিরপুর 10" wins over "মিরপুর"
        self._terms.sort(key=lambda t: len(t[0]), reverse=True)

    def get(self, place_id: str | None) -> Place | None:
        return self.by_id.get(place_id or "")

    def thana_of(self, place: Place) -> Place:
        return self.by_id[place.parent] if place.parent in self.by_id else place

    def find_all(self, text: str) -> list[Place]:
        """Places mentioned in the text, most specific first, without overlapping matches."""
        n = f" {normalize(text)} "
        found: list[Place] = []
        taken: list[tuple[int, int]] = []
        for term, place in self._terms:
            start = n.find(term)
            while start != -1:
                end = start + len(term)
                word_end = n.find(" ", end)
                rest = n[end:word_end]
                ok_boundary = n[start - 1] == " " and rest in SUFFIXES
                prev_word = n[:start].rstrip().rsplit(" ", 1)[-1]
                if ok_boundary and _other_district(prev_word):
                    ok_boundary = False  # e.g. Kushtia's Mirpur, Chattogram's Kotwali
                if ok_boundary and not any(s < end and start < e for s, e in taken):
                    taken.append((start, end))
                    if place not in found:
                        found.append(place)
                start = n.find(term, end)
        return sorted(found, key=lambda p: -KIND_RANK.get(p.kind, 0))

    def best_match(self, text: str) -> Place | None:
        hits = self.find_all(text)
        return hits[0] if hits else None

    def mentions_dhaka(self, text: str) -> bool:
        n = normalize(text)
        return any(normalize(t) in n for t in DHAKA_TERMS) or bool(self.find_all(text))

    def prompt_table(self) -> str:
        """Compact catalogue for the model prompt: id | Bangla | English | kind | parent."""
        lines = ["id | name_bn | name_en | kind | parent_thana"]
        for p in self.places:
            lines.append(f"{p.id} | {p.name_bn} | {p.name_en} | {p.kind} | {p.parent or '-'}")
        return "\n".join(lines)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))


@lru_cache(maxsize=1)
def load() -> Gazetteer:
    raw = json.loads((ROOT / "data" / "dhaka_places.json").read_text(encoding="utf-8"))
    return Gazetteer([Place(r["id"], r["name_en"], r["name_bn"], tuple(r["aliases"]), r["kind"],
                            r["parent"], r["lat"], r["lng"]) for r in raw])
