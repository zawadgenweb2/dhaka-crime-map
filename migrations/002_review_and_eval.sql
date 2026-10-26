-- Human review of incidents (precision first) and offline model evaluation.

-- auto      published automatically (checks passed, PUBLISH_MODE=auto)
-- pending   checks passed, waiting for a reviewer (PUBLISH_MODE=review)
-- failed    automatic checks failed (e.g. evidence not in article); a reviewer may still approve
-- approved / rejected   decided by a reviewer
ALTER TABLE incidents ADD COLUMN review_status TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE incidents ADD COLUMN reviewed_by TEXT;
ALTER TABLE incidents ADD COLUMN reviewed_at TIMESTAMPTZ;
UPDATE incidents SET review_status = 'failed' WHERE NOT published;
CREATE INDEX incidents_review_idx ON incidents (review_status);

-- Reviewer notes on whole articles (e.g. "model missed an incident").
CREATE TABLE article_reviews (
  id          BIGSERIAL PRIMARY KEY,
  article_id  BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  verdict     TEXT NOT NULL,          -- ok | missed_incident | not_crime | outside_dhaka | other
  note        TEXT,
  reviewed_by TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Offline evaluation runs: a candidate model's answers, never written into incidents.
CREATE TABLE eval_results (
  id            BIGSERIAL PRIMARY KEY,
  run_label     TEXT NOT NULL,
  article_id    BIGINT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
  backend       TEXT NOT NULL,
  model         TEXT,
  ok            BOOLEAN NOT NULL,
  error         TEXT,
  result        JSONB,
  latency_s     REAL,
  input_tokens  INT,
  output_tokens INT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX eval_results_run_idx ON eval_results (run_label);
