-- NOTE: the `embedding` dimension must match the embedding method used by the
-- pipeline: MACCS = 167 (default), Morgan = 2048, ChemBERTa = 768. Change the
-- vector(...) size below if you switch methods.
CREATE TABLE IF NOT EXISTS molecules (
  id BIGSERIAL PRIMARY KEY,
  smiles TEXT,
  name TEXT,
  rank INTEGER NOT NULL DEFAULT 1,
  geom geometry(Point, 4326) NOT NULL,
  embedding vector(167)
);

CREATE INDEX IF NOT EXISTS molecules_geom_gist ON molecules USING GIST (geom);
CREATE INDEX IF NOT EXISTS molecules_rank_idx ON molecules (rank);

-- If you will do similarity search:
-- Note: choose the operator class based on distance metric you want (L2/cosine/etc).
-- For cosine distance, you typically store normalized vectors and use vector_cosine_ops.
CREATE INDEX IF NOT EXISTS molecules_embedding_ivfflat
ON molecules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

