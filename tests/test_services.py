"""Service tests against a real Postgres (TEST_DATABASE_URL). Run: docker compose --profile test run --rm test"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (Postgres)")

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.classifiers.base import Classifier, ClassifierError  # noqa: E402
from app.collector import Collector, collect  # noqa: E402
from app.schema import ArticleAnalysis, Incident  # noqa: E402
from app.scraper import Candidate, parse_article  # noqa: E402
from app.worker import Worker  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "prothom_alo_crime.html"
URL = "https://www.prothomalo.com/bangladesh/crime/n8b6mizawc"


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
        return parse_article(FIXTURE.read_text(encoding="utf-8"), url)


def _incident(**kw):
    base = dict(category="drugs_arms", headline_bn="গ্রেপ্তার", headline_en="Arrest",
                location_text="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশন", place_id="mirpur11", geocode_query=None,
                precision="exact", incident_date="2026-10-24", time_of_day="afternoon", victims=0,
                evidence="মিরপুর ১১ নম্বর মেট্রোরেল স্টেশনের নিচে")
    base.update(kw)
    return Incident(**base)


class FakeClassifier(Classifier):
    def __init__(self, name="claude:fake", fail=None, incidents=None):
        self.name, self.calls, self.fail = name, 0, fail
        self.incidents = incidents if incidents is not None else [_incident()]

    def classify(self, article):
        return self.classify_with_meta(article)[0]

    def classify_with_meta(self, article):
        self.calls += 1
        if self.fail:
            raise self.fail
        return (ArticleAnalysis(is_crime_report=True, in_dhaka=True, incidents=self.incidents, note="ok"),
                {"model": "fake", "input_tokens": 10, "output_tokens": 5, "cost_usd": 0.001})


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


def test_daily_budget_stops_paid_calls(monkeypatch):
    collect("test", client=FakeSite(urls=(URL, URL + "b")))
    import dataclasses
    import app.worker as worker_mod
    monkeypatch.setattr(worker_mod, "settings", dataclasses.replace(worker_mod.settings, max_llm_calls_per_day=1))
    clf = FakeClassifier()
    w = Worker(classifier=clf, use_geocoder=False)
    outcomes = w.drain()
    assert outcomes == {"done": 1, "budget": 1}
    assert clf.calls == 1
    assert q1("SELECT count(*) n FROM jobs WHERE state='queued' AND available_at > now()")["n"] == 1


def test_crash_after_sending_marks_uncertain_not_resent():
    collect("test", client=FakeSite())
    w = Worker(classifier=FakeClassifier(), use_geocoder=False)
    job = w.claim()
    with db.tx() as c:   # simulate: call recorded as sent, worker died, lease expired
        c.execute("INSERT INTO llm_calls (job_id, backend) VALUES (%s, 'claude')", (job["id"],))
        c.execute("UPDATE jobs SET dispatches = 1, lease_until = now() - interval '1 minute' WHERE id = %s",
                  (job["id"],))
    assert w.recover_expired() == 1
    assert q1("SELECT state FROM jobs")["state"] == "uncertain"
    assert q1("SELECT status FROM articles")["status"] == "uncertain"
    assert w.drain() == {}


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
    api = TestClient(create_app())
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
    # "collect now": blocked without the UI header, blocked cross-origin, allowed same-origin, then 409
    assert api.post("/api/scrape").status_code == 403
    assert api.post("/api/scrape", headers={"x-dcm-ui": "1", "origin": "http://hostile.example"}).status_code == 403
    assert api.post("/api/scrape", headers={"x-dcm-ui": "1", "origin": "http://testserver"}).status_code == 202
    assert api.post("/api/scrape", headers={"x-dcm-ui": "1"}).status_code == 409
