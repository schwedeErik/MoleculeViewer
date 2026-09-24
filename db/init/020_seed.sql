-- Small synthetic seed so the map renders immediately.
-- Generates ~1,000,000 points within a rough Europe-ish bbox.

INSERT INTO datasets (slug, name, embedding_method, embedding_dim)
VALUES ('demo-seed', 'Demo seed (1M synthetic)', 'maccs', 167)
ON CONFLICT (slug) DO NOTHING;

WITH inserted AS (
  INSERT INTO molecule_map (dataset_id, rank, geom)
  SELECT
    (SELECT id FROM datasets WHERE slug = 'demo-seed'),
    gs,
    ST_SetSRID(ST_MakePoint(
      -10 + random() * 40,
      35 + random() * 25
    ), 4326)
  FROM generate_series(1, 1000000) AS gs
  RETURNING id, rank
)
INSERT INTO molecule_details (molecule_id, name, embedding)
SELECT
  inserted.id,
  'mol_' || inserted.rank::text,
  NULL
FROM inserted;

ANALYZE molecule_map;
ANALYZE molecule_details;
