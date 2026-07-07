#!/bin/bash
#SBATCH --job-name=molmap-build
#SBATCH --partition=gpu              # adjust: run `sinfo` to see GPU partition names
# GPU request — format is cluster-specific. Run:
#   sinfo -o "%P %G"     # shows GRES per partition, e.g. gpu:a100:2(S:0-1)
# Then pick ONE line below (uncomment the one that matches your cluster):
#SBATCH --gres=gpu:1
#SBATCH --gres=gpu:a100:1
#SBATCH --gres=gpu:v100:1
#SBATCH --gpus=1
#SBATCH --gpus-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --output=molmap-build-%j.log

# --- Environment ---
# 1) Create once on the cluster (from backend/):
#      bash scripts/setup_conda_env.sh
#    If CUDA 11.8:  CUDA_VERSION=11.8 bash scripts/setup_conda_env.sh
# 2) Uncomment and adjust the conda block below before submitting.
#
# module load cuda          # if your cluster requires it
# source "$(conda info --base)/etc/profile.d/conda.sh"
# conda activate molmap-build

set -euo pipefail

cd "$SLURM_SUBMIT_DIR/backend" 2>/dev/null || cd backend

python -m scripts.build_map_dataset \
  --repo-id "${REPO_ID:-edmanft/zinc250k}" \
  --column "${COLUMN:-smiles}" \
  --limit "${LIMIT:-1000000}" \
  --method "${METHOD:-maccs}" \
  --metric "${METRIC:-euclidean}" \
  --out-dir "${OUT_DIR:-./out}" \
  --name "${NAME:-molecules}"

echo "Done. Load into Postgres with:"
echo "  psql \"\$DATABASE_URL\" -f ${OUT_DIR:-./out}/${NAME:-molecules}_load.sql"
