"""Precompute MVT PMTiles archives for each LOD aggressiveness step.

For every dataset LOD level (1–6), generates a ``lod_<n>.pmtiles`` file whose
tiles at zoom ``z`` contain molecules with ``rank <= rank_max(z, lod)`` — the
same filter the live ``/tiles`` endpoint uses.

Requires: PostGIS up, ``mercantile``, ``pmtiles``, ``tqdm``.

Run from ``backend/``:

    python -m scripts.build_precomputed_tiles --dataset zinc10k --max-zoom 10

Env:
    DATABASE_URL=postgresql://app:app@localhost:5432/molecules
    TILE_CACHE_DIR=../data/tile_cache   (optional)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import mercantile
import psycopg
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from tqdm import tqdm

# Allow ``python -m scripts.build_precomputed_tiles`` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.rank_lod import (  # noqa: E402
    LOD_STEP_COUNT,
    label_for_lod_level,
    rank_max_for_zoom,
)
from app.services.tile_cache import (  # noqa: E402
    available_lod_levels,
    dataset_cache_dir,
    pmtiles_path,
    write_manifest,
)


TILE_SQL = """
WITH
  bounds AS (
    SELECT ST_TileEnvelope(%(z)s, %(x)s, %(y)s) AS b3857
  ),
  bounds4326 AS (
    SELECT ST_Transform(b3857, 4326) AS b4326, b3857 FROM bounds
  ),
  spatial AS MATERIALIZED (
    SELECT m.id, m.rank, m.geom
    FROM molecule_map m, bounds4326 b
    WHERE m.dataset_id = %(dataset_id)s
      AND m.geom && b.b4326
      AND m.rank <= %(rank_max)s
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


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


# Web Mercator / mercantile valid geographic limits.
_MAX_LON = 180.0
_MAX_LAT = 85.05112878


def _clamp_bbox(west: float, south: float, east: float, north: float) -> tuple[float, float, float, float]:
    west = max(-_MAX_LON, min(_MAX_LON, west))
    east = max(-_MAX_LON, min(_MAX_LON, east))
    south = max(-_MAX_LAT, min(_MAX_LAT, south))
    north = max(-_MAX_LAT, min(_MAX_LAT, north))
    if west > east:
        west, east = east, west
    if south > north:
        south, north = north, south
    return west, south, east, north


def _dataset_meta(conn: psycopg.Connection, slug: str) -> dict:
    """Load dataset stats and a robust tiling bbox.

    Absolute min/max can be ruined by a few outlier embeddings (e.g. ChemBL
    stretches to ±4500). Tile coverage uses 0.5%–99.5% percentiles so we
    don't enumerate near-world-sized tile sets.
    """
    row = conn.execute(
        """
        SELECT
          d.id,
          d.slug,
          d.name,
          COUNT(m.id)::int AS count,
          COALESCE(MAX(m.rank), 0)::int AS max_rank,
          MIN(ST_X(m.geom)) AS min_lng,
          MAX(ST_X(m.geom)) AS max_lng,
          MIN(ST_Y(m.geom)) AS min_lat,
          MAX(ST_Y(m.geom)) AS max_lat,
          percentile_cont(0.005) WITHIN GROUP (ORDER BY ST_X(m.geom)) AS p_min_lng,
          percentile_cont(0.995) WITHIN GROUP (ORDER BY ST_X(m.geom)) AS p_max_lng,
          percentile_cont(0.005) WITHIN GROUP (ORDER BY ST_Y(m.geom)) AS p_min_lat,
          percentile_cont(0.995) WITHIN GROUP (ORDER BY ST_Y(m.geom)) AS p_max_lat
        FROM datasets d
        LEFT JOIN molecule_map m ON m.dataset_id = d.id
        WHERE d.slug = %s
        GROUP BY d.id
        """,
        (slug,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"Dataset not found: {slug}")
    west, south, east, north = _clamp_bbox(
        float(row[9]), float(row[11]), float(row[10]), float(row[12])
    )
    meta = dict(
        id=row[0],
        slug=row[1],
        name=row[2],
        count=row[3],
        max_rank=row[4],
        # Absolute envelope (informational / fitBounds elsewhere).
        abs_min_lng=row[5],
        abs_max_lng=row[6],
        abs_min_lat=row[7],
        abs_max_lat=row[8],
        # Robust bbox used for mercantile tile enumeration.
        min_lng=west,
        max_lng=east,
        min_lat=south,
        max_lat=north,
    )
    if not meta["count"]:
        raise SystemExit(f"Dataset has no molecules: {slug}")
    return meta


def _fetch_tile(
    conn: psycopg.Connection,
    *,
    dataset_id: int,
    z: int,
    x: int,
    y: int,
    rank_max: int,
) -> bytes:
    row = conn.execute(
        TILE_SQL,
        {"z": z, "x": x, "y": y, "dataset_id": dataset_id, "rank_max": rank_max},
    ).fetchone()
    return bytes(row[0] or b"")


def build_lod_pmtiles(
    conn: psycopg.Connection,
    *,
    meta: dict,
    lod_level: int,
    max_zoom: int,
    min_zoom: int = 0,
) -> dict:
    slug = meta["slug"]
    out_path = pmtiles_path(slug, lod_level)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".pmtiles.tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    west, south = float(meta["min_lng"]), float(meta["min_lat"])
    east, north = float(meta["max_lng"]), float(meta["max_lat"])
    # Pad so edge / near-percentile points are included in tiles
    pad_lng = max((east - west) * 0.05, 1e-6)
    pad_lat = max((north - south) * 0.05, 1e-6)
    west, east = west - pad_lng, east + pad_lng
    south, north = south - pad_lat, north + pad_lat
    west, south, east, north = _clamp_bbox(west, south, east, north)

    tile_jobs: list[tuple[int, int, int, int]] = []
    for z in range(min_zoom, max_zoom + 1):
        rank_max = rank_max_for_zoom(z, meta["max_rank"], lod_level)
        for tile in mercantile.tiles(west, south, east, north, zooms=[z]):
            tile_jobs.append((z, tile.x, tile.y, rank_max))

    written = 0
    empty = 0
    with tmp_path.open("wb") as f:
        writer = Writer(f)
        label = label_for_lod_level(lod_level)
        for z, x, y, rank_max in tqdm(
            tile_jobs,
            desc=f"{slug} LOD {lod_level} ({label})",
            unit="tile",
        ):
            data = _fetch_tile(
                conn,
                dataset_id=meta["id"],
                z=z,
                x=x,
                y=y,
                rank_max=rank_max,
            )
            if not data:
                empty += 1
                continue
            writer.write_tile(zxy_to_tileid(z, x, y), data)
            written += 1

        header = {
            "tile_type": TileType.MVT,
            "tile_compression": Compression.NONE,
            "min_zoom": min_zoom,
            "max_zoom": max_zoom,
            "min_lon": west,
            "min_lat": south,
            "max_lon": east,
            "max_lat": north,
            "center_zoom": min(max_zoom, max(min_zoom, 3)),
            "center_lon": (west + east) / 2,
            "center_lat": (south + north) / 2,
        }
        metadata = {
            "name": f"{slug} LOD {lod_level} ({label})",
            "dataset": slug,
            "lod_level": str(lod_level),
            "lod_label": label,
            "attribution": "Molecule Map",
            "type": "overlay",
            "format": "pbf",
            "generator": "build_precomputed_tiles",
        }
        writer.finalize(header, metadata)

    tmp_path.replace(out_path)
    return {
        "lod_level": lod_level,
        "label": label_for_lod_level(lod_level),
        "path": str(out_path),
        "tiles_written": written,
        "tiles_empty": empty,
        "bytes": out_path.stat().st_size,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="Dataset slug, e.g. zinc10k")
    ap.add_argument("--min-zoom", type=int, default=0)
    ap.add_argument("--max-zoom", type=int, default=12)
    ap.add_argument(
        "--lod",
        type=int,
        nargs="*",
        default=None,
        help=f"LOD levels to bake (default: 1..{LOD_STEP_COUNT})",
    )
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/molecules"),
    )
    args = ap.parse_args()

    lods = args.lod or list(range(1, LOD_STEP_COUNT + 1))
    for level in lods:
        if level < 1 or level > LOD_STEP_COUNT:
            raise SystemExit(f"LOD level must be 1..{LOD_STEP_COUNT}, got {level}")

    url = _psycopg_url(args.database_url)
    print(f"Connecting to {url.split('@')[-1]} …", flush=True)
    with psycopg.connect(url) as conn:
        meta = _dataset_meta(conn, args.dataset)
        print(
            f"Dataset {meta['slug']}: {meta['count']:,} molecules, "
            f"max_rank={meta['max_rank']:,}, "
            f"tile_bbox=({meta['min_lng']:.4f},{meta['min_lat']:.4f})"
            f"→({meta['max_lng']:.4f},{meta['max_lat']:.4f})",
            flush=True,
        )
        abs_span = (
            float(meta["abs_max_lng"]) - float(meta["abs_min_lng"]),
            float(meta["abs_max_lat"]) - float(meta["abs_min_lat"]),
        )
        tile_span = (
            float(meta["max_lng"]) - float(meta["min_lng"]),
            float(meta["max_lat"]) - float(meta["min_lat"]),
        )
        if abs_span[0] > tile_span[0] * 2 or abs_span[1] > tile_span[1] * 2:
            print(
                f"  (absolute bbox has outliers: "
                f"({meta['abs_min_lng']:.2f},{meta['abs_min_lat']:.2f})"
                f"→({meta['abs_max_lng']:.2f},{meta['abs_max_lat']:.2f}); "
                f"tile coverage uses percentiles)",
                flush=True,
            )
        print(f"Cache dir: {dataset_cache_dir(meta['slug'])}", flush=True)

        results = []
        for level in lods:
            info = build_lod_pmtiles(
                conn,
                meta=meta,
                lod_level=level,
                max_zoom=args.max_zoom,
                min_zoom=args.min_zoom,
            )
            results.append(info)
            print(
                f"  LOD {level}: {info['tiles_written']:,} tiles "
                f"({info['bytes'] / 1e6:.2f} MB)",
                flush=True,
            )

    manifest = {
        "slug": meta["slug"],
        "name": meta["name"],
        "molecule_count": meta["count"],
        "max_rank": meta["max_rank"],
        "min_zoom": args.min_zoom,
        "max_zoom": args.max_zoom,
        "lod_levels": available_lod_levels(meta["slug"]),
        "archives": results,
    }
    write_manifest(meta["slug"], manifest)
    print(f"Wrote manifest with LOD levels {manifest['lod_levels']}", flush=True)


if __name__ == "__main__":
    main()
