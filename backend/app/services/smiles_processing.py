from enum import Enum
from typing import Sequence

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, MACCSkeys

from .smiles_ranking import rank_molecules


class EmbeddingMethod(Enum):
    MACCS = "maccs"
    MORGAN = "morgan"
    CHEMBERT = "chembert"


# Output dimensionality of each embedding method. The database `embedding`
# column dimension must match the method actually used.
EMBEDDING_DIMS = {
    EmbeddingMethod.MACCS: 167,
    EmbeddingMethod.MORGAN: 2048,
    EmbeddingMethod.CHEMBERT: 768,
}


def _embed_mol(mol: Chem.Mol, method: EmbeddingMethod) -> np.ndarray:
    if method == EmbeddingMethod.MACCS:
        fp = MACCSkeys.GenMACCSKeys(mol)
    elif method == EmbeddingMethod.MORGAN:
        fp = AllChem.GetMorganFingerprintAsBitVect(mol, radius=2, nBits=EMBEDDING_DIMS[method])
    elif method == EmbeddingMethod.CHEMBERT:
        raise NotImplementedError("chembert is not implemented yet")
    else:
        raise ValueError(f"Unsupported embedding method: {method}")
    return np.array(fp, dtype=np.float32)


def embed_smiles(smiles: str, method: EmbeddingMethod = EmbeddingMethod.MACCS) -> np.ndarray:
    """Embed a single SMILES string into a fingerprint vector."""
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smiles!r}")
    return _embed_mol(mol, method)


def embed_many(
    smiles: Sequence[str],
    method: EmbeddingMethod = EmbeddingMethod.MACCS,
) -> tuple[np.ndarray, np.ndarray]:
    """Embed many SMILES, skipping any that RDKit cannot parse.

    Args:
        smiles: Iterable of SMILES strings.
        method: Embedding method to use.

    Returns:
        ``(kept_smiles, embeddings)`` where ``kept_smiles`` has shape ``(m,)``
        (object array of the SMILES that parsed) and ``embeddings`` has shape
        ``(m, dim)``. Order is preserved and the two arrays are row-aligned.
    """
    kept_smiles: list[str] = []
    vectors: list[np.ndarray] = []

    for smi in smiles:
        if not isinstance(smi, str) or not smi.strip():
            continue
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            continue
        kept_smiles.append(smi)
        vectors.append(_embed_mol(mol, method))

    if not vectors:
        return np.empty((0,), dtype=object), np.empty((0, EMBEDDING_DIMS[method]), dtype=np.float32)

    return np.array(kept_smiles, dtype=object), np.vstack(vectors).astype(np.float32)


def _gpu_umap_available() -> bool:
    """Return True if cuML's GPU UMAP can actually be used on this machine.

    cuML requires an NVIDIA GPU with compute capability >= 7.0. We check that
    cuML imports *and* that at least one CUDA device is visible; either being
    absent means we must fall back to CPU UMAP.
    """
    try:
        from cuml.manifold import UMAP  # noqa: F401
    except Exception:
        return False

    try:
        from numba import cuda

        return len(cuda.gpus) > 0
    except Exception:
        # cuML imported but we can't confirm a device; assume usable and let the
        # caller's runtime error handling deal with it if not.
        return True


