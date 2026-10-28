-- Lookups that grow with the data (council ops review, 27 Oct)
CREATE INDEX IF NOT EXISTS analyses_job_idx ON analyses (job_id, id);
CREATE INDEX IF NOT EXISTS incidents_article_idx ON incidents (article_id);
CREATE INDEX IF NOT EXISTS incidents_duplicate_of_idx ON incidents (duplicate_of) WHERE duplicate_of IS NOT NULL;
