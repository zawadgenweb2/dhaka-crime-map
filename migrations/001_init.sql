-- Dhaka Crime Map schema (PostgreSQL 17). Applied once by `python -m app migrate`.

CREATE TABLE articles (
  id            BIGSERIAL PRIMARY KEY,
  url           TEXT NOT NULL UNIQUE,
  section       TEXT,
  title         TEXT,
  keywords      TEXT,
  body          TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- skipped (pre-filter) | queued | classified | failed | uncertain
  status        TEXT NOT NULL,
  classifier    TEXT,
  note          TEXT,
  error         TEXT,
  classified_at TIMESTAMPTZ
);
CREATE INDEX articles_status_idx ON articles (status);

-- Classification work queue. One job per article and analysis version.
CREATE TABLE jobs (
  id                    BIGSERIAL PRIMARY KEY,
  article_id            BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  analysis_version      INT NOT NULL DEFAULT 1,
  -- queued | running | done | failed | uncertain
  state                 TEXT NOT NULL DEFAULT 'queued',
  backend               TEXT,
  available_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  lease_until           TIMESTAMPTZ,
  owner                 TEXT,
  generation            INT NOT NULL DEFAULT 0,
  dispatches            INT NOT NULL DEFAULT 0,   -- paid model calls sent for this job
  max_dispatches        INT NOT NULL DEFAULT 2,
  materialize_attempts  INT NOT NULL DEFAULT 0,
  last_error            TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (article_id, analysis_version)
);
CREATE INDEX jobs_claim_idx ON jobs (state, available_at);

-- Every model call is recorded before it is sent (cost control and crash recovery).
CREATE TABLE llm_calls (
  id            BIGSERIAL PRIMARY KEY,
  job_id        BIGINT REFERENCES jobs(id) ON DELETE SET NULL,
  backend       TEXT NOT NULL,
  sent_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ,
  -- sent | ok | error
  outcome       TEXT NOT NULL DEFAULT 'sent',
  error         TEXT
);
CREATE INDEX llm_calls_sent_idx ON llm_calls (sent_at);

-- The model's full answer, saved before anything else can fail.
CREATE TABLE analyses (
  id                BIGSERIAL PRIMARY KEY,
  article_id        BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  job_id            BIGINT REFERENCES jobs(id) ON DELETE SET NULL,
  llm_call_id       BIGINT REFERENCES llm_calls(id) ON DELETE SET NULL,
  backend           TEXT NOT NULL,
  model             TEXT,
  result            JSONB NOT NULL,
  input_tokens      INT,
  cache_read_tokens INT,
  cache_write_tokens INT,
  output_tokens     INT,
  cost_usd          NUMERIC(10, 5),
  legacy            BOOLEAN NOT NULL DEFAULT false,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  materialized_at   TIMESTAMPTZ
);
CREATE INDEX analyses_article_idx ON analyses (article_id);

CREATE TABLE incidents (
  id             BIGSERIAL PRIMARY KEY,
  article_id     BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  analysis_id    BIGINT REFERENCES analyses(id) ON DELETE SET NULL,
  category       TEXT NOT NULL,
  headline_bn    TEXT,
  headline_en    TEXT,
  location_text  TEXT,
  place_id       TEXT,
  thana_id       TEXT,
  lat            DOUBLE PRECISION,
  lng            DOUBLE PRECISION,
  precision      TEXT,
  geocoded       BOOLEAN NOT NULL DEFAULT false,
  incident_date  DATE,
  event_date     DATE,
  time_of_day    TEXT,
  victims        INT NOT NULL DEFAULT 0,
  evidence       TEXT,
  evidence_ok    BOOLEAN NOT NULL DEFAULT false,
  -- shown on the map and in the API (evidence verified, analysis consistent)
  published      BOOLEAN NOT NULL DEFAULT false,
  duplicate_of   BIGINT REFERENCES incidents(id) ON DELETE SET NULL,
  classifier     TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX incidents_event_idx ON incidents (event_date);
CREATE INDEX incidents_group_idx ON incidents (category, place_id, event_date);

-- Collector runs (scraping only; classification is tracked per job).
CREATE TABLE runs (
  id           BIGSERIAL PRIMARY KEY,
  trigger      TEXT,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  status       TEXT NOT NULL DEFAULT 'running',
  discovered   INT NOT NULL DEFAULT 0,
  fetched      INT NOT NULL DEFAULT 0,
  queued       INT NOT NULL DEFAULT 0,
  errors       INT NOT NULL DEFAULT 0,
  message      TEXT
);

-- One row per scheduled slot (08:00 / 20:00 Asia/Dhaka), so a slot runs once.
CREATE TABLE schedule_slots (
  scheduled_for TIMESTAMPTZ PRIMARY KEY,
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  run_id        BIGINT REFERENCES runs(id) ON DELETE SET NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- "Collect now" requests from the dashboard or CLI, consumed by the collector.
CREATE TABLE run_requests (
  id           BIGSERIAL PRIMARY KEY,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source       TEXT,
  days_back    INT NOT NULL DEFAULT 1,
  status       TEXT NOT NULL DEFAULT 'pending',  -- pending | running | done | failed
  run_id       BIGINT REFERENCES runs(id) ON DELETE SET NULL
);

CREATE TABLE geocache (
  query       TEXT PRIMARY KEY,
  lat         DOUBLE PRECISION,
  lng         DOUBLE PRECISION,
  display     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Shared rate limiter lanes (e.g. Nominatim) across processes and containers.
CREATE TABLE rate_limits (
  name     TEXT PRIMARY KEY,
  last_at  TIMESTAMPTZ NOT NULL DEFAULT 'epoch'
);
INSERT INTO rate_limits (name) VALUES ('nominatim');

-- Liveness of long-running services, shown in the dashboard.
CREATE TABLE heartbeats (
  service    TEXT PRIMARY KEY,
  seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  detail     JSONB
);
