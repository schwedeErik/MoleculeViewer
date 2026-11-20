# RQ1 large-dataset extension

Orders: **ranked** (pipeline FPS / hierarchical FPS), **cluster_rr** (round-robin over embedding clusters), **shuffled_mean** (mean over seeds).

Bridge: exact FPS vs hierarchical FPS vs one shuffle on a fixed subsample.

## chembl13m

At $k=10000$:

- **cluster_rr**: hmax=6.245, hmean=3.662, cov=1.000, red=0.937
- **ranked**: hmax=6.245, hmean=3.364, cov=1.000, red=0.901
- **shuffled_mean**: hmax=5.854, hmean=3.290, cov=1.000, red=0.743

## chembl13m_bridge25000

At $k=2000$:

- **exact_fps**: hmax=4.899, hmean=3.900, cov=1.000, red=0.644
- **hierarchical_fps**: hmax=6.000, hmean=3.375, cov=1.000, red=0.840
- **shuffled**: hmax=6.325, hmean=3.509, cov=1.000, red=0.741

