# RQ2 Analysis: Deepscatter vs deck.gl MVT (PMTiles)

Protocol: LOD step **3**, Deepscatter order **ranked**, MVT uses precomputed PMTiles (not live SQL).

Fairness note: LOD step 3 maps to Deepscatter `max_points=75_000` but MVT `rank_max` depends on zoom; cold-load measures asset fetch cost, not identical visual density.

## Offline asset size

| Dataset | Deepscatter ranked | MVT lod 1–6 | lod_3 only |
|---------|-------------------|-------------|------------|
| zinc10k | 0.4 MB | 13.5 MB | 2.3 MB |
| zinc250k | 10.0 MB | 257.6 MB | 41.1 MB |
| chembl13m | 54.5 MB | 1206.6 MB | 168.3 MB |

## Online cold load (median)

| Dataset | Renderer | Time (s) | Transfer (MB) |
|---------|----------|----------|---------------|
| chembl13m | deepscatter | 0.64 | 54.48 |
| chembl13m | mvt_pmtiles | 0.88 | 168.28 |
| zinc10k | deepscatter | 0.04 | 0.42 |
| zinc10k | mvt_pmtiles | 0.02 | 2.28 |
| zinc250k | deepscatter | 0.17 | 10.01 |
| zinc250k | mvt_pmtiles | 0.23 | 41.12 |

## Interpretation

Deepscatter ranked trees are substantially smaller on disk than the full PMTiles LOD ladder, because MVT archives duplicate spatial tiles across six LOD aggressiveness levels. Cold transfer for MVT lod_3 is dominated by the single archive size; Deepscatter overview fetches a shallow subset of feathers.

