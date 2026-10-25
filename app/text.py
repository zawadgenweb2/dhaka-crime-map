"""Bangla text helpers shared by the scraper, gazetteer and validators."""
import re

_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# Common spelling variants that should match each other
_VARIANTS = [("\u09df", "\u09af\u09bc"), ("\u09dc", "\u09a1\u09bc"), ("\u09dd", "\u09a2\u09bc"),
             ("\u200c", ""), ("\u200d", "")]


def normalize(text: str) -> str:
    """Lower-noise form for matching: ASCII digits, unified nukta forms, no 'নম্বর/নং', single spaces."""
    t = text or ""
    for a, b in _VARIANTS:
        t = t.replace(a, b)
    t = t.translate(_DIGITS)
    t = re.sub(r"(\d)\s*(?:নম্বর|নম্বরের|নং|নাম্বার)", r"\1", t)
    t = re.sub(r"[-–—_/]", " ", t)
    t = re.sub(r"[\"'‘’“”()\[\],;:!?।]", " ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


CRIME_TERMS = [
    "হত্যা", "খুন", "লাশ", "মরদেহ", "ছুরিকাঘাত", "কুপিয়ে", "গুলি", "ছিনতাই", "ডাকাতি", "চুরি",
    "ধর্ষণ", "যৌন", "নিপীড়ন", "অপহরণ", "মাদক", "ইয়াবা", "হেরোইন", "গাঁজা", "অস্ত্র", "চাঁদা",
    "প্রতারণা", "জালিয়াতি", "মারধর", "হামলা", "সংঘর্ষ", "গ্রেপ্তার", "আটক", "র‍্যাব", "পুলিশ",
    "মামলা", "নির্যাতন", "গণপিটুনি", "লুট", "পকেটমার", "বিস্ফোরণ", "ককটেল", "অপরাধ",
]
_CRIME_NORM = [normalize(t) for t in CRIME_TERMS]


def crime_signal(text: str) -> int:
    """Number of distinct crime terms present (cheap pre-filter before calling a model)."""
    n = normalize(text)
    return sum(1 for t in _CRIME_NORM if t in n)
