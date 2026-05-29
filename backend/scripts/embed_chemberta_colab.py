# ── Run in Google Colab (GPU runtime, T4) ──
# Cell 1: install deps
# !pip install datasets transformers torch tqdm numpy

import os
import numpy as np
import torch
from datasets import load_dataset
from transformers import AutoTokenizer, AutoModel
from tqdm import tqdm

DATASET = "edmanft/zinc250k"
SMILES_COL = "smiles"
SPLIT = "train"
LIMIT = 0  # 0 = all
BATCH_SIZE = 256
MODEL = "seyonec/ChemBERTa-zinc-base-v1"
OUTPUT = "zinc250k_chemberta.npz"

# ── 1. Load SMILES ──
print(f"Loading {DATASET} …")
ds = load_dataset(DATASET, split=SPLIT)
smiles_list = [s for s in ds[SMILES_COL] if isinstance(s, str) and s.strip()]
if LIMIT > 0:
    smiles_list = smiles_list[:LIMIT]
print(f"  {len(smiles_list)} molecules")

# ── 2. Load model ──
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")
tokenizer = AutoTokenizer.from_pretrained(MODEL)
model = AutoModel.from_pretrained(MODEL).to(device).eval()

# ── 3. Batched inference ──
embeddings = []

with torch.no_grad():
    for i in tqdm(range(0, len(smiles_list), BATCH_SIZE), desc="ChemBERTa"):
        batch = smiles_list[i : i + BATCH_SIZE]
        enc = tokenizer(batch, return_tensors="pt", padding=True,
                        truncation=True, max_length=256)
        enc = {k: v.to(device) for k, v in enc.items()}
        out = model(**enc)

        # mean pooling over tokens (mask-aware)
        hidden = out.last_hidden_state
        mask = enc["attention_mask"].unsqueeze(-1)
        pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
        embeddings.append(pooled.cpu().numpy().astype(np.float32))

X = np.concatenate(embeddings, axis=0)
smiles_arr = np.array(smiles_list[:X.shape[0]], dtype=object)

print(f"{X.shape[0]} molecules, embedding dim = {X.shape[1]}")
np.savez(OUTPUT, embeddings=X, smiles=smiles_arr)
print(f"Saved to {OUTPUT}")
