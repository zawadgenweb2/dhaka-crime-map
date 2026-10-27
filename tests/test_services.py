"""Service tests against a real Postgres (TEST_DATABASE_URL). Run: docker compose --profile test run --rm test"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (Postgres)")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.classifiers.base import Classifier, ClassifierError  # noqa: E402
from app.collector import Collector, collect  # noqa: E402
from app.schema import ArticleAnalysis, Incident  # noqa: E402
from app.scraper import DHAKA_TZ, Candidate, parse_article  # noqa: E402
from app.worker import Worker  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "prothom_alo_crime.html"
URL = "https://www.prothomalo.com/bangladesh/crime/n8b6mizawc"


TOKEN = "t" * 24


@pytest.fixture(autouse=True)
def admin_token(monkeypatch):
    """Every test runs with a known machine token on the admin app."""
    import dataclasses
    import app.api as api_mod
    import app.auth as auth_mod
    monkeypatch.setattr(auth_mod, "settings", dataclasses.replace(auth_mod.settings, admin_token=TOKEN))
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token=TOKEN))


def _admin():
    """Admin app client authenticated with the machine token."""
    from app.api import create_app
    return TestClient(create_app(), base_url="https://testserver", headers={"x-admin-token": TOKEN})


def _anon():
    from app.api import create_app
    return TestClient(create_app(), base_url="https://testserver")


def _public():
    from app.public import create_public_app
    return TestClient(create_public_app())


@pytest.fixture(autouse=True)
def one_paper(monkeypatch):
    """The service tests use one paper (Prothom Alo fixtures); multi-paper behaviour has its own tests."""
    monkeypatch.setenv("SOURCES_DISABLED", "samakal,ittefaq,banglatribune,ajkerpatrika,deshrupantor")


@pytest.fixture(autouse=True)
def fresh_db():
    with db.connect(autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
    db.migrate()
    yield


class FakeSite:
    def __init__(self, urls=(URL,)):
        self.urls = urls

    def news_sitemap(self):
        return [Candidate(u, "bangladesh/crime", "পিস্তলসহ গ্রেপ্তার", "মিরপুর, অস্ত্র",
                          datetime(2026, 10, 24, 17, 25, tzinfo=timezone.utc)) for u in self.urls]

    def daily_sitemap(self, day):
        return []

    def article(self, url):
        art = parse_article(FIXTURE.read_text(encoding="utf-8"), url)
        art.published_at = datetime.now(timezone.utc) - timedelta(hours=2)   # always inside the run's window
        return art


def _incident(**kw):
    base = dict(category="drugs_arms", headline_bn="গ্রেপ্তার", headline_en="Arrest",
                location_text="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশন", place_id="mirpur11", geocode_query=None,
                precision="exact", incident_date="2026-10-24", time_of_day="afternoon", victims=0,
                evidence="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")
    base.update(kw)
    return Incident(**base)


class FakeClassifier(Classifier):
    def __init__(self, name="gemma:fake", fail=None, incidents=None):
        self.name, self.calls, self.fail = name, 0, fail
        self.incidents = incidents if incidents is not None else [_incident()]

    def classify(self, article):
        return self.classify_with_meta(article)[0]

    def classify_with_meta(self, article):
        self.calls += 1
        if self.fail:
            raise self.fail
        return (ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=self.incidents, note="ok"),
                {"model": "fake", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0})


def q1(sql, *params):
    with db.connect() as c:
        return c.execute(sql, params).fetchone()


# ---- collector + worker happy path ---------------------------------------------------------------
def test_collect_queues_then_worker_classifies_once():
    r = collect("test", client=FakeSite())
    assert r["status"] == "ok" and r["queued"] == 1
    assert collect("test", client=FakeSite())["queued"] == 0           # nothing new the second time
    clf = FakeClassifier()
    w = Worker(classifier=clf, use_geocoder=False)
    assert w.drain() == {"done": 1}
    assert clf.calls == 1
    inc = q1("SELECT * FROM incidents")
    assert inc["place_id"] == "mirpur11" and inc["thana_id"] == "pallabi" and inc["published"]
    assert q1("SELECT status FROM articles")["status"] == "classified"
    assert q1("SELECT count(*) n FROM analyses")["n"] == 1
    assert q1("SELECT outcome FROM llm_calls")["outcome"] == "ok"
    assert w.drain() == {}                                              # never re-classified


def test_two_workers_never_claim_the_same_job():
    collect("test", client=FakeSite(urls=(URL, URL + "b")))
    a, b = Worker(classifier=FakeClassifier()), Worker(classifier=FakeClassifier())
    ja, jb = a.claim(), b.claim()
    assert ja and jb and ja["id"] != jb["id"]
    assert a.claim() is None


# ---- cost protection ---------------------------------------------------------------------------
def test_materialize_failure_retries_without_new_model_call(monkeypatch):
    collect("test", client=FakeSite())
    clf = FakeClassifier()
    w = Worker(classifier=clf, use_geocoder=False)
    import app.worker as worker_mod
    real = worker_mod.materialize
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk hiccup")
        return real(*a, **k)
    monkeypatch.setattr(worker_mod, "materialize", flaky)
    assert w.run_once() == "retry"
    with db.tx() as c:
        c.execute("UPDATE jobs SET available_at = now()")
    assert w.run_once() == "done"
    assert clf.calls == 1                                               # paid once
    assert q1("SELECT count(*) n FROM incidents")["n"] == 1


def test_failure_after_geocode_keeps_old_incidents(monkeypatch):
    collect("test", client=FakeSite())
    Worker(classifier=FakeClassifier(), use_geocoder=False).drain()
    before = q1("SELECT count(*) n FROM incidents")["n"]
    # Re-run materialize for the same article and make it fail inside the transaction
    import app.store as store_mod
    monkeypatch.setattr(store_mod, "rebuild_groups", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    art = q1("SELECT * FROM articles")
    analysis = ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=[_incident(), _incident()], note="")
    from app.gazetteer import load
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            store_mod.materialize(c, art, None, analysis, "test", load(), {})
    assert q1("SELECT count(*) n FROM incidents")["n"] == before          # rolled back, nothing deleted


def test_transient_errors_retry_then_fail_with_bounded_calls():
    collect("test", client=FakeSite())
    clf = FakeClassifier(fail=ClassifierError("rate limited"))
    w = Worker(classifier=clf, use_geocoder=False)
    assert w.run_once() == "retry"
    with db.tx() as c:
        c.execute("UPDATE jobs SET available_at = now()")
    assert w.run_once() == "failed"
    assert w.drain() == {}
    assert clf.calls == 2                                               # max_dispatches


def test_permanent_error_pauses_without_burning_attempts():
    collect("test", client=FakeSite())
    clf = FakeClassifier(fail=ClassifierError("invalid API key", permanent=True))
    w = Worker(classifier=clf, use_geocoder=False)
    assert w.run_once() == "paused"
    assert q1("SELECT state FROM jobs")["state"] == "queued"


# ---- duplicates --------------------------------------------------------------------------------
def test_distinct_events_in_same_thana_are_not_merged():
    collect("test", client=FakeSite(urls=(URL, URL + "b", URL + "c")))
    # one classifier answer per article, in claim order
    answers = iter([[_incident(category="murder", time_of_day="night")],
                    [_incident(category="murder", time_of_day="night", place_id="mirpur12",
                               location_text="মিরপুর ১২")],
                    [_incident(category="murder", time_of_day="unknown")]])

    class Seq(FakeClassifier):
        def classify_with_meta(self, article):
            self.incidents = next(answers)
            return super().classify_with_meta(article)
    Worker(classifier=Seq(), use_geocoder=False).drain()
    with db.connect() as c:
        rows = c.execute("SELECT place_id, duplicate_of FROM incidents ORDER BY id").fetchall()
    assert rows[1]["duplicate_of"] is None                              # Mirpur 12 is a separate event
    assert rows[2]["duplicate_of"] is not None                          # same spot, compatible time → same event


# ---- scheduler ---------------------------------------------------------------------------------
def test_slots_run_once_and_crash_is_retried(monkeypatch):
    ran = []
    monkeypatch.setattr("app.collector.collect", lambda trigger, days_back=1: ran.append(trigger) or
                        {"status": "ok", "run_id": None})
    col = Collector()
    col._plan_slots()
    assert col._run_slot() is True and ran == ["schedule"]
    assert col._run_slot() is False                                     # same slot never runs twice
    with db.tx() as c:
        c.execute("UPDATE schedule_slots SET status = 'running' WHERE status = 'done'")
        c.execute("UPDATE schedule_slots SET status = 'pending' WHERE status = 'running'")  # what serve() does
    assert col._run_slot() is True


# ---- importer ----------------------------------------------------------------------------------
def test_sqlite_import_preserves_results_without_queueing(tmp_path):
    p = tmp_path / "old.db"
    s = sqlite3.connect(p)
    s.executescript("""
      CREATE TABLE articles (id INTEGER PRIMARY KEY, url TEXT UNIQUE, section TEXT, title TEXT, keywords TEXT, body TEXT,
        published_at TEXT, fetched_at TEXT, status TEXT, classifier TEXT, note TEXT, error TEXT, attempts INT,
        classified_at TEXT);
      CREATE TABLE incidents (id INTEGER PRIMARY KEY, article_id INT, category TEXT, headline_bn TEXT, headline_en TEXT,
        location_text TEXT, place_id TEXT, thana_id TEXT, lat REAL, lng REAL, precision TEXT, geocoded INT,
        incident_date TEXT, event_date TEXT, time_of_day TEXT, victims INT, evidence TEXT, evidence_ok INT,
        duplicate_of INT, classifier TEXT, created_at TEXT);
      CREATE TABLE runs (id INTEGER PRIMARY KEY, trigger TEXT, started_at TEXT, finished_at TEXT, status TEXT,
        discovered INT, fetched INT, classified INT, incidents INT, errors INT, message TEXT);
      CREATE TABLE geocache (query TEXT PRIMARY KEY, lat REAL, lng REAL, display TEXT, created_at TEXT);
      INSERT INTO articles VALUES (1,'u1','bangladesh/crime','t','k','b','2026-10-24T23:25:23+06:00',
        '2026-10-25T11:15:44+00:00','classified','claude:claude-opus-5-5','n',NULL,0,'2026-10-25T11:26:51+00:00');
      INSERT INTO articles VALUES (2,'u2','bangladesh/crime','t','k','b',NULL,'2026-10-25T11:15:44+00:00',
        'classified','claude:claude-opus-5-5','no incident',NULL,0,'2026-10-25T11:26:51+00:00');
      INSERT INTO articles VALUES (3,'u3','bangladesh/capital','t','k','b',NULL,'2026-10-25T11:15:44+00:00',
        'skipped',NULL,'pre-filter',NULL,0,NULL);
      INSERT INTO incidents VALUES (7,1,'murder','h','h','l','mirpur11','pallabi',23.8,90.3,'exact',1,'2026-10-24',
        '2026-10-24','night',1,'e',1,NULL,'claude','2026-10-25T11:26:51+00:00');
      INSERT INTO incidents VALUES (8,2,'murder','h','h','l','mirpur11','pallabi',23.8,90.3,'exact',1,'2026-10-24',
        '2026-10-24','night',1,'e',1,7,'claude','2026-10-25T11:26:51+00:00');
      INSERT INTO runs VALUES (1,'cli','2026-10-25T11:14:34+00:00','2026-10-25T11:15:04+00:00','ok',4,4,4,2,0,'m');
      INSERT INTO geocache VALUES ('q',23.8,90.3,'d','2026-10-25T11:20:00+00:00');
    """)
    s.commit()
    s.close()
    from app.importer import import_sqlite
    counts = import_sqlite(str(p))
    assert counts["articles"] == 3 and counts["incidents"] == 2 and counts["queued_jobs"] == 0
    assert counts["classified"] == 2 and counts["canonical"] == 1
    assert q1("SELECT duplicate_of FROM incidents WHERE id = 8")["duplicate_of"] == 7
    assert Worker(classifier=FakeClassifier()).drain() == {}            # nothing re-sent to a model
    from app.api import create_app
    assert _admin().get("/api/incidents", params={"days": 3650}).json() == []  # never served
    with pytest.raises(RuntimeError):
        import_sqlite(str(p))                                           # refuses to run twice
    with db.tx() as c:                                                  # new ids continue after imported ones
        assert c.execute("INSERT INTO incidents (article_id, category) VALUES (1,'theft') RETURNING id"
                         ).fetchone()["id"] > 8


# ---- API ---------------------------------------------------------------------------------------
def test_api_reads_and_guards_trigger():
    collect("test", client=FakeSite())
    Worker(classifier=FakeClassifier(), use_geocoder=False).drain()
    from app.api import create_app
    api = _admin()
    assert api.get("/").status_code == 200
    meta = api.get("/api/meta").json()
    assert meta["running"] is False and meta["queue"] == {"done": 1}
    inc = api.get("/api/incidents", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert inc[0]["place_bn"] == "মিরপুর ১১" and inc[0]["event_date"] == "2026-10-24"
    st = api.get("/api/stats", params={"start": "2026-10-01", "end": "2026-10-31"}).json()
    assert st["total"] == 1 and st["by_thana"][0]["id"] == "pallabi"
    assert api.get("/api/incidents", params={"limit": -1}).status_code == 422
    assert api.get("/api/runs", params={"limit": 0}).status_code == 422
    assert api.get("/api/stats", params={"end": "0001-01-01", "days": 30}).status_code == 400
    # "collect now" is an admin action: the old dashboard header alone is not enough
    anon = _anon()
    assert anon.post("/api/scrape").status_code == 401
    assert anon.post("/api/scrape", headers={"x-dcm-ui": "1", "origin": "https://testserver"}).status_code == 401
    assert api.post("/api/scrape").status_code == 202                       # the machine token may


def test_review_flow(monkeypatch):
    import dataclasses
    import app.api as api_mod
    import app.store as store_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    monkeypatch.setattr(store_mod, "settings", dataclasses.replace(store_mod.settings, publish_mode="review"))
    collect("test", client=FakeSite())
    Worker(classifier=FakeClassifier(), use_geocoder=False).drain()
    inc = q1("SELECT id, published, review_status FROM incidents")
    assert inc["review_status"] == "pending" and not inc["published"]
    api = _admin()
    assert _anon().get("/api/review/queue").status_code == 401
    h = {"x-admin-token": "t" * 24, "x-reviewer": "zawad"}
    queue = api.get("/api/review/queue", headers=h).json()
    assert [i["id"] for i in queue["items"]] == [inc["id"]]
    assert api.get("/api/stats", params={"start": "2026-10-01", "end": "2026-10-31"}).json()["total"] == 0
    r = api.post(f"/api/review/incidents/{inc['id']}", headers=h, json={"action": "approve", "place_id": "badda"})
    assert r.status_code == 200
    row = q1("SELECT published, review_status, place_id, thana_id, reviewed_by FROM incidents")
    assert row["published"] and row["review_status"] == "approved" and row["thana_id"] == "badda"
    assert row["reviewed_by"] == "token"                                  # the authenticated identity, not a header
    assert api.get("/api/stats", params={"start": "2026-10-01", "end": "2026-10-31"}).json()["total"] == 1
    api.post(f"/api/review/incidents/{inc['id']}", headers=h, json={"action": "reject"})
    assert not q1("SELECT published FROM incidents")["published"]
    assert api.post("/api/review/articles/1", headers=h, json={"verdict": "missed_incident"}).status_code == 200


def _seed_incident(article_id, day, place="mirpur11", category="murder", published=True, lat=23.81, geocoded=False,
                   backend="gemma", evidence="মিরপুর ১১ নম্বরে রাকিব হাসান (২৫) নামে যুবক খুন"):
    """An incident with a saved analysis of the given backend (only 'gemma' rows are ever served)."""
    with db.tx() as c:
        aid = c.execute("""INSERT INTO analyses (article_id, backend, model, result) VALUES (%s, %s, 'fake', '{}')
                           RETURNING id""", (article_id, backend)).fetchone()["id"]
        return c.execute("""INSERT INTO incidents (article_id, analysis_id, category, place_id, thana_id, lat, lng,
                              event_date, time_of_day, published, review_status, geocoded, evidence_ok, evidence)
                            VALUES (%s,%s,%s,%s,'pallabi',%s,90.36,%s,'night',%s,%s,%s,true,%s) RETURNING id""",
                         (article_id, aid, category, place, lat, day, published, "auto" if published else "pending",
                          geocoded, evidence)).fetchone()["id"]


def _seed_articles(n):
    with db.tx() as c:
        return [c.execute("INSERT INTO articles (url, status) VALUES (%s, 'classified') RETURNING id",
                          (f"https://www.prothomalo.com/x/{i}",)).fetchone()["id"] for i in range(n)]


def test_review_keeps_duplicate_chains_and_exact_points(monkeypatch):
    import dataclasses
    from datetime import date
    import app.api as api_mod
    from app.store import rebuild_groups
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    a1, a2, a3 = _seed_articles(3)
    first = _seed_incident(a1, date(2026, 10, 1))
    second = _seed_incident(a2, date(2026, 10, 2))
    third = _seed_incident(a3, date(2026, 10, 5), published=False, lat=23.8191, geocoded=True)
    with db.tx() as c:
        rebuild_groups(c, {("murder", "mirpur11")})
    assert q1("SELECT duplicate_of FROM incidents WHERE id = %s", second)["duplicate_of"] == first
    api = _admin()
    h = {"x-admin-token": "t" * 24}
    # approving with the unchanged place keeps the exact geocode and does not break the 1→2 Oct chain
    assert api.post(f"/api/review/incidents/{third}", headers=h,
                    json={"action": "approve", "place_id": "mirpur11"}).status_code == 200
    row = q1("SELECT lat, geocoded, duplicate_of FROM incidents WHERE id = %s", third)
    assert row["geocoded"] and row["lat"] == 23.8191 and row["duplicate_of"] is None   # 5 Oct: separate event
    assert q1("SELECT duplicate_of FROM incidents WHERE id = %s", second)["duplicate_of"] == first
    api.post(f"/api/review/incidents/{third}", headers=h, json={"action": "reject"})
    assert q1("SELECT duplicate_of FROM incidents WHERE id = %s", second)["duplicate_of"] == first


def test_failed_article_retry_and_dismiss(monkeypatch):
    import dataclasses
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    a1, a2 = _seed_articles(2)
    with db.tx() as c:
        c.execute("UPDATE articles SET status = 'failed' WHERE id IN (%s, %s)", (a1, a2))
        c.execute("INSERT INTO jobs (article_id, state) VALUES (%s, 'failed')", (a1,))
    api = _admin()
    h = {"x-admin-token": "t" * 24}
    assert api.post(f"/api/review/articles/{a1}", headers=h, json={"verdict": "retry"}).status_code == 200
    assert q1("SELECT count(*) n FROM jobs WHERE article_id = %s AND state = 'queued' AND analysis_version = 2",
              a1)["n"] == 1
    assert q1("SELECT analysis_version FROM articles WHERE id = %s", a1)["analysis_version"] == 2
    assert api.post(f"/api/review/articles/{a2}", headers=h, json={"verdict": "dismiss"}).status_code == 200
    assert q1("SELECT status FROM articles WHERE id = %s", a2)["status"] == "dismissed"


def test_evaluation_penalizes_invented_incidents(monkeypatch, tmp_path):
    import json
    collect("test", client=FakeSite())
    art = q1("SELECT id FROM articles")["id"]
    with db.tx() as c:                                         # the frozen reference (migration 005 tables)
        c.execute("INSERT INTO eval_reference_articles (article_id, source) VALUES (%s, 'test')", (art,))
        c.execute("""INSERT INTO eval_reference_incidents (article_id, category, place_id, thana_id, incident_date,
                     time_of_day) VALUES (%s, 'drugs_arms', 'mirpur11', 'pallabi', '2026-10-24', 'afternoon')""", (art,))
    invented = FakeClassifier(name="gemma:fake", incidents=[_incident(), _incident(category="theft")])
    monkeypatch.setattr("app.evaluate.get_classifier", lambda name: invented)
    from app.evaluate import compare
    out = tmp_path / "r.json"
    compare("gemma", 10, str(out))
    r = json.loads(out.read_text())
    assert r["incident_counts"] == {"matched": 1, "extra": 1, "missed": 0}
    assert r["incident_precision"] == 0.5 and not r["passes_all_gates"] and len(r["disagreements"]) == 1
    assert q1("SELECT count(*) n FROM incidents")["n"] == 0                              # eval never writes incidents


def test_failed_slot_is_retried_then_given_up(monkeypatch):
    results = iter([{"status": "failed", "run_id": None}] * 3)
    monkeypatch.setattr("app.collector.collect", lambda trigger, days_back=1: next(results))
    col = Collector()
    col._plan_slots()
    assert col._run_slot() is True
    assert q1("SELECT status, attempts FROM schedule_slots WHERE attempts > 0")["status"] == "pending"
    assert col._run_slot() is False                                        # waits for next_try_at
    for _ in range(2):
        with db.tx() as c:
            c.execute("UPDATE schedule_slots SET next_try_at = now() WHERE status = 'pending' AND attempts > 0")
        assert col._run_slot() is True
    assert q1("SELECT status, attempts FROM schedule_slots WHERE attempts > 0") == {"status": "failed", "attempts": 3}


def test_crashed_call_is_requeued():
    collect("test", client=FakeSite())
    w = Worker(classifier=FakeClassifier(name="gemma:fake"), use_geocoder=False)
    job = w.claim()
    with db.tx() as c:
        c.execute("INSERT INTO llm_calls (job_id, backend) VALUES (%s, 'gemma')", (job["id"],))
        c.execute("UPDATE jobs SET lease_until = now() - interval '1 minute' WHERE id = %s", (job["id"],))
    assert w.recover_expired() == 1
    assert q1("SELECT state FROM jobs")["state"] == "queued"            # free call: just retry


def test_meta_data_version_changes_on_approval(monkeypatch):
    import dataclasses
    import app.api as api_mod
    import app.store as store_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    monkeypatch.setattr(store_mod, "settings", dataclasses.replace(store_mod.settings, publish_mode="review"))
    collect("test", client=FakeSite())
    Worker(classifier=FakeClassifier(), use_geocoder=False).drain()
    api = _admin()
    before = api.get("/api/meta").json()["data_version"]
    inc = q1("SELECT id FROM incidents")["id"]
    api.post(f"/api/review/incidents/{inc}", headers={"x-admin-token": "t" * 24}, json={"action": "approve"})
    assert api.get("/api/meta").json()["data_version"] != before


def test_api_fixes_from_endpoint_review(monkeypatch):
    import dataclasses
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    collect("test", client=FakeSite(urls=(URL, URL + "b")))
    Worker(classifier=FakeClassifier(), use_geocoder=False).run_once()          # one done, one still queued
    api = _admin()
    h = {"x-admin-token": "t" * 24}
    # Swagger can authorize: the token is declared as a security scheme
    spec = api.get("/openapi.json").json()
    assert "APIKeyHeader" in spec["components"]["securitySchemes"]
    # unknown category -> 400 instead of silently returning everything
    assert api.get("/api/incidents", params={"categories": "murdr"}).status_code == 400
    # truncation is visible
    r = api.get("/api/incidents", params={"start": "2026-10-01", "end": "2026-10-31", "limit": 1})
    assert r.headers["x-total-count"] == "1" and r.headers["x-truncated"] == "false"
    # one active collect-now request, enforced by the database
    assert api.post("/api/scrape", headers=h).status_code == 202
    assert api.post("/api/scrape", headers=h).status_code == 409
    # retry refused while a job is active; dismiss cancels the waiting job
    queued = q1("SELECT article_id FROM jobs WHERE state = 'queued'")["article_id"]
    assert api.post(f"/api/review/articles/{queued}", headers=h, json={"verdict": "retry"}).status_code == 409
    assert api.post(f"/api/review/articles/{queued}", headers=h, json={"verdict": "dismiss"}).status_code == 200
    assert q1("SELECT state FROM jobs WHERE article_id = %s", queued)["state"] == "cancelled"
    assert Worker(classifier=FakeClassifier()).drain() == {}


# ---- Gemma-only live data (migration 005) -------------------------------------------------------
def _api():
    return _admin()


def test_only_gemma_incidents_are_served():
    a1, a2, a3 = _seed_articles(3)
    from datetime import date
    keep = _seed_incident(a1, date(2026, 10, 20), place="mirpur11")
    _seed_incident(a2, date(2026, 10, 20), place="badda", backend="claude")
    with db.tx() as c:                                                  # an imported row without any analysis
        c.execute("""INSERT INTO incidents (article_id, category, place_id, event_date, published, evidence_ok)
                     VALUES (%s, 'theft', 'gulshan', '2026-10-20', true, true)""", (a3,))
    api = _api()
    p = {"start": "2026-10-01", "end": "2026-10-31"}
    assert [i["id"] for i in api.get("/api/incidents", params=p).json()] == [keep]
    assert api.get("/api/stats", params=p).json()["total"] == 1
    assert api.get("/api/meta").json()["incident_count"] == 1


def test_reprocess_all_replaces_old_output_with_gemma():
    collect("test", client=FakeSite())
    Worker(classifier=FakeClassifier(name="claude:fake"), use_geocoder=False).drain()   # prototype-era output
    api = _api()
    p = {"start": "2026-10-01", "end": "2026-10-31"}
    assert api.get("/api/incidents", params=p).json() == []                         # stored, but never served
    from app.reprocess import reprocess_all
    r = reprocess_all()
    assert r["articles_queued"] == 1 and r["non_gemma_incidents_removed"] == 1
    assert q1("SELECT count(*) n FROM incidents")["n"] == 0
    job = q1("SELECT analysis_version, run_id, state FROM jobs WHERE state = 'queued'")
    assert job["analysis_version"] == 2 and job["run_id"] == r["run_id"]
    assert [b["jobs"] for b in api.get("/api/meta").json()["batches"]] == [1]
    clf = FakeClassifier()
    assert Worker(classifier=clf, use_geocoder=False).drain() == {"done": 1} and clf.calls == 1  # fresh call
    assert len(api.get("/api/incidents", params=p).json()) == 1
    assert q1("SELECT classifier FROM incidents")["classifier"] == "gemma:fake"


def test_older_version_job_cannot_overwrite_newer_output():
    collect("test", client=FakeSite())
    w = Worker(classifier=FakeClassifier(), use_geocoder=False)
    job = w.claim()
    with db.tx() as c:                                                  # a newer version was requested meanwhile
        c.execute("UPDATE articles SET analysis_version = 2")
    assert w.process(job) == "superseded"
    assert q1("SELECT count(*) n FROM incidents")["n"] == 0


def test_saved_answer_from_another_model_is_not_reused():
    collect("test", client=FakeSite())
    job = Worker(classifier=FakeClassifier()).claim()
    with db.tx() as c:
        c.execute("""INSERT INTO analyses (article_id, job_id, backend, model, result)
                     VALUES (%s, %s, 'claude', 'x', '{}')""", (job["article_id"], job["id"]))
    assert Worker(classifier=FakeClassifier()).process(job) == "failed"
    assert q1("SELECT count(*) n FROM incidents")["n"] == 0


def test_exact_spot_geocoding_after_publication(monkeypatch):
    collect("test", client=FakeSite(urls=(URL, URL + "b")))
    answers = iter([[_incident(geocode_query="Mirpur 11 metro station, Dhaka")],
                    [_incident(geocode_query="Somewhere far, Dhaka", place_id="pallabi", location_text="পল্লবী")]])

    class Seq(FakeClassifier):
        def classify_with_meta(self, article):
            self.incidents = next(answers)
            return super().classify_with_meta(article)
    Worker(classifier=Seq(), use_geocoder=False).drain()
    assert q1("SELECT count(*) n FROM incidents WHERE geocode_state = 'todo' AND published")["n"] == 2
    import dataclasses
    import app.store as store_mod
    hits = {"Mirpur 11 metro station, Dhaka": (23.8191, 90.3653), "Somewhere far, Dhaka": (22.33, 91.83)}
    monkeypatch.setattr(store_mod, "geocode", lambda q, viewbox=None: hits[q])
    monkeypatch.setattr(store_mod, "settings", dataclasses.replace(store_mod.settings, geocode_enabled=True))
    from app.gazetteer import load
    rev = q1("SELECT rev FROM data_revision")["rev"]
    assert sorted([store_mod.enrich_next(load()), store_mod.enrich_next(load())]) == ["done", "far"]
    assert store_mod.enrich_next(load()) is None
    near = q1("SELECT lat, geocoded, precision FROM incidents WHERE geocode_state = 'done'")
    assert near["geocoded"] and near["lat"] == 23.8191 and near["precision"] == "exact"
    assert q1("SELECT geocoded FROM incidents WHERE geocode_state = 'far'")["geocoded"] is False
    assert q1("SELECT rev FROM data_revision")["rev"] == rev + 1               # the map refreshes once


def test_dismiss_hides_incidents_and_failed_ones_cannot_be_approved(monkeypatch):
    import dataclasses
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    collect("test", client=FakeSite(urls=(URL, URL + "b")))
    answers = iter([[_incident()], [_incident(evidence="this sentence is not in the article")]])

    class Seq(FakeClassifier):
        def classify_with_meta(self, article):
            self.incidents = next(answers)
            return super().classify_with_meta(article)
    Worker(classifier=Seq(), use_geocoder=False).drain()
    api = _admin()
    h = {"x-admin-token": "t" * 24}
    failed = q1("SELECT id FROM incidents WHERE review_status = 'failed'")["id"]
    assert api.post(f"/api/review/incidents/{failed}", headers=h, json={"action": "approve"}).status_code == 409
    good = q1("SELECT id, article_id FROM incidents WHERE published")
    before = api.get("/api/meta").json()["data_version"]
    assert api.post(f"/api/review/articles/{good['article_id']}", headers=h,
                    json={"verdict": "dismiss"}).status_code == 200
    assert api.get("/api/incidents", params={"start": "2026-10-01", "end": "2026-10-31"}).json() == []
    assert api.get("/api/meta").json()["data_version"] != before


def test_backfill_request_cap_and_batch_membership(monkeypatch):
    monkeypatch.setattr("app.collector.NewsClient", lambda src: FakeSite(urls=(URL, URL + "b")))
    with db.tx() as c:
        c.execute("INSERT INTO run_requests (source, days_back, max_articles) VALUES ('cli', 90, 1)")
    Collector()._run_request()
    run = q1("SELECT id, days_back, discovered FROM runs")
    assert run["days_back"] == 90 and run["discovered"] == 1
    assert q1("SELECT run_id FROM jobs")["run_id"] == run["id"]


def test_try_an_article_answers_without_saving(monkeypatch):
    import dataclasses
    import threading
    import time
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    api = _admin()
    body = {"title": "পিস্তলসহ গ্রেপ্তার", "published_at": "2026-10-24T20:00:00+06:00",
            "body": "রাজধানীর মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে পিস্তলসহ একজনকে গ্রেপ্তার করা হয়েছে।"}
    assert _anon().post("/api/classify", json=body).status_code == 401       # uses the GPU: login required
    w, stop = Worker(classifier=FakeClassifier(), use_geocoder=False), threading.Event()

    def loop():
        while not stop.is_set():
            if not w.run_preview():
                time.sleep(0.05)
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    try:
        r = api.post("/api/classify", json=body, params={"wait": 10}, headers={"x-admin-token": "t" * 24})
    finally:
        stop.set()
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "done" and out["saved"] is False and "mirpur11" in out["place_candidates_sent"]
    inc = out["after_checks"][0]
    assert inc["place_id"] == "mirpur11" and inc["thana"].endswith("Pallabi") and inc["evidence_in_article"]
    assert inc["would_be_published"] and out["gemma_answer"]["incidents"][0]["category"] == "drugs_arms"
    assert q1("SELECT count(*) n FROM articles")["n"] == 0 and q1("SELECT count(*) n FROM incidents")["n"] == 0
    assert api.get(f"/api/classify/{out['id']}", headers={"x-admin-token": "t" * 24}).json()["status"] == "done"


def test_coverage_marks_each_day(monkeypatch):
    from datetime import timedelta
    from app.scraper import DHAKA_TZ
    yday = datetime.now(DHAKA_TZ).date() - timedelta(days=1)
    when = datetime.combine(yday, datetime.min.time(), tzinfo=DHAKA_TZ).replace(hour=10)

    class DailySite(FakeSite):
        def news_sitemap(self):
            return []

        def daily_sitemap(self, day):
            if day != yday:
                return []
            return [Candidate(u, "bangladesh/crime", published_at=when) for u in self.urls] + \
                   [Candidate("https://www.prothomalo.com/sports/cricket/zz", "sports/cricket", published_at=when)]

        def article(self, url):
            art = super().article(url)
            art.published_at = when
            return art
    site = DailySite(urls=(URL, URL + "b"))
    collect("test", days_back=3, client=site, max_articles=1)           # cap: one of two candidates downloaded
    from app.api import create_app
    api = _admin()
    cov = api.get("/api/coverage", params={"days": 6}).json()
    by = {d["date"]: d for d in cov["days"]}
    assert by[yday.isoformat()]["status"] == "partial" and by[yday.isoformat()]["candidates"] == 2
    assert by[(yday - timedelta(days=1)).isoformat()]["status"] == "complete"      # read, verified empty
    assert by[(yday - timedelta(days=1)).isoformat()]["links"] == 0
    assert by[(yday - timedelta(days=4)).isoformat()]["status"] == "not_collected"  # never read
    assert cov["days_to_collect"] >= 1
    collect("test", days_back=3, client=site, max_articles=10)          # the rest
    assert api.get("/api/coverage", params={"days": 3}).json()["summary"]["processing"] == 1
    Worker(classifier=FakeClassifier(), use_geocoder=False).drain()
    by = {d["date"]: d for d in api.get("/api/coverage", params={"days": 3}).json()["days"]}
    assert by[yday.isoformat()]["status"] == "complete" and by[yday.isoformat()]["missing"] == 0
    with db.tx() as c:                                  # a failed article keeps its day from looking complete
        c.execute("UPDATE articles SET status = 'failed' WHERE url = %s", (URL,))
    by = {d["date"]: d for d in api.get("/api/coverage", params={"days": 3}).json()["days"]}
    assert by[yday.isoformat()]["status"] == "failed"



def test_backfill_window_skips_old_articles(monkeypatch):
    class OldSite(FakeSite):
        def article(self, url):
            art = super().article(url)
            art.published_at = datetime.now(timezone.utc) - timedelta(days=40)
            return art
    r = collect("test", days_back=29, client=OldSite())
    assert r["queued"] == 0
    assert q1("SELECT status, note FROM articles") == {"status": "skipped", "note": "outside the window"}
    from app.reprocess import requeue_set_aside
    assert requeue_set_aside(29)["articles_queued"] == 0                 # 40 days old: still outside
    assert requeue_set_aside(45)["articles_queued"] == 1


def test_page_without_article_text_is_examined_not_missing():
    class NoText(FakeSite):
        def article(self, url):
            raise ValueError("no JSON-LD article body")
    r = collect("test", client=NoText())
    assert r["errors"] == 0 and r["queued"] == 0
    row = q1("SELECT status, note FROM articles")
    assert row["status"] == "skipped" and row["note"].startswith("no article text")



# ---- safety fixes (council, 27 Oct) ---------------------------------------------------------------
def test_rejected_backfill_changes_nothing(monkeypatch):
    import dataclasses
    import app.api as api_mod
    monkeypatch.setattr(api_mod, "settings", dataclasses.replace(api_mod.settings, admin_token="t" * 24))
    a1, = _seed_articles(1)
    with db.tx() as c:
        c.execute("""UPDATE articles SET status = 'skipped', note = 'outside the window', published_at = now()
                     WHERE id = %s""", (a1,))
        c.execute("INSERT INTO run_requests (source, days_back) VALUES ('cli', 1)")       # one already active
    api = _admin()
    r = api.post("/api/scrape", params={"days_back": 29}, headers={"x-admin-token": "t" * 24})
    assert r.status_code == 409
    assert q1("SELECT status FROM articles WHERE id = %s", a1)["status"] == "skipped"       # nothing re-queued


def test_late_answer_after_lost_lease_is_not_saved():
    collect("test", client=FakeSite())

    class Slow(FakeClassifier):
        def classify_with_meta(self, article):
            with db.tx() as c:                                   # meanwhile the lease ran out and was re-claimed
                c.execute("UPDATE jobs SET generation = generation + 1, owner = 'other'")
            return super().classify_with_meta(article)
    w = Worker(classifier=Slow(), use_geocoder=False)
    job = w.claim()
    assert w.process(job) == "lost"
    assert q1("SELECT count(*) n FROM analyses")["n"] == 0 and q1("SELECT count(*) n FROM incidents")["n"] == 0



# ---- public site / admin panel (27 Oct) ----------------------------------------------------------
def test_admin_login_session_csrf_and_logout():
    from app import auth
    auth.add_user("rahim", "correct horse battery")
    c = _anon()
    assert c.get("/", follow_redirects=False).status_code == 303                     # not logged in -> /login
    assert c.get("/api/meta").status_code == 401
    page = c.get("/login")
    pre = page.text.split('name="pre" content="')[1].split('"')[0]
    origin = {"origin": "https://testserver"}
    assert c.post("/api/login", json={"username": "rahim", "password": "correct horse battery"},
                  headers={"x-csrf-token": "wrong", **origin}).status_code == 403    # pre-login CSRF
    assert c.post("/api/login", json={"username": "rahim", "password": "nope nope nope"},
                  headers={"x-csrf-token": pre, **origin}).status_code == 401
    r = c.post("/api/login", json={"username": "rahim", "password": "correct horse battery"},
               headers={"x-csrf-token": pre, **origin})
    assert r.status_code == 200 and auth.COOKIE in r.cookies
    sess = c.get("/api/session").json()
    assert sess["user"] == "rahim" and sess["csrf"]
    assert c.get("/api/meta").status_code == 200
    assert c.post("/api/scrape", headers=origin).status_code == 403                 # no CSRF token
    assert c.post("/api/scrape", headers={"x-csrf-token": sess["csrf"]}).status_code == 403   # no Origin
    assert c.post("/api/scrape", headers={"x-csrf-token": sess["csrf"], "origin": "https://evil.example"}).status_code == 403
    assert c.post("/api/scrape", headers={"x-csrf-token": sess["csrf"], **origin}).status_code == 202
    assert q1("SELECT source FROM run_requests")["source"] == "rahim"
    assert q1("SELECT count(*) n FROM admin_audit WHERE action = 'collect' AND actor = 'rahim'")["n"] == 1
    assert c.post("/api/logout", headers={"x-csrf-token": sess["csrf"], **origin}).status_code == 200
    assert c.get("/api/meta").status_code == 401
    docs = _admin().get("/docs").text
    assert TOKEN not in docs and "requestInterceptor" in docs                        # no secret in the docs page


def test_login_throttling():
    from app import auth
    auth.add_user("karim", "correct horse battery")
    c = _anon()
    pre = c.get("/login").text.split('name="pre" content="')[1].split('"')[0]
    h = {"x-csrf-token": pre, "origin": "https://testserver"}
    for _ in range(5):
        assert c.post("/api/login", json={"username": "karim", "password": "wrong password!"}, headers=h).status_code == 401
    assert c.post("/api/login", json={"username": "karim", "password": "correct horse battery"}, headers=h).status_code == 429


def test_public_site_has_no_admin_surface_and_safe_fields():
    a1, a2 = _seed_articles(2)
    from datetime import date
    _seed_incident(a1, date(2026, 10, 20), category="murder")
    _seed_incident(a2, date(2026, 10, 20), place="badda", category="sexual_violence")
    with db.tx() as c:
        c.execute("UPDATE articles SET url = 'https://www.prothomalo.com/bangladesh/crime/x1' WHERE id = %s", (a1,))
        c.execute("UPDATE incidents SET evidence = 'secret quote', headline_bn = 'নাম', victims = 3")
    pub = _public()
    for path in ("/docs", "/redoc", "/openapi.json", "/api/meta", "/api/runs", "/api/coverage", "/review",
                 "/static/review.html", "/api/review/queue", "/login"):
        assert pub.get(path).status_code == 404, path
    assert pub.post("/api/scrape").status_code in (404, 405) and pub.post("/api/classify", json={}).status_code in (404, 405)
    p = {"start": "2026-10-01", "end": "2026-10-31"}
    inc = pub.get("/api/incidents", params=p).json()
    assert [i["category"] for i in inc] == ["murder"]                                 # sexual violence: totals only
    for k in ("evidence", "headline_bn", "headline_en", "victims", "title", "location_text"):
        assert k not in inc[0]
    assert inc[0]["url"].startswith("https://www.prothomalo.com/") and inc[0]["publisher_en"] == "Prothom Alo"
    st = pub.get("/api/stats", params=p).json()
    assert st["total"] == 2 and st["by_category"]["sexual_violence"] == 1 and "victims" not in st
    v = pub.get("/api/version").json()
    assert set(v) == {"data_version", "updated_at", "today"}
    assert "model" not in str(pub.get("/api/config").json()).lower()



def test_coverage_needs_every_paper_and_lanes_record_their_paper(monkeypatch):
    monkeypatch.delenv("SOURCES_DISABLED")
    monkeypatch.setenv("SOURCES_DISABLED", "ittefaq,banglatribune,ajkerpatrika,deshrupantor")   # two papers
    day = datetime.now(DHAKA_TZ).date()

    class Site(FakeSite):
        def __init__(self, key):
            super().__init__(urls=(f"https://{'www.prothomalo.com' if key == 'prothomalo' else 'samakal.com'}/bangladesh/crime/{key}",))
            self.key = key

        def daily_sitemap(self, d):
            return [Candidate(self.urls[0], "bangladesh/crime")] if d == day else []

        def article(self, url):
            if self.key == "samakal":
                raise httpx.ConnectError("down")
            return super().article(url)
    monkeypatch.setattr("app.collector.NewsClient", lambda src: Site(src.key))
    r = collect("test", days_back=0)
    assert r["status"] == "ok" and r["fetched"] == 1 and r["errors"] == 1          # one paper down, run still ok
    with db.connect() as c:
        assert [x["source"] for x in c.execute("SELECT source FROM articles")] == ["prothomalo"]
        assert {x["source"] for x in c.execute("SELECT source FROM coverage_days")} == {"prothomalo", "samakal"}
    cov = _admin().get("/api/coverage", params={"days": 1}).json()
    assert cov["days"][-1]["status"] == "partial"            # Samakal's candidate was not downloaded
