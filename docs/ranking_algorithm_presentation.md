---
marp: true
theme: default
paginate: true
header: "Molecule Map — Ranking Algorithm"
footer: "Thesis · Chemical Space Visualization"
style: |
  section { font-size: 28px; }
  h1 { color: #1a73e8; }
  h2 { color: #333; }
  table { font-size: 22px; }
  code { font-size: 20px; }
---

# Ranking Molecules for Large-Scale Chemical Maps

**Representativeness-based level of detail for 10M+ molecules**

Thesis project · Molecule Map (deck.gl + PostGIS)

---

## Motivation

- Goal: a **Google Maps–like** interface for **chemical space**
- Each molecule has a high-dimensional **embedding** (MACCS, Morgan, ChemBERTa)
- **UMAP** projects embeddings to 2D for visualization
- Problem: we cannot render **all** points at once

| Scale | Challenge |
|-------|-----------|
| 250K | Feasible to overplot |
| 1M+ | Screen has ~2M pixels; points overlap |
| 10M+ | Must **choose** what to draw per viewport |

**Need:** a **rank** per molecule — *which points matter most when budget is limited?*

---

## What “rank” means

- **Rank 1** = best representative of the whole set
- **Low ranks** = important, diverse, should be drawn **first**
- **High ranks** = redundant, near an already-chosen representative (“rank → ∞”)
- Every molecule gets a **unique** rank: `1, 2, 3, …, n` (no duplicates)

**Rendering rule:** show only molecules with `rank ≤ k` (budget `k` depends on zoom / viewport)

---

## Design goal

When the user sees the map at low zoom, they should see molecules that:

1. **Cover** different regions of chemical space (not one dense blob)
2. **Represent** their local neighborhood (typical / central within a region)
3. **Scale** to millions of molecules in reasonable compute time

This is a **budgeted selection** problem, not random subsampling.

---

## Core idea: Farthest Point Sampling (FPS)

**FPS** = greedy spread-out selection (also called *greedy k-center*)

1. **Rank 1:** molecule closest to the **centroid** of all embeddings
2. **Rank 2:** molecule **farthest** from rank 1
3. **Rank 3:** molecule farthest from {rank 1, rank 2}
4. Repeat until all `n` molecules are ordered

**Intuition:** always add the point in the **least-covered** region next.

---

## FPS — visual intuition

```
     rank 2 ●
                    rank 3 ●

        rank 1 ●  (near center)

   rank 4 ●              rank 5 ●
```

- Early picks → **spread** across space
- Late picks → sit **next to** someone already chosen → high rank

Taking `rank ≤ 5` gives 5 maximally spread representatives.

---

## Why FPS fits a chemical map

| Property | Benefit for visualization |
|----------|---------------------------|
| Spread-first ordering | Low zoom shows **global** structure |
| Unique ranks | Simple SQL filter: `WHERE rank <= :budget` |
| Redundancy at end | Near-duplicate SMILES naturally get **bad** ranks |
| Prefix property | `rank ≤ k` is always a **representative** subset of size `k` |

---

## Two algorithmic paths

```
                    n molecules
                         │
              n ≤ 50,000? ──yes──► Exact FPS on all points
                         │
                         no
                         │
              Hierarchical approximation
              (cluster → FPS → interleave)
```

| Path | When | Quality | Cost |
|------|------|---------|------|
| **Exact FPS** | n ≤ 50k | Optimal spread | O(n²) |
| **Hierarchical** | n > 50k | Approximate | ~O(n · K) |

Threshold `50,000` is configurable (`exact_threshold`).

---

## Path A — Exact FPS (detail)

**Input:** embedding matrix `X` with shape `(n, d)`

```
centroid ← mean of all rows
start    ← argmin distance(row, centroid)     → rank 1

min_dist[i] ← distance from point i to nearest selected point

repeat until all n selected:
    next ← argmax(min_dist)                    → next rank
    update min_dist using distance to next
```

**Output:** `order[0..n-1]` then `ranks[order[i]] = i + 1`

**Used as:** accuracy reference for smaller datasets.

---

## Path B — Why not exact FPS at 10M?

For `n = 10,000,000`, `d = 167` (MACCS):

- Each FPS iteration scans all `n` points
- ~`n²` distance work → **weeks to months** on CPU
- Memory: repeated full-matrix passes

**Solution:** approximate FPS via **hierarchical decomposition**

1. Cluster into `K` regions (cheap, linear-ish)
2. Run **exact FPS on K centroids** only (K is small)
3. Pick molecules **inside** clusters in a structured order

---

## Path B — Step 1: Clustering

**Mini-batch k-means** on all `n` embeddings

- Assigns each molecule a cluster label `0 … K-1`
- Computes cluster **centroids** (region centers in embedding space)
- Near-linear in `n` for fixed `K`
- Reproducible via `random_state=42`

Clusters ≈ **coarse chemical regions** in embedding space.

---

## Path B — How many clusters K?

**Not fixed** — scales with dataset size:

```
K = min( max(1024, √n), n )
```

| n | √n | K used |
|---|-----|--------|
| 100,000 | 316 | 1,024 |
| 1,000,000 | 1,000 | 1,024 |
| 10,000,000 | 3,162 | 3,162 |

**Why √n?** Sublinear growth: more regions for larger data, but K ≪ n so clustering stays feasible.

**Override:** `rank_molecules(X, n_clusters=5000)`

---

## Why √n? (rationale)

1. **Ranks 1…K** = one rep per cluster → K controls overview resolution
2. **Average cluster size** `n/K ≈ √n` when `K ≈ √n`
3. **Cost:** k-means ~`O(n·K)`; FPS on centroids ~`O(K²)` — both manageable
4. **Floor 1024:** even at n=100k, we keep ≥1024 regions (not only ~316)

This is an **engineering heuristic** — tunable and evaluable in the thesis.

---

## Path B — Step 2: FPS on centroids

Run **exact FPS** on the `K` cluster centroids (not all `n` points)

- Orders clusters by **spatial spread**
- `centroid_order[0]` = most central cluster
- `centroid_order[1]` = cluster farthest from first
- etc.

Cost: `O(K²)` — cheap because `K ≈ 3000`, not 10M.

---

## Path B — Step 3: Within-cluster ordering

For each cluster `c`:

- Collect all member molecules
- Sort by distance to **centroid[c]**
- Closest first = **most typical** molecule in that region

Each cluster has an ordered list: `[best, 2nd best, 3rd best, …]`

---

## Path B — Step 4: Round-robin interleaving

Walk clusters in **centroid FPS order**, one layer at a time:

| Rank | Molecule taken from |
|------|---------------------|
| 1 | best in cluster A (most spread cluster) |
| 2 | best in cluster B |
| 3 | best in cluster C |
| … | … |
| K | best in cluster K |
| K+1 | 2nd-best in cluster A |
| K+2 | 2nd-best in cluster B |
| … | … |

**Key property:** ranks `1…K` always span **K different regions** before any region gets a second point.

---

## Round-robin — example (K = 4)

```
Layer 0:  rank 1←A₁   rank 2←B₁   rank 3←C₁   rank 4←D₁
Layer 1:  rank 5←A₂   rank 6←B₂   rank 7←C₂   rank 8←D₂
Layer 2:  rank 9←A₃   ...
```

Preserves **spread at every prefix** of the ranking — important for level-of-detail rendering.

---

## From order to ranks

Both paths produce a **selection order** `order` (length `n`):

```
order[0]   = index of rank-1 molecule
order[1]   = index of rank-2 molecule
...
order[n-1] = index of rank-n molecule

ranks[ order[i] ] = i + 1
```

**Guarantee:** `ranks` is a permutation of `{1, 2, …, n}` — every rank appears exactly once.

---

## Integration in the pipeline

```
SMILES
  → embed (MACCS / Morgan / ChemBERTa)
  → rank_molecules(embeddings)     ← this algorithm
  → project_umap(embeddings)       → 2D coordinates
  → store (smiles, embedding, rank, geom)
```

**Offline (HPC / Slurm):** batch job writes CSV for PostgreSQL bulk load.

**Online (FastAPI + deck.gl):** viewport query with `rank ≤ budget`.

---

## Database & rendering

**Stored per molecule:**

| Field | Role |
|-------|------|
| `smiles` | identity |
| `embedding` | pgvector, similarity / future features |
| `rank` | importance for LOD |
| `geom` | PostGIS point (UMAP x, y as lng/lat) |

**Query pattern:**
```sql
SELECT ... FROM molecules
WHERE geom && viewport_envelope
  AND rank <= :rank_max
ORDER BY rank ASC
LIMIT :pixel_budget;
```

---

## Complexity summary

| Step | Exact path | Hierarchical path |
|------|------------|-------------------|
| Clustering | — | O(n · K · iters) |
| FPS | O(n² · d) | O(K² · d) on centroids |
| Within-cluster sort | — | O(n log(n/K)) per cluster |
| **Feasible at 10M?** | No | Yes |

| n | Exact FPS (est.) | Hierarchical (est.) |
|---|------------------|---------------------|
| 50K | seconds–minutes | overkill |
| 1M | hours | minutes |
| 10M | infeasible | tens of minutes |

---

## Parameters (thesis evaluation knobs)

| Parameter | Default | Effect |
|-----------|---------|--------|
| `exact_threshold` | 50,000 | Switch exact vs hierarchical |
| `n_clusters` | max(1024, √n) | Finer regions → better spread at low ranks |
| `random_state` | 42 | Reproducible k-means |
| Distance | Euclidean on embeddings | Could compare Tanimoto for fingerprints |

**Possible experiments:** rank stability, coverage metrics, comparison to random / density-only ranking.

---

## Limitations & future work

**Current limitations:**
- Hierarchical path is an **approximation** of global FPS
- k-means assumes roughly spherical clusters in embedding space
- Euclidean distance may be suboptimal for binary fingerprints (Tanimoto)
- Global rank is **precomputed** — not yet viewport-adaptive

**Future work (thesis scope):**
- Viewport-local re-ranking or rank refinement on zoom
- Multi-resolution tile pyramids keyed by rank
- Chemical diversity metrics (scaffold / Murcko) in the objective
- Ablation: exact vs hierarchical quality at n ≈ 100k

---

## Summary

1. **Problem:** 10M molecules, finite pixels → must rank what to show
2. **Rank 1 = best representative; high rank = redundant**
3. **FPS** greedily maximizes spread in embedding space
4. **Small n:** exact FPS (reference quality)
5. **Large n:** cluster → FPS on centroids → round-robin interleave
6. **K ≈ √n** balances resolution and compute
7. **Unique ranks 1…n** enable simple LOD queries for deck.gl

---

## Questions?

**Demo assets:**
- Code: `backend/app/services/smiles_ranking.py`
- Pipeline: `backend/scripts/build_map_dataset.py`
- Figure: `python scripts/visualize_ranking.py` → PNG explainer

**Thank you**
