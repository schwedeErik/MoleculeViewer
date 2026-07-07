-- NOTE: the `embedding` dimension must match the embedding method used by the
-- pipeline: MACCS = 167 (default), Morgan = 2048, ChemBERTa = 768.

CREATE TABLE IF NOT EXISTS datasets (
  id SERIAL PRIMARY KEY,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  embedding_method TEXT NOT NULL DEFAULT 'maccs',
  embedding_dim INTEGER NOT NULL DEFAULT 167,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS molecules (
  id BIGSERIAL PRIMARY KEY,
  dataset_id INTEGER NOT NULL REFERENCES datasets (id) ON DELETE CASCADE,
  smiles TEXT,
  name TEXT,
  rank INTEGER NOT NULL DEFAULT 1,
  geom geometry(Point, 4326) NOT NULL,
  embedding vector(167)
);

CREATE INDEX IF NOT EXISTS molecules_dataset_id_idx ON molecules (dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS molecules_dataset_rank_uidx ON molecules (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecules_geom_gist ON molecules USING GIST (geom);
CREATE INDEX IF NOT EXISTS molecules_dataset_rank_idx ON molecules (dataset_id, rank);

CREATE INDEX IF NOT EXISTS molecules_embedding_ivfflat
ON molecules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
