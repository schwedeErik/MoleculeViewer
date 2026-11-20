"""Extended RQ1 experiments on large libraries (keeps current RQ framing).

Adds, beyond ``eval_rq1``:

* multi-seed random prefixes (mean ± std) so shuffle is not a single draw
* ``cluster_rr`` order: round-robin over MiniBatch k-means clusters (chemotype-aware baseline)
* optional exact-vs-hierarchical FPS bridge on a fixed subsample (default 40k)

Run from ``backend/``::

    export DATABASE_URL=postgresql://app:app@localhost:5432/molecules
    python -m scripts.eval_rq1_large --datasets zinc250k chembl13m --shuffle-seeds 10
    python -m scripts.eval_rq1_large --datasets zinc250k --bridge-n 40000

Outputs under ``data/eval_rq1_large/``.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.smiles_ranking import rank_molecules  # noqa: E402
from scripts import eval_rq1 as rq1  # noqa: E402

DEFAULT_DATASETS = ("zinc250k", "chembl13m")
SHUFFLE_SEEDS = 10
BRIDGE_N = 40_000


def out_dir() -> Path:
    d = rq1.repo_root() / "data" / "eval_rq1_large"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cluster_round_robin_order(cluster_ids: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """Order: visit clusters by FPS of centroids, round-robin pick unused members.

    Within each cluster, members are sorted by distance to the cluster centroid
    (closest first = more typical).
    """
    n = len(cluster_ids)
    labels = cluster_ids.astype(np.int64)
    uniq = np.unique(labels)
    centroids = np.zeros((len(uniq), embeddings.shape[1]), dtype=np.float32)
    members: dict[int, np.ndarray] = {}
    for i, c in enumerate(uniq):
        idx = np.where(labels == c)[0]
        members[int(c)] = idx
        centroids[i] = embeddings[idx].mean(axis=0)

    # FPS order over centroids
    cent_order = _fps_indices(centroids)
    cluster_seq = [int(uniq[j]) for j in cent_order]

    # Within-cluster queues: nearest to centroid first
    queues: dict[int, list[int]] = {}
    for c, idx in members.items():
        cen = embeddings[idx].mean(axis=0, keepdims=True)
        d = np.sum((embeddings[idx] - cen) ** 2, axis=1)
        order = idx[np.argsort(d)]
        queues[c] = order.tolist()

    out: list[int] = []
    while len(out) < n:
        progressed = False
        for c in cluster_seq:
            q = queues[c]
            if q:
                out.append(q.pop(0))
                progressed = True
        if not progressed:
            break
    return np.asarray(out, dtype=np.int64)


def _fps_indices(X: np.ndarray) -> np.ndarray:
    """Exact FPS order on rows of X (small n = n_clusters)."""
    n = X.shape[0]
    order = np.empty(n, dtype=np.int64)
    centroid = X.mean(axis=0, keepdims=True)
    start = int(np.argmin(np.sum((X - centroid) ** 2, axis=1)))
    min_sq = np.sum((X - X[start]) ** 2, axis=1)
    order[0] = start
    min_sq[start] = -1.0
    for i in range(1, n):
        nxt = int(np.argmax(min_sq))
        order[i] = nxt
        if i + 1 < n:
            d = np.sum((X - X[nxt]) ** 2, axis=1)
            min_sq = np.minimum(min_sq, d)
            min_sq[nxt] = -1.0
            min_sq[order[: i + 1]] = -1.0
    return order


def evaluate_orders(
    bundle: rq1.DatasetBundle,
    *,
    orders: dict[str, np.ndarray],
    compute_scaffolds: bool,
    query_idx: np.ndarray,
) -> list[dict]:
    n = len(bundle.ids)
    ks = rq1.prefix_ladder(n)
    n_clusters = int(bundle.cluster_ids.max()) + 1
    rows: list[dict] = []

    for k in ks:
        for order_name, perm in orders.items():
            sel = perm[:k]
            t0 = time.time()
            h_max, h_mean, h_med = rq1.fill_stats(bundle.embeddings, sel, query_idx)
            covered = len(np.unique(bundle.cluster_ids[sel]))
            cluster_cov = covered / n_clusters
            redundancy = rq1.tanimoto_nn_mean(bundle.embeddings[sel])

            n_scaffolds = float("nan")
            scaffolds_per_point = float("nan")
            if compute_scaffolds and k <= rq1.SCAFFOLD_K_CAP:
                n_scaffolds = float(rq1.unique_scaffolds(bundle.smiles[sel].tolist()))
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
                    "n_scaffolds": n_scaffolds,
                    "scaffolds_per_point": scaffolds_per_point,
                    "redundancy_nn_tanimoto": redundancy,
                    "seconds": time.time() - t0,
                }
            )
            print(
                f"  {bundle.slug} k={k:>8,} {order_name:14s} "
                f"hmax={h_max:.3f} hmean={h_mean:.3f} cov={cluster_cov:.3f} "
                f"red={redundancy:.3f} ({time.time() - t0:.1f}s)",
                flush=True,
            )
    return rows


def aggregate_shuffle(rows: list[dict]) -> list[dict]:
    """Collapse shuffled_seed* rows into shuffled_mean / shuffled_std companion rows."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    kept: list[dict] = []
    for r in rows:
        if str(r["order"]).startswith("shuffled_seed"):
            groups[(r["dataset"], r["k"])].append(r)
        else:
            kept.append(r)

    for (ds, k), items in groups.items():
        def _agg(metric: str) -> tuple[float, float]:
            vals = [
                float(x[metric])
                for x in items
                if not (isinstance(x.get(metric), float) and np.isnan(x[metric]))
            ]
            if not vals:
                return float("nan"), float("nan")
            return float(np.mean(vals)), float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0

        base = dict(items[0])
        base["order"] = "shuffled_mean"
        for metric in (
            "fill_max",
            "fill_mean",
            "fill_median",
            "cluster_coverage",
            "scaffolds_per_point",
            "redundancy_nn_tanimoto",
        ):
            m, s = _agg(metric)
            base[metric] = m
            base[f"{metric}_std"] = s
        base["n_seeds"] = len(items)
        kept.append(base)
    return kept


