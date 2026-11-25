"""Lightweight registry for Deepscatter-only datasets (no Postgres molecule rows)."""

from __future__ import annotations

import json
from pathlib import Path

from .deepscatter_tiles import deepscatter_root


def catalog_path() -> Path:
    return deepscatter_root() / "catalog.json"


def load_catalog() -> dict[str, dict]:
    path = catalog_path()
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items()}


def save_catalog(catalog: dict[str, dict]) -> None:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2) + "\n")


def upsert_entry(entry: dict) -> dict:
    slug = entry["slug"]
    catalog = load_catalog()
    catalog[slug] = entry
    save_catalog(catalog)
    return entry


def remove_entry(slug: str) -> bool:
    catalog = load_catalog()
    if slug not in catalog:
        return False
    del catalog[slug]
    save_catalog(catalog)
    return True


def list_entries() -> list[dict]:
    return sorted(load_catalog().values(), key=lambda e: e.get("name") or e.get("slug") or "")
