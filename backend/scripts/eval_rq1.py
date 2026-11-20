"""RQ1 evaluation: HD importance order vs shuffled file order.

Uses rank prefixes ``P_k`` as an offline proxy for Deepscatter coarse visible
sets (Chapter Evaluation Methodology). For each dataset and each ``k``:

* **ranked** — the ``k`` molecules with smallest pipeline ``rank``
* **shuffled** — the first ``k`` molecules after the same seeded shuffle used
  when building Deepscatter tiles (``seed=42``)

Metrics (HD embedding space unless noted):

* fill distance / mean NN distance (coverage)
* cluster coverage (mini-batch k-means, fixed ``K``)
* unique Bemis–Murcko scaffolds
* mean pairwise nearest-neighbour Tanimoto similarity inside ``P_k`` (redundancy)

Run from ``backend/``::

    python -m scripts.eval_rq1
    python -m scripts.eval_rq1 --datasets zinc10k zinc250k
    python -m scripts.eval_rq1 --skip-scaffolds   # faster, no RDKit scaffolds

Outputs under ``data/eval_rq1/`` (CSV, PNG plots, analysis markdown).
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import psycopg
from sklearn.cluster import MiniBatchKMeans
from sklearn.neighbors import NearestNeighbors

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DEFAULT_DATASETS = ("zinc10k", "zinc250k", "chembl13m")
SHUFFLE_SEED = 42
N_CLUSTERS = 100
FILL_QUERY_CAP = 20_000  # subsample of full library for fill-distance queries
SCAFFOLD_K_CAP = 20_000  # skip scaffolds for larger prefixes (RDKit cost)
REDUNDANCY_SAMPLE = 2_000


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def out_dir() -> Path:
    d = repo_root() / "data" / "eval_rq1"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_dir() -> Path:
    d = out_dir() / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def prefix_ladder(n: int) -> list[int]:
    if n <= 12_000:
        base = [100, 250, 500, 1_000, 2_000, 5_000, 10_000]
    elif n <= 300_000:
        base = [100, 500, 1_000, 2_000, 5_000, 10_000, 25_000, 50_000, 100_000]
    else:
        # Large libraries: coarse ladder only (Deepscatter overview regime).
        base = [500, 1_000, 2_000, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000]
    ks = [k for k in base if k < n]
    if n not in ks:
        ks.append(min(n, base[-1] if base else n))
        if n not in ks and n <= 50_000:
            ks.append(n)
    # unique sorted
    return sorted(set(ks))


@dataclass
class DatasetBundle:
    slug: str
    ids: np.ndarray  # (n,) int64, sorted by rank ascending
    ranks: np.ndarray  # (n,) int64
    embeddings: np.ndarray  # (n, d) float32
    smiles: np.ndarray  # (n,) object
    cluster_ids: np.ndarray  # (n,) int32


def load_dataset(database_url: str, slug: str) -> DatasetBundle:
    cache_path = cache_dir() / f"{slug}.npz"
    if cache_path.is_file():
        print(f"  cache hit {cache_path.name}", flush=True)
        data = np.load(cache_path, allow_pickle=True)
        return DatasetBundle(
            slug=slug,
            ids=data["ids"],
            ranks=data["ranks"],
            embeddings=data["embeddings"],
            smiles=data["smiles"],
            cluster_ids=data["cluster_ids"],
        )

    print(f"  loading {slug} from Postgres…", flush=True)
    t0 = time.time()
    ids: list[int] = []
    ranks: list[int] = []
    smiles: list[str] = []
    emb_rows: list[np.ndarray] = []

    sql = """
        SELECT m.id, m.rank, COALESCE(d.smiles, ''), d.embedding::text
        FROM molecule_map m
        JOIN datasets ds ON ds.id = m.dataset_id
        LEFT JOIN molecule_details d ON d.molecule_id = m.id
        WHERE ds.slug = %s
        ORDER BY m.rank ASC, m.id ASC
    """
    with psycopg.connect(_psycopg_url(database_url)) as conn:
        with conn.cursor(name=f"rq1_{slug}") as cur:
            cur.itersize = 20_000
            cur.execute(sql, (slug,))
            for molecule_id, rank, smi, emb_txt in cur:
                ids.append(int(molecule_id))
                ranks.append(int(rank))
                smiles.append(smi or "")
                vec = np.fromstring(emb_txt.strip("[]"), sep=",", dtype=np.float32)
                emb_rows.append(vec)

    embeddings = np.vstack(emb_rows).astype(np.float32, copy=False)
    ids_a = np.asarray(ids, dtype=np.int64)
    ranks_a = np.asarray(ranks, dtype=np.int64)
    smiles_a = np.asarray(smiles, dtype=object)
    print(
        f"  loaded {len(ids_a):,} × {embeddings.shape[1]} in {time.time() - t0:.1f}s",
        flush=True,
    )

    print(f"  clustering K={N_CLUSTERS}…", flush=True)
    t1 = time.time()
    km = MiniBatchKMeans(
        n_clusters=min(N_CLUSTERS, len(ids_a)),
        random_state=42,
        batch_size=min(4096, len(ids_a)),
        n_init=3,
    )
    cluster_ids = km.fit_predict(embeddings).astype(np.int32)
    print(f"  clustered in {time.time() - t1:.1f}s", flush=True)

    np.savez_compressed(
        cache_path,
        ids=ids_a,
        ranks=ranks_a,
        embeddings=embeddings,
        smiles=smiles_a,
        cluster_ids=cluster_ids,
    )
    return DatasetBundle(
        slug=slug,
        ids=ids_a,
        ranks=ranks_a,
        embeddings=embeddings,
        smiles=smiles_a,
        cluster_ids=cluster_ids,
    )


def shuffled_index_order(n: int, seed: int = SHUFFLE_SEED) -> np.ndarray:
    """Permutation matching ``build_deepscatter_tiles --order shuffled``."""
    idx = np.arange(n, dtype=np.int64)
    rng = random.Random(seed)
    # random.shuffle on a Python list matches the tile builder
    lst = idx.tolist()
    rng.shuffle(lst)
    return np.asarray(lst, dtype=np.int64)


def unique_scaffolds(smiles_list: list[str]) -> int:
    from rdkit import Chem
    from rdkit.Chem.Scaffolds import MurckoScaffold

    scaffolds: set[str] = set()
    for smi in smiles_list:
        if not smi:
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        try:
            scaf = MurckoScaffold.MurckoScaffoldSmiles(mol=mol)
        except Exception:
            continue
        if scaf:
            scaffolds.add(scaf)
    return len(scaffolds)


def tanimoto_nn_mean(bits: np.ndarray, sample_cap: int = REDUNDANCY_SAMPLE) -> float:
    """Mean nearest-neighbour Tanimoto similarity inside the set (higher = more redundant)."""
    X = bits
    n = X.shape[0]
    if n < 2:
        return float("nan")
    if n > sample_cap:
        rng = np.random.default_rng(0)
        pick = rng.choice(n, size=sample_cap, replace=False)
        X = X[pick]
        n = X.shape[0]

    # Jaccard / Tanimoto for binary vectors via sklearn pairwise is heavy;
    # use NN in Euclidean on binary bits as proxy is wrong for Tanimoto.
    # Efficient: for binary, Tanimoto = <a,b> / (|a|+|b|-<a,b>)
    # Approximate with sklearn NearestNeighbors on float and convert — not exact.
    # Exact-ish: use float32 matmul on a sample.
    Xt = X.astype(np.float32, copy=False)
    norms = Xt.sum(axis=1, keepdims=True)  # popcounts
    # Blocked NN Tanimoto
    nn_sim = np.full(n, 0.0, dtype=np.float64)
    block = 512
    for i0 in range(0, n, block):
        i1 = min(n, i0 + block)
        dots = Xt[i0:i1] @ Xt.T  # (b, n)
        denom = norms[i0:i1] + norms.T - dots
        with np.errstate(divide="ignore", invalid="ignore"):
            sim = np.where(denom > 0, dots / denom, 0.0)
        # exclude self
        for bi, gi in enumerate(range(i0, i1)):
            sim[bi, gi] = -1.0
        nn_sim[i0:i1] = sim.max(axis=1)
    return float(nn_sim.mean())


def fill_stats(
    embeddings: np.ndarray,
    selected_idx: np.ndarray,
    query_idx: np.ndarray,
) -> tuple[float, float, float]:
    """Return (max, mean, median) Euclidean distance from queries to nearest selected."""
    S = embeddings[selected_idx]
    Q = embeddings[query_idx]
    if len(S) == 0 or len(Q) == 0:
        return float("nan"), float("nan"), float("nan")
    nn = NearestNeighbors(n_neighbors=1, algorithm="auto", metric="euclidean", n_jobs=-1)
    nn.fit(S)
    dists, _ = nn.kneighbors(Q, return_distance=True)
    d = dists.ravel()
    return float(d.max()), float(d.mean()), float(np.median(d))


def evaluate_dataset(
    bundle: DatasetBundle,
    *,
    compute_scaffolds: bool,
) -> list[dict]:
    n = len(bundle.ids)
    ks = prefix_ladder(n)
    shuffle_order = shuffled_index_order(n)

    # Query subsample for fill distance (fixed across k / orderings)
    rng = np.random.default_rng(0)
    if n > FILL_QUERY_CAP:
        query_idx = np.sort(rng.choice(n, size=FILL_QUERY_CAP, replace=False))
    else:
        query_idx = np.arange(n, dtype=np.int64)

    n_clusters = int(bundle.cluster_ids.max()) + 1
    rows: list[dict] = []

    for k in ks:
        ranked_idx = np.arange(k, dtype=np.int64)  # already rank-sorted
        shuffled_idx = shuffle_order[:k]

        for order_name, sel in (("ranked", ranked_idx), ("shuffled", shuffled_idx)):
            t0 = time.time()
            h_max, h_mean, h_med = fill_stats(bundle.embeddings, sel, query_idx)
            covered = len(np.unique(bundle.cluster_ids[sel]))
            cluster_cov = covered / n_clusters

            # Redundancy on binary MACCS via Tanimoto NN
            redundancy = tanimoto_nn_mean(bundle.embeddings[sel])

            n_scaffolds = float("nan")
            scaffolds_per_point = float("nan")
            if compute_scaffolds and k <= SCAFFOLD_K_CAP:
                n_scaffolds = float(
                    unique_scaffolds(bundle.smiles[sel].tolist())
                )
                scaffolds_per_point = n_scaffolds / k

            rows.append(
                {
                    "dataset": bundle.slug,
                    "n": n,
                    "k": k,
                    "order": order_name,
                    "fill_max": h_max,
                    "fill_mean": h_mean,
                    "fill_median": h_med,
                    "cluster_coverage": cluster_cov,
                    "n_clusters_hit": covered,
                    "n_clusters": n_clusters,
                    "n_scaffolds": n_scaffolds,
                    "scaffolds_per_point": scaffolds_per_point,
                    "redundancy_nn_tanimoto": redundancy,
                    "seconds": time.time() - t0,
                }
            )
            print(
                f"  {bundle.slug} k={k:>8,} {order_name:8s} "
                f"fill_mean={h_mean:.4f} cov={cluster_cov:.3f} "
                f"red={redundancy:.3f} "
                f"({time.time() - t0:.1f}s)",
                flush=True,
            )
    return rows


def save_results_csv(rows: list[dict], path: Path) -> None:
    import csv

    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def plot_results(rows: list[dict], figures_dir: Path) -> list[Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    df = pd.DataFrame(rows)
    paths: list[Path] = []
    metrics = [
        ("fill_mean", "Mean fill distance (↓ better)", True),
        ("fill_max", "Max fill distance / covering radius (↓ better)", True),
        ("cluster_coverage", "Cluster coverage (↑ better)", False),
        ("scaffolds_per_point", "Unique scaffolds per point (↑ better)", False),
        ("redundancy_nn_tanimoto", "NN Tanimoto redundancy (↓ better)", True),
    ]

    datasets = list(df["dataset"].unique())
    for metric, title, _ in metrics:
        fig, axes = plt.subplots(
            1,
            len(datasets),
            figsize=(4.2 * len(datasets), 3.6),
            sharey=False,
            squeeze=False,
        )
        for ax, slug in zip(axes[0], datasets):
            sub = df[df["dataset"] == slug]
            for order, style in (("ranked", "-"), ("shuffled", "--")):
                part = sub[sub["order"] == order].sort_values("k")
                y = part[metric].astype(float)
                if y.isna().all():
                    continue
                ax.plot(part["k"], y, linestyle=style, marker="o", markersize=3, label=order)
            ax.set_xscale("log")
            ax.set_xlabel(r"Prefix size $k$")
            ax.set_title(slug)
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=8)
        axes[0][0].set_ylabel(title)
        fig.suptitle(f"RQ1: {title}", fontsize=11)
        fig.tight_layout()
        out = figures_dir / f"rq1_{metric}.png"
        fig.savefig(out, dpi=160)
        plt.close(fig)
        paths.append(out)

    # Combined relative improvement: fill_mean shuffled - ranked
    fig, ax = plt.subplots(figsize=(6.5, 4))
    for slug in datasets:
        sub = df[df["dataset"] == slug]
        r = sub[sub["order"] == "ranked"].set_index("k").sort_index()
        s = sub[sub["order"] == "shuffled"].set_index("k").sort_index()
        common = r.index.intersection(s.index)
        delta = (s.loc[common, "fill_mean"] - r.loc[common, "fill_mean"]) / s.loc[
            common, "fill_mean"
        ].replace(0, np.nan)
        ax.plot(common, 100 * delta, marker="o", markersize=3, label=slug)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xscale("log")
    ax.set_xlabel(r"Prefix size $k$")
    ax.set_ylabel("% lower mean fill distance (ranked vs shuffled)")
    ax.set_title("RQ1: relative coverage gain of HD ranking")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    out = figures_dir / "rq1_relative_fill_gain.png"
    fig.savefig(out, dpi=160)
    plt.close(fig)
    paths.append(out)
    return paths


def write_analysis(rows: list[dict], path: Path, figure_paths: list[Path]) -> None:
    import pandas as pd

    df = pd.DataFrame(rows)
    lines: list[str] = []
    lines.append("# RQ1 Analysis: Importance Order vs Shuffled Order\n")
    lines.append(
        "Prefixes $P_k$ approximate coarse Deepscatter views: ranked = pipeline "
        "importance order; shuffled = same molecules with seed-42 row permutation "
        "(same as Deepscatter tile ablation).\n"
    )
    lines.append("## Setup\n")
    for slug in df["dataset"].unique():
        n = int(df[df["dataset"] == slug]["n"].iloc[0])
        lines.append(f"- **{slug}**: $n={n:,}$; clusters $K={N_CLUSTERS}$; shuffle seed {SHUFFLE_SEED}")
    lines.append("")
    lines.append(
        f"Fill distance is estimated against a query subsample of up to "
        f"{FILL_QUERY_CAP:,} molecules (Euclidean in the MACCS embedding, matching FPS ranking).\n"
    )

    lines.append("## Main findings\n")
    for slug in df["dataset"].unique():
        sub = df[df["dataset"] == slug]
        lines.append(f"### {slug}\n")
        # Pick a representative coarse k (~1% or 1000)
        n = int(sub["n"].iloc[0])
        target = min(max(1000, n // 100), n)
        ks = sorted(sub["k"].unique())
        k = min(ks, key=lambda x: abs(x - target))
        r = sub[(sub["k"] == k) & (sub["order"] == "ranked")].iloc[0]
        s = sub[(sub["k"] == k) & (sub["order"] == "shuffled")].iloc[0]
        gain = (s["fill_mean"] - r["fill_mean"]) / s["fill_mean"] * 100 if s["fill_mean"] else 0.0
        lines.append(f"At $k={k:,}$ (~coarse overview):")
        lines.append(
            f"- Mean fill distance: ranked **{r['fill_mean']:.4f}** vs shuffled "
            f"**{s['fill_mean']:.4f}** ({gain:+.1f}% for ranked)."
        )
        lines.append(
            f"- Cluster coverage: ranked **{r['cluster_coverage']:.3f}** vs "
            f"shuffled **{s['cluster_coverage']:.3f}**."
        )
        if not np.isnan(r["n_scaffolds"]) and not np.isnan(s["n_scaffolds"]):
            lines.append(
                f"- Unique scaffolds: ranked **{int(r['n_scaffolds'])}** vs "
                f"shuffled **{int(s['n_scaffolds'])}** "
                f"({r['scaffolds_per_point']:.3f} vs {s['scaffolds_per_point']:.3f} per point)."
            )
        lines.append(
            f"- Redundancy (NN Tanimoto): ranked **{r['redundancy_nn_tanimoto']:.3f}** vs "
            f"shuffled **{s['redundancy_nn_tanimoto']:.3f}** (lower is less duplicate-dominated)."
        )
        lines.append("")

    # Overall verdict
    gains = []
    for slug in df["dataset"].unique():
        sub = df[df["dataset"] == slug]
        n = int(sub["n"].iloc[0])
        target = min(max(1000, n // 100), n)
        ks = sorted(sub["k"].unique())
        k = min(ks, key=lambda x: abs(x - target))
        r = sub[(sub["k"] == k) & (sub["order"] == "ranked")].iloc[0]
        s = sub[(sub["k"] == k) & (sub["order"] == "shuffled")].iloc[0]
        if s["fill_mean"]:
            gains.append((s["fill_mean"] - r["fill_mean"]) / s["fill_mean"])
    mean_gain = float(np.mean(gains)) if gains else 0.0

    lines.append("## Interpretation (RQ1)\n")
    if mean_gain > 0.02:
        lines.append(
            f"Across datasets, HD importance ordering improves mean fill distance by about "
            f"**{100 * mean_gain:.1f}%** at coarse prefixes relative to a random file order. "
            "That supports RQ1: ranking in embedding space yields chemically better Deepscatter "
            "overviews when only the early file rows (shallow quadtree) are visible."
        )
    elif mean_gain > 0:
        lines.append(
            f"HD ordering shows a modest mean-fill improvement (~{100 * mean_gain:.1f}%) over "
            "shuffle at coarse $k$. Gains are clearest for coverage-oriented metrics; scaffold "
            "and redundancy effects vary with library density and $k$."
        )
    else:
        lines.append(
            "At the tested prefixes, ranked order did not consistently beat shuffle on mean fill "
            "distance. Inspect per-dataset plots—UMAP distortion or hierarchical ranking "
            "approximation on large $n$ may weaken the signal."
        )
    lines.append("")
    lines.append("## Figures\n")
    for p in figure_paths:
        lines.append(f"- `{p.name}`")
    lines.append("")
    lines.append("## Limitations\n")
    lines.append(
        "- $P_k$ is a proxy for Deepscatter visible sets $S_z$ (spatial tile clipping ignored).\n"
        f"- Fill distance uses a query subsample (≤{FILL_QUERY_CAP:,}), not the full library.\n"
        f"- Scaffolds computed only for $k≤{SCAFFOLD_K_CAP:,}$.\n"
        "- Distance for fill is Euclidean on MACCS bits (consistent with FPS ranking); "
        "redundancy uses Tanimoto.\n"
    )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--datasets",
        nargs="+",
        default=list(DEFAULT_DATASETS),
        help="Dataset slugs to evaluate",
    )
    ap.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/molecules"),
    )
    ap.add_argument(
        "--skip-scaffolds",
        action="store_true",
        help="Skip Bemis–Murcko scaffold counts (faster)",
    )
    ap.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore cached embeddings/clusters",
    )
    args = ap.parse_args()

    if args.refresh_cache:
        for slug in args.datasets:
            p = cache_dir() / f"{slug}.npz"
            if p.is_file():
                p.unlink()
                print(f"removed cache {p.name}", flush=True)

    # pandas optional dependency for plotting convenience
    try:
        import pandas  # noqa: F401
    except ImportError:
        import subprocess

        subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas", "-q"])

    all_rows: list[dict] = []
    for slug in args.datasets:
        print(f"\n=== {slug} ===", flush=True)
        try:
            bundle = load_dataset(args.database_url, slug)
        except Exception as exc:
            print(f"  SKIP {slug}: {exc}", flush=True)
            continue
        all_rows.extend(
            evaluate_dataset(bundle, compute_scaffolds=not args.skip_scaffolds)
        )

    if not all_rows:
        raise SystemExit("No results produced")

    root = out_dir()
    csv_path = root / "rq1_metrics.csv"
    save_results_csv(all_rows, csv_path)
    print(f"\nWrote {csv_path}", flush=True)

    figures = plot_results(all_rows, root / "figures")
    for p in figures:
        print(f"Wrote {p}", flush=True)

    analysis_path = root / "rq1_analysis.md"
    write_analysis(all_rows, analysis_path, figures)
    print(f"Wrote {analysis_path}", flush=True)

    meta = {
        "datasets": args.datasets,
        "shuffle_seed": SHUFFLE_SEED,
        "n_clusters": N_CLUSTERS,
        "fill_query_cap": FILL_QUERY_CAP,
        "scaffold_k_cap": SCAFFOLD_K_CAP,
        "n_rows": len(all_rows),
    }
    (root / "rq1_meta.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
