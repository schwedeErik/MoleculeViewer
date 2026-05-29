import os
from multiprocessing import Pool, cpu_count

import numpy as np
import matplotlib.pyplot as plt
from cuml.manifold import UMAP

EMBEDDINGS_FILE = "zinc250k_maccs.npz"
N_WORKERS = cpu_count()


def _smiles_to_maccs(smi: str):
    """Worker function — runs in a separate process."""
    from rdkit import Chem
    from rdkit.Chem import MACCSkeys
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return smi, np.array(MACCSkeys.GenMACCSKeys(mol), dtype=np.int8)


def load_or_compute_maccs(path=EMBEDDINGS_FILE):
    """Load cached MACCS fingerprints from disk, or compute and save them."""
    if os.path.exists(path):
        print(f"Loading cached embeddings from {path} …")
        data = np.load(path, allow_pickle=True)
        return data["embeddings"].astype(np.float32), data["smiles"]

    from datasets import load_dataset
    from tqdm import tqdm

    ds = load_dataset("edmanft/zinc250k", split="train")
    smiles_list = [s for s in ds["smiles"] if isinstance(s, str) and s.strip()]

    print(f"Computing MACCS keys with {N_WORKERS} workers …")
    kept_smiles = []
    fps = []
    with Pool(N_WORKERS) as pool:
        for result in tqdm(pool.imap(_smiles_to_maccs, smiles_list, chunksize=512),
                           total=len(smiles_list), desc="MACCS keys"):
            if result is not None:
                kept_smiles.append(result[0])
                fps.append(result[1])

    X = np.vstack(fps).astype(np.float32)
    smiles_arr = np.array(kept_smiles, dtype=object)

    np.savez(path, embeddings=X, smiles=smiles_arr)
    print(f"Saved embeddings to {path}")
    return X, smiles_arr

X, smiles_arr = load_or_compute_maccs()
print(f"{X.shape[0]} molecules, fingerprint dim = {X.shape[1]}")

# ── 3. Project to 2D with UMAP (GPU via cuML) ──
print("Running UMAP on GPU …")
reducer = UMAP(n_components=2, n_neighbors=25, min_dist=0.1, random_state=42)
Y = reducer.fit_transform(X)
Y = np.asarray(Y, dtype=np.float32)
print(f"UMAP done – projected shape: {Y.shape}")

np.savez("zinc250k_maccs_umap2d.npz", points=Y, smiles=smiles_arr)
print("Saved 2D projection to zinc250k_maccs_umap2d.npz")

# ── 4. Scatter plot ──
plt.figure(figsize=(10, 8))
plt.scatter(Y[:, 0], Y[:, 1], s=0.3, alpha=0.4, edgecolors="none")
plt.xlabel("UMAP dim 1")
plt.ylabel("UMAP dim 2")
plt.title(f"ZINC250K – MACCS keys + UMAP  ({Y.shape[0]} molecules)")
plt.tight_layout()
plt.savefig("zinc250k_maccs_umap2d.png", dpi=150)
plt.show()
print("Saved plot to zinc250k_maccs_umap2d.png")
