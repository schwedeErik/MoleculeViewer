# ── Colab / local script ──
# Downloads 1M precomputed ChemBERTa embeddings from PubChem FAISS library,
# projects to 2D with UMAP, and visualizes.
#
# pip install huggingface_hub pandas pyarrow umap-learn matplotlib numpy tqdm requests

import struct
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import requests
from huggingface_hub import hf_hub_url
from tqdm import tqdm
from umap import UMAP

REPO = "YinkaiW/pubchem-faiss-library"
N_MOLECULES = 1_000_000

# ── 1. Partial download of .npy (only first N rows) ──

def partial_load_npy(repo_id: str, filename: str, n_rows: int) -> np.ndarray:
    """Download only the first n_rows from a remote .npy file via byte-range requests."""
    url = hf_hub_url(repo_id, filename, repo_type="dataset")

    # read .npy header (first 4 KB is plenty)
    resp = requests.get(url, headers={"Range": "bytes=0-4095"}, timeout=30)
    resp.raise_for_status()
    raw = resp.content

    assert raw[:6] == b"\x93NUMPY", "Not a valid .npy file"
    major = raw[6]
    if major == 1:
        header_len = struct.unpack("<H", raw[8:10])[0]
        data_offset = 10 + header_len
    else:
        header_len = struct.unpack("<I", raw[8:12])[0]
        data_offset = 12 + header_len

    header_str = raw[10 : 10 + header_len] if major == 1 else raw[12 : 12 + header_len]
    header_dict = eval(header_str.decode().strip())
    dtype = np.dtype(header_dict["descr"])
    shape = header_dict["shape"]
    cols = shape[1] if len(shape) > 1 else 1

    n = min(n_rows, shape[0])
    row_bytes = cols * dtype.itemsize
    total_bytes = n * row_bytes

    print(f"  Remote array: shape={shape}, dtype={dtype}")
    print(f"  Downloading first {n:,} rows ({total_bytes / 1e9:.2f} GB) …")

    # stream in 64 MB chunks
    chunk_size = 64 * 1024 * 1024
    start = data_offset
    end = start + total_bytes - 1
    buf = bytearray()

    with requests.get(url, headers={"Range": f"bytes={start}-{end}"}, stream=True, timeout=600) as r:
        r.raise_for_status()
        for chunk in tqdm(r.iter_content(chunk_size=chunk_size),
                          total=(total_bytes // chunk_size) + 1, desc="Downloading"):
            buf.extend(chunk)

    return np.frombuffer(bytes(buf), dtype=dtype).reshape(n, cols)


# ── 2. Download SMILES metadata ──

def load_smiles(repo_id: str, n_rows: int) -> np.ndarray:
    """Download meta.parquet and extract SMILES for the first n_rows."""
    url = hf_hub_url(repo_id, "meta.parquet", repo_type="dataset")
    print(f"  Downloading meta.parquet …")
    df = pd.read_parquet(url, columns=["smiles"])
    smiles = df["smiles"].values[:n_rows]
    print(f"  Loaded {len(smiles):,} SMILES")
    return smiles


# ── 3. Run ──

print(f"Loading {N_MOLECULES:,} ChemBERTa embeddings from {REPO} …")
X = partial_load_npy(REPO, "vectors_chem.npy", N_MOLECULES)
print(f"  Embeddings: {X.shape}")

print("Loading SMILES …")
smiles_arr = load_smiles(REPO, N_MOLECULES)

# save raw embeddings + smiles
np.savez("pubchem1m_chemberta.npz", embeddings=X, smiles=smiles_arr)
print("Saved embeddings to pubchem1m_chemberta.npz")

# ── 4. UMAP projection ──
print("Running UMAP (this may take 5–15 min on CPU) …")
reducer = UMAP(n_components=2, n_neighbors=25, min_dist=0.1, metric="cosine", random_state=42)
Y = reducer.fit_transform(X).astype(np.float32)
print(f"UMAP done – shape: {Y.shape}")

np.savez("pubchem1m_chemberta_umap2d.npz", points=Y, smiles=smiles_arr)
print("Saved 2D projection to pubchem1m_chemberta_umap2d.npz")

# ── 5. Scatter plot ──
plt.figure(figsize=(10, 8))
plt.scatter(Y[:, 0], Y[:, 1], s=0.1, alpha=0.3, edgecolors="none")
plt.xlabel("UMAP dim 1")
plt.ylabel("UMAP dim 2")
plt.title(f"PubChem – ChemBERTa + UMAP ({Y.shape[0]:,} molecules)")
plt.tight_layout()
plt.savefig("pubchem1m_chemberta_umap2d.png", dpi=150)
plt.show()
print("Saved plot to pubchem1m_chemberta_umap2d.png")