def run_bridge(bundle: rq1.DatasetBundle, bridge_n: int, compute_scaffolds: bool) -> list[dict]:
    """Exact FPS vs hierarchical FPS vs random on a fixed subsample."""
    n = len(bundle.ids)
    rng = np.random.default_rng(0)
    bridge_n = min(bridge_n, n)
    pick = np.sort(rng.choice(n, size=bridge_n, replace=False))
    X = bundle.embeddings[pick]
    smiles = bundle.smiles[pick]
    # Re-cluster on subsample for coverage metric
    from sklearn.cluster import MiniBatchKMeans

    km = MiniBatchKMeans(
        n_clusters=min(100, bridge_n),
        random_state=42,
        batch_size=min(4096, bridge_n),
        n_init=3,
    )
    cl = km.fit_predict(X).astype(np.int32)

    print(f"  bridge subsample n={bridge_n}: exact FPS…", flush=True)
    t0 = time.time()
    ranks_exact = rank_molecules(X, exact_threshold=bridge_n + 1)  # force exact
    print(f"    exact done in {time.time() - t0:.1f}s", flush=True)
    print(f"  bridge: hierarchical FPS…", flush=True)
    t0 = time.time()
    ranks_hier = rank_molecules(X, exact_threshold=0)  # force hierarchical
    print(f"    hier done in {time.time() - t0:.1f}s", flush=True)

    order_exact = np.argsort(ranks_exact, kind="stable")
    order_hier = np.argsort(ranks_hier, kind="stable")
    order_rand = rq1.shuffled_index_order(bridge_n, seed=42)

    # Fake a mini-bundle for evaluate_orders
    mini = rq1.DatasetBundle(
        slug=f"{bundle.slug}_bridge{bridge_n}",
        ids=bundle.ids[pick],
        ranks=np.arange(1, bridge_n + 1),
        embeddings=X,
        smiles=smiles,
        cluster_ids=cl,
    )
    query_idx = np.arange(bridge_n, dtype=np.int64)
    return evaluate_orders(
        mini,
        orders={
            "exact_fps": order_exact,
            "hierarchical_fps": order_hier,
            "shuffled": order_rand,
        },
        compute_scaffolds=compute_scaffolds,
        query_idx=query_idx,
    )


