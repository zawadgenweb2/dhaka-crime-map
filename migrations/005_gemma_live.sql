-- Gemma-only live data: frozen evaluation reference, data revision, current analysis version,
-- exact-spot geocoding after publication, and per-batch progress.

-- 1. Frozen offline-evaluation reference (the prototype-phase labels, historical backend 'claude').
--    Used only by `python -m app compare`; no API endpoint reads these tables. Articles with zero
--    incidents are part of the reference too (they test "not a Dhaka crime report").
CREATE TABLE eval_reference_articles (
  article_id  BIGINT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
  source      TEXT NOT NULL,
  frozen_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE eval_reference_incidents (
  id                 BIGSERIAL PRIMARY KEY,
  article_id         BIGINT NOT NULL REFERENCES eval_reference_articles(article_id) ON DELETE CASCADE,
  source_incident_id BIGINT,           -- no FK: the live incident row is deleted later
  category           TEXT NOT NULL,
  place_id           TEXT,
  thana_id           TEXT,
  incident_date      DATE,
  time_of_day        TEXT
);
INSERT INTO eval_reference_articles (article_id, source)
  SELECT DISTINCT x.article_id, 'claude-prototype' FROM analyses x
  JOIN articles a ON a.id = x.article_id AND a.status = 'classified'
  WHERE x.backend = 'claude';
INSERT INTO eval_reference_incidents (article_id, source_incident_id, category, place_id, thana_id, incident_date, time_of_day)
  SELECT i.article_id, i.id, i.category, i.place_id, i.thana_id, i.incident_date, i.time_of_day
  FROM incidents i JOIN eval_reference_articles r ON r.article_id = i.article_id
  WHERE i.classifier LIKE 'claude%' AND (i.published OR i.review_status = 'approved') AND i.review_status <> 'rejected'
  ORDER BY i.id;

-- 2. One counter for "the data the map shows changed". Bumped in the same transaction as every such change.
CREATE TABLE data_revision (
  id         BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
  rev        BIGINT NOT NULL DEFAULT 1,
  changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO data_revision DEFAULT VALUES;

-- 3. The analysis version that is current for an article; an older job can never overwrite newer output.
ALTER TABLE articles ADD COLUMN analysis_version INT NOT NULL DEFAULT 1;
UPDATE articles a SET analysis_version = v.max_v
  FROM (SELECT article_id, max(analysis_version) max_v FROM jobs GROUP BY article_id) v WHERE v.article_id = a.id;

-- 4. Exact-spot geocoding runs after an incident is published (Nominatim allows 1 request / 15 s).
--    none: nothing to look up · todo: waiting · done: exact point set · miss: no result · far: result too far away
ALTER TABLE incidents ADD COLUMN geocode_query TEXT;
ALTER TABLE incidents ADD COLUMN geocode_state TEXT NOT NULL DEFAULT 'none';
CREATE INDEX incidents_geocode_todo_idx ON incidents (id) WHERE geocode_state = 'todo';

-- 5. Batch progress: which collection run queued a job; how big a manual run may be.
ALTER TABLE jobs ADD COLUMN run_id BIGINT REFERENCES runs(id) ON DELETE SET NULL;
CREATE INDEX jobs_run_idx ON jobs (run_id);
ALTER TABLE run_requests ADD COLUMN max_articles INT CHECK (max_articles BETWEEN 1 AND 5000);
ALTER TABLE runs ADD COLUMN days_back INT;
ALTER TABLE runs ADD COLUMN candidates INT;   -- matching links found (before the per-run cap)
