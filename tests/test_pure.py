"""Tests that need no database or network."""
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.classifiers.base import system_prompt
from app.classifiers.rules import RulesClassifier
from app.gazetteer import load
from app.scheduler import next_run, previous_slot
from app.schema import ArticleAnalysis, Incident
from app.scraper import (DHAKA_TZ, Article, Candidate, FetchBlocked, ProthomAloClient, is_candidate, parse_article,
                         parse_news_sitemap)
from app.store import _same_event, build_rows, clean_incident_date, evidence_ok, locate
from app.text import normalize

FIXTURE = Path(__file__).parent / "fixtures" / "prothom_alo_crime.html"
URL = "https://www.prothomalo.com/bangladesh/crime/n8b6mizawc"


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
    assert g.find_all("উত্তরাঞ্চলে বন্যা") == []
    assert g.find_all("চাঁপাইনবাবগঞ্জে হত্যা") == []


@pytest.mark.parametrize("text", ["কুষ্টিয়ার মিরপুরে হত্যা", "চট্টগ্রামের কোতোয়ালিতে হত্যা",
                                  "দিনাজপুরের নবাবগঞ্জে হত্যা"])
def test_gazetteer_rejects_other_district_namesakes(text):
    assert load().find_all(text) == []


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
    assert a.section == "bangladesh/crime" and "পিস্তল" in a.title
    assert "মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের" in a.body
    assert "<p>" not in a.body and "&lt;" not in a.body
    assert a.published_at.utcoffset().total_seconds() == 6 * 3600


NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
<url><loc>https://www.prothomalo.com/bangladesh/crime/abc</loc><news:news><news:publication_date>2026-10-25T10:52:34.497Z</news:publication_date>
<news:title>শিরোনাম</news:title><news:keywords>হত্যা, পুলিশ</news:keywords></news:news></url>
<url><loc>https://www.prothomalo.com/sports/cricket/xyz</loc><news:news><news:title>খেলা</news:title></news:news></url>
</urlset>"""


def test_news_sitemap_and_prefilter():
    items = parse_news_sitemap(NEWS_XML)
    assert [c.section for c in items] == ["bangladesh/crime", "sports/cricket"]
    g = load()
    assert is_candidate(items[0], g) and not is_candidate(items[1], g)       # sports, no crime word in the title
    P = "https://www.prothomalo.com/"
    # a crime word in the title is enough, in any section; Dhaka is checked in the full text afterwards
    assert is_candidate(Candidate(P + "bangladesh/district/a", "bangladesh/district", "স্ত্রীকে গলা টিপে হত্যা", ""), g)
    assert is_candidate(Candidate(P + "sports/cricket/b", "sports/cricket", "ক্রিকেটার গ্রেপ্তার", ""), g)
    assert not is_candidate(Candidate(P + "video/c", "video", "হত্যা", ""), g)
    for bare in ("topic", "author", "amp"):                                  # non-article pages, even with a crime word
        assert not is_candidate(Candidate(P + bare + "/হত্যা", bare, "হত্যা", ""), g)
    assert not is_candidate(Candidate("https://www.kishoralo.com/x/y", "https:", "হত্যা", ""), g)   # sister site
    assert is_candidate(Candidate(P + "bangladesh/district/d", "bangladesh/district"), g)    # no title yet: read it
    assert not is_candidate(Candidate(P + "sports/cricket/e", "sports/cricket"), g)


def test_full_text_decides_dhaka():
    from app.scraper import belongs_to_dhaka
    g = load()
    assert belongs_to_dhaka("bangladesh/district", "কেরানীগঞ্জে স্ত্রীকে হত্যার মামলায় রায়", g)
    assert not belongs_to_dhaka("bangladesh/district", "চট্টগ্রাম নগরের বিবিরহাটে ছিনতাই, ঢাকা মেডিকেলে নেওয়া হয়", g)
    assert not belongs_to_dhaka("bangladesh/district", "টঙ্গীতে শিশুকে নিপীড়ন, গাজীপুর", g)
    assert belongs_to_dhaka("bangladesh", "রাজধানীতে ছিনতাই", g)


def _client(handler):
    return ProthomAloClient(client=httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
                            delay=0)


def test_robots_server_error_blocks_crawling():
    c = _client(lambda req: httpx.Response(503))
    with pytest.raises(FetchBlocked):
        c._get("https://www.prothomalo.com/bangladesh/crime/x")


def test_robots_404_allows_and_redirect_off_host_is_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8100/api/meta"})
    with pytest.raises(FetchBlocked):
        _client(handler)._get("https://www.prothomalo.com/bangladesh/crime/x")


def test_redirect_into_disallowed_path_is_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        if req.url.path == "/public":
            return httpx.Response(301, headers={"location": "/private/article"})
        return httpx.Response(200, text="secret")
    with pytest.raises(FetchBlocked):
        _client(handler)._get("https://www.prothomalo.com/public")


def test_oversized_response_is_cut_off_while_streaming():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        return httpx.Response(200, content=b"x" * (9 * 1024 * 1024))
    with pytest.raises(FetchBlocked):
        _client(handler)._get("https://www.prothomalo.com/big")


def test_gzip_responses_are_decoded_once():
    import gzip

    def handler(req):
        body = b"User-agent: *\nAllow: /\n" if req.url.path == "/robots.txt" else "ঢাকা".encode()
        return httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(body))
    assert _client(handler)._get("https://www.prothomalo.com/x") == "ঢাকা"


# ---- dates, evidence, duplicates ---------------------------------------------------------------
def test_dates_after_publication_or_absurd_are_dropped():
    pub = date(2026, 10, 24)
    assert clean_incident_date("2026-10-24", pub) == pub
    assert clean_incident_date("2026-10-25", pub) is None
    assert clean_incident_date("0001-01-01", pub) is None
    assert clean_incident_date("not a date", pub) is None


def test_evidence_must_be_in_article():
    assert evidence_ok("মিরপুর ১১ নম্বর মেট্রোরেল", "", "রাজধানীর মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")
    assert not evidence_ok("বানানো উদ্ধৃতি যা নেই", "", "অন্য লেখা")


def _row(**kw):
    base = dict(article_id=1, category="murder", place_id="mirpur11", event_date=date(2026, 10, 24),
                time_of_day="night")
    base.update(kw)
    return base


def test_duplicate_rule_needs_same_specific_place_and_compatible_time():
    a = _row()
    assert _same_event(a, _row(article_id=2))
    assert _same_event(a, _row(article_id=2, time_of_day="unknown", event_date=date(2026, 10, 25)))
    assert not _same_event(a, _row(article_id=2, place_id="mirpur12"))          # same thana, other place
    assert not _same_event(a, _row(article_id=2, time_of_day="morning"))
    assert not _same_event(a, _row(article_id=2, event_date=date(2026, 10, 26)))
    assert not _same_event(a, _row())                                            # same article


def _inc(**kw):
    base = dict(category="drugs_arms", headline_bn="গ্রেপ্তার", headline_en="Arrest",
                location_text="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশন", place_id="mirpur11", geocode_query=None,
                precision="exact", incident_date="2026-10-24", time_of_day="afternoon", victims=0,
                evidence="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")
    base.update(kw)
    return Incident(**base)


ARTICLE = {"id": 1, "title": "পিস্তলসহ গ্রেপ্তার", "body": "রাজধানীর মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে গ্রেপ্তার।",
           "published_at": datetime(2026, 10, 24, 17, 0, tzinfo=timezone.utc)}


def test_build_rows_publication_policy():
    g = load()
    ok = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note=""), g, {})
    assert ok[0]["published"] and ok[0]["thana_id"] == "pallabi"
    fake = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                               incidents=[_inc(evidence="বানানো উদ্ধৃতি যা প্রবন্ধে নেই")]), g, {})
    assert not fake[0]["published"]
    contradictory = ArticleAnalysis(is_crime_report=False, in_dhaka=True, incidents=[_inc()], note="")
    assert build_rows(ARTICLE, contradictory, g, {}) == []


def test_locate_geocode_only_when_close_to_place():
    g = load()
    near = locate(_inc(geocode_query="q"), g, {"q": (23.8191, 90.3653)})
    far = locate(_inc(geocode_query="q"), g, {"q": (22.33, 91.83)})  # Chattogram
    assert near["geocoded"] and near["precision"] == "exact"
    assert not far["geocoded"] and far["lat"] == g.get("mirpur11").lat


def test_rules_classifier_uses_dhaka_date():
    art = Article(url="u", section="bangladesh/crime", title="মিরপুর ১১-তে ছিনতাই",
                  body="রাজধানীর মিরপুর ১১ নম্বরে রাতে ছিনতাই হয়েছে।",
                  published_at=datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc))  # 25 Oct in Dhaka
    out = RulesClassifier().classify(art)
    assert out.incidents[0].incident_date == "2026-10-25"


def test_scheduler_slots():
    assert next_run(datetime(2026, 10, 25, 9, 0, tzinfo=DHAKA_TZ)) == datetime(2026, 10, 25, 20, 0, tzinfo=DHAKA_TZ)
    assert next_run(datetime(2026, 10, 25, 21, 0, tzinfo=DHAKA_TZ)) == datetime(2026, 10, 26, 8, 0, tzinfo=DHAKA_TZ)
    assert previous_slot(datetime(2026, 10, 25, 7, 0, tzinfo=DHAKA_TZ)) == datetime(2026, 10, 24, 20, 0, tzinfo=DHAKA_TZ)


# ---- local model adapter (fake OpenAI-compatible server) -----------------------------------------
def _gemma(responses, seen=None):
    from app.classifiers.gemma import GemmaClassifier
    it = iter(responses)

    def handler(req):
        if seen is not None:
            seen.append(req)
        return next(it)
    return GemmaClassifier(base_url="http://llm/v1", model="dhaka-gemma", api_key="k",
                           transport=httpx.MockTransport(handler))


def _completion(content, finish="stop"):
    return httpx.Response(200, json={"model": "dhaka-gemma", "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                                     "choices": [{"finish_reason": finish, "message": {"content": content}}]})


GOOD = ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note="ok").model_dump_json()
ART = Article(url="u", section="bangladesh/crime", title="t", body="রাজধানীর মিরপুর ১১ নম্বরে গ্রেপ্তার।",
              published_at=datetime(2026, 10, 24, tzinfo=timezone.utc))


def test_gemma_sends_key_and_schema_and_parses():
    seen = []
    analysis, meta = _gemma([_completion(GOOD)], seen).classify_with_meta(ART)
    assert analysis.incidents[0].place_id == "mirpur11" and meta["cost_usd"] == 0
    req = seen[0]
    assert req.headers["authorization"] == "Bearer k"
    body = __import__("json").loads(req.content)
    assert body["response_format"]["type"] == "json_schema" and body["temperature"] == 0


def test_gemma_retries_with_feedback_after_truncation():
    seen = []
    analysis, meta = _gemma([_completion('{"is_crime', "length"), _completion(GOOD)], seen).classify_with_meta(ART)
    assert meta["attempts"] == 2 and meta["input_tokens"] == 200
    retry = __import__("json").loads(seen[1].content)["messages"]
    assert "invalid" in retry[-1]["content"]


def test_gemma_errors():
    from app.classifiers.base import ClassifierError
    with pytest.raises(ClassifierError) as e:
        _gemma([httpx.Response(401)]).classify(ART)
    assert e.value.permanent
    with pytest.raises(ClassifierError) as e:
        _gemma([_completion("not json"), _completion("{}")]).classify(ART)
    assert not e.value.permanent


def test_review_mode_holds_incidents():
    g = load()
    rows = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note=""),
                      g, {}, "review")
    assert rows[0]["passes"] and not rows[0]["published"] and rows[0]["review_status"] == "pending"


def test_compact_prompt_shortlists_places_and_constrains_ids():
    seen = []
    art = Article(url="u", section="bangladesh/crime", title="মিরপুর ১১-তে ছিনতাই", keywords="",
                  body="রাজধানীর মিরপুর ১১ নম্বরে রাতে ছিনতাই হয়েছে।",
                  published_at=datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc))
    _gemma([_completion(GOOD)], seen).classify(art)
    body = __import__("json").loads(seen[0].content)
    user = __import__("json").loads(body["messages"][1]["content"])
    assert user["publication_date_asia_dhaka"] == "2026-10-25" and user["yesterday_গতকাল"] == "2026-10-24"
    assert user["recent_dates"][0] == "2026-10-25 | রবিবার | today/আজ"
    assert user["recent_dates"][1] == "2026-10-24 | শনিবার | yesterday/গতকাল" and len(user["recent_dates"]) == 8
    assert [c.split(" | ")[0] for c in user["place_candidates"]] == ["mirpur11", "pallabi"]
    pid = body["response_format"]["json_schema"]["schema"]["$defs"]["Incident"]["properties"]["place_id"]
    assert pid["anyOf"][0]["enum"] == ["mirpur11", "pallabi"]
    assert "mirpur11 | মিরপুর ১১" not in body["messages"][0]["content"]          # no full catalogue


# ---- robots.txt per RFC 9309 ----------------------------------------------------------------------
def test_robots_longest_match_beats_file_order():
    from app.scraper import RobotsPolicy
    # Prothom Alo's real shape: a broad Allow first, specific Disallows after it.
    p = RobotsPolicy.parse("User-agent: *\nAllow: /\nDisallow: /story/*/element/\nDisallow: /api/auth/\n",
                           "DhakaCrimeMap/0.2")
    assert p.can_fetch("https://www.prothomalo.com/bangladesh/crime/abc")
    assert not p.can_fetch("https://www.prothomalo.com/story/123/element/456")
    assert not p.can_fetch("https://www.prothomalo.com/api/auth/login")
    tie = RobotsPolicy.parse("User-agent: *\nDisallow: /a\nAllow: /a\n", "x")
    assert tie.can_fetch("https://www.prothomalo.com/a")                    # equal length: Allow wins
    own = RobotsPolicy.parse("User-agent: dhakacrimemap\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "DhakaCrimeMap/0.2")
    assert not own.can_fetch("https://www.prothomalo.com/x")                # our own group overrides '*'
    end = RobotsPolicy.parse("User-agent: *\nDisallow: /*.xml$\n", "x")
    assert not end.can_fetch("https://www.prothomalo.com/a.xml") and end.can_fetch("https://www.prothomalo.com/a.xml.gz")


def test_robots_redirect_is_followed_on_site():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(301, headers={"location": "/robots-real.txt"})
        if req.url.path == "/robots-real.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, text="ok")
    c = _client(handler)
    assert c._get("https://www.prothomalo.com/public") == "ok"
    with pytest.raises(FetchBlocked):
        c._get("https://www.prothomalo.com/private/x")


def test_no_future_dates_even_without_publication_time():
    from datetime import timedelta
    g = load()
    art = {**ARTICLE, "published_at": None, "fetched_at": datetime(2026, 10, 24, 6, 0, tzinfo=timezone.utc)}
    rows = build_rows(art, ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                           incidents=[_inc(incident_date="2099-01-01")]), g, {}, "auto")
    assert rows[0]["incident_date"] is None and rows[0]["event_date"] == date(2026, 10, 24)


# ---- Gemma-only live data -----------------------------------------------------------------------
def test_place_outside_the_shortlist_is_dropped():
    art = Article(url="u", section="bangladesh/crime", title="মিরপুর ১১-তে ছিনতাই", keywords="",
                  body="রাজধানীর মিরপুর ১১ নম্বরে রাতে ছিনতাই হয়েছে।",
                  published_at=datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc))
    off = ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                          incidents=[_inc(place_id="shahali"), _inc(place_id="pallabi")]).model_dump_json()
    got = _gemma([_completion(off)]).classify(art)
    assert [i.place_id for i in got.incidents] == [None, "pallabi"]       # not in the shortlist -> null


def test_identical_incidents_collapse_but_distinct_ones_stay():
    g = load()
    same = ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="", incidents=[_inc(), _inc(), _inc(category="theft")])
    rows = build_rows(ARTICLE, same, g, {}, "auto")
    assert [r["category"] for r in rows] == ["drugs_arms", "theft"]


def test_location_fallback_needs_the_phrase_in_the_article():
    g = load()
    made_up = ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                              incidents=[_inc(place_id=None, location_text="গুলশান ২ নম্বরে")])
    real = ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                           incidents=[_inc(place_id=None, location_text="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")])
    assert build_rows(ARTICLE, made_up, g, {}, "auto")[0]["place_id"] is None
    assert build_rows(ARTICLE, real, g, {}, "auto")[0]["place_id"] == "mirpur11"


def test_geocoding_is_queued_not_done_inline():
    g = load()
    rows = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                               incidents=[_inc(geocode_query="Mirpur 11 metro, Dhaka")]), g, {}, "auto")
    assert rows[0]["geocode_state"] == "todo" and rows[0]["published"] and not rows[0]["geocoded"]


def test_prompt_counts_one_episode_once():
    from app.classifiers.base import compact_system_prompt
    p = compact_system_prompt()
    assert "ONE incident" in p and "never separate incidents" in p and "drugs_arms only when" in p


def test_streaming_measures_prefill_and_decode(monkeypatch):
    import json as _json
    monkeypatch.setenv("GEMMA_STREAM", "1")
    half = len(GOOD) // 2
    events = [{"model": "dhaka-gemma", "choices": [{"delta": {"content": GOOD[:half]}}]},
              {"choices": [{"delta": {"content": GOOD[half:]}, "finish_reason": "stop"}]},
              {"choices": [], "usage": {"prompt_tokens": 2000, "completion_tokens": 300,
                                        "prompt_tokens_details": {"cached_tokens": 1500}}}]
    sse = "".join(f"data: {_json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    analysis, meta = _gemma([httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})]
                            ).classify_with_meta(ART)
    assert analysis.incidents[0].place_id == "mirpur11"
    assert meta["prompt_tokens"] == 2000 and meta["cached_tokens"] == 1500 and meta["ttft_s"] >= 0
    assert meta["output_tokens"] == 300


def test_referral_hospital_is_not_dhaka_evidence():
    from app.scraper import belongs_to_dhaka
    g = load()
    assert not belongs_to_dhaka("bangladesh", "চট্টগ্রামে ছুরিকাঘাত, আহত ব্যক্তিকে ঢাকা মেডিকেলে নেওয়া হয়", g)
    assert belongs_to_dhaka("bangladesh/crime", "চট্টগ্রামে ছুরিকাঘাত, ঢাকা মেডিকেলে নেওয়া হয়", g)   # crime section: Gemma decides
    assert belongs_to_dhaka("bangladesh", "মিরপুরে ছিনতাই, ঢাকা মেডিকেলে নেওয়া হয়", g)



# ---- publication grounding (council review, 26 Oct) ---------------------------------------------
def test_namesake_through_connector_words():
    g = load()
    assert [p.id for p in g.find_all("চট্টগ্রাম নগরের চকবাজারে ছিনতাই")] == []
    assert [p.id for p in g.find_all("কুষ্টিয়া সদর উপজেলার মিরপুরে হামলা")] == []
    assert "chawkbazar" in [p.id for p in g.find_all("পুরান ঢাকার চকবাজারে ছিনতাই")]


def test_published_only_when_the_article_names_the_place():
    g = load()
    ok = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note=""), g, {}, "auto")
    assert ok[0]["published"] and ok[0]["located_in_dhaka"]
    invented = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                                   incidents=[_inc(place_id="badda", location_text="বাড্ডা")]), g, {}, "auto")
    assert not invented[0]["published"] and invented[0]["evidence_ok"]       # quote fine, place not in the article
    unlocated = build_rows(ARTICLE, ArticleAnalysis(is_crime_report=True, in_dhaka=True, note="",
                                                    incidents=[_inc(place_id=None, location_text="")]), g, {}, "auto")
    assert not unlocated[0]["published"]
    ctg = {**ARTICLE, "body": "চট্টগ্রাম নগরের চকবাজারে ছিনতাই হয়েছে। চকবাজার থানার পুলিশ জানায়, মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে …"}
    rows = build_rows(ctg, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_inc()], note=""), g, {}, "auto")
    assert not rows[0]["published"]                                            # the lead puts it in Chattogram


def test_no_dhaka_place_means_no_shortlist():
    from app.classifiers.base import candidate_places
    far = Article(url="u", section="bangladesh", title="চট্টগ্রামে ছিনতাই", body="চট্টগ্রাম নগরের বিবিরহাটে ছিনতাই, ঢাকা মেডিকেলে নেওয়া হয়",
                  published_at=None)
    assert candidate_places(far) == []



def test_victims_home_is_not_the_crime_location():
    g = load()
    assert g.lead_in_other_district("চট্টগ্রামে ছিনতাই হয়েছে। আহত ব্যক্তির বাড়ি মিরপুরে।")
    art = {**ARTICLE, "title": "ছিনতাই", "body": "চট্টগ্রামে ছিনতাই হয়েছে। আহত ব্যক্তির বাড়ি মিরপুরে।"}
    inc = _inc(place_id="mirpur", location_text="মিরপুরে", evidence="চট্টগ্রামে ছিনতাই হয়েছে")
    assert not build_rows(art, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[inc], note=""),
                          g, {}, "auto")[0]["published"]
    # place named only far from where the incident is described: held
    art2 = {**ARTICLE, "body": "রাজধানীর মিরপুরে আজ একটি সভা হয়েছে। সভায় অনেকে বক্তব্য দেন। পরে সবাই চলে যান। "
                               "সন্ধ্যায় বৃষ্টি হয়। রাতে বিদ্যুৎ ছিল না। এক দোকানে চুরি হয়েছে।"}
    inc2 = _inc(place_id="mirpur", location_text="দোকানে", evidence="এক দোকানে চুরি হয়েছে")
    assert not build_rows(art2, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[inc2], note=""),
                          g, {}, "auto")[0]["published"]
    # the incident's own sentence says রাজধানী and the article names the place: published (e.g. ECB Chattar,
    # not in the place list, inside Cantonment)
    art3 = {**ARTICLE, "body": "ক্যান্টনমেন্ট থানার পুলিশ জানায়, মামলা হয়েছে। গত রাতে রাজধানীর ইসিবি চত্বরে একটি প্রকল্পে হামলা হয়।"}
    inc3 = _inc(category="assault", place_id="cantonment", location_text="ইসিবি চত্বরে",
                evidence="গত রাতে রাজধানীর ইসিবি চত্বরে একটি প্রকল্পে হামলা হয়")
    assert build_rows(art3, ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[inc3], note=""),
                      g, {}, "auto")[0]["published"]
