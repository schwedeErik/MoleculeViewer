from __future__ import annotations

from fastapi import FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from .datasets import delete_dataset, list_datasets, resolve_dataset_id, validate_slug
from .db import engine
from .molecules_pb2 import Points
from .services import deepscatter_tiles, structure_svg
from .services.smiles_database import import_dataset_from_csv
from .services.tile_cache import available_lod_levels, pmtiles_path, read_manifest, tile_cache_root
from .services.rank_lod import clamp_lod_level


app = FastAPI(title="Molecule Map API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/datasets")
def datasets() -> list[dict]:
    with engine.connect() as conn:
        rows = list_datasets(conn)
    for row in rows:
        row["precomputed_lods"] = available_lod_levels(row["slug"])
        row["deepscatter_orders"] = deepscatter_tiles.available_orders(row["slug"])
    return rows


@app.get("/deepscatter/{slug}/{order}/{file_path:path}")
def deepscatter_tile(slug: str, order: str, file_path: str):
    """Serve a file from a quadfeather / Deepscatter tile tree."""
    validate_slug(slug)
    if order not in {"ranked", "shuffled"}:
        raise HTTPException(status_code=400, detail="order must be ranked or shuffled")
    path = deepscatter_tiles.resolve_tile_file(slug, order, file_path)
    if path is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Deepscatter tile not found: {slug}/{order}/{file_path}. "
                f"Build with: python -m scripts.build_deepscatter_tiles --dataset {slug}"
                + (" --order shuffled" if order == "shuffled" else "")
            ),
        )
    media = "application/json" if path.suffix == ".json" else "application/octet-stream"
    if path.suffix == ".feather":
        media = "application/vnd.apache.arrow.file"
    return FileResponse(
        path,
        media_type=media,
        headers={
            # Tiles change when rebuilt; avoid sticky browser caches of bad feathers.
            "Cache-Control": "no-cache, must-revalidate",
        },
    )


@app.head("/deepscatter/{slug}/{order}/{file_path:path}")
def deepscatter_tile_head(slug: str, order: str, file_path: str):
    """HEAD support for tile probes (some clients check existence first)."""
    return deepscatter_tile(slug, order, file_path)


