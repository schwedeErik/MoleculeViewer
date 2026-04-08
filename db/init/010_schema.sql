CREATE TABLE IF NOT EXISTS molecules (
  id BIGSERIAL PRIMARY KEY,
  name TEXT,
  rank SMALLINT NOT NULL DEFAULT 1,
  geom geometry(Point, 4326) NOT NULL,
  embedding vector(384)
);

CREATE INDEX IF NOT EXISTS molecules_geom_gist ON molecules USING GIST (geom);
CREATE INDEX IF NOT EXISTS molecules_rank_idx ON molecules (rank);

-- If you will do similarity search:
-- Note: choose the operator class based on distance metric you want (L2/cosine/etc).
-- For cosine distance, you typically store normalized vectors and use vector_cosine_ops.
CREATE INDEX IF NOT EXISTS molecules_embedding_ivfflat
ON molecules USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

