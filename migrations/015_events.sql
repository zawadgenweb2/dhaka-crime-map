-- Events: one row per real crime, built from newspaper reports (incidents) by the matcher (app/events.py).
-- A report keeps a stable key across re-analysis (article + its quote), so links survive rematerialisation.
ALTER TABLE incidents ADD COLUMN report_key TEXT;
CREATE INDEX incidents_report_key_idx ON incidents (report_key);

CREATE TABLE events (
  id                  BIGSERIAL PRIMARY KEY,
  state               TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'retired')),
  category            TEXT,
  district_id         TEXT,
  place_id            TEXT,
  thana_id            TEXT,
  event_date          DATE,
  primary_report_key  TEXT,
  primary_incident_id BIGINT,
  report_count        INT NOT NULL DEFAULT 0,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_primary_idx ON events (primary_incident_id) WHERE state = 'active';
CREATE INDEX events_block_idx ON events (district_id, event_date) WHERE state = 'active';

-- current membership: every reduced report belongs to exactly one event
CREATE TABLE event_reports (
  report_key   TEXT PRIMARY KEY,
  event_id     BIGINT NOT NULL REFERENCES events(id),
  article_id   BIGINT NOT NULL,
  linked_by    TEXT NOT NULL,              -- 'matcher' or 'admin:<name>'
  decision_id  BIGINT,
  linked_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX event_reports_event_idx ON event_reports (event_id);

-- every candidate the matcher looked at, and why it linked or not (append-only audit)
CREATE TABLE match_decisions (
  id               BIGSERIAL PRIMARY KEY,
  report_key       TEXT NOT NULL,
  event_id         BIGINT,
  candidate_key    TEXT,
  stage            TEXT NOT NULL,          -- new, embed, judge, final, admin
  outcome          TEXT NOT NULL,          -- linked, new_event, rejected, ambiguous, error, split, merged
  score            REAL,
  evidence         JSONB NOT NULL DEFAULT '{}',
  matcher_version  TEXT NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX match_decisions_report_idx ON match_decisions (report_key, id);
CREATE INDEX match_decisions_event_idx ON match_decisions (event_id, id);

-- "never put this report in that event again" (admin split); the matcher honours it on every replay
CREATE TABLE event_exclusions (
  report_key  TEXT NOT NULL,
  event_id    BIGINT NOT NULL,
  actor       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (report_key, event_id)
);

-- embedding cache (EmbeddingGemma 2), internal only
CREATE TABLE report_vectors (
  report_key  TEXT NOT NULL,
  model       TEXT NOT NULL,
  input_hash  TEXT NOT NULL,
  vec         REAL[] NOT NULL,
  PRIMARY KEY (report_key, model)
);

-- reports waiting for the matcher (fresh first)
CREATE TABLE match_queue (
  report_key    TEXT PRIMARY KEY,
  seq           BIGSERIAL,                -- arrival order (oldest report first within a priority)
  priority      SMALLINT NOT NULL DEFAULT 0,
  available_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts      INT NOT NULL DEFAULT 0,
  last_error    TEXT
);
CREATE INDEX match_queue_claim_idx ON match_queue (priority, available_at, seq);

CREATE TABLE app_flags (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
