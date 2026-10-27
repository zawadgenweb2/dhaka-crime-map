-- Fresh news before history: 0 = scheduled runs and small "collect now"; 2 = backfills and reprocessing.
ALTER TABLE jobs ADD COLUMN priority SMALLINT NOT NULL DEFAULT 1;
UPDATE jobs j SET priority = CASE WHEN r.trigger = 'schedule' OR (r.trigger = 'manual' AND coalesce(r.days_back, 1) <= 1) THEN 0 ELSE 2 END
FROM runs r WHERE r.id = j.run_id AND j.state = 'queued';
CREATE INDEX jobs_priority_claim_idx ON jobs (priority, available_at, id) WHERE state = 'queued';
