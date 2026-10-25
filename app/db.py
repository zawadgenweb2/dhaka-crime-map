"""SQLite storage. One file, WAL mode, safe for the API + scheduler threads."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY,
  url TEXT UNIQUE NOT NULL,
  section TEXT, title TEXT, keywords TEXT, body TEXT,
  published_at TEXT, fetched_at TEXT,
  status TEXT NOT NULL,            -- pending | skipped | classified | error
  classifier TEXT, note TEXT, error TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  classified_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_articles_status ON articles(status);

CREATE TABLE IF NOT EXISTS incidents (
  id INTEGER PRIMARY KEY,
  article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  category TEXT NOT NULL,
  headline_bn TEXT, headline_en TEXT,
  location_text TEXT, place_id TEXT, thana_id TEXT,
  lat REAL, lng REAL, precision TEXT, geocoded INTEGER NOT NULL DEFAULT 0,
  incident_date TEXT, event_date TEXT, time_of_day TEXT,
  victims INTEGER NOT NULL DEFAULT 0,
  evidence TEXT, evidence_ok INTEGER NOT NULL DEFAULT 0,
  duplicate_of INTEGER REFERENCES incidents(id),
  classifier TEXT, created_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_incidents_event ON incidents(event_date);
CREATE INDEX IF NOT EXISTS ix_incidents_thana ON incidents(thana_id);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY,
  trigger TEXT, started_at TEXT, finished_at TEXT, status TEXT,
  discovered INTEGER DEFAULT 0, fetched INTEGER DEFAULT 0, classified INTEGER DEFAULT 0,
  incidents INTEGER DEFAULT 0, errors INTEGER DEFAULT 0, message TEXT
);

CREATE TABLE IF NOT EXISTS geocache (
  query TEXT PRIMARY KEY, lat REAL, lng REAL, display TEXT, created_at TEXT
);
"""

_local = threading.local()
_init_lock = threading.Lock()
_initialised: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path or settings.database_path)
    key = str(path)
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    if key not in conns:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        with _init_lock:
            if key not in _initialised:
                conn.executescript(SCHEMA)
                _initialised.add(key)
        conns[key] = conn
    return conns[key]


@contextmanager
def tx(path: Path | None = None):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
