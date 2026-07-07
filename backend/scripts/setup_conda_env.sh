#!/usr/bin/env bash
# Create the conda environment for backend/scripts/build_map_dataset.slurm
#
# Usage (from backend/):
#   bash scripts/setup_conda_env.sh
#
# Pick CUDA version to match the cluster (check: module avail cuda  OR  nvidia-smi):
#   CUDA_VERSION=11.8 bash scripts/setup_conda_env.sh
#
# After install:
#   conda activate molmap-build
#   python -c "from cuml.manifold import UMAP; from rdkit import Chem; print('OK')"

set -euo pipefail

ENV_NAME="${ENV_NAME:-molmap-build}"
CUDA_VERSION="${CUDA_VERSION:-12.0}"
PYTHON_VERSION="${PYTHON_VERSION:-3.11}"

if ! command -v conda &>/dev/null; then
  echo "Error: conda not found. Load your cluster's Anaconda/Miniconda module first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  echo "Environment '$ENV_NAME' already exists."
  echo "Remove it first:  conda env remove -n $ENV_NAME"
  exit 1
fi

echo "Creating conda env '$ENV_NAME' (python=$PYTHON_VERSION, cuda-version=$CUDA_VERSION) …"
echo "This may take several minutes (RAPIDS/cuML is large)."

# Prefer mamba/libmamba solver if available (much faster resolves).
CONDA_CREATE=(conda create -y -n "$ENV_NAME")
if conda config --show solver 2>/dev/null | grep -q libmamba; then
  CONDA_CREATE+=(--solver=libmamba)
fi

"${CONDA_CREATE[@]}" \
  -c rapidsai -c conda-forge -c nvidia \
  "python=${PYTHON_VERSION}" \
  "cuda-version=${CUDA_VERSION}" \
  "cuml=24.10" \
  "umap-learn>=0.5.5" \
  "scikit-learn>=1.5" \
  "rdkit" \
  "numpy" \
  "tqdm" \
  "pip"

conda activate "$ENV_NAME"

pip install --no-input "datasets>=3.0" "huggingface_hub>=0.23"

echo ""
echo "Environment '$ENV_NAME' is ready."
echo ""
echo "Activate:"
echo "  conda activate $ENV_NAME"
echo ""
echo "Quick sanity check (run on a GPU login/compute node):"
echo "  python -c \"from cuml.manifold import UMAP; from rdkit import Chem; import sklearn; print('molmap-build OK')\""
