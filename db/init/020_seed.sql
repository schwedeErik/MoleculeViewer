-- Small synthetic seed so the map renders immediately.
-- Generates ~1,000,000 points within a rough Europe-ish bbox.

INSERT INTO datasets (slug, name, embedding_method, embedding_dim)
VALUES ('demo-seed', 'Demo seed (1M synthetic)', 'maccs', 167)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO molecules (dataset_id, name, rank, geom, embedding)
SELECT
  (SELECT id FROM datasets WHERE slug = 'demo-seed'),
  'mol_' || gs::text,
  gs,
  ST_SetSRID(ST_MakePoint(
    -10 + random() * 40,
    35 + random() * 25
  ), 4326),
  NULL
FROM generate_series(1, 1000000) AS gs;

ANALYZE molecules;
