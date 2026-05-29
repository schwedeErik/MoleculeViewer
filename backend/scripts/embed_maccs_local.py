"""
Run locally: computes MACCS fingerprints and saves to .npz.
Upload the output file to Colab for UMAP projection.

    pip install datasets rdkit-pypi tqdm numpy
    python embed_maccs_local.py
"""
from multiprocessing import Pool, cpu_count

import numpy as np
from datasets import load_dataset
from rdkit import Chem
from rdkit.Chem import MACCSkeys
from tqdm import tqdm

DATASET = "fabikru/chembl-2025-randomized-smiles-cleaned-explicit-hs"
SMILES_COL = "smiles"
SPLIT = "train"
LIMIT = 1_000_000 # 0 = all
OUTPUT = "chembl1m_maccs.npz"
N_WORKERS = cpu_count()


def _process(smi):
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        return None
    return smi, np.array(MACCSkeys.GenMACCSKeys(mol), dtype=np.int8)


print(f"Loading {DATASET} …")
ds = load_dataset(DATASET, split=SPLIT)
smiles_list = [s for s in ds[SMILES_COL] if isinstance(s, str) and s.strip()]
if LIMIT > 0:
    smiles_list = smiles_list[:LIMIT]

print(f"Computing MACCS keys for {len(smiles_list)} molecules ({N_WORKERS} workers) …")
kept_smiles = []
fps = []

with Pool(N_WORKERS) as pool:
    for result in tqdm(pool.imap(_process, smiles_list, chunksize=512),
                       total=len(smiles_list), desc="MACCS keys"):
        if result is not None:
            kept_smiles.append(result[0])
            fps.append(result[1])

X = np.vstack(fps).astype(np.float32)
smiles_arr = np.array(kept_smiles, dtype=object)

np.savez(OUTPUT, embeddings=X, smiles=smiles_arr)
print(f"Done – {X.shape[0]} molecules, dim={X.shape[1]} → {OUTPUT}")
