# Molecule Map (PostGIS + pgvector + FastAPI + deck.gl)

This is a scaffold for a “Google Maps for molecules” style app:

- **DB**: PostgreSQL + **PostGIS** + **pgvector**
- **Backend**: **FastAPI** serving:
  - binary **Protobuf** point streams for viewport queries
  - **MVT** (Mapbox Vector Tiles) for tile-based rendering at scale
- **Frontend**: **React + deck.gl** (WebGL) for millions of points

## Quick start

### 1) Start database

```bash
docker compose up -d db
```

If `docker` isn’t installed, install Docker Engine (or use Podman + `podman-docker`), then rerun the command above.

### 2) Run backend (dev)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend health check: `http://localhost:8000/health`

### 3) Run frontend (dev)

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

## API endpoints

- `GET /tiles/{z}/{x}/{y}.mvt?rank_max=3`
  - Returns **MVT** (`application/vnd.mapbox-vector-tile`)
- `GET /points.pb?minLng=...&minLat=...&maxLng=...&maxLat=...&limit=...`
  - Returns **Protobuf** (`application/x-protobuf`)

## Notes

- The DB seeds a small synthetic dataset on first start (enough to see something render).
- For 100M points, you’ll typically:
  - precompute / manage **rank by zoom** rules
  - serve **MVT tiles** as the primary visualization path
  - use point-stream endpoints only for selection/inspection or low-volume overlays

