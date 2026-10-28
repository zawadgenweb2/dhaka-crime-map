-- Six supported districts: every incident records the district of its place (NULL when it has no place).
ALTER TABLE incidents ADD COLUMN district_id TEXT
  CHECK (district_id IN ('dhaka', 'chattogram', 'sylhet', 'khulna', 'barishal', 'rangpur'));
-- Everything before this change was located with the Dhaka-only catalogue.
UPDATE incidents SET district_id = 'dhaka' WHERE place_id IS NOT NULL;
CREATE INDEX incidents_district_date_idx ON incidents (district_id, event_date);