@app.get("/molecules/{molecule_id}")
def molecule_detail(
    molecule_id: int,
    dataset: str = Query(..., min_length=1),
) -> dict:
    """Return map + detail fields for a clicked molecule."""
    sql = text(
        """
        SELECT
          m.id,
          m.rank,
          ST_X(m.geom) AS lng,
          ST_Y(m.geom) AS lat,
          d.smiles,
          d.name
        FROM molecule_map m
        LEFT JOIN molecule_details d ON d.molecule_id = m.id
        WHERE m.id = :molecule_id
          AND m.dataset_id = :dataset_id
        """
    )
    with engine.connect() as conn:
        dataset_id = resolve_dataset_id(conn, dataset)
        row = conn.execute(
            sql, {"molecule_id": molecule_id, "dataset_id": dataset_id}
        ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Molecule not found: {molecule_id}")
    return dict(row)


@app.get("/molecules/{molecule_id}/structure.svg")
def molecule_structure_svg(
    molecule_id: int,
    dataset: str = Query(..., min_length=1),
    width: int = Query(240, ge=structure_svg.MIN_SIZE, le=structure_svg.MAX_SIZE),
    height: int = Query(180, ge=structure_svg.MIN_SIZE, le=structure_svg.MAX_SIZE),
) -> Response:
    """Return a 2D structure depiction (SVG) of one molecule, drawn with RDKit."""
    sql = text(
        """
        SELECT d.smiles
        FROM molecule_map m
        JOIN molecule_details d ON d.molecule_id = m.id
        WHERE m.id = :molecule_id
          AND m.dataset_id = :dataset_id
        """
    )
    with engine.connect() as conn:
        dataset_id = resolve_dataset_id(conn, dataset)
        smiles = conn.execute(
            sql, {"molecule_id": molecule_id, "dataset_id": dataset_id}
        ).scalar_one_or_none()
    if not smiles:
        raise HTTPException(status_code=404, detail=f"No SMILES for molecule: {molecule_id}")
    svg = structure_svg.smiles_to_svg(smiles, width, height)
    if svg is None:
        raise HTTPException(status_code=422, detail=f"RDKit could not parse SMILES of {molecule_id}")
    return Response(
        content=svg,
        media_type="image/svg+xml",
        # A molecule's structure never changes, so the browser may cache it.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/datasets/{slug}/pmtiles/{lod_level}.pmtiles")
def dataset_pmtiles(slug: str, lod_level: int):
    """Serve a precomputed PMTiles archive for one LOD step (supports Range requests)."""
    validate_slug(slug)
    level = clamp_lod_level(lod_level)
    path = pmtiles_path(slug, level)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"No precomputed tiles for dataset={slug} lod={level}. "
            f"Build with: python -m scripts.build_precomputed_tiles --dataset {slug}",
        )
    return FileResponse(
        path,
        media_type="application/vnd.pmtiles",
        filename=f"{slug}_lod_{level}.pmtiles",
        headers={"Cache-Control": "public, max-age=86400", "Accept-Ranges": "bytes"},
    )


@app.get("/datasets/{slug}/tiles-manifest")
def dataset_tiles_manifest(slug: str) -> dict:
    validate_slug(slug)
    with engine.connect() as conn:
        resolve_dataset_id(conn, slug)
    manifest = read_manifest(slug)
    lods = available_lod_levels(slug)
    if manifest is None and not lods:
        raise HTTPException(status_code=404, detail=f"No precomputed tiles for {slug}")
    return manifest or {
        "slug": slug,
        "lod_levels": lods,
        "tile_cache_dir": str(tile_cache_root() / slug),
    }


@app.post("/datasets")
async def create_dataset(
    file: UploadFile = File(...),
    slug: str = Form(...),
    name: str = Form(...),
    embedding_method: str = Form("maccs"),
) -> dict:
    """Import a pipeline CSV (smiles, rank, lng, lat, embedding) as a new dataset."""
    validate_slug(slug.strip())
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")

    try:
        import io

        text_stream = io.TextIOWrapper(file.file, encoding="utf-8", newline="")
        count = import_dataset_from_csv(
            text_stream,
            slug=slug.strip(),
            name=name.strip(),
            embedding_method=embedding_method.strip() or "maccs",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}") from exc

    with engine.connect() as conn:
        rows = list_datasets(conn)
    created = next((row for row in rows if row["slug"] == slug.strip()), None)
    if not created:
        raise HTTPException(status_code=500, detail="Dataset imported but not found")
    return created


@app.delete("/datasets/{slug}")
def remove_dataset(slug: str) -> dict:
    """Delete a dataset and all of its molecules."""
    with engine.connect() as conn:
        delete_dataset(conn, slug)
    return {"ok": True, "slug": slug}


@app.get("/bounds")
def bounds(dataset: str = Query(..., min_length=1)) -> dict:
    sql = text(
        """
        SELECT
          MIN(ST_X(geom)) AS min_lng,
          MAX(ST_X(geom)) AS max_lng,
          MIN(ST_Y(geom)) AS min_lat,
          MAX(ST_Y(geom)) AS max_lat,
          MIN(rank) AS min_rank,
          MAX(rank) AS max_rank,
          COUNT(*)::int AS count
        FROM molecule_map
        WHERE dataset_id = :dataset_id
        """
    )
    with engine.connect() as conn:
        dataset_id = resolve_dataset_id(conn, dataset)
        row = conn.execute(sql, {"dataset_id": dataset_id}).mappings().one()
    result = dict(row)
    if not result["count"]:
        raise HTTPException(status_code=404, detail=f"Dataset has no molecules: {dataset}")
    return result


@app.get("/tiles/{z}/{x}/{y}.mvt")
def tile(
    z: int,
    x: int,
    y: int,
    dataset: str = Query(..., min_length=1),
    rank_max: int = Query(10_000, ge=1, le=10_000_000),
) -> Response:
    """Return every molecule with ``1 <= rank <= rank_max`` inside a WebMercator tile."""
    sql = text(
        """
        WITH
          bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS b3857
          ),
          bounds4326 AS (
            SELECT ST_Transform(b3857, 4326) AS b4326, b3857 FROM bounds
          ),
          spatial AS MATERIALIZED (
            SELECT m.id, m.rank, m.geom
            FROM molecule_map m, bounds4326 b
            WHERE m.dataset_id = :dataset_id
              AND m.geom && b.b4326
              AND m.rank <= :rank_max
          ),
          mvtgeom AS (
            SELECT
              s.id,
              s.rank,
              ST_AsMVTGeom(
                ST_Transform(s.geom, 3857),
                b.b3857,
                4096,
                256,
                true
              ) AS geom
            FROM spatial s, bounds4326 b
          )
        SELECT COALESCE(ST_AsMVT(mvtgeom, 'molecules', 4096, 'geom'), ''::bytea) AS tile
        FROM mvtgeom;
        """
    )
    with engine.connect() as conn:
        dataset_id = resolve_dataset_id(conn, dataset)
        tile_bytes = conn.execute(
            sql,
            {"z": z, "x": x, "y": y, "rank_max": rank_max, "dataset_id": dataset_id},
        ).scalar_one()
    return Response(
        content=bytes(tile_bytes),
        media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": "public, max-age=60"},
    )


@app.get("/points.pb")
def points(
    minLng: float,
    minLat: float,
    maxLng: float,
    maxLat: float,
    dataset: str = Query(..., min_length=1),
    limit: int = Query(1000, ge=1, le=200_000),
) -> Response:
    """Return the top-``limit`` molecules by rank inside the viewport bbox."""
    sql = text(
        """
        SELECT
          id,
          rank,
          ST_X(geom) AS lng,
          ST_Y(geom) AS lat
        FROM molecule_map
        WHERE dataset_id = :dataset_id
          AND geom && ST_MakeEnvelope(:minLng, :minLat, :maxLng, :maxLat, 4326)
        ORDER BY rank ASC, id ASC
        LIMIT :limit;
        """
    )
    out = Points()
    with engine.connect() as conn:
        dataset_id = resolve_dataset_id(conn, dataset)
        for row in conn.execute(
            sql,
            {
                "dataset_id": dataset_id,
                "minLng": minLng,
                "minLat": minLat,
                "maxLng": maxLng,
                "maxLat": maxLat,
                "limit": limit,
            },
        ):
            p = out.points.add()
            p.id = int(row.id)
            p.lng = float(row.lng)
            p.lat = float(row.lat)
            p.rank = int(row.rank)

    return Response(
        content=out.SerializeToString(),
        media_type="application/x-protobuf",
        headers={"Cache-Control": "no-store"},
    )
