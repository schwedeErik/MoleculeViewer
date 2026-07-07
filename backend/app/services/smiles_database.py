import csv
from pathlib import Path

import numpy as np

INSERT_SQL = """
INSERT INTO molecules (smiles, rank, geom, embedding)
VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s::vector)
"""

CSV_HEADER = ["smiles", "rank", "lng", "lat", "embedding"]


def _psycopg_url(database_url: str) -> str:
    """Convert a SQLAlchemy-style URL to one psycopg accepts.

    ``settings.database_url`` uses the ``postgresql+psycopg://`` dialect prefix
    that SQLAlchemy expects; psycopg itself wants a plain ``postgresql://`` URL.
    """
    return database_url.replace("postgresql+psycopg://", "postgresql://")


def _vector_literal(vec: np.ndarray) -> str:
    """Format a 1D array as a pgvector text literal, e.g. ``[1,2,3]``."""
    return "[" + ",".join(repr(float(v)) for v in vec) + "]"


def _validate_rows(
    smiles: np.ndarray,
    embeddings: np.ndarray,
    projection: np.ndarray,
    ranks: np.ndarray,
) -> int:
    """Validate that all arrays are row-aligned and projection is 2D. Returns n."""
    n = len(smiles)
    if not (n == embeddings.shape[0] == projection.shape[0] == ranks.shape[0]):
        raise ValueError(
            "Row counts must match: "
            f"smiles={n}, embeddings={embeddings.shape[0]}, "
            f"projection={projection.shape[0]}, ranks={ranks.shape[0]}"
        )
    if n and projection.shape[1] != 2:
        raise ValueError(f"projection must have 2 columns, got {projection.shape[1]}")
    return n


def export_molecules(
    *,
    smiles: np.ndarray,
    embeddings: np.ndarray,
    projection: np.ndarray,
    ranks: np.ndarray,
    csv_path: str,
    sql_path: str | None = None,
    table: str = "molecules",
) -> int:
    """Write the pipeline output to a CSV that PostgreSQL can bulk-load.

    Designed for HPC/Slurm runs where the compute node cannot reach the database
    directly: the job writes files, and you load them into Postgres afterwards.

    Produces:
      * ``csv_path``: columns ``smiles, rank, lng, lat, embedding`` with a header.
        ``lng``/``lat`` are the 2D UMAP coordinates; ``embedding`` is a pgvector
        text literal (``[v1,v2,...]``).
      * ``sql_path`` (optional, defaults to ``<csv stem>_load.sql``): a loader
        script for ``psql`` that COPYs the CSV into a staging table and inserts
        into ``table``, building ``geom`` and casting ``embedding`` to ``vector``.
        Run it with: ``psql "$DATABASE_URL" -f <sql_path>``.

    Returns:
        Number of rows written.
    """
    n = _validate_rows(smiles, embeddings, projection, ranks)

    csv_file = Path(csv_path)
    csv_file.parent.mkdir(parents=True, exist_ok=True)

    with csv_file.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        for i in range(n):
            writer.writerow(
                [
                    str(smiles[i]),
                    int(ranks[i]),
                    float(projection[i, 0]),
                    float(projection[i, 1]),
                    _vector_literal(embeddings[i]),
                ]
            )

    sql_file = Path(sql_path) if sql_path else csv_file.with_name(csv_file.stem + "_load.sql")
    sql_file.write_text(_loader_sql(csv_file.resolve(), table))

    return n


def _loader_sql(abs_csv_path: Path, table: str) -> str:
    """Build a psql loader script for the exported CSV.

    Uses a temp staging table so the geometry and pgvector conversions are
    explicit and unambiguous. ``\\copy`` runs client-side, so the CSV is read
    from wherever you invoke psql (no server-side file access needed).
    """
    return f"""\
-- Load exported molecules into the `{table}` table.
-- Usage: psql "$DATABASE_URL" -f {abs_csv_path.with_name(abs_csv_path.stem + '_load.sql').name}
BEGIN;

CREATE TEMP TABLE molecules_staging (
  smiles    text,
  rank      integer,
  lng       double precision,
  lat       double precision,
  embedding text
) ON COMMIT DROP;

\\copy molecules_staging (smiles, rank, lng, lat, embedding) FROM '{abs_csv_path}' WITH (FORMAT csv, HEADER true)

INSERT INTO {table} (smiles, rank, geom, embedding)
SELECT smiles, rank, ST_SetSRID(ST_MakePoint(lng, lat), 4326), embedding::vector
FROM molecules_staging;

COMMIT;
"""


def store_molecules(
    *,
    smiles: np.ndarray,
    embeddings: np.ndarray,
    projection: np.ndarray,
    ranks: np.ndarray,
    database_url: str | None = None,
    truncate: bool = False,
    batch_size: int = 10_000,
) -> int:
    """Persist molecules and their derived data to the ``molecules`` table.

    Each row stores the SMILES string, its representativeness rank, the 2D UMAP
    projection (as a PostGIS point in ``geom``), and the embedding vector.

    Args:
        smiles: Object/str array of shape ``(n,)``.
        embeddings: Float array of shape ``(n, dim)``; ``dim`` must match the
            ``embedding vector(dim)`` column in the schema.
        projection: Float array of shape ``(n, 2)`` of UMAP coordinates,
            interpreted as ``(x -> longitude, y -> latitude)``.
        ranks: Integer array of shape ``(n,)``.
        database_url: Override for ``settings.database_url``.
        truncate: If True, empty the table before inserting.
        batch_size: Rows per ``executemany`` batch.

    Returns:
        Number of rows inserted.
    """
    import psycopg

    from ..config import settings

    n = _validate_rows(smiles, embeddings, projection, ranks)
    if n == 0:
        return 0

    url = _psycopg_url(database_url or settings.database_url)

    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            if truncate:
                cur.execute("TRUNCATE TABLE molecules RESTART IDENTITY;")

            batch: list[tuple] = []
            for i in range(n):
                batch.append(
                    (
                        str(smiles[i]),
                        int(ranks[i]),
                        float(projection[i, 0]),
                        float(projection[i, 1]),
                        _vector_literal(embeddings[i]),
                    )
                )
                if len(batch) >= batch_size:
                    cur.executemany(INSERT_SQL, batch)
                    batch.clear()

            if batch:
                cur.executemany(INSERT_SQL, batch)

        conn.commit()

    return n
