"""Build a molecule-map dataset for bulk import into PostgreSQL.

Downloads SMILES from HuggingFace, embeds them, ranks them by
representativeness, projects to 2D with UMAP (GPU if available), and writes a
CSV plus a psql loader script. Intended to run as an HPC/Slurm job that has no
direct database access; the produced files are loaded into Postgres afterwards.

Run from the ``backend`` directory:

    python -m scripts.build_map_dataset \\
        --repo-id edmanft/zinc250k --column smiles --limit 250000 \\
        --method maccs --metric euclidean \\
        --out-dir ./out

Then, on a machine that can reach the database:

    psql "$DATABASE_URL" -f ./out/molecules_load.sql
"""
from __future__ import annotations

import argparse
from pathlib import Path

from app.services.smiles_downloader import download_smiles_database_huggingface
from app.services.smiles_processing import EmbeddingMethod, process_and_export


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-id", required=True, help="HuggingFace dataset id, e.g. edmanft/zinc250k")
    ap.add_argument("--column", default="smiles", help="SMILES column name")
    ap.add_argument("--limit", type=int, default=1_000_000, help="Max molecules to load")
    ap.add_argument("--method", default="maccs", choices=[m.value for m in EmbeddingMethod])
    ap.add_argument("--metric", default="euclidean", help="UMAP distance metric")
    ap.add_argument("--n-neighbors", type=int, default=15)
    ap.add_argument("--min-dist", type=float, default=0.1)
    ap.add_argument("--out-dir", default="./out", help="Directory for the CSV + loader SQL")
    ap.add_argument("--name", default="molecules", help="Base filename (without extension)")
    ap.add_argument("--dataset-slug", default=None, help="Dataset slug in Postgres (default: --name)")
    ap.add_argument("--dataset-name", default=None, help="Human-readable dataset name")
    ap.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Parallel embedding workers (default: all CPUs)",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    csv_path = out_dir / f"{args.name}.csv"
    sql_path = out_dir / f"{args.name}_load.sql"

    print(f"Downloading up to {args.limit:,} SMILES from {args.repo_id} …", flush=True)
    smiles = download_smiles_database_huggingface(args.repo_id, column_name=args.column, limit=args.limit)
    print(f"  got {len(smiles):,} SMILES", flush=True)

    print(f"Embedding ({args.method}), ranking, and projecting (UMAP/{args.metric}) …", flush=True)
    n = process_and_export(
        smiles,
        EmbeddingMethod(args.method),
        csv_path=str(csv_path),
        sql_path=str(sql_path),
        dataset_slug=args.dataset_slug or args.name,
        dataset_name=args.dataset_name or args.dataset_slug or args.name,
        umap_kwargs={
            "metric": args.metric,
            "n_neighbors": args.n_neighbors,
            "min_dist": args.min_dist,
        },
        n_workers=args.workers,
    )
    del smiles

    print(f"Wrote {n:,} rows to {csv_path}", flush=True)
    print(f"Loader script: {sql_path}", flush=True)
    print(f'Load with:  psql "$DATABASE_URL" -f {sql_path}', flush=True)


if __name__ == "__main__":
    main()
