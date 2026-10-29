"""Shared output schema for every classifier (in-house Gemma model; keyword rules offline)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# THE category list (single source of truth): the model's enum, the prompt, storage checks, the public API, filters,
# legend, map colours and the painter all derive from it. Order = display order.
#   visibility: "mapped" (points, links, heat) or "totals_only" (counted in totals, never located or linked publicly)
#   color: the category's map colour (sRGB hex). Nine high-contrast colours chosen on 29 Oct (owner: "8 crimes super
#          contrasty"), distinct in hue AND lightness. Checked by the Codex council (CIEDE2000 under normal vision and
#          simulated protan/deutan/tritan, Machado 2009): every pair >= 18 for normal vision, >= 6.5 for the
#          colour-blind simulations; every colour >= 3:1 against the #fcfcfb page. Keep a published colour unless the
#          owner changes it; re-run that check when adding one.
#   family: grouping for when there are too many colours (violent / property / drugs / other)
# To add a category: add an entry with visibility, family and (mapped) a colour far from the others.
CATEGORIES: dict[str, dict] = {
    "murder": {"bn": "হত্যা", "en": "Murder", "visibility": "mapped", "color": "#d7191c", "family": "violent"},
    "assault": {"bn": "হামলা ও সংঘর্ষ", "en": "Assault & clashes", "visibility": "mapped", "color": "#e66101",
                "family": "violent"},
    "robbery": {"bn": "ছিনতাই ও ডাকাতি", "en": "Mugging & robbery", "visibility": "mapped", "color": "#7b3fbf",
                "family": "property"},
    "theft": {"bn": "চুরি", "en": "Theft & burglary", "visibility": "mapped", "color": "#7f6000", "family": "property"},
    # mapped since 28 Oct (owner: the newspapers already protect victims; we show what they published).
    "sexual_violence": {"bn": "যৌন সহিংসতা", "en": "Sexual violence", "visibility": "mapped", "color": "#e7298a",
                        "family": "violent"},
    "kidnapping": {"bn": "অপহরণ", "en": "Kidnapping", "visibility": "mapped", "color": "#4a90e2", "family": "violent"},
    "drugs_arms": {"bn": "মাদক ও অস্ত্র", "en": "Drugs & weapons", "visibility": "mapped", "color": "#1a9850",
                   "family": "drugs"},
    "fraud_extortion": {"bn": "প্রতারণা ও চাঁদাবাজি", "en": "Fraud & extortion", "visibility": "mapped",
                        "color": "#00a3a3", "family": "property"},
    "other": {"bn": "অন্যান্য", "en": "Other", "visibility": "mapped", "color": "#6e6e6e", "family": "other"},
}
MAX_MAPPED_COLOURS = 9           # council advised 8 for readability; owner added sexual violence as a ninth (28 Oct)
MAPPED = [k for k, v in CATEGORIES.items() if v["visibility"] == "mapped"]
TOTALS_ONLY = {k for k, v in CATEGORIES.items() if v["visibility"] == "totals_only"}


def _check_categories() -> None:
    import re
    for k, v in CATEGORIES.items():                       # fail closed: every entry states its public visibility
        assert v.get("visibility") in ("mapped", "totals_only"), f"category {k}: visibility missing"
        assert v.get("bn") and v.get("en") and v.get("family"), f"category {k}: labels/family missing"
        assert (v["visibility"] == "mapped") == bool(v.get("color")), f"category {k}: mapped needs a colour"
        assert not v.get("color") or re.fullmatch(r"#[0-9a-f]{6}", v["color"]), f"category {k}: colour must be #rrggbb"
    colours = [CATEGORIES[k]["color"] for k in MAPPED]
    assert len(set(colours)) == len(colours), "two mapped categories share a colour"


_check_categories()

Category = Literal[tuple(CATEGORIES)]          # the model's enum, generated from the list above
Precision = Literal["exact", "neighbourhood", "thana", "city"]
# Divisions and districts of Bangladesh (8 and 64, Bangladesh National Portal), from data/places.json
_PLACES = json.loads((Path(__file__).resolve().parent.parent / "data" / "places.json").read_text(encoding="utf-8"))
DIVISIONS: dict[str, dict[str, str]] = {d["id"]: {"bn": d["name_bn"], "en": d["name_en"]} for d in _PLACES["divisions"]}
DISTRICTS: dict[str, dict[str, str]] = {d["id"]: {"bn": d["name_bn"], "en": d["name_en"], "division": d["division"]}
                                        for d in _PLACES["districts"]}
District = Literal[tuple(DISTRICTS)]           # the model's enum: all 64 districts
TimeOfDay = Literal["morning", "afternoon", "evening", "night", "unknown"]

TIME_OF_DAY = {
    "morning": {"bn": "সকাল (৫–১২)", "en": "Morning (5–12)"},
    "afternoon": {"bn": "দুপুর–বিকেল (১২–১৭)", "en": "Afternoon (12–17)"},
    "evening": {"bn": "সন্ধ্যা (১৭–২১)", "en": "Evening (17–21)"},
    "night": {"bn": "রাত (২১–৫)", "en": "Night (21–5)"},
    "unknown": {"bn": "অজানা", "en": "Unknown"},
}


class Incident(BaseModel):
    category: Category
    district: District | None = Field(None, description="District of Bangladesh where the crime happened, or null")
    headline_bn: str = Field(description="One-line Bangla summary of this incident (max ~90 chars)")
    headline_en: str = Field(description="Same summary in English")
    location_text: str = Field(description="Most specific location phrase exactly as written in the article")
    place_id: str | None = Field(description="Most specific matching id from the place catalogue, or null")
    geocode_query: str | None = Field(
        description="English search query for the exact spot if the article names a street, building, "
                    "market, station or junction, e.g. 'Mirpur 11 metro station, Dhaka'; else null")
    precision: Precision
    incident_date: str | None = Field(description="YYYY-MM-DD in Asia/Dhaka, or null if unknown")
    time_of_day: TimeOfDay
    victims: int = Field(description="Number of victims killed or injured; 0 if none or unknown")
    evidence: str = Field(description="Short verbatim Bangla quote from the article that supports this incident")


class ArticleAnalysis(BaseModel):
    is_crime_report: bool
    in_scope: bool = Field(description="True only if at least one incident happened in Bangladesh")
    incidents: list[Incident]
    note: str = Field(description="One short sentence on why incidents were or were not extracted")

    @model_validator(mode="before")
    @classmethod
    def _legacy(cls, data):
        """Answers saved before the six-district change said `in_dhaka` and had no per-incident district."""
        if isinstance(data, dict) and "in_dhaka" in data and "in_scope" not in data:
            data = {**data, "in_scope": data["in_dhaka"]}
            data.pop("in_dhaka")
            data["incidents"] = [{"district": "dhaka", **i} if isinstance(i, dict) else i
                                 for i in data.get("incidents") or []]
        return data
