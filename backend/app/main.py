from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import text

from .datasets import delete_dataset, list_datasets, resolve_dataset_id, validate_slug
from .db import engine
from .services import deepscatter_tiles, structure_svg
from .services import deepscatter_catalog, deepscatter_import, import_jobs
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
    by_slug = {row["slug"]: row for row in rows}
    for row in rows:
        row["precomputed_lods"] = available_lod_levels(row["slug"])
        row["deepscatter_orders"] = deepscatter_tiles.available_orders(row["slug"])
        row.setdefault("deepscatter_only", False)

    # Deepscatter-only uploads (no Postgres molecule rows).
    for entry in deepscatter_catalog.list_entries():
        slug = entry["slug"]
        if slug in by_slug:
            by_slug[slug]["deepscatter_only"] = True
            if entry.get("molecule_count"):
                by_slug[slug]["molecule_count"] = entry["molecule_count"]
            by_slug[slug]["deepscatter_orders"] = deepscatter_tiles.available_orders(slug)
            continue
        entry = dict(entry)
        entry["precomputed_lods"] = entry.get("precomputed_lods") or []
        entry["deepscatter_orders"] = deepscatter_tiles.available_orders(slug)
        entry["deepscatter_only"] = True
        rows.append(entry)
        by_slug[slug] = entry

    rows.sort(key=lambda r: (r.get("name") or r.get("slug") or "").lower())
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


def _run_deepscatter_job(
    job_id: str,
    csv_path,
    *,
    slug: str,
    name: str,
    embedding_method: str,
) -> None:
    progress_cb = import_jobs.make_progress_cb(job_id)
    try:
        import_jobs.update_job(job_id, status="running", phase="export", progress=5, message="Starting…")
        created = deepscatter_import.build_deepscatter_from_csv(
            csv_path,
            slug=slug,
            name=name,
            embedding_method=embedding_method,
            include_smiles=True,
            build_shuffled=False,
            progress_cb=progress_cb,
        )
        created["precomputed_lods"] = []
        created["deepscatter_orders"] = deepscatter_tiles.available_orders(slug)
        created["deepscatter_only"] = True
        import_jobs.update_job(
            job_id,
            status="done",
            phase="done",
            progress=100,
            message="Done",
            dataset=created,
        )
    except Exception as exc:
        import_jobs.update_job(
            job_id,
            status="error",
            phase="error",
            progress=100,
            message=str(exc),
            error=str(exc),
        )


def _run_full_import_job(
    job_id: str,
    csv_path,
    *,
    slug: str,
    name: str,
    embedding_method: str,
) -> None:
    try:
        import_jobs.update_job(
            job_id,
            status="running",
            phase="import",
            progress=15,
            message="Loading CSV into Postgres…",
        )
        with csv_path.open(newline="", encoding="utf-8") as f:
            import_dataset_from_csv(
                f,
                slug=slug,
                name=name,
                embedding_method=embedding_method,
            )
        import_jobs.update_job(
            job_id,
            status="running",
            phase="finalize",
            progress=90,
            message="Finalizing…",
        )
        with engine.connect() as conn:
            rows = list_datasets(conn)
        created = next((row for row in rows if row["slug"] == slug), None)
        if not created:
            raise RuntimeError("Dataset imported but not found")
        created["precomputed_lods"] = available_lod_levels(slug)
        created["deepscatter_orders"] = deepscatter_tiles.available_orders(slug)
        created["deepscatter_only"] = False
        import_jobs.update_job(
            job_id,
            status="done",
            phase="done",
            progress=100,
            message="Done",
            dataset=created,
        )
    except Exception as exc:
        import_jobs.update_job(
            job_id,
            status="error",
            phase="error",
            progress=100,
            message=str(exc),
            error=str(exc),
        )


@app.get("/datasets/jobs/{job_id}")
def dataset_job_status(job_id: str) -> dict:
    job = import_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown import job")
    return job


@app.post("/datasets")
async def create_dataset(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    slug: str = Form(...),
    name: str = Form(...),
    embedding_method: str = Form("maccs"),
    # ``deepscatter`` = tiles only (skip Postgres / deck.gl). ``full`` = legacy DB import.
    renderer: str = Form("deepscatter"),
) -> dict:
    """Start a dataset import job.

    Returns a ``job_id`` immediately after the CSV is saved. Poll
    ``GET /datasets/jobs/{job_id}`` for progress until ``status`` is ``done`` or ``error``.
    """
    validate_slug(slug.strip())
    if not name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload a .csv file")
    mode = (renderer or "deepscatter").strip().lower()
    if mode not in {"deepscatter", "full"}:
        raise HTTPException(status_code=400, detail="renderer must be 'deepscatter' or 'full'")

    slug_s = slug.strip()
    name_s = name.strip()
    method = embedding_method.strip() or "maccs"

    try:
        csv_path = deepscatter_import.save_upload(slug_s, file)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc

    job_id = import_jobs.create_job(slug=slug_s, name=name_s, renderer=mode)
    import_jobs.update_job(
        job_id,
        status="running",
        phase="upload",
        progress=8,
        message="CSV saved — starting import…",
    )

    if mode == "deepscatter":
        background_tasks.add_task(
            _run_deepscatter_job,
            job_id,
            csv_path,
            slug=slug_s,
            name=name_s,
            embedding_method=method,
        )
    else:
        background_tasks.add_task(
            _run_full_import_job,
            job_id,
            csv_path,
            slug=slug_s,
            name=name_s,
            embedding_method=method,
        )

    return {
        "job_id": job_id,
        "status": "running",
        "slug": slug_s,
        "name": name_s,
        "renderer": mode,
        "progress": 8,
        "message": "CSV saved — starting import…",
    }


@app.delete("/datasets/{slug}")
def remove_dataset(slug: str) -> dict:
    """Delete a dataset (Postgres rows and/or Deepscatter-only tiles)."""
    validate_slug(slug)
    deepscatter_import.delete_deepscatter_dataset(slug)
    try:
        with engine.connect() as conn:
            delete_dataset(conn, slug)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    return {"ok": True, "slug": slug}


@app.get("/bounds")
def bounds(dataset: str = Query(..., min_length=1)) -> dict:
    # Deepscatter-only datasets: bounds live in the tile manifest.
    manifest = deepscatter_tiles.read_manifest(dataset, "ranked") or deepscatter_tiles.read_manifest(
        dataset, "shuffled"
    )
    if manifest and manifest.get("bounds"):
        b = manifest["bounds"]
        return {
            "min_lng": b["min_x"],
            "max_lng": b["max_x"],
            "min_lat": b["min_y"],
            "max_lat": b["max_y"],
            "min_rank": 1,
            "max_rank": manifest.get("max_rank") or manifest.get("count") or 1,
            "count": manifest.get("count") or 0,
        }

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
