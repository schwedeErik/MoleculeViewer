"""Visualize the molecule ranking algorithm (farthest-point sampling).

Run from backend/ (no RDKit needed — uses synthetic 2D points):

    pip install matplotlib numpy scikit-learn
    python scripts/visualize_ranking.py

Writes: scripts/ranking_algorithm_explainer.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from sklearn.cluster import KMeans

OUT = Path(__file__).resolve().parent / "ranking_algorithm_explainer.png"

# Marker sizes (matplotlib scatter `s` is area in points² — keep these small)
BG_PT = 8
HIGHLIGHT_PT = 28
HIGHLIGHT_LATEST_PT = 40
CENTROID_PT = 36


def _pad_limits(ax, pts: np.ndarray, pad: float = 0.12) -> None:
    """Add margin so points are not glued to the subplot border."""
    xmin, xmax = pts[:, 0].min(), pts[:, 0].max()
    ymin, ymax = pts[:, 1].min(), pts[:, 1].max()
    dx = max(xmax - xmin, 0.5)
    dy = max(ymax - ymin, 0.5)
    ax.set_xlim(xmin - pad * dx, xmax + pad * dx)
    ax.set_ylim(ymin - pad * dy, ymax + pad * dy)


def fps_order_2d(points: np.ndarray) -> list[int]:
    """Same logic as smiles_ranking._fps_order, on 2D points for plotting."""
    n = len(points)
    centroid = points.mean(axis=0)
    start = int(np.argmin(np.sum((points - centroid) ** 2, axis=1)))
    order = [start]
    min_sq = np.sum((points - points[start]) ** 2, axis=1)
    min_sq[start] = -1.0
    for _ in range(1, n):
        nxt = int(np.argmax(min_sq))
        order.append(nxt)
        new_sq = np.sum((points - points[nxt]) ** 2, axis=1)
        np.minimum(min_sq, new_sq, out=min_sq)
        min_sq[nxt] = -1.0
    return order


def make_synthetic_points(rng: np.random.Generator, n: int = 80) -> np.ndarray:
    """Three blobs in 2D — stands in for chemical embedding space."""
    centers = np.array([[0, 0], [5, 1], [2.5, 4.5]])
    per = n // 3
    chunks = [
        centers[i] + rng.normal(0, 0.45, size=(per, 2)) for i in range(3)
    ]
    extra = centers[0:1] + rng.normal(0, 0.45, size=(n - 3 * per, 2))
    return np.vstack(chunks + [extra])


def hierarchical_demo_order(
    points: np.ndarray, labels: np.ndarray, centroids: np.ndarray, k: int
) -> list[int]:
    """Mini version of hierarchical round-robin interleaving."""
    centroid_order = fps_order_2d(centroids)
    members: dict[int, list[int]] = {}
    for c in range(k):
        idx = np.where(labels == c)[0]
        if len(idx) == 0:
            continue
        d = np.sum((points[idx] - centroids[c]) ** 2, axis=1)
        members[c] = idx[np.argsort(d)].tolist()

    ordered_clusters = [c for c in centroid_order if c in members]
    order: list[int] = []
    layer = 0
    while len(order) < len(points):
        for c in ordered_clusters:
            if layer < len(members[c]):
                order.append(members[c][layer])
        layer += 1
    return order


def main() -> None:
    rng = np.random.default_rng(42)
    points = make_synthetic_points(rng, n=60)
    fps = fps_order_2d(points)

    k = 6
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(points)
    centroids = km.cluster_centers_
    hier = hierarchical_demo_order(points, labels, centroids, k)

    fig = plt.figure(figsize=(20, 11), constrained_layout=True)
    fig.suptitle(
        "Molecule ranking: spread representatives first (good rank = low number)",
        fontsize=16,
        fontweight="bold",
    )

    # More vertical space for plots; compact text band in the middle.
    gs = fig.add_gridspec(3, 5, height_ratios=[3.2, 0.5, 3.2], hspace=0.2, wspace=0.12)

    # --- Row 1: FPS step by step ---
    steps = [1, 2, 3, 5]
    colors = plt.cm.tab10(np.linspace(0, 1, 10))

    ax0 = fig.add_subplot(gs[0, 0])
    ax0.scatter(points[:, 0], points[:, 1], s=BG_PT, c="#cccccc", alpha=0.85, edgecolors="none")
    ax0.set_title("All molecules (2D embedding)", fontsize=11)
    _pad_limits(ax0, points)
    ax0.set_aspect("equal")
    ax0.axis("off")

    for i, step in enumerate(steps):
        ax = fig.add_subplot(gs[0, i + 1])
        ax.scatter(points[:, 0], points[:, 1], s=BG_PT, c="#dddddd", alpha=0.55, edgecolors="none")
        selected = fps[:step]
        for rank, idx in enumerate(selected, start=1):
            ax.scatter(
                points[idx, 0],
                points[idx, 1],
                s=HIGHLIGHT_LATEST_PT if rank == step else HIGHLIGHT_PT,
                c=[colors[rank - 1]],
                edgecolors="black",
                linewidths=0.5,
                zorder=5,
            )
            if rank == step:
                ax.annotate(
                    f"rank {rank}",
                    (points[idx, 0], points[idx, 1]),
                    xytext=(4, 4),
                    textcoords="offset points",
                    fontsize=8,
                    fontweight="bold",
                )
        ax.set_title(f"After rank {step}", fontsize=11)
        _pad_limits(ax, points)
        ax.set_aspect("equal")
        ax.axis("off")

    # --- Row 2: intuition ---
    ax_text = fig.add_subplot(gs[1, :])
    ax_text.axis("off")
    ax_text.text(
        0.02, 0.92,
        "Exact mode (≤ 50k): Farthest-Point Sampling  ·  "
        "Rank 1 = closest to centroid  ·  "
        "Rank 2+ = farthest from already chosen  ·  "
        "Low rank = draw first  ·  High rank = redundant",
        fontsize=10,
        va="top",
        family="monospace",
        bbox=dict(boxstyle="round", facecolor="#f5f5f5", edgecolor="#ccc"),
    )

    # --- Row 3: hierarchical for millions ---
    cluster_colors = plt.cm.tab10(labels / max(k - 1, 1))
    ax_h1 = fig.add_subplot(gs[2, 0])
    ax_h1.scatter(
        points[:, 0], points[:, 1], s=BG_PT, c=cluster_colors, alpha=0.75, edgecolors="none"
    )
    for c in range(k):
        ax_h1.scatter(
            centroids[c, 0],
            centroids[c, 1],
            s=CENTROID_PT,
            c="black",
            marker="X",
            linewidths=0.8,
            zorder=5,
        )
        ax_h1.annotate(
            str(c),
            (centroids[c, 0], centroids[c, 1]),
            xytext=(3, 3),
            textcoords="offset points",
            fontsize=7,
            fontweight="bold",
        )
    ax_h1.set_title("Step A: cluster (k-means)", fontsize=11)
    _pad_limits(ax_h1, points)
    ax_h1.set_aspect("equal")
    ax_h1.axis("off")

    ax_h2 = fig.add_subplot(gs[2, 1:3])
    ax_h2.scatter(points[:, 0], points[:, 1], s=BG_PT, c="#dddddd", alpha=0.5, edgecolors="none")
    co = fps_order_2d(centroids)
    for r, ci in enumerate(co[:k], start=1):
        ax_h2.scatter(
            centroids[ci, 0], centroids[ci, 1], s=CENTROID_PT, c=[colors[r - 1]],
            edgecolors="black", linewidths=0.5,
        )
        ax_h2.annotate(
            str(r), (centroids[ci, 0], centroids[ci, 1]),
            ha="center", va="center", fontsize=7, color="white", fontweight="bold",
        )
    ax_h2.set_title("Step B: FPS on cluster centroids", fontsize=11)
    _pad_limits(ax_h2, points)
    ax_h2.set_aspect("equal")
    ax_h2.axis("off")

    ax_h3 = fig.add_subplot(gs[2, 3:5])
    ax_h3.scatter(points[:, 0], points[:, 1], s=BG_PT, c="#dddddd", alpha=0.5, edgecolors="none")
    top = hier[:k]
    for rank, idx in enumerate(top, start=1):
        ax_h3.scatter(
            points[idx, 0], points[idx, 1], s=HIGHLIGHT_PT, c=[colors[rank - 1]],
            edgecolors="black", linewidths=0.5,
        )
        ax_h3.annotate(
            str(rank), (points[idx, 0], points[idx, 1]),
            ha="center", va="center", fontsize=7, color="white", fontweight="bold",
        )
    ax_h3.set_title(f"Step C: ranks 1–{k} = one per cluster (round-robin)", fontsize=11)
    _pad_limits(ax_h3, points)
    ax_h3.set_aspect("equal")
    ax_h3.axis("off")

    fig.savefig(OUT, dpi=200, bbox_inches="tight", pad_inches=0.1)
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
