-- Split legacy `molecules` into skinny `molecule_map` + `molecule_details`.
-- Safe to re-run: only migrates when the old table still exists.

CREATE TABLE IF NOT EXISTS molecule_map (
  id BIGSERIAL PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
  rank INTEGER NOT NULL DEFAULT 1,
  geom geometry(Point, 4326) NOT NULL
);

CREATE TABLE IF NOT EXISTS molecule_details (
  molecule_id BIGINT PRIMARY KEY REFERENCES molecule_map (id) ON DELETE CASCADE,
  smiles TEXT,
  name TEXT,
  embedding vector(167)
);

DO $$
BEGIN
  IF to_regclass('public.molecules') IS NULL THEN
    RETURN;
  END IF;

  IF EXISTS (SELECT 1 FROM molecule_map LIMIT 1) THEN
    RAISE NOTICE 'molecule_map already has rows; dropping leftover molecules table if present';
    DROP TABLE IF EXISTS molecules CASCADE;
    RETURN;
  END IF;

  IF EXISTS (SELECT 1 FROM molecules LIMIT 1) THEN
    INSERT INTO molecule_map (id, dataset_id, rank, geom)
    SELECT id, dataset_id, rank, geom
    FROM molecules;

    INSERT INTO molecule_details (molecule_id, smiles, name, embedding)
    SELECT id, smiles, name, embedding
    FROM molecules;

    PERFORM setval(
      pg_get_serial_sequence('molecule_map', 'id'),
      COALESCE((SELECT MAX(id) FROM molecule_map), 1),
      true
    );
  END IF;

  DROP TABLE molecules CASCADE;
END $$;

CREATE INDEX IF NOT EXISTS molecule_map_dataset_id_idx ON molecule_map (dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS molecule_map_dataset_rank_uidx ON molecule_map (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecule_map_dataset_rank_idx ON molecule_map (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecule_map_geom_gist ON molecule_map USING GIST (geom);

CREATE INDEX IF NOT EXISTS molecule_details_embedding_ivfflat
ON molecule_details USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

ANALYZE molecule_map;
ANALYZE molecule_details;
