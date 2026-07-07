-- Multi-dataset support for existing databases created before datasets table existed.

CREATE TABLE IF NOT EXISTS datasets (
  id SERIAL PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  embedding_method TEXT NOT NULL DEFAULT 'maccs',
  embedding_dim INTEGER NOT NULL DEFAULT 167,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Create a fallback dataset only when backfilling legacy rows (not on every re-run).
INSERT INTO datasets (slug, name, embedding_method, embedding_dim)
SELECT 'default', 'Default dataset', 'maccs', 167
WHERE EXISTS (SELECT 1 FROM molecules WHERE dataset_id IS NULL)
ON CONFLICT (slug) DO NOTHING;

ALTER TABLE molecules ADD COLUMN IF NOT EXISTS dataset_id INTEGER REFERENCES datasets (id) ON DELETE CASCADE;

UPDATE molecules
SET dataset_id = (SELECT id FROM datasets WHERE slug = 'default')
WHERE dataset_id IS NULL;

ALTER TABLE molecules ALTER COLUMN dataset_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS molecules_dataset_id_idx ON molecules (dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS molecules_dataset_rank_uidx ON molecules (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecules_dataset_rank_idx ON molecules (dataset_id, rank);
