# RQ1 large-dataset extension

Orders: **ranked** (pipeline FPS / hierarchical FPS), **cluster_rr** (round-robin over embedding clusters), **shuffled_mean** (mean over seeds).

Bridge: exact FPS vs hierarchical FPS vs one shuffle on a fixed subsample.

## zinc250k

At $k=5000$:

- **cluster_rr**: hmax=5.916, hmean=3.523, cov=1.000, red=0.898
- **ranked**: hmax=5.916, hmean=3.308, cov=1.000, red=0.867
- **shuffled_mean**: hmax=5.594, hmean=3.414, cov=1.000, red=0.746

## zinc250k_bridge25000

At $k=2000$:

- **exact_fps**: hmax=4.690, hmean=3.734, cov=1.000, red=0.648
- **hierarchical_fps**: hmax=5.657, hmean=3.306, cov=1.000, red=0.828
- **shuffled**: hmax=5.657, hmean=3.441, cov=1.000, red=0.749

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

