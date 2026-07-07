from __future__ import annotations

from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .db import engine
from .molecules_pb2 import Points


app = FastAPI(title="Molecule Map API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/bounds")
def bounds() -> dict:
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
        FROM molecules
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql).mappings().one()
    return dict(row)


@app.get("/tiles/{z}/{x}/{y}.mvt")
def tile(
    z: int,
    x: int,
    y: int,
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
            FROM molecules m, bounds4326 b
            WHERE m.geom && b.b4326
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
        tile_bytes = conn.execute(
            sql,
            {"z": z, "x": x, "y": y, "rank_max": rank_max},
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
        FROM molecules
        WHERE geom && ST_MakeEnvelope(:minLng, :minLat, :maxLng, :maxLat, 4326)
        ORDER BY rank ASC, id ASC
        LIMIT :limit;
        """
    )
    out = Points()
    with engine.connect() as conn:
        for row in conn.execute(
            sql,
            {
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

