-- Coverage by article, not by count: which URLs each day's sitemap listed and whether they passed stage 1.
-- A URL once seen as a candidate stays a candidate (a later run with less metadata cannot shrink a day).
-- Day status is then read from the articles themselves: missing / set aside / queued / failed / examined.
CREATE TABLE coverage_urls (
  day        DATE NOT NULL,
  url        TEXT NOT NULL,
  candidate  BOOLEAN NOT NULL,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (day, url)
);
CREATE INDEX coverage_urls_url_idx ON coverage_urls (url);
