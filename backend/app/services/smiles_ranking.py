import math

import numpy as np


def rank_molecules(
    embeddings: np.ndarray,
    *,
    exact_threshold: int = 50_000,
    n_clusters: int | None = None,
    random_state: int = 42,
) -> np.ndarray:
    """Assign a representativeness rank to every molecule.

    Rank 1 is the best representative of the whole set; the largest rank is the
    worst (the "rank infinity" end of the scale). Taking every molecule with
    ``rank <= k`` yields a subset of size ``k`` that is spread across the
    embedding space -- exactly what a level-of-detail renderer wants when it
    cannot draw all points at once.

    Two strategies are used depending on the set size:

    * ``n <= exact_threshold``: exact farthest-point sampling (greedy k-center).
      O(n^2) but optimal coverage; used as the accuracy reference.
    * ``n > exact_threshold``: a near-linear hierarchical approximation that
      clusters the set, spreads the cluster representatives by farthest-point
      sampling, and interleaves within-cluster points. This is what scales to
      millions of molecules.

    Args:
        embeddings: Array of shape ``(n_molecules, n_features)``.
        exact_threshold: Largest ``n`` for which exact FPS is used.
        n_clusters: Number of clusters for the hierarchical path. Defaults to
            ``max(1024, isqrt(n))``, capped at ``n``.
        random_state: Seed for the clustering, for reproducible ranks.

    Returns:
        Integer array of shape ``(n_molecules,)`` with ranks in ``1..n``.
    """
    X = np.asarray(embeddings, dtype=np.float32)
    if X.ndim != 2:
        raise ValueError(f"embeddings must be 2D (n_molecules, n_features), got shape {X.shape}")

    n = X.shape[0]
    if n == 0:
        return np.empty((0,), dtype=np.int64)
    if n == 1:
        return np.array([1], dtype=np.int64)

    if n <= exact_threshold:
        order = _fps_order(X)
    else:
        order = _hierarchical_order(X, n_clusters=n_clusters, random_state=random_state)

    ranks = np.empty(n, dtype=np.int64)
    ranks[order] = np.arange(1, n + 1, dtype=np.int64)
    return ranks


def _fps_order(X: np.ndarray) -> np.ndarray:
    """Exact farthest-point sampling order (greedy k-center).

    Returns point indices in selection order: ``order[0]`` is the molecule
    closest to the centroid, and each subsequent index is the molecule farthest
    from everything already selected. O(n^2) in distance work.
    """
    n = X.shape[0]
    order = np.empty(n, dtype=np.int64)

    centroid = X.mean(axis=0, keepdims=True)
    start = int(np.argmin(np.sum((X - centroid) ** 2, axis=1)))

    # min_sq_dist[i] = squared distance from i to the nearest selected point.
    # Selected points are marked with a negative sentinel so argmax skips them.
    min_sq_dist = np.sum((X - X[start]) ** 2, axis=1)
    order[0] = start
    min_sq_dist[start] = -1.0

    for i in range(1, n):
        nxt = int(np.argmax(min_sq_dist))
        order[i] = nxt
        new_sq_dist = np.sum((X - X[nxt]) ** 2, axis=1)
        np.minimum(min_sq_dist, new_sq_dist, out=min_sq_dist)
        min_sq_dist[nxt] = -1.0

    return order


def _hierarchical_order(
    X: np.ndarray,
    *,
    n_clusters: int | None,
    random_state: int,
) -> np.ndarray:
    """Near-linear approximate farthest-point order for large sets.

    Steps:
      1. Cluster the molecules with mini-batch k-means (near-linear in ``n``).
      2. Order the cluster centroids by exact FPS so consecutive clusters cover
         distinct regions of the embedding space.
      3. Inside each cluster, order points by distance to their centroid
         (most typical first).
      4. Interleave clusters round-robin in centroid-FPS order: rank 1..K is one
         representative from each cluster (spread), the next layer adds a second
         representative per cluster, and so on.

    This keeps the level-of-detail property (every rank prefix is spread across
    space) while running in roughly O(n * n_clusters * iters) instead of O(n^2).
    """
    from sklearn.cluster import MiniBatchKMeans

    n = X.shape[0]
    if n_clusters is None:
        n_clusters = max(1024, math.isqrt(n))
    n_clusters = min(n_clusters, n)

    km = MiniBatchKMeans(
        n_clusters=n_clusters,
        random_state=random_state,
        batch_size=10_000,
        n_init=3,
    )
    labels = km.fit_predict(X)
    centroids = km.cluster_centers_

    # Spread the clusters: FPS over centroids (n_clusters is small, so O(K^2) is cheap).
    centroid_order = _fps_order(centroids)

    # Group point indices per cluster, each ordered by distance to its centroid.
    members_by_cluster: dict[int, np.ndarray] = {}
    for c in range(n_clusters):
        idx = np.flatnonzero(labels == c)
        if idx.size == 0:
            continue
        d = np.sum((X[idx] - centroids[c]) ** 2, axis=1)
        members_by_cluster[c] = idx[np.argsort(d, kind="stable")]

    # Round-robin interleave across clusters in centroid-FPS order.
    ordered_clusters = [c for c in centroid_order if c in members_by_cluster]
    order = np.empty(n, dtype=np.int64)
    pos = 0
    layer = 0
    remaining = n
    while remaining > 0:
        for c in ordered_clusters:
            members = members_by_cluster[c]
            if layer < members.size:
                order[pos] = members[layer]
                pos += 1
                remaining -= 1
        layer += 1

    return order
