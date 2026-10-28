-- A paper that refused us (403, challenge, repeated 429) is left alone until not_before, across runs and restarts.
CREATE TABLE source_state (
  source      TEXT PRIMARY KEY,
  not_before  TIMESTAMPTZ,
  reason      TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
