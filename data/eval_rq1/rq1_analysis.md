# RQ1 Analysis: Importance Order vs Shuffled Order

Prefixes $P_k$ approximate coarse Deepscatter views: **ranked** = pipeline
importance order; **shuffled** = same molecules with seed-42 row permutation
(same as the Deepscatter tile ablation).

## Setup

| Dataset | $n$ | Embedding | Clusters $K$ | Shuffle seed |
|---------|-----|-----------|--------------|--------------|
| zinc10k | 10,000 | MACCS (167) | 100 | 42 |
| zinc250k | 249,455 | MACCS (167) | 100 | 42 |
| chembl13m | 1,358,976 | MACCS (167) | 100 | 42 |

Fill distance uses Euclidean distance in the MACCS embedding (consistent with
FPS ranking) against a query subsample of ≤20,000 molecules.
Scaffold counts use Bemis–Murcko frameworks (RDKit) for $k≤20{,}000$.

## Coverage: fill distance

FPS / $k$-center ranking **optimizes covering radius** ($h_{\max}$), not mean
distance. Results:

### zinc10k (exact FPS, $n≤50$k threshold)

| $k$ | fill_max ranked | fill_max shuffled | fill_mean ranked | fill_mean shuffled |
|-----|-----------------|-------------------|------------------|--------------------|
| 100 | **5.92** | 6.48 | 5.05 | **4.62** |
| 1,000 | **4.80** | 5.75 | 3.81 | **3.56** |
| 5,000 | **3.74** | 5.39 | **1.67** | 1.74 |

**Ranked clearly wins on $h_{\max}$** (the FPS objective). Mean fill can favour
shuffle at small $k$ because FPS spreads outliers first while random may land
near denser regions on average.

### zinc250k / chembl13m (hierarchical ranking)

At coarse $k$, ranked often wins **mean** fill on zinc250k (e.g.\ +5.7% at
$k=2{,}000$) and at small $k$ on ChemBL, but **$max$ fill is mixed** and can
favour shuffle at larger prefixes. Hierarchical FPS approximates global
$k$-center; it does not guarantee the same covering-radius dominance as exact
FPS on zinc10k.

## Diversity: scaffolds and redundancy

- **zinc10k:** ranked has **lower** NN-Tanimoto redundancy (0.63 vs 0.72 at
  $k=1{,}000$) — fewer near-duplicates in the overview. Scaffold counts are
  similar.
- **zinc250k / chembl13m:** shuffle often yields **more unique scaffolds** and
  **lower** redundancy at the same $k$. Hierarchical ranking interleaves
  within-cluster points after placing representatives, so early prefixes can
  still look locally crowded in fingerprint space while random samples more
  chemotypes by chance.

Cluster coverage saturates quickly ($K=100$) for both orders once $k\gtrsim 500$.

## Interpretation for RQ1

1. **Exact FPS (small $n$) improves worst-case coverage** ($h_{\max}$) vs random
   order — direct support for RQ1 under the metric FPS optimizes.
2. **On million-scale hierarchical ranking the chemical win is nuanced:** mean
   coverage sometimes improves, but scaffold diversity and low redundancy are
   not automatically better than random prefixes. Deepscatter overviews may
   still *look* more structured because early points are chemically
   representative *centers*, not because they maximize Murcko counts.
3. **Practical takeaway:** importance order is the right Deepscatter file order
   for LOD semantics and for FPS-style coverage on moderate libraries; for
   large libraries, report $h_{\max}$ / qualitative maps alongside scaffold
   counts, and consider diversity-aware ranking variants if chemotype count is
   the primary goal.

## Figures

Generated under `data/eval_rq1/figures/` (also copied to `latex_thesis/gfx/eval_rq1/`):

- `rq1_fill_mean.png` / `rq1_fill_max.png` — coverage vs $k$
- `rq1_cluster_coverage.png`
- `rq1_scaffolds_per_point.png`
- `rq1_redundancy_nn_tanimoto.png`
- `rq1_relative_fill_gain.png` — % mean-fill gain of ranked vs shuffled

## How to reproduce

```bash
cd webAPP/backend
source .venv/bin/activate
export DATABASE_URL=postgresql://app:app@localhost:5432/molecules
python -m scripts.eval_rq1 --datasets zinc10k zinc250k chembl13m
```

## Limitations

- $P_k$ proxies Deepscatter $S_z$ (no spatial tile clipping).
- Fill queries use a ≤20k subsample.
- Scaffolds only for $k≤20$k.
- Large-$n$ ranks use hierarchical FPS, not exact $k$-center.
