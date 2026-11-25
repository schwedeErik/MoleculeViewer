# ChemMaps

**Interactive, zoomable maps of large chemical libraries in the browser.**

ChemMaps is the software for the Master's thesis *"ChemMaps: Real-Time Interactive Exploration of Large-Scale Chemical Spaces"* (RPTU Kaiserslautern-Landau, 2026). It works in two stages:

- **Offline pipeline.** Turns a list of SMILES strings into a map:
  1. computes a fingerprint for each molecule (MACCS or Morgan),
  2. gives every molecule a unique importance rank using farthest-point sampling,
  3. projects the molecules to 2D with UMAP,
  4. writes the result as a tile tree.
- **Web explorer.** Renders the map with [Deepscatter](https://github.com/nomic-ai/deepscatter):
  - Coarse zoom levels show the best-ranked molecules.
  - Zooming in or raising the level-of-detail (LOD) slider adds more.
  - Clicking a molecule shows its structure.

## Try it now: https://chemmaps.de

The static demo at **[chemmaps.de](https://chemmaps.de)** runs entirely in the browser. You don't need to install anything.

- **Datasets:** ChEMBL (~1.36 M molecules) and ZINC 250k.
- **Ranked vs. shuffled:** each dataset comes in two row orders. **Ranked** is the importance order. **Shuffled** is the random baseline from the thesis. Switching between them shows the effect of the ranking.
- **Controls:** pan and zoom, the LOD slider (point budget), point size, and hover/click for structure details. Structures are drawn client-side from SMILES.
- **Not included:** the demo has no backend, so you can't upload datasets and the legacy deck.gl/MVT viewer isn't available. For those, run the full stack locally (below).

The demo runs the same frontend code as `main` in static mode, with the tiles bundled in. See [Static build](#static-build-chemmapsde).

---

## Repository layout

```
backend/
  app/                FastAPI service (datasets, tiles, molecule details, uploads)
    services/         pipeline code: featurization, ranking, UMAP, export, tiling
  scripts/            command-line tools: dataset build, tile build, evaluation
frontend/             React + Vite + TypeScript explorer (Deepscatter, legacy deck.gl view)
db/
  init/               schema applied automatically on first `docker compose up`
  migrations/         upgrades for databases created by older versions
data/                 generated data (tiles, CSVs, caches are gitignored)
  eval_rq1*/, eval_rq2/   evaluation results used in the thesis (tables, figures)
docs/                 ranking algorithm notes and slides
docker-compose.yml    PostgreSQL + PostGIS + pgvector
```

## Requirements

- Docker (for the database)
- Python 3.12
- Node.js 20+
- Optional: an NVIDIA GPU with RAPIDS cuML. UMAP falls back to CPU `umap-learn`, which is slow for more than a few hundred thousand molecules.

---

## Run locally (full stack)

### 1. Start the database

```bash
docker compose up -d db
export DATABASE_URL="postgresql://app:app@localhost:5432/molecules"
```

On first start, `db/init/` creates the `datasets`, `molecule_map`, and `molecule_details` tables. The credentials `app:app` are for local development only.

### 2. Start the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health check: <http://localhost:8000/health>. The backend reads `DATABASE_URL`; the default is the value above.

### 3. Start the frontend

```bash
cd frontend
npm install --legacy-peer-deps
npm run dev
```

Open <http://localhost:5173>. Vite forwards `/api/*` to the backend on port 8000.

The map is empty until a dataset exists. To add one, either upload a pipeline CSV in the UI, or build one as described in the next section.

---

## Build a dataset

### Step 1: Run the pipeline (SMILES → ranked 2D map)

The pipeline downloads SMILES from Hugging Face, computes fingerprints, ranks, and projects. It writes a CSV and a matching SQL loader script.

```bash
cd backend && source .venv/bin/activate
python -m scripts.build_map_dataset \
  --repo-id edmanft/zinc250k --column smiles --limit 250000 \
  --method maccs --metric euclidean \
  --out-dir ./out --name zinc250k --dataset-slug zinc250k --dataset-name "ZINC 250k"
```

The options above (`--method maccs --metric euclidean`) and the defaults of `--n-neighbors 15` and `--min-dist 0.1` are the settings used in the thesis.

How ranking works:

- **Up to 50,000 molecules:** exact farthest-point sampling.
- **Larger libraries:** a hierarchical approximation. Details are in [`docs/ranking_algorithm_presentation.md`](docs/ranking_algorithm_presentation.md) and `backend/app/services/smiles_ranking.py`.

For large libraries, run the pipeline on a GPU machine:

- **Google Colab:** use [`backend/scripts/build_map_dataset_colab.ipynb`](backend/scripts/build_map_dataset_colab.ipynb) on a GPU runtime. Afterwards, download `out/*.csv` and `out/*_load.sql`.
- **Slurm cluster:**
  1. Set up the environment once with `bash scripts/setup_conda_env.sh`, then `conda activate molmap-build`.
  2. Edit `scripts/build_map_dataset.slurm`.
  3. Submit it with variables, for example `REPO_ID=edmanft/zinc250k LIMIT=250000 sbatch scripts/build_map_dataset.slurm`.

### Step 2: Load into PostgreSQL

```bash
psql "$DATABASE_URL" -f backend/out/zinc250k_load.sql
psql "$DATABASE_URL" -c "SELECT d.slug, COUNT(*) FROM molecule_map m JOIN datasets d ON d.id = m.dataset_id GROUP BY d.slug;"
```

The loader script contains the absolute path of the CSV. If you move the CSV, edit the `\copy` line.

### Step 3: Build the Deepscatter tiles

```bash
cd backend
python -m scripts.build_deepscatter_tiles --dataset zinc250k                    # ranked (importance order)
python -m scripts.build_deepscatter_tiles --dataset zinc250k --order shuffled   # random baseline (RQ1 ablation)
```

- **Output:** tiles are written to `data/deepscatter/<slug>/{ranked,shuffled}/` and served at `/deepscatter/<slug>/<order>/…`.
- **From a CSV:** add `--csv <file> --slug <slug>` to build directly from a pipeline CSV, without loading it into the database first.
- **SMILES in tiles:** `--include-smiles` stores SMILES in the tiles so that details work without the database. The tiles become about 2–3× larger.

### Alternative: upload in the UI

In the dataset dialog, upload a pipeline CSV (`smiles,rank,lng,lat,…`). The backend builds the tiles in a background job.

### Embedding dimension

`molecule_details.embedding` is `vector(167)` (MACCS). To store Morgan fingerprints (2048 bits), change the dimension in `db/init/010_schema.sql` before the database is created.

---

## Legacy deck.gl / MVT viewer (RQ2 baseline)

The explorer toolbar also has the earlier deck.gl viewer. It reads Mapbox Vector Tiles with a rank threshold per zoom level, in one of two modes:

- **Live mode** queries PostGIS for every tile and works as soon as a dataset is in the database.
- **Precomputed mode** reads PMTiles archives, which you build with:

```bash
cd backend
python -m scripts.build_precomputed_tiles --dataset zinc250k --max-zoom 10
```

This writes `data/tile_cache/<slug>/lod_1.pmtiles … lod_6.pmtiles`.

---

## Reproduce the thesis evaluation

All scripts run from `backend/` with `DATABASE_URL` set. Results go to `data/eval_*/` as CSV tables, figures, and a Markdown summary.

```bash
# RQ1: ranked vs shuffled prefixes (fill distance, cluster coverage, scaffolds, redundancy)
python -m scripts.eval_rq1 --datasets zinc10k zinc250k chembl13m

# RQ1, large libraries: 10 shuffle seeds, cluster round-robin baseline,
# and the exact-vs-hierarchical FPS "bridge" on 25,000-molecule subsamples
python -m scripts.eval_rq1_large --datasets zinc250k chembl13m --shuffle-seeds 10 --bridge-n 25000

# RQ2: asset sizes and cold-load transfer (needs the backend running on :8000)
python -m scripts.eval_rq2 --api-base http://127.0.0.1:8000 --repeats 3
```

Two things to know before rerunning these:

- **RQ2 tiles fetched:** the thesis's RQ2 numbers came from a version of `eval_rq2.py` that downloaded the *complete* Deepscatter tree. The thesis documents this. The current script fetches only tiles up to quadtree depth 2 (`OVERVIEW_MAX_DEPTH`).
- **Tile size:** the RQ2 asset sizes in the thesis refer to tiles built *without* `--include-smiles`. Build without it if you want comparable numbers.

---

## Static build (chemmaps.de)

The frontend also runs **without a backend** when it is built with `VITE_STATIC=true`. In static mode:

- **Datasets:** the catalog comes from `frontend/src/staticDatasets.json`.
- **Tiles:** loaded from `frontend/public/deepscatter/<slug>/<order>/`.
- **Structures:** drawn in the browser from the SMILES stored in the tiles, using `smiles-drawer`. In the full stack they come from the backend (RDKit).
- **Hidden features:** upload, delete, and the legacy MVT viewer.

To run static mode locally:

```bash
# 1. Build tiles that contain SMILES (needed for structure drawings without a backend)
cd backend
python -m scripts.build_deepscatter_tiles --dataset zinc250k --include-smiles
python -m scripts.build_deepscatter_tiles --dataset zinc250k --order shuffled --include-smiles

# 2. Copy them into the frontend (gitignored on main) and list the dataset in src/staticDatasets.json
mkdir -p ../frontend/public/deepscatter
cp -r ../data/deepscatter/zinc250k ../frontend/public/deepscatter/

# 3. Run or build
cd ../frontend
npm run dev:static      # local preview without a backend
npm run build:pages     # production build into frontend/dist
```

**Deployment.** The [`static-gh-pages`](https://github.com/schwedeErik/MoleculeViewer/tree/static-gh-pages) branch adds three things to this code:

- the bundled tile trees under `frontend/public/deepscatter/`,
- `frontend/public/CNAME`,
- a GitHub Actions workflow that publishes `frontend/dist` to GitHub Pages under `chemmaps.de`.

Pushing to that branch redeploys the site. To ship frontend changes from `main`, merge `main` into `static-gh-pages`.

---

## Database migrations

`db/init/` applies only to a **fresh** database volume. A database created by an older version may still have the single `molecules` table. To upgrade one, run the migrations in `db/migrations/` once, in order:

```bash
psql "$DATABASE_URL" -f db/migrations/030_multidataset.sql
psql "$DATABASE_URL" -f db/migrations/040_map_details.sql
```

To start over instead, run `docker compose down -v` (this deletes all loaded data).

---

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/datasets` | List datasets with their available tile variants |
| POST | `/datasets` | Upload a pipeline CSV and start an import job |
| GET | `/datasets/jobs/{job_id}` | Import job progress |
| DELETE | `/datasets/{slug}` | Delete a dataset and its tiles |
| GET | `/deepscatter/{slug}/{order}/{path}` | Static quadfeather tile files (`ranked` / `shuffled`) |
| GET | `/molecules/{id}?dataset=` | Molecule details (SMILES, rank, coordinates) |
| GET | `/molecules/{id}/structure.svg?dataset=` | RDKit structure depiction |
| GET | `/bounds?dataset=` | Bounding box, count, and rank range |
| GET | `/tiles/{z}/{x}/{y}.mvt?dataset=&rank_max=` | Legacy live vector tile |
| GET | `/datasets/{slug}/pmtiles/{lod}.pmtiles` | Legacy precomputed vector-tile archive |
| GET | `/datasets/{slug}/tiles-manifest` | Metadata of the precomputed archives |

## How the level of detail works

- **Row order is the importance order.** Molecules are sorted by rank and written to a quadfeather tile tree, so each row's index in the files equals its rank − 1.
- **Deepscatter draws a rank prefix.** It draws every point inside the viewport whose index is at most `max_points · zoom^1.6`, where `zoom_balance` = 0.2.
- **What that means on screen:** the full view shows exactly the `max_points` best-ranked molecules, and zooming in reveals further ranks.
- **Effect of the shuffled tree:** a tree built in shuffled order shows a uniformly random subset of the same size instead.

## Licenses and notes

- Deepscatter is licensed CC BY-NC-SA 4.0.
- The default credentials and the permissive CORS setting are for local development only.
