-- All 64 districts of Bangladesh (29 Oct 2026). The list lives in data/places.json (from the Bangladesh National
-- Portal) and the app validates it, so the six-value check from 010 goes. A division is derived from the district.
ALTER TABLE incidents DROP CONSTRAINT IF EXISTS incidents_district_id_check;
ALTER TABLE incidents ADD CONSTRAINT incidents_district_id_slug CHECK (district_id ~ '^[a-z][a-z_]*$');
