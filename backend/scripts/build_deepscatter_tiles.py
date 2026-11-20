"""Build Deepscatter / quadfeather tile trees from Postgres or a pipeline CSV.

Ranking becomes the **sort key** for the export: lower ``rank`` = earlier file
rows = shallower quadtree priority in Deepscatter. Runtime ``rank_max`` MVT
filtering is not used.

Requires: ``quadfeather`` CLI (``pip install quadfeather`` or
``pip install git+https://github.com/bmschmidt/quadfeather``).

Run from ``backend/``:

    # From DB (preferred when the dataset is already loaded)
    python -m scripts.build_deepscatter_tiles --dataset zinc10k

    # Ablation: same coordinates, shuffled file order
    python -m scripts.build_deepscatter_tiles --dataset zinc10k --order shuffled

    # From pipeline CSV (columns: smiles, rank, lng, lat, …)
    python -m scripts.build_deepscatter_tiles --csv ../data/molecules_10k.csv \\
        --slug zinc10k --order ranked

Env:
    DATABASE_URL=postgresql://app:app@localhost:5432/molecules
    DEEPSCATTER_TILE_DIR=../data/deepscatter   (optional)
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.deepscatter_tiles import (  # noqa: E402
    dataset_tiles_dir,
    write_manifest,
)


EXPORT_COLUMNS = ("x", "y", "id", "rank", "smiles")


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _resolve_quadfeather() -> list[str]:
    """Return argv prefix to invoke quadfeather."""
    which = shutil.which("quadfeather")
    if which:
        return [which]
    # Fallback: python -m quadfeather (if installed as module)
    return [sys.executable, "-m", "quadfeather"]


def export_from_db(
    database_url: str,
    slug: str,
    out_csv: Path,
    *,
    include_smiles: bool,
) -> dict:
    sql = """
        SELECT
          m.id,
          m.rank,
          ST_X(m.geom) AS x,
          ST_Y(m.geom) AS y,
          d.smiles
        FROM molecule_map m
        JOIN datasets ds ON ds.id = m.dataset_id
        LEFT JOIN molecule_details d ON d.molecule_id = m.id
        WHERE ds.slug = %(slug)s
        ORDER BY m.rank ASC, m.id ASC
    """
    count = 0
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    max_rank = 0

    fieldnames = list(EXPORT_COLUMNS) if include_smiles else ["x", "y", "id", "rank"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with conn.cursor() as cur, out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            cur.execute(sql, {"slug": slug})
            for molecule_id, rank, x, y, smiles in cur:
                x_f, y_f = float(x), float(y)
                row = {"x": x_f, "y": y_f, "id": int(molecule_id), "rank": int(rank)}
                if include_smiles:
                    row["smiles"] = smiles or ""
                writer.writerow(row)
                count += 1
                min_x, max_x = min(min_x, x_f), max(max_x, x_f)
                min_y, max_y = min(min_y, y_f), max(max_y, y_f)
                max_rank = max(max_rank, int(rank))

    if count == 0:
        raise SystemExit(f"No molecules for dataset slug={slug!r}")

    return {
        "count": count,
        "max_rank": max_rank,
        "bounds": {"min_x": min_x, "max_x": max_x, "min_y": min_y, "max_y": max_y},
        "columns": fieldnames,
    }


def export_from_csv(
    src: Path,
    out_csv: Path,
    *,
    include_smiles: bool,
) -> dict:
    """Read pipeline CSV (smiles, rank, lng, lat, …) → Deepscatter x/y CSV sorted by rank."""
    if not src.is_file():
        raise SystemExit(f"CSV not found: {src}")

    rows: list[dict] = []
    with src.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("CSV has no header")
        fields = {name.lower(): name for name in reader.fieldnames}
        for required in ("rank", "lng", "lat"):
            if required not in fields:
                raise SystemExit(f"CSV missing required column: {required}")
        id_key = fields.get("id")
        smiles_key = fields.get("smiles")
        rank_key, lng_key, lat_key = fields["rank"], fields["lng"], fields["lat"]

        for i, raw in enumerate(reader, start=1):
            x_f = float(raw[lng_key])
            y_f = float(raw[lat_key])
            rank = int(float(raw[rank_key]))
            molecule_id = int(raw[id_key]) if id_key and raw.get(id_key) not in (None, "") else i
            row = {"x": x_f, "y": y_f, "id": molecule_id, "rank": rank}
            if include_smiles:
                row["smiles"] = (raw.get(smiles_key) if smiles_key else "") or ""
            rows.append(row)

    rows.sort(key=lambda r: (r["rank"], r["id"]))
    fieldnames = list(EXPORT_COLUMNS) if include_smiles else ["x", "y", "id", "rank"]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    return {
        "count": len(rows),
        "max_rank": max(r["rank"] for r in rows),
        "bounds": {
            "min_x": min(xs),
            "max_x": max(xs),
            "min_y": min(ys),
            "max_y": max(ys),
        },
        "columns": fieldnames,
    }


def apply_order(src_csv: Path, dest_csv: Path, order: str, seed: int) -> None:
    """Copy ranked CSV, optionally shuffle data rows (header preserved)."""
    with src_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if order == "shuffled":
        rng = random.Random(seed)
        rng.shuffle(rows)
    elif order != "ranked":
        raise SystemExit(f"Unknown order: {order}")

    with dest_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_quadfeather(csv_path: Path, destination: Path, tile_size: int) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)

    cmd = [
        *_resolve_quadfeather(),
        "--files",
        str(csv_path),
        "--tile_size",
        str(tile_size),
        "--destination",
        str(destination),
    ]
    print("Running:", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as exc:
        raise SystemExit(
            "quadfeather not found. Install with:\n"
            "  pip install quadfeather\n"
            "or:\n"
            "  pip install git+https://github.com/bmschmidt/quadfeather"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"quadfeather failed with exit code {exc.returncode}") from exc


def _parent_tile_key(key: str) -> str | None:
    z, x, y = (int(part) for part in key.split("/"))
    if z <= 0:
        return None
    return f"{z - 1}/{x // 2}/{y // 2}"


def inject_deepscatter_metadata(destination: Path) -> None:
    """Write ``extent`` / ``children`` schema metadata Deepscatter expects.

    Recent quadfeather + pyarrow builds often omit per-tile Arrow schema
    metadata. Without ``extent`` on the root tile, Deepscatter recurses forever
    between ``extent`` and ``theoretical_extent`` (Maximum call stack size exceeded).
    """
    import json

    import pyarrow as pa
    import pyarrow.feather as feather

    manifest_path = destination / "manifest.feather"
    if not manifest_path.is_file():
        print("  warning: no manifest.feather — skipping metadata inject", flush=True)
        return

    manifest = feather.read_table(manifest_path)
    keys = [str(k) for k in manifest.column("key").to_pylist()]
    extents = [str(e) for e in manifest.column("extent").to_pylist()]
    extent_by_key = dict(zip(keys, extents, strict=True))

    children_by_key: dict[str, list[str]] = {key: [] for key in keys}
    for key in keys:
        parent = _parent_tile_key(key)
        if parent is not None and parent in children_by_key:
            children_by_key[parent].append(key)

    patched = 0
    for key in keys:
        tile_path = destination.joinpath(*key.split("/")).with_suffix(".feather")
        if not tile_path.is_file():
            print(f"  warning: missing tile {tile_path}", flush=True)
            continue
        table = feather.read_table(tile_path)
        meta = dict(table.schema.metadata or {})
        meta[b"extent"] = extent_by_key[key].encode("utf-8")
        meta[b"children"] = json.dumps(children_by_key[key]).encode("utf-8")
        # Keep sidecars key if present so Deepscatter sidecar loading stays happy.
        meta.setdefault(b"sidecars", b"{}")
        feather.write_feather(
            table.replace_schema_metadata(meta),
            tile_path,
            compression="uncompressed",
        )
        patched += 1

    print(f"  injected extent/children metadata into {patched} tiles", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", help="Dataset slug already loaded in Postgres")
    ap.add_argument("--csv", type=Path, help="Pipeline CSV (smiles, rank, lng, lat, …)")
    ap.add_argument("--slug", help="Slug for output path when using --csv (default: stem)")
    ap.add_argument(
        "--order",
        choices=("ranked", "shuffled"),
        default="ranked",
        help="File order for quadfeather (shuffled = RQ1 ablation)",
    )
    ap.add_argument("--seed", type=int, default=42, help="Shuffle seed")
    ap.add_argument("--tile-size", type=int, default=50_000, help="quadfeather tile_size")
    ap.add_argument(
        "--include-smiles",
        action="store_true",
        help="Embed smiles strings in tiles (larger files; click details work offline)",
    )
    ap.add_argument(
        "--keep-csv",
        action="store_true",
        help="Keep the intermediate ranked CSV next to the tile tree",
    )
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/molecules"),
    )
    args = ap.parse_args()

    if bool(args.dataset) == bool(args.csv):
        raise SystemExit("Provide exactly one of --dataset or --csv")

    slug = args.dataset or (args.slug or args.csv.stem)  # type: ignore[union-attr]
    slug = slug.strip()
    if not slug:
        raise SystemExit("Empty dataset slug")

    dest = dataset_tiles_dir(slug, args.order)
    print(f"Building Deepscatter tiles → {dest}", flush=True)

    with tempfile.TemporaryDirectory(prefix="deepscatter_") as tmp:
        tmp_path = Path(tmp)
        ranked_csv = tmp_path / "ranked.csv"
        ordered_csv = tmp_path / f"{args.order}.csv"

        if args.dataset:
            meta = export_from_db(
                args.database_url,
                args.dataset,
                ranked_csv,
                include_smiles=args.include_smiles,
            )
        else:
            meta = export_from_csv(
                args.csv,  # type: ignore[arg-type]
                ranked_csv,
                include_smiles=args.include_smiles,
            )

        print(
            f"  exported {meta['count']:,} rows "
            f"(max_rank={meta['max_rank']}, columns={meta['columns']})",
            flush=True,
        )
        apply_order(ranked_csv, ordered_csv, args.order, args.seed)
        run_quadfeather(ordered_csv, dest, args.tile_size)
        inject_deepscatter_metadata(dest)

        if args.keep_csv:
            kept = dest / f"export_{args.order}.csv"
            shutil.copy2(ordered_csv, kept)
            print(f"  kept CSV: {kept}", flush=True)

    manifest = {
        "slug": slug,
        "order": args.order,
        "seed": args.seed if args.order == "shuffled" else None,
        "tile_size": args.tile_size,
        "include_smiles": args.include_smiles,
        "built_at": datetime.now(timezone.utc).isoformat(),
        **meta,
        "source_url_path": f"/deepscatter/{slug}/{args.order}",
        "notes": (
            "Deepscatter LOD follows file row order: ranked = low rank first; "
            "shuffled = same points, random order (RQ1 ablation)."
        ),
    }
    write_manifest(slug, args.order, manifest)
    print(f"Done. Serve tiles at /deepscatter/{slug}/{args.order}/", flush=True)
    print(f"Manifest: {dest / 'manifest.json'}", flush=True)


if __name__ == "__main__":
    main()
