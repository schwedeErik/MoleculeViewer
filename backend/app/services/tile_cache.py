"""Filesystem + PMTiles helpers for precomputed MVT LOD archives."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .rank_lod import LOD_STEP_COUNT


def tile_cache_root() -> Path:
    """Root directory for precomputed tiles (override with ``TILE_CACHE_DIR``)."""
    env = os.environ.get("TILE_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # backend/app/services → repo data/tile_cache
    return (Path(__file__).resolve().parents[3] / "data" / "tile_cache").resolve()


def dataset_cache_dir(slug: str) -> Path:
    return tile_cache_root() / slug


def pmtiles_path(slug: str, lod_level: int) -> Path:
    return dataset_cache_dir(slug) / f"lod_{lod_level}.pmtiles"


def manifest_path(slug: str) -> Path:
    return dataset_cache_dir(slug) / "manifest.json"


def available_lod_levels(slug: str) -> list[int]:
    """Return LOD steps that have a non-empty PMTiles archive."""
    found: list[int] = []
    for level in range(1, LOD_STEP_COUNT + 1):
        path = pmtiles_path(slug, level)
        if path.is_file() and path.stat().st_size > 0:
            found.append(level)
    return found


def read_manifest(slug: str) -> dict | None:
    path = manifest_path(slug)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def write_manifest(slug: str, manifest: dict) -> Path:
    path = manifest_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path
