-- Load exported molecules into the `molecules` table.
-- Usage: psql "$DATABASE_URL" -f molecules_load.sql
BEGIN;

CREATE TEMP TABLE molecules_staging (
  smiles    text,
  rank      integer,
  lng       double precision,
  lat       double precision,
  embedding text
) ON COMMIT DROP;

\copy molecules_staging (smiles, rank, lng, lat, embedding) FROM '/home/erik/Documents/CS_Master/Thesis/leitte/webAPP/data/molecules.csv' WITH (FORMAT csv, HEADER true)

INSERT INTO molecules (smiles, rank, geom, embedding)
SELECT smiles, rank, ST_SetSRID(ST_MakePoint(lng, lat), 4326), embedding::vector
FROM molecules_staging;

COMMIT;
