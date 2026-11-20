# Molecule Map (PostGIS + pgvector + FastAPI + Deepscatter)

A “Google Maps for molecules” viewer:

- **Tiles**: **quadfeather** trees; **Deepscatter** renders millions of points
- **LOD**: importance encoded as **file row order** (rank-sorted before tiling)
- **Full stack**: PostgreSQL + PostGIS + FastAPI for dataset import, click details, and RDKit structure SVGs
- **Static demo**: GitHub Pages build on branch `static-gh-pages` (Deepscatter only, no backend / no MVT)

## GitHub Pages (static)

Branch `static-gh-pages` ships a backend-free Deepscatter demo with bundled `zinc10k` tiles under `frontend/public/deepscatter/`.

```bash
cd frontend
npm install --legacy-peer-deps
npm run build:pages          # base = /MoleculeViewer/
# or local preview without repo subpath:
npm run dev:static
```

Deploy: push `static-gh-pages`, enable **Settings → Pages → Source: GitHub Actions**. The workflow builds `frontend/dist` with base `/` for the custom domain.

**Custom domain `chemmaps.de`:** `frontend/public/CNAME` is included in the build. In repo **Settings → Pages → Custom domain**, set `chemmaps.de` and enable **Enforce HTTPS** after DNS works. At Namecheap (Advanced DNS):

| Type | Host | Value |
|------|------|-------|
| A | `@` | `185.199.108.153` |
| A | `@` | `185.199.109.153` |
| A | `@` | `185.199.110.153` |
| A | `@` | `185.199.111.153` |
| CNAME | `www` | `schwedeErik.github.io` |

Remove Namecheap parking/URL-redirect records that conflict. DNS can take minutes to hours; then https://chemmaps.de/

Structure hover/detail SVGs need the FastAPI + RDKit backend; the static build shows rank/id only.

## Quick start (full stack)

### 1) Start database

```bash
docker compose up -d db
```

This creates `datasets`, `molecule_map`, and `molecule_details` from `db/init/010_schema.sql`. A synthetic seed (`020_seed.sql`) may also load on first start; skip or truncate it when loading a real dataset (see below).

Existing databases created before the map/details split: run:

```bash
psql "$DATABASE_URL" -f db/init/040_map_details.sql
```

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

### 3) Build Deepscatter tiles

After a dataset is in Postgres (e.g. `zinc10k`):

```bash
cd backend
source .venv/bin/activate
python -m scripts.build_deepscatter_tiles --dataset zinc10k
# RQ1 ablation (same coords, shuffled file order):
python -m scripts.build_deepscatter_tiles --dataset zinc10k --order shuffled
```

Or from a pipeline CSV (`smiles,rank,lng,lat,…`):

```bash
python -m scripts.build_deepscatter_tiles --csv ../data/molecules_10k.csv --slug zinc10k
```

Outputs under `data/deepscatter/<slug>/{ranked|shuffled}/` (gitignored).
Tiles are served at `/deepscatter/<slug>/<order>/…`.

### 4) Run frontend (dev)

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). Choose a dataset and
**Open Deepscatter map**. Use **Legacy MVT** in the toolbar for the old deck.gl viewer.

---

## Building a dataset

The map needs molecules with:

| Field | Table | Meaning |
|-------|--------|---------|
| `rank` | `molecule_map` | Global importance rank (`1` = best, unique per dataset) |
| `geom` | `molecule_map` | PostGIS point from 2D UMAP coordinates (`lng`, `lat`) |
| `smiles` | `molecule_details` | SMILES string |
| `embedding` | `molecule_details` | Fingerprint vector (pgvector) used for ranking / search |

The build pipeline:

1. Download SMILES from HuggingFace
2. Embed (MACCS or Morgan fingerprints via RDKit)
3. Rank by representativeness (`app/services/smiles_ranking.py`)
4. Project to 2D with UMAP (GPU via cuML when available)
5. Export **`molecules.csv`** + **`molecules_load.sql`** for PostgreSQL
6. **New:** `python -m scripts.build_deepscatter_tiles --dataset <slug>` → quadfeather tiles

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

### 2) (Recommended) Clear old data

If the synthetic seed or a previous dataset is already loaded:

```bash
psql "$DATABASE_URL" -c "TRUNCATE molecule_map RESTART IDENTITY CASCADE;"
```

### 3) Load

```bash
psql "$DATABASE_URL" -f data/molecules_load.sql
```

### 4) Verify

```bash
psql "$DATABASE_URL" -c "SELECT COUNT(*), MIN(rank), MAX(rank) FROM molecule_map;"
curl "http://localhost:8000/bounds?dataset=zinc10k"
```

### 5) Build Deepscatter tiles

```bash
cd backend && python -m scripts.build_deepscatter_tiles --dataset zinc10k
```

---

## API endpoints

- `GET /datasets` — list datasets (`precomputed_lods`, `deepscatter_orders`)
- `GET /deepscatter/{slug}/{order}/{path}` — static quadfeather tile files (`order`: `ranked`|`shuffled`)
- `GET /molecules/{id}?dataset=` — click detail (SMILES, rank, coords)
- `GET /bounds` — dataset bounding box, count, rank range
- `GET /datasets/{slug}/pmtiles/{lod}.pmtiles` — legacy precomputed MVT archive
- `GET /datasets/{slug}/tiles-manifest` — legacy PMTiles bake metadata
- `GET /tiles/{z}/{x}/{y}.mvt?rank_max=N` — legacy live MVT tile
- `GET /points.pb?…` — Protobuf viewport query (optional)

### Deepscatter LOD model

1. Export molecules sorted by **`rank` ascending** (`x`,`y` from UMAP; optional `id`,`rank`,`smiles`).
2. Run **quadfeather** → nested Feather tile tree (row order = quadtree priority).
3. Frontend Deepscatter draws with a **`max_points`** budget (LOD slider) and colors by `rank`.
4. For RQ1, build a second tree with `--order shuffled` (same points, different file order).

### Legacy precomputed tiles (PMTiles)

```bash
pip install mercantile pmtiles
export DATABASE_URL="postgresql://app:app@localhost:5432/molecules"
python -m scripts.build_precomputed_tiles --dataset zinc10k --max-zoom 12
```

Outputs under `data/tile_cache/<slug>/lod_1.pmtiles` … `lod_6.pmtiles`.

---

## Notes

- Ranks are **globally unique** (`1` … `N`). In Deepscatter, low ranks appear earlier in the file and therefore in coarser quadtree levels.
- Deepscatter is licensed **NC-CC-BY-SA** (fine for thesis; document it).
- Ranking details: [`docs/ranking_algorithm_presentation.md`](docs/ranking_algorithm_presentation.md)
