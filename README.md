# Molecule Map (PostGIS + pgvector + FastAPI + deck.gl)

A “Google Maps for molecules” viewer:

- **DB**: PostgreSQL + **PostGIS** + **pgvector**
- **Backend**: **FastAPI** serving **MVT** tiles and optional **Protobuf** viewport queries
- **Frontend**: **React + deck.gl** with zoom-based rank LOD

## Quick start

### 1) Start database

```bash
docker compose up -d db
```

This creates the `molecules` table from `db/init/010_schema.sql`. A synthetic seed (`020_seed.sql`) may also load on first start; skip or truncate it when loading a real dataset (see below).

Default connection:

```bash
export DATABASE_URL="postgresql://app:app@localhost:5432/molecules"
```

### 2) Run backend (dev)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

### 3) Run frontend (dev)

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

---

## Building a dataset

The map needs molecules with:

| Field | Meaning |
|-------|---------|
| `smiles` | SMILES string |
| `rank` | Global importance rank (`1` = best, unique per molecule) |
| `geom` | PostGIS point from 2D UMAP coordinates (`lng`, `lat`) |
| `embedding` | Fingerprint vector (pgvector) used for ranking |

The build pipeline:

1. Download SMILES from HuggingFace
2. Embed (MACCS or Morgan fingerprints via RDKit)
3. Rank by representativeness (`app/services/smiles_ranking.py`)
4. Project to 2D with UMAP (GPU via cuML when available)
5. Export **`molecules.csv`** + **`molecules_load.sql`** for PostgreSQL

Code lives in `backend/app/services/` and is driven by `backend/scripts/build_map_dataset.py`.

### Option A — Google Colab (GPU)

Notebook: [`backend/scripts/build_map_dataset_colab.ipynb`](backend/scripts/build_map_dataset_colab.ipynb)

1. **Runtime → Change runtime type → GPU** (T4 is enough).
2. Run the install cell (`datasets`, `rdkit`, `umap-learn`, `cuml-cu12`, …).
3. Upload a zip of the `backend/` folder (or clone from GitHub once the repo is available).
4. Set config in the notebook, e.g.:

   ```python
   REPO_ID = "edmanft/zinc250k"
   COLUMN = "smiles"
   LIMIT = 250_000        # start with 10_000 to test
   METHOD = "maccs"       # maccs | morgan
   METRIC = "euclidean"
   ```

5. Run the pipeline cell, then download `out/molecules.csv` and `out/molecules_load.sql`.

Colab has no direct DB access; copy the files to your machine and load with `psql` (see below).

### Option B — HPC / Slurm cluster (GPU)

For larger runs (250k–10M molecules), use the cluster job script.

**One-time environment** (from `backend/`):

```bash
bash scripts/setup_conda_env.sh
# If the cluster uses CUDA 11.8:
CUDA_VERSION=11.8 bash scripts/setup_conda_env.sh

conda activate molmap-build
```

Or: `conda env create -f scripts/environment.yml`

**Configure and submit** — edit `backend/scripts/build_map_dataset.slurm`:

- Uncomment the `conda activate molmap-build` block
- Uncomment the `#SBATCH --gres=…` line that matches your cluster (`sinfo -o "%P %G"`)

Submit:

```bash
cd backend
sbatch scripts/build_map_dataset.slurm
```

Override defaults via environment variables:

```bash
REPO_ID=edmanft/zinc250k LIMIT=1000000 METHOD=maccs OUT_DIR=./out sbatch scripts/build_map_dataset.slurm
```

**Or run directly** on a GPU node (no Slurm):

```bash
cd backend
conda activate molmap-build

python -m scripts.build_map_dataset \
  --repo-id edmanft/zinc250k \
  --column smiles \
  --limit 250000 \
  --method maccs \
  --metric euclidean \
  --out-dir ./out \
  --name molecules
```

Output:

- `out/molecules.csv`
- `out/molecules_load.sql`

Copy both files to the machine where Postgres runs.

### Embedding method vs schema

`db/init/010_schema.sql` sets `embedding vector(167)` for **MACCS** (default). If you use another method, change the dimension before loading:

| Method | Dimension |
|--------|-----------|
| `maccs` | 167 |
| `morgan` | 2048 |
| `chembert` | 768 (not implemented in the pipeline yet) |

---

## Loading a dataset into PostgreSQL

### 1) Prepare the loader SQL path

The generated `molecules_load.sql` contains an absolute path to the CSV in its `\copy` line. Either:

- Run `psql` from the directory that contains the CSV and edit the path in the SQL file, or
- Keep the CSV next to the SQL file and use the path written by the export script.

Example after copying files to `data/`:

```bash
# Edit the \copy ... FROM '...' line in molecules_load.sql if needed
```

### 2) (Recommended) Clear old data

If the synthetic seed or a previous dataset is already loaded:

```bash
psql "$DATABASE_URL" -c "TRUNCATE molecules RESTART IDENTITY;"
```

### 3) Load

```bash
psql "$DATABASE_URL" -f data/molecules_load.sql
```

The loader:

1. `\copy` CSV rows into a temp staging table
2. Inserts into `molecules`, building `geom` from `lng`/`lat` and casting `embedding` to `vector`

### 4) Verify

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*), MIN(rank), MAX(rank) FROM molecules;"
curl http://localhost:8000/bounds
```

Restart or refresh the frontend; it auto-fits to `/bounds`.

---

## API endpoints

- `GET /health` — DB connectivity
- `GET /bounds` — dataset bounding box, count, rank range
- `GET /tiles/{z}/{x}/{y}.mvt?rank_max=N` — MVT tile; all molecules with `1 <= rank <= N` in that tile
- `GET /points.pb?minLng=…&minLat=…&maxLng=…&maxLat=…&limit=N` — Protobuf viewport query (optional / future use)

The frontend uses MVT tiles with per-tile zoom LOD: each tile requests a `rank_max` based on its zoom level and the **rank max** / **zoom LOD** sliders.

---

## Notes

- Ranks are **globally unique** (`1` … `N`). `rank_max=10_000` means exactly those 10,000 molecules, split across tiles by location.
- For 10M+ molecules, build on a GPU cluster, load once, then serve via MVT + zoom LOD (no need to fetch the full rank range at low zoom).
- Ranking details: [`docs/ranking_algorithm_presentation.md`](docs/ranking_algorithm_presentation.md)
