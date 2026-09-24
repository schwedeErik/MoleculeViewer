-- Map table: skinny hot path used by MVT tiles / bounds.
-- Details table: SMILES + embeddings, joined only when needed.
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

CREATE INDEX IF NOT EXISTS molecule_map_dataset_id_idx ON molecule_map (dataset_id);
CREATE UNIQUE INDEX IF NOT EXISTS molecule_map_dataset_rank_uidx ON molecule_map (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecule_map_dataset_rank_idx ON molecule_map (dataset_id, rank);
CREATE INDEX IF NOT EXISTS molecule_map_geom_gist ON molecule_map USING GIST (geom);

CREATE INDEX IF NOT EXISTS molecule_details_embedding_ivfflat
ON molecule_details USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
