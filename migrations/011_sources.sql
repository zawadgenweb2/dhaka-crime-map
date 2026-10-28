-- Several newspapers: each article remembers its paper; coverage is per paper and day.
ALTER TABLE articles ADD COLUMN source TEXT NOT NULL DEFAULT 'prothomalo';
CREATE INDEX articles_source_idx ON articles (source, published_at);

ALTER TABLE coverage_days ADD COLUMN source TEXT NOT NULL DEFAULT 'prothomalo';
ALTER TABLE coverage_days DROP CONSTRAINT coverage_days_pkey;
ALTER TABLE coverage_days ADD PRIMARY KEY (source, day);
