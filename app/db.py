"""PostgreSQL access. Short-lived connections; every transaction is explicit and short."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from .config import ROOT, settings

log = logging.getLogger(__name__)
MIGRATIONS = ROOT / "migrations"
MIGRATION_LOCK = 7_000_001  # advisory lock id: only one migrator at a time


def connect(url: str | None = None, autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(url or settings.database_url, row_factory=dict_row, autocommit=autocommit)


@contextmanager
def tx(url: str | None = None):
    """One transaction on its own connection: commit on success, roll back on error."""
    with connect(url) as conn:
        with conn.transaction():
            yield conn


def migrate(url: str | None = None) -> list[str]:
    """Apply migrations/NNN_*.sql in order, once each. Safe to run concurrently."""
    applied: list[str] = []
    with connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                              version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(Path(MIGRATIONS).glob("*.sql")):
                if path.stem in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                applied.append(path.stem)
                log.info("applied migration %s", path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
    return applied


def heartbeat(service: str, detail: dict | None = None) -> None:
    from psycopg.types.json import Jsonb
    with tx() as c:
        c.execute("""INSERT INTO heartbeats (service, seen_at, detail) VALUES (%s, now(), %s)
                     ON CONFLICT (service) DO UPDATE SET seen_at = now(), detail = EXCLUDED.detail""",
                  (service, Jsonb(detail or {})))
