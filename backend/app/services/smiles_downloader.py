import numpy as np
from datasets import load_dataset

def download_smiles_database_huggingface(repo_id: str, column_name: str = "smiles", limit: int = 1000000) -> np.ndarray:
    ds = load_dataset(repo_id, split="train")
    smiles_list = [s for s in ds[column_name] if isinstance(s, str) and s.strip()]
    smiles_list = smiles_list[:limit]
    return np.array(smiles_list)