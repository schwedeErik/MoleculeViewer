"""Filesystem helpers for Deepscatter / quadfeather tile trees.

Deepscatter LOD is driven by **file row order** in the ranked export that
quadfeather consumes: earlier rows (lower ``rank``) land in shallower
quadtree nodes and appear first at coarse zoom.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def deepscatter_root() -> Path:
    """Root directory for Deepscatter tile trees (override with ``DEEPSCATTER_TILE_DIR``)."""
    env = os.environ.get("DEEPSCATTER_TILE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # backend/app/services → repo data/deepscatter
    return (Path(__file__).resolve().parents[3] / "data" / "deepscatter").resolve()


def dataset_tiles_dir(slug: str, order: str = "ranked") -> Path:
    """Tile tree for one dataset + order variant (``ranked`` or ``shuffled``)."""
    safe_order = order if order in {"ranked", "shuffled"} else "ranked"
    return deepscatter_root() / slug / safe_order


def manifest_path(slug: str, order: str = "ranked") -> Path:
    return dataset_tiles_dir(slug, order) / "manifest.json"


def is_ready(slug: str, order: str = "ranked") -> bool:
    """True when a tile tree looks usable (manifest or root feather present)."""
    root = dataset_tiles_dir(slug, order)
    if not root.is_dir():
        return False
    if (root / "manifest.json").is_file():
        return True
    # quadfeather writes nested feathers; any .feather under root is enough
    return any(root.rglob("*.feather"))


def available_orders(slug: str) -> list[str]:
    return [order for order in ("ranked", "shuffled") if is_ready(slug, order)]


def read_manifest(slug: str, order: str = "ranked") -> dict | None:
    path = manifest_path(slug, order)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def write_manifest(slug: str, order: str, manifest: dict) -> Path:
    path = manifest_path(slug, order)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return path


def resolve_tile_file(slug: str, order: str, relative: str) -> Path | None:
    """Resolve a path under the tile tree; reject path traversal."""
    root = dataset_tiles_dir(slug, order).resolve()
    if not root.is_dir():
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate
