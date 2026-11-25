"""Import a pipeline CSV as Deepscatter tiles without loading Postgres / MVT."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import deepscatter_catalog, deepscatter_tiles


def uploads_dir() -> Path:
    return deepscatter_tiles.deepscatter_root().parent / "uploads"


def save_upload(slug: str, upload_file) -> Path:
    """Persist an UploadFile to ``data/uploads/<slug>.csv``."""
    dest_dir = uploads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{slug}.csv"
    upload_file.file.seek(0)
    with dest.open("wb") as out:
        shutil.copyfileobj(upload_file.file, out)
    return dest


def build_deepscatter_from_csv(
    csv_path: Path,
    *,
    slug: str,
    name: str,
    embedding_method: str = "maccs",
    include_smiles: bool = True,
    build_shuffled: bool = False,
    tile_size: int = 50_000,
    progress_cb=None,
) -> dict:
    """Build ranked (and optional shuffled) tile trees; register in the catalog."""
    def report(phase: str, progress: int, message: str) -> None:
        if progress_cb is not None:
            progress_cb(phase, progress, message)
        print(f"[{progress:3d}%] {phase}: {message}", flush=True)

    backend_root = Path(__file__).resolve().parents[2]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from scripts import build_deepscatter_tiles as build  # noqa: WPS433

    orders = ["ranked"] + (["shuffled"] if build_shuffled else [])
    meta: dict = {}
    n_orders = len(orders)
    for oi, order in enumerate(orders):
        base = int(5 + (90 * oi) / n_orders)
        span = int(90 / n_orders)
        dest = deepscatter_tiles.dataset_tiles_dir(slug, order)
        report("export", base + int(span * 0.05), f"Reading CSV for {order} tiles…")
        print(f"Building Deepscatter tiles → {dest}", flush=True)
        with tempfile.TemporaryDirectory(prefix="deepscatter_") as tmp:
            tmp_path = Path(tmp)
            ranked_csv = tmp_path / "ranked.csv"
            ordered_csv = tmp_path / f"{order}.csv"
            try:
                meta = build.export_from_csv(
                    csv_path, ranked_csv, include_smiles=include_smiles
                )
                report(
                    "export",
                    base + int(span * 0.35),
                    f"Exported {meta.get('count', 0):,} rows — ordering ({order})…",
                )
                build.apply_order(ranked_csv, ordered_csv, order, seed=42)
                report(
                    "tiling",
                    base + int(span * 0.45),
                    f"Running quadfeather ({order})…",
                )
                build.run_quadfeather(ordered_csv, dest, tile_size)
                report(
                    "tiling",
                    base + int(span * 0.85),
                    f"Writing tile metadata ({order})…",
                )
                build.inject_deepscatter_metadata(dest)
                # int64 columns become JS BigInt and break Deepscatter hover/colour scales.
                build.cast_ids_to_float64(dest)
            except SystemExit as exc:
                raise ValueError(str(exc) or "Deepscatter tile build failed") from exc

        manifest = {
            "slug": slug,
            "order": order,
            "seed": 42 if order == "shuffled" else None,
            "tile_size": tile_size,
            "include_smiles": include_smiles,
            "built_at": datetime.now(timezone.utc).isoformat(),
            **meta,
            "source_url_path": f"/deepscatter/{slug}/{order}",
            "deepscatter_only": True,
            "notes": "Deepscatter-only import (no Postgres molecule rows).",
        }
        deepscatter_tiles.write_manifest(slug, order, manifest)
        report("tiling", base + span, f"Finished {order} tiles")

    report("finalize", 97, "Registering dataset…")
    entry = {
        "id": -abs(hash(slug)) % 1_000_000_000,
        "slug": slug,
        "name": name,
        "embedding_method": embedding_method,
        "embedding_dim": 0,
        "molecule_count": int(meta.get("count") or 0),
        "deepscatter_only": True,
        "precomputed_lods": [],
        "deepscatter_orders": deepscatter_tiles.available_orders(slug),
    }
    entry = deepscatter_catalog.upsert_entry(entry)
    report("done", 100, f"Ready — {entry['molecule_count']:,} molecules")
    return entry


def delete_deepscatter_dataset(slug: str) -> None:
    """Remove catalog entry, tile trees, and saved CSV upload."""
    deepscatter_catalog.remove_entry(slug)
    root = deepscatter_tiles.deepscatter_root() / slug
    if root.is_dir():
        shutil.rmtree(root, ignore_errors=True)
    csv_path = uploads_dir() / f"{slug}.csv"
    if csv_path.is_file():
        csv_path.unlink()
