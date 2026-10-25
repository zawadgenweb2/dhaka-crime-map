"""Keyword baseline. No network, no model: used for tests, demos and as a sanity check."""
from __future__ import annotations

import re

from ..gazetteer import load as load_gazetteer
from ..schema import ArticleAnalysis, Incident
from ..scraper import DHAKA_TZ, Article
from ..text import crime_signal, normalize
from .base import Classifier

# First match wins, so the most serious categories come first
RULES = [
    ("murder", ["হত্যা", "খুন", "লাশ উদ্ধার", "কুপিয়ে হত্যা", "গুলিতে নিহত"]),
    ("sexual_violence", ["ধর্ষণ", "যৌন নিপীড়ন", "যৌন হয়রানি", "শ্লীলতাহানি"]),
    ("kidnapping", ["অপহরণ", "মুক্তিপণ"]),
    ("robbery", ["ছিনতাই", "ডাকাতি", "ডাকাত", "লুট"]),
    ("theft", ["চুরি", "চোর", "পকেটমার"]),
    ("drugs_arms", ["ইয়াবা", "মাদক", "হেরোইন", "গাঁজা", "ফেনসিডিল", "অস্ত্র", "গুলিসহ", "পিস্তল"]),
    ("fraud_extortion", ["চাঁদা", "প্রতারণা", "জালিয়াতি", "প্রতারক"]),
    ("assault", ["মারধর", "হামলা", "সংঘর্ষ", "ছুরিকাঘাত", "গণপিটুনি", "আহত"]),
]
TIME_WORDS = [("night", ["রাতে", "মধ্যরাতে", "রাত"]), ("evening", ["সন্ধ্যা"]),
              ("afternoon", ["দুপুর", "বিকেল"]), ("morning", ["ভোর", "সকাল"])]


class RulesClassifier(Classifier):
    name = "rules"

    def classify(self, article: Article) -> ArticleAnalysis:
        gaz = load_gazetteer()
        text = f"{article.title}\n{article.body}"
        n = normalize(text)
        if crime_signal(text) == 0:
            return ArticleAnalysis(is_crime_report=False, in_dhaka=False, incidents=[], note="no crime terms")
        category = next((c for c, words in RULES if any(normalize(w) in n for w in words)), "other")
        place = gaz.best_match(article.title) or gaz.best_match(article.body[:1500])
        if place is None:
            return ArticleAnalysis(is_crime_report=True, in_dhaka=False, incidents=[], note="no Dhaka place found")
        sentence = next((s for s in re.split(r"(?<=[।\n])", article.body) if place.name_bn in s or
                         any(a in s for a in place.aliases)), article.body[:150])
        tod = next((t for t, words in TIME_WORDS if any(w in sentence for w in words)), "unknown")
        day = article.published_at.astimezone(DHAKA_TZ).date().isoformat() if article.published_at else None
        precision = {"landmark": "exact", "area": "neighbourhood"}.get(place.kind, "thana")
        return ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="keyword baseline", incidents=[Incident(
            category=category, headline_bn=article.title[:120], headline_en="", location_text=place.name_bn,
            place_id=place.id, geocode_query=None, precision=precision, incident_date=day, time_of_day=tod,
            victims=0, evidence=sentence.strip()[:200])])
