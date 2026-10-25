from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import create_app
from app.classifiers.base import ClassifierError, system_prompt
from app.classifiers.claude import ClaudeClassifier
from app.classifiers.rules import RulesClassifier
from app.gazetteer import load
from app.pipeline import Pipeline, locate, store_analysis
from app.scheduler import next_run
from app.schema import ArticleAnalysis, Incident
from app.scraper import DHAKA_TZ, Article, Candidate, is_candidate, parse_article, parse_news_sitemap
from app.text import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "prothom_alo_crime.html"
URL = "https://www.prothomalo.com/bangladesh/crime/n8b6mizawc"


@pytest.fixture(autouse=True)
def clean_db():
    with db.tx() as c:
        for table in ("incidents", "articles", "runs"):
            c.execute(f"DELETE FROM {table}")
    yield


# ---- text + gazetteer ------------------------------------------------------------------------
def test_normalize_digits_and_number_words():
    assert normalize("মিরপুর-১০ নম্বর") == "মিরপুর 10"


@pytest.mark.parametrize("text,expected", [
    ("রাজধানীর মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে", "mirpur11"),
    ("রাজধানীর বাড্ডায় ছিনতাই", "badda"),
    ("যাত্রাবাড়ীর কাজলায় খুন", "kajla"),
    ("গুলশান ২ নম্বরে", "gulshan2"),
    ("কেরানীগঞ্জের জিঞ্জিরায়", "jinjira"),
])
def test_gazetteer_most_specific(text, expected):
    assert load().best_match(text).id == expected


def test_gazetteer_word_boundaries():
    g = load()
    assert g.find_all("উত্তরাঞ্চলে বন্যা") == []          # not Uttara
    assert g.find_all("চাঁপাইনবাবগঞ্জে হত্যা") == []      # not Dhaka's Nawabganj


def test_gazetteer_integrity():
    g = load()
    assert len([p for p in g.places if p.kind == "thana"]) == 50
    for p in g.places:
        assert 23.55 < p.lat < 24.0 and 90.1 < p.lng < 90.6
        assert p.parent is None or p.parent in g.by_id


def test_prompt_contains_catalogue():
    prompt = system_prompt()
    assert "mirpur11 | মিরপুর ১১" in prompt and "untrusted" in prompt


# ---- scraper ---------------------------------------------------------------------------------
def test_parse_article_fixture():
    a = parse_article(FIXTURE.read_text(encoding="utf-8"), URL)
    assert a.section == "bangladesh/crime"
    assert "পিস্তল" in a.title
    assert "মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের" in a.body
    assert "<p>" not in a.body and "&lt;" not in a.body
    assert a.published_at and a.published_at.utcoffset().total_seconds() == 6 * 3600


NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://www.prothomalo.com/bangladesh/crime/abc</loc><news:news><news:publication_date>2026-10-25T10:52:34.497Z</news:publication_date>
<news:title>শিরোনাম</news:title><news:keywords>হত্যা, পুলিশ</news:keywords></news:news></url>
<url><loc>https://www.prothomalo.com/sports/cricket/xyz</loc><news:news><news:title>খেলা</news:title></news:news></url>
</urlset>"""


def test_news_sitemap_and_prefilter():
    items = parse_news_sitemap(NEWS_XML)
    assert [c.section for c in items] == ["bangladesh/crime", "sports/cricket"]
    assert items[0].keywords == "হত্যা, পুলিশ" and items[0].published_at.tzinfo
    g = load()
    assert is_candidate(items[0], g) and not is_candidate(items[1], g)
    district = Candidate("u", "bangladesh/district", "টঙ্গীতে শিশুকে নিপীড়ন", "গাজীপুর, টঙ্গী, ঢাকা বিভাগ")
    assert not is_candidate(district, g)  # Gazipur is outside Dhaka district
    savar = Candidate("u", "bangladesh/district", "সাভারে ছিনতাই", "সাভার, ঢাকা বিভাগ")
    assert is_candidate(savar, g)


# ---- location + storage ----------------------------------------------------------------------
def _inc(**kw):
    base = dict(category="drugs_arms", headline_bn="পিস্তলসহ গ্রেপ্তার", headline_en="Arrested with pistol",
                location_text="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশন", place_id="mirpur11", geocode_query=None,
                precision="exact", incident_date="2026-10-24", time_of_day="afternoon", victims=0,
                evidence="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")
    base.update(kw)
    return Incident(**base)


def test_locate_uses_gazetteer_and_fixes_unknown_ids():
    g = load()
    loc = locate(_inc(), g, use_geocoder=False)
    assert loc["place_id"] == "mirpur11" and loc["thana_id"] == "pallabi"
    loc = locate(_inc(place_id="made-up", location_text="বাড্ডায়"), g, use_geocoder=False)
    assert loc["place_id"] == "badda"
    loc = locate(_inc(place_id=None, location_text="রাজধানীতে", precision="city"), g, use_geocoder=False)
    assert loc["lat"] is None and loc["precision"] == "city"


def _article(url, body="রাজধানীর মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে পিস্তলসহ গ্রেপ্তার।"):
    return Article(url=url, section="bangladesh/crime", title="পিস্তলসহ গ্রেপ্তার", body=body,
                   published_at=datetime(2026, 10, 24, 23, 0, tzinfo=DHAKA_TZ))


def _insert_article(conn, a):
    return conn.execute("INSERT INTO articles (url, section, title, body, published_at, status) VALUES (?,?,?,?,?,?)",
                        (a.url, a.section, a.title, a.body, a.published_at.isoformat(), "pending")).lastrowid


def test_store_analysis_validates_and_dedups():
    g = load()
    with db.tx() as c:
        a1, a2 = _article("https://x/1"), _article("https://x/2")
        id1, id2 = _insert_article(c, a1), _insert_article(c, a2)
        ok = ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note="")
        assert store_analysis(c, id1, a1, ok, "test", g, False) == 1
        # same event in a second article -> duplicate; a future date -> dropped to publication day
        later = ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                incidents=[_inc(incident_date="2026-12-31", evidence="not in the text")])
        store_analysis(c, id2, a2, later, "test", g, False)
        rows = c.execute("SELECT * FROM incidents ORDER BY id").fetchall()
        assert rows[0]["evidence_ok"] == 1 and rows[1]["evidence_ok"] == 0
        assert rows[1]["incident_date"] is None and rows[1]["event_date"] == "2026-10-24"
        assert rows[1]["duplicate_of"] == rows[0]["id"]
        # not in Dhaka -> nothing stored
        outside = ArticleAnalysis(is_crime_report=True, in_dhaka=False, incidents=[_inc()], note="")
        assert store_analysis(c, id2, a2, outside, "test", g, False) == 0


# ---- claude adapter (no network) ---------------------------------------------------------------
class FakeMessages:
    def __init__(self, response):
        self.response, self.calls = response, []

    def parse(self, **kw):
        self.calls.append(kw)
        return self.response


def _fake_client(response):
    return SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(response)))


def test_claude_request_shape_and_result():
    parsed = ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note="ok")
    usage = SimpleNamespace(input_tokens=10, cache_read_input_tokens=0, output_tokens=5)
    client = _fake_client(SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, usage=usage))
    out = ClaudeClassifier(client=client).classify(_article("https://x/3"))
    assert out.incidents[0].place_id == "mirpur11"
    kw = client.beta.messages.calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["output_format"] is ArticleAnalysis and kw["fallbacks"] == "default"
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_claude_refusal_raises():
    client = _fake_client(SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None))
    with pytest.raises(ClassifierError):
        ClaudeClassifier(client=client).classify(_article("https://x/4"))


# ---- end to end: pipeline + API ---------------------------------------------------------------
class FakeProthomAlo:
    def news_sitemap(self):
        return [Candidate(URL, "bangladesh/crime", "পিস্তলসহ গ্রেপ্তার", "মিরপুর, অস্ত্র",
                          datetime(2026, 10, 24, 17, 25, tzinfo=timezone.utc)),
                Candidate("https://www.prothomalo.com/sports/cricket/zz", "sports/cricket", "খেলা", "")]

    def daily_sitemap(self, day):
        return []

    def article(self, url):
        return parse_article(FIXTURE.read_text(encoding="utf-8"), url)


def test_pipeline_and_api_end_to_end():
    result = Pipeline(client=FakeProthomAlo(), classifier=RulesClassifier(), use_geocoder=False).run(trigger="test")
    assert result["status"] == "ok" and result["fetched"] == 1 and result["incidents"] == 1
    # second run finds nothing new
    assert Pipeline(client=FakeProthomAlo(), classifier=RulesClassifier(), use_geocoder=False).run()["fetched"] == 0

    api = TestClient(create_app(enable_scheduler=False))
    assert api.get("/").status_code == 200
    meta = api.get("/api/meta").json()
    assert len(meta["categories"]) == 9 and any(t["id"] == "pallabi" for t in meta["thanas"])
    inc = api.get("/api/incidents", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    hit = next(i for i in inc if i["url"] == URL)
    assert hit["place_id"] == "mirpur11" and hit["lat"] and hit["category"] == "drugs_arms"
    stats = api.get("/api/stats", params={"start": "2026-10-01", "end": "2026-10-31", "categories": "drugs_arms"}).json()
    assert stats["total"] >= 1 and stats["by_thana"][0]["id"] in {"pallabi", "mirpur"}
    assert api.get("/api/stats", params={"start": "bad"}).status_code == 400
    assert api.post("/api/scrape").status_code == 403  # test client is not localhost and no token is set


def test_scheduler_next_run():
    after = datetime(2026, 10, 25, 9, 0, tzinfo=DHAKA_TZ)
    assert next_run(after) == datetime(2026, 10, 25, 20, 0, tzinfo=DHAKA_TZ)
    assert next_run(datetime(2026, 10, 25, 21, 0, tzinfo=DHAKA_TZ)) == datetime(2026, 10, 26, 8, 0, tzinfo=DHAKA_TZ)