def project_umap(
    embeddings: np.ndarray,
    *,
    n_components: int = 2,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    metric: str = "euclidean",
    random_state: int | None = None,
    use_gpu: bool | None = None,
) -> np.ndarray:
    """Project high-dimensional embeddings to 2D with UMAP.

    Prefers GPU-accelerated ``cuml.manifold.UMAP`` (RAPIDS) so it scales to the
    very large point counts this pipeline targets, and falls back to CPU
    ``umap.UMAP`` (umap-learn) when no compatible GPU is available. cuML needs an
    NVIDIA GPU with compute capability >= 7.0; imports are deferred so this
    module stays importable everywhere.

    Args:
        embeddings: Array of shape ``(n_molecules, n_features)``.
        n_components: Output dimensionality (2 for the map).
        n_neighbors: UMAP neighborhood size.
        min_dist: UMAP minimum distance.
        metric: Distance metric. ``"euclidean"`` is a safe default; ``"cosine"``
            often suits dense transformer embeddings.
        random_state: Seed for reproducibility. Note that fixing it forces
            single-threaded execution in some backends.
        use_gpu: Force the backend. ``True`` requires cuML, ``False`` forces CPU
            umap-learn, ``None`` (default) auto-detects.

    Returns:
        Array of shape ``(n_molecules, n_components)`` as float32.
    """
    X = np.asarray(embeddings, dtype=np.float32)
    if X.ndim != 2:
        raise ValueError(f"embeddings must be 2D (n_molecules, n_features), got shape {X.shape}")
    if X.shape[0] == 0:
        return np.empty((0, n_components), dtype=np.float32)

    if use_gpu is None:
        use_gpu = _gpu_umap_available()

    if use_gpu:
        from cuml.manifold import UMAP
    else:
        from umap import UMAP

    reducer = UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )
    projection = reducer.fit_transform(X)
    return np.asarray(projection, dtype=np.float32)


def process_smiles(
    smiles: Sequence[str],
    method: EmbeddingMethod = EmbeddingMethod.MACCS,
    *,
    umap_kwargs: dict | None = None,
    rank_kwargs: dict | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Run the full embed -> rank -> project pipeline.

    Returns:
        ``(kept_smiles, embeddings, projection, ranks)``, all row-aligned:
        - ``kept_smiles``: object array ``(m,)`` of parseable SMILES.
        - ``embeddings``: float32 ``(m, dim)``.
        - ``projection``: float32 ``(m, 2)`` UMAP coordinates.
        - ``ranks``: int64 ``(m,)`` representativeness ranks (1 = best).
    """
    kept_smiles, embeddings = embed_many(smiles, method)
    if kept_smiles.size == 0:
        return kept_smiles, embeddings, np.empty((0, 2), dtype=np.float32), np.empty((0,), dtype=np.int64)

    ranks = rank_molecules(embeddings, **(rank_kwargs or {}))
    projection = project_umap(embeddings, **(umap_kwargs or {}))
    return kept_smiles, embeddings, projection, ranks


def process_and_store(
    smiles: Sequence[str],
    method: EmbeddingMethod = EmbeddingMethod.MACCS,
    *,
    database_url: str | None = None,
    truncate: bool = False,
    umap_kwargs: dict | None = None,
    rank_kwargs: dict | None = None,
) -> int:
    """Run the full pipeline and persist the result to the database.

    Stores ``(smiles, embedding vector, 2D projection, rank)`` per molecule.

    Returns:
        The number of molecules stored.
    """
    from .smiles_database import store_molecules

    kept_smiles, embeddings, projection, ranks = process_smiles(
        smiles, method, umap_kwargs=umap_kwargs, rank_kwargs=rank_kwargs
    )
    if kept_smiles.size == 0:
        return 0

    return store_molecules(
        smiles=kept_smiles,
        embeddings=embeddings,
        projection=projection,
        ranks=ranks,
        database_url=database_url,
        truncate=truncate,
    )


def process_and_export(
    smiles: Sequence[str],
    method: EmbeddingMethod = EmbeddingMethod.MACCS,
    *,
    csv_path: str,
    sql_path: str | None = None,
    umap_kwargs: dict | None = None,
    rank_kwargs: dict | None = None,
) -> int:
    """Run the full pipeline and write a CSV (+ loader SQL) for bulk DB import.

    Use this on machines that cannot reach the database directly (e.g. HPC/Slurm
    compute nodes): the job writes files, which you later load into Postgres with
    ``psql "$DATABASE_URL" -f <sql_path>``.

    Returns:
        The number of molecules written.
    """
    from .smiles_database import export_molecules

    kept_smiles, embeddings, projection, ranks = process_smiles(
        smiles, method, umap_kwargs=umap_kwargs, rank_kwargs=rank_kwargs
    )
    if kept_smiles.size == 0:
        return 0

    return export_molecules(
        smiles=kept_smiles,
        embeddings=embeddings,
        projection=projection,
        ranks=ranks,
        csv_path=csv_path,
        sql_path=sql_path,
    )
