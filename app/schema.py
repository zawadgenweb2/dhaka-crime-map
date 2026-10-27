"""Shared output schema for every classifier (in-house Gemma model; keyword rules offline)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Eight colour-coded categories plus "other". Order is fixed: it maps to the UI palette.
CATEGORIES: dict[str, dict[str, str]] = {
    "murder": {"bn": "হত্যা", "en": "Murder"},
    "assault": {"bn": "হামলা ও সংঘর্ষ", "en": "Assault & clashes"},
    "robbery": {"bn": "ছিনতাই ও ডাকাতি", "en": "Mugging & robbery"},
    "theft": {"bn": "চুরি", "en": "Theft & burglary"},
    "sexual_violence": {"bn": "যৌন সহিংসতা", "en": "Sexual violence"},
    "kidnapping": {"bn": "অপহরণ", "en": "Kidnapping"},
    "drugs_arms": {"bn": "মাদক ও অস্ত্র", "en": "Drugs & weapons"},
    "fraud_extortion": {"bn": "প্রতারণা ও চাঁদাবাজি", "en": "Fraud & extortion"},
    "other": {"bn": "অন্যান্য", "en": "Other"},
}

Category = Literal["murder", "assault", "robbery", "theft", "sexual_violence", "kidnapping",
                   "drugs_arms", "fraud_extortion", "other"]
Precision = Literal["exact", "neighbourhood", "thana", "city"]
District = Literal["dhaka", "chattogram", "sylhet", "khulna", "barishal", "rangpur"]
DISTRICTS: dict[str, dict[str, str]] = {
    "dhaka": {"bn": "ঢাকা", "en": "Dhaka"}, "chattogram": {"bn": "চট্টগ্রাম", "en": "Chattogram"},
    "sylhet": {"bn": "সিলেট", "en": "Sylhet"}, "khulna": {"bn": "খুলনা", "en": "Khulna"},
    "barishal": {"bn": "বরিশাল", "en": "Barishal"}, "rangpur": {"bn": "রংপুর", "en": "Rangpur"},
}
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
    district: District | None = Field(None, description="Supported district where the crime happened, or null")
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
    in_scope: bool = Field(description="True only if at least one incident happened inside a supported district")
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
