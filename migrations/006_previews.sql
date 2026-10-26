-- "Try an article" (POST /api/classify): the API queues pasted text, the classifier (the only service that talks
-- to the model) answers it ahead of normal jobs, and nothing is written to articles or incidents.
CREATE TABLE previews (
  id           BIGSERIAL PRIMARY KEY,
  input        JSONB NOT NULL,
  status       TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | failed
  result       JSONB,
  error        TEXT,
  requested_by TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ
);
CREATE INDEX previews_queued_idx ON previews (id) WHERE status = 'queued';
