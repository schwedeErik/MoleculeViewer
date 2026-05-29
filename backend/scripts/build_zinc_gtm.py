from __future__ import annotations

import argparse
import os
import random
from typing import Iterable

import numpy as np
import psycopg
import torch
from datasets import load_dataset
from tqdm import tqdm
from transformers import AutoModel, AutoTokenizer
from ugtm import eGTM


def batched(it: Iterable[str], batch_size: int) -> Iterable[list[str]]:
    batch: list[str] = []
    for x in it:
        batch.append(x)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5432/molecules"))
    ap.add_argument("--dataset", default="zinc", help="HuggingFace dataset name containing SMILES")
    ap.add_argument("--smiles-column", default="smiles", help="Column name for SMILES")
    ap.add_argument("--split", default="train")
    ap.add_argument("--limit", type=int, default=200_000, help="How many molecules to process (start small)")
    ap.add_argument("--batch-size", type=int, default=128)
    ap.add_argument("--rank-max", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default="seyonec/ChemBERTa-zinc-base-v1")
    args = ap.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    ds = load_dataset(args.dataset, split=args.split)
    if args.smiles_column not in ds.column_names:
        raise SystemExit(f"SMILES column '{args.smiles_column}' not found. Columns: {ds.column_names}")

    smiles_list = [s for s in ds[args.smiles_column] if isinstance(s, str)]
    smiles_list = smiles_list[: args.limit]
    if not smiles_list:
        raise SystemExit("No SMILES found.")

    tok = AutoTokenizer.from_pretrained(args.model)
    mdl = AutoModel.from_pretrained(args.model)
    mdl.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    mdl.to(device)

    emb: list[np.ndarray] = []
    kept_smiles: list[str] = []

    with torch.no_grad():
        for batch in tqdm(list(batched(smiles_list, args.batch_size)), desc="ChemBERTa embeddings"):
            enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=256)
            enc = {k: v.to(device) for k, v in enc.items()}
            out = mdl(**enc)
            # Mean pooling over tokens (mask-aware)
            last = out.last_hidden_state  # [B, T, H]
            mask = enc["attention_mask"].unsqueeze(-1)  # [B, T, 1]
            summed = (last * mask).sum(dim=1)
            denom = mask.sum(dim=1).clamp(min=1)
            pooled = (summed / denom).detach().cpu().numpy().astype(np.float32)
            emb.append(pooled)
            kept_smiles.extend(batch)

    X = np.concatenate(emb, axis=0)

    # Fit GTM on embeddings (can be expensive; start with smaller --limit).
    gtm = eGTM(k=16, m=4, s=0.7, regul=1e-3, niter=200, random_state=args.seed)
    gtm.fit(X)
    Y = gtm.transform(X).astype(np.float32)  # [N, 2]

    ranks = np.random.randint(1, args.rank_max + 1, size=(Y.shape[0],), dtype=np.int16)

    with psycopg.connect(args.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE zinc_gtm;")
            rows = [
                (kept_smiles[i], int(ranks[i]), float(Y[i, 0]), float(Y[i, 1]), X[i].tolist())
                for i in range(Y.shape[0])
            ]
            cur.executemany(
                "INSERT INTO zinc_gtm (smiles, rank, x, y, embedding) VALUES (%s, %s, %s, %s, %s)",
                rows,
            )
        conn.commit()

    print(f"Inserted {Y.shape[0]} rows into zinc_gtm.")


if __name__ == "__main__":
    main()

