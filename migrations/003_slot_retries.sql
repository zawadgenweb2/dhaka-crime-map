-- A scheduled collection that fails (e.g. robots.txt unreachable for a moment) is retried a few times.
ALTER TABLE schedule_slots ADD COLUMN attempts INT NOT NULL DEFAULT 0;
ALTER TABLE schedule_slots ADD COLUMN next_try_at TIMESTAMPTZ;
