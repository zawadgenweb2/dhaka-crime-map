-- Which publication days have actually been collected, so a period on the map can say how complete it is.
-- One row per Asia/Dhaka day, written by every collection run that read that day's daily sitemap.
-- A day's status is computed when read: no row = not collected; missing > 0 = partly collected;
-- queued Gemma jobs for that day's articles = processing; otherwise complete.
CREATE TABLE coverage_days (
  day         DATE PRIMARY KEY,
  links       INT NOT NULL,          -- articles the publisher listed that day
  candidates  INT NOT NULL,          -- passed stage 1 of the pre-filter
  missing     INT NOT NULL,          -- candidates not downloaded yet (run cap, errors, interruption)
  run_id      BIGINT REFERENCES runs(id) ON DELETE SET NULL,
  checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
