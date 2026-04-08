-- Small synthetic seed so the map renders immediately.
-- Generates ~1,000,000 points within a rough Europe-ish bbox.

INSERT INTO molecules (name, rank, geom, embedding)
SELECT
  'mol_' || gs::text,
  (1 + (random() * 4)::int)::smallint,
  ST_SetSRID(ST_MakePoint(
    -10 + random() * 40,  -- lng
    35 + random() * 25    -- lat
  ), 4326),
  NULL
FROM generate_series(1, 1000000) AS gs;

ANALYZE molecules;

