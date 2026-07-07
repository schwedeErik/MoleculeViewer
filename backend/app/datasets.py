from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Connection

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def validate_slug(slug: str) -> None:
    if not SLUG_PATTERN.match(slug):
        raise HTTPException(
            status_code=400,
            detail="Slug must be 1–64 chars: lowercase letters, numbers, hyphens, underscores",
        )


def list_datasets(conn: Connection) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT
              d.id,
              d.slug,
              d.name,
              d.embedding_method,
              d.embedding_dim,
              COUNT(m.id)::int AS molecule_count
            FROM datasets d
            LEFT JOIN molecules m ON m.dataset_id = d.id
            GROUP BY d.id
            ORDER BY d.name
            """
        )
    ).mappings()
    return [dict(row) for row in rows]


def resolve_dataset_id(conn: Connection, slug: str) -> int:
    row = conn.execute(
        text("SELECT id FROM datasets WHERE slug = :slug"),
        {"slug": slug},
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {slug}")
    return int(row.id)


def delete_dataset(conn: Connection, slug: str) -> None:
    validate_slug(slug)
    dataset_id = resolve_dataset_id(conn, slug)
    conn.execute(text("DELETE FROM datasets WHERE id = :id"), {"id": dataset_id})
    conn.commit()