def plot_large(rows: list[dict], figures_dir: Path) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    import pandas as pd

    df = pd.DataFrame(rows)
    # Prefer aggregated shuffle for plots
    plot_orders = ["ranked", "cluster_rr", "shuffled_mean", "shuffled"]
    metrics = [
        ("fill_max", "Max fill distance (↓ better)"),
        ("fill_mean", "Mean fill distance (↓ better)"),
        ("scaffolds_per_point", "Scaffolds per point (↑ better)"),
        ("redundancy_nn_tanimoto", "NN Tanimoto redundancy (↓ better)"),
    ]
    datasets = [d for d in df["dataset"].unique() if "bridge" not in str(d)]
    for metric, title in metrics:
        if not datasets:
            continue
        fig, axes = plt.subplots(1, len(datasets), figsize=(4.5 * len(datasets), 3.8), squeeze=False)
        for ax, slug in zip(axes[0], datasets):
            sub = df[df["dataset"] == slug]
            for order in plot_orders:
                part = sub[sub["order"] == order].sort_values("k")
                if part.empty or part[metric].isna().all():
                    continue
                y = part[metric].astype(float)
                ax.plot(part["k"], y, marker="o", markersize=3, label=order)
                std_col = f"{metric}_std"
                if std_col in part.columns and part[std_col].notna().any():
                    s = part[std_col].astype(float)
                    ax.fill_between(
                        part["k"].astype(float),
                        y - s,
                        y + s,
                        alpha=0.15,
                    )
            ax.set_xscale("log")
            ax.set_xlabel(r"Prefix size $k$")
            ax.set_title(slug)
            ax.grid(True, which="both", alpha=0.3)
            ax.legend(fontsize=7)
        axes[0][0].set_ylabel(title)
        fig.suptitle(f"RQ1 large: {title}", fontsize=11)
        fig.tight_layout()
        fig.savefig(figures_dir / f"rq1_large_{metric}.png", dpi=160)
        plt.close(fig)

    # Bridge plots
    bridge = df[df["dataset"].astype(str).str.contains("bridge")]
    if not bridge.empty:
        fig, ax = plt.subplots(figsize=(6.5, 4))
        for order, style in (
            ("exact_fps", "-"),
            ("hierarchical_fps", "--"),
            ("shuffled", ":"),
        ):
            part = bridge[bridge["order"] == order].sort_values("k")
            if part.empty:
                continue
            ax.plot(part["k"], part["fill_max"], linestyle=style, marker="o", markersize=3, label=order)
        ax.set_xscale("log")
        ax.set_xlabel(r"Prefix size $k$")
        ax.set_ylabel(r"$h_{\max}$ (↓ better)")
        ax.set_title("Exact vs hierarchical FPS vs shuffle (bridge subsample)")
        ax.grid(True, which="both", alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(figures_dir / "rq1_large_bridge_hmax.png", dpi=160)
        plt.close(fig)


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    keys: list[str] = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_analysis(rows: list[dict], path: Path) -> None:
    lines = [
        "# RQ1 large-dataset extension",
        "",
        "Orders: **ranked** (pipeline FPS / hierarchical FPS), **cluster_rr** "
        "(round-robin over embedding clusters), **shuffled_mean** (mean over seeds).",
        "",
        "Bridge: exact FPS vs hierarchical FPS vs one shuffle on a fixed subsample.",
        "",
    ]
    import pandas as pd

    df = pd.DataFrame(rows)
    for slug in df["dataset"].unique():
        sub = df[df["dataset"] == slug]
        lines.append(f"## {slug}")
        lines.append("")
        # pick a mid k
        ks = sorted(sub["k"].unique())
        mid = ks[len(ks) // 2]
        lines.append(f"At $k={mid}$:")
        lines.append("")
        for order in sorted(sub["order"].unique()):
            if str(order).startswith("shuffled_seed"):
                continue
            r = sub[(sub["order"] == order) & (sub["k"] == mid)]
            if r.empty:
                continue
            row = r.iloc[0]
            lines.append(
                f"- **{order}**: hmax={row['fill_max']:.3f}, hmean={row['fill_mean']:.3f}, "
                f"cov={row['cluster_coverage']:.3f}, red={row['redundancy_nn_tanimoto']:.3f}"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS))
    ap.add_argument("--shuffle-seeds", type=int, default=SHUFFLE_SEEDS)
    ap.add_argument("--bridge-n", type=int, default=BRIDGE_N, help="0 to skip bridge")
    ap.add_argument("--skip-scaffolds", action="store_true")
    ap.add_argument("--skip-cluster-rr", action="store_true")
    ap.add_argument("--refresh-cache", action="store_true")
    args = ap.parse_args()

    db = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/molecules")
    if args.refresh_cache:
        for slug in args.datasets:
            p = rq1.cache_dir() / f"{slug}.npz"
            if p.is_file():
                p.unlink()

    all_rows: list[dict] = []
    for slug in args.datasets:
        print(f"\n=== {slug} ===", flush=True)
        bundle = rq1.load_dataset(db, slug)
        n = len(bundle.ids)
        rng = np.random.default_rng(0)
        query_idx = (
            np.sort(rng.choice(n, size=min(rq1.FILL_QUERY_CAP, n), replace=False))
            if n > rq1.FILL_QUERY_CAP
            else np.arange(n, dtype=np.int64)
        )

        orders: dict[str, np.ndarray] = {
            "ranked": np.arange(n, dtype=np.int64),
        }
        for s in range(args.shuffle_seeds):
            # seed 42 matches original tile ablation; others are extra draws
            seed = rq1.SHUFFLE_SEED if s == 0 else (1000 + s)
            orders[f"shuffled_seed{seed}"] = rq1.shuffled_index_order(n, seed=seed)

        if not args.skip_cluster_rr:
            print("  building cluster_rr order…", flush=True)
            t0 = time.time()
            orders["cluster_rr"] = cluster_round_robin_order(
                bundle.cluster_ids, bundle.embeddings
            )
            print(f"  cluster_rr ready in {time.time() - t0:.1f}s", flush=True)

        rows = evaluate_orders(
            bundle,
            orders=orders,
            compute_scaffolds=not args.skip_scaffolds,
            query_idx=query_idx,
        )
        all_rows.extend(rows)

        if args.bridge_n > 0 and n >= args.bridge_n:
            print(f"\n=== bridge on {slug} (n={args.bridge_n}) ===", flush=True)
            all_rows.extend(
                run_bridge(bundle, args.bridge_n, compute_scaffolds=not args.skip_scaffolds)
            )

    agg = aggregate_shuffle(all_rows)
    root = out_dir()
    write_csv(all_rows, root / "rq1_large_raw.csv")
    write_csv(agg, root / "rq1_large_metrics.csv")
    plot_large(agg, root / "figures")
    write_analysis(agg, root / "rq1_large_analysis.md")
    meta = {
        "datasets": args.datasets,
        "shuffle_seeds": args.shuffle_seeds,
        "bridge_n": args.bridge_n,
    }
    (root / "rq1_large_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"\nWrote results under {root}", flush=True)


if __name__ == "__main__":
    main()
