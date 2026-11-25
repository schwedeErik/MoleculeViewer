"""RQ2 evaluation: Deepscatter vs deck.gl MVT (PMTiles) scalability.

Measures offline asset cost and online cold-load transfer / latency for
zinc10k, zinc250k, chembl13m at LOD step 3 (Deepscatter max_points=75k;
MVT uses precomputed lod_3.pmtiles).

Run from ``backend/`` with API up::

    export DATABASE_URL=postgresql://app:app@localhost:5432/molecules
    python -m scripts.eval_rq2
    python -m scripts.eval_rq2 --api-base http://127.0.0.1:8000 --repeats 3

Outputs under ``data/eval_rq2/`` (CSV, PNG, analysis markdown).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DEFAULT_DATASETS = ("zinc10k", "zinc250k", "chembl13m")
LOD_LEVEL = 3
DEEPSCATTER_ORDER = "ranked"
REPEATS = 3
OVERVIEW_MAX_DEPTH = 2  # quadtree levels fetched for the cold overview (root = 0)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def out_dir() -> Path:
    d = repo_root() / "data" / "eval_rq2"
    d.mkdir(parents=True, exist_ok=True)
    return d


def deepscatter_dir(slug: str) -> Path:
    return repo_root() / "data" / "deepscatter" / slug / DEEPSCATTER_ORDER


def tile_cache_dir(slug: str) -> Path:
    return repo_root() / "data" / "tile_cache" / slug


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def http_get(url: str, timeout: float = 120.0) -> tuple[int, float, bytes]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read()
        status = resp.status
    elapsed = time.perf_counter() - t0
    return status, elapsed, body


def measure_offline(datasets: tuple[str, ...]) -> list[dict]:
    rows: list[dict] = []
    for slug in datasets:
        ds = deepscatter_dir(slug)
        tc = tile_cache_dir(slug)
        pm = tc / f"lod_{LOD_LEVEL}.pmtiles"
        rows.append(
            {
                "dataset": slug,
                "renderer": "deepscatter",
                "asset_path": str(ds),
                "bytes_on_disk": dir_size_bytes(ds),
                "lod_level": LOD_LEVEL,
                "notes": f"quadfeather tree order={DEEPSCATTER_ORDER}",
            }
        )
        rows.append(
            {
                "dataset": slug,
                "renderer": "mvt_pmtiles",
                "asset_path": str(tc),
                "bytes_on_disk": dir_size_bytes(tc),
                "lod_level": LOD_LEVEL,
                "notes": f"all lod_1..6 PMTiles; lod_{LOD_LEVEL} alone={pm.stat().st_size if pm.is_file() else 0}",
            }
        )
        if pm.is_file():
            rows.append(
                {
                    "dataset": slug,
                    "renderer": "mvt_pmtiles_lod3_only",
                    "asset_path": str(pm),
                    "bytes_on_disk": pm.stat().st_size,
                    "lod_level": LOD_LEVEL,
                    "notes": "single LOD archive used in online protocol",
                }
            )
    return rows


def list_deepscatter_files(slug: str) -> list[str]:
    """Relative paths under the deepscatter tree to fetch for a cold overview.

    Quadfeather tiles live at ``z/x/y.feather``, where ``z`` is the quadtree
    depth (``0/0/0.feather`` is the root). We fetch manifests plus all feathers
    with ``z <= OVERVIEW_MAX_DEPTH`` (root + first two quad levels), which
    approximates an overview load before deep zoom.

    Note: an earlier version derived the depth from ``rel.count("/")``, which is
    2 for every ``z/x/y`` path, so it fetched the complete tree. The RQ2 numbers
    reported in the thesis were produced by that version.
    """
    root = deepscatter_dir(slug)
    if not root.is_dir():
        return []
    files: list[str] = []
    for name in ("manifest.json", "manifest.feather", "tileset.json"):
        if (root / name).is_file():
            files.append(name)
    feathers: list[tuple[int, str]] = []
    for p in root.rglob("*.feather"):
        rel = p.relative_to(root).as_posix()
        if rel in files:
            continue
        parts = rel.split("/")
        if len(parts) != 3 or not parts[0].isdigit():
            continue  # not a z/x/y tile (e.g. a sidecar or manifest)
        depth = int(parts[0])
        if depth <= OVERVIEW_MAX_DEPTH:
            feathers.append((depth, rel))
    feathers.sort()
    files.extend(rel for _, rel in feathers)
    return files


def measure_online_http(
    api_base: str,
    datasets: tuple[str, ...],
    repeats: int,
) -> list[dict]:
    rows: list[dict] = []
    base = api_base.rstrip("/")

    # Warm health
    try:
        http_get(f"{base}/health")
    except Exception as e:
        print(f"API not reachable at {base}: {e}", flush=True)
        return rows

    for slug in datasets:
        # Deepscatter cold load: bounds + deepscatter assets
        ds_files = list_deepscatter_files(slug)
        for rep in range(repeats):
            bytes_total = 0
            t_start = time.perf_counter()
            err = ""
            try:
                _, _, b = http_get(f"{base}/bounds?dataset={slug}")
                bytes_total += len(b)
                for rel in ds_files:
                    url = f"{base}/deepscatter/{slug}/{DEEPSCATTER_ORDER}/{rel}"
                    _, _, body = http_get(url)
                    bytes_total += len(body)
            except Exception as e:
                err = str(e)
            elapsed = time.perf_counter() - t_start
            rows.append(
                {
                    "dataset": slug,
                    "renderer": "deepscatter",
                    "repeat": rep,
                    "lod_level": LOD_LEVEL,
                    "seconds": round(elapsed, 4),
                    "bytes_transferred": bytes_total,
                    "n_requests": 1 + len(ds_files),
                    "error": err,
                }
            )
            print(
                f"  deepscatter {slug} rep={rep} {elapsed:.2f}s "
                f"{bytes_total/1e6:.2f} MB reqs={1+len(ds_files)} {err}",
                flush=True,
            )

        # MVT PMTiles cold load: bounds + full lod_3.pmtiles download
        for rep in range(repeats):
            bytes_total = 0
            t_start = time.perf_counter()
            err = ""
            try:
                _, _, b = http_get(f"{base}/bounds?dataset={slug}")
                bytes_total += len(b)
                url = f"{base}/datasets/{slug}/pmtiles/{LOD_LEVEL}.pmtiles"
                _, _, body = http_get(url, timeout=300.0)
                bytes_total += len(body)
            except Exception as e:
                err = str(e)
            elapsed = time.perf_counter() - t_start
            rows.append(
                {
                    "dataset": slug,
                    "renderer": "mvt_pmtiles",
                    "repeat": rep,
                    "lod_level": LOD_LEVEL,
                    "seconds": round(elapsed, 4),
                    "bytes_transferred": bytes_total,
                    "n_requests": 2,
                    "error": err,
                }
            )
            print(
                f"  mvt_pmtiles {slug} rep={rep} {elapsed:.2f}s "
                f"{bytes_total/1e6:.2f} MB {err}",
                flush=True,
            )
    return rows


def summarize_online(rows: list[dict]) -> list[dict]:
    from collections import defaultdict

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("error"):
            continue
        groups[(r["dataset"], r["renderer"])].append(r)
    out: list[dict] = []
    for (slug, rend), items in sorted(groups.items()):
        secs = [x["seconds"] for x in items]
        byts = [x["bytes_transferred"] for x in items]
        out.append(
            {
                "dataset": slug,
                "renderer": rend,
                "n": len(items),
                "seconds_median": statistics.median(secs),
                "seconds_mean": statistics.mean(secs),
                "seconds_stdev": statistics.stdev(secs) if len(secs) > 1 else 0.0,
                "bytes_median": statistics.median(byts),
                "bytes_mean": statistics.mean(byts),
            }
        )
    return out


def plot_results(
    offline: list[dict],
    online_summary: list[dict],
    figures_dir: Path,
) -> list[Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    datasets = list(dict.fromkeys(r["dataset"] for r in offline))

    # Disk size comparison (full trees)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    x = range(len(datasets))
    width = 0.35
    ds_sizes = []
    mvt_sizes = []
    for slug in datasets:
        ds_b = next(
            (r["bytes_on_disk"] for r in offline if r["dataset"] == slug and r["renderer"] == "deepscatter"),
            0,
        )
        mvt_b = next(
            (
                r["bytes_on_disk"]
                for r in offline
                if r["dataset"] == slug and r["renderer"] == "mvt_pmtiles"
            ),
            0,
        )
        ds_sizes.append(ds_b / 1e6)
        mvt_sizes.append(mvt_b / 1e6)
    ax.bar([i - width / 2 for i in x], ds_sizes, width, label="Deepscatter (ranked)")
    ax.bar([i + width / 2 for i in x], mvt_sizes, width, label="MVT PMTiles (lod 1–6)")
    ax.set_xticks(list(x))
    ax.set_xticklabels(datasets)
    ax.set_ylabel("On-disk size (MB)")
    ax.set_title("RQ2: offline asset size")
    ax.legend()
    ax.set_yscale("log")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    p = figures_dir / "rq2_asset_size.png"
    fig.savefig(p, dpi=160)
    plt.close(fig)
    paths.append(p)

    # Cold load time
    if online_summary:
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        ds_t, mvt_t = [], []
        for slug in datasets:
            ds_t.append(
                next(
                    (
                        r["seconds_median"]
                        for r in online_summary
                        if r["dataset"] == slug and r["renderer"] == "deepscatter"
                    ),
                    float("nan"),
                )
            )
            mvt_t.append(
                next(
                    (
                        r["seconds_median"]
                        for r in online_summary
                        if r["dataset"] == slug and r["renderer"] == "mvt_pmtiles"
                    ),
                    float("nan"),
                )
            )
        ax.bar([i - width / 2 for i in x], ds_t, width, label="Deepscatter")
        ax.bar([i + width / 2 for i in x], mvt_t, width, label="MVT PMTiles (lod_3)")
        ax.set_xticks(list(x))
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Cold load time (s, median)")
        ax.set_title(f"RQ2: cold asset fetch latency (LOD={LOD_LEVEL})")
        ax.legend()
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        p = figures_dir / "rq2_cold_load_time.png"
        fig.savefig(p, dpi=160)
        plt.close(fig)
        paths.append(p)

        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        ds_b = [
            next(
                (
                    r["bytes_median"] / 1e6
                    for r in online_summary
                    if r["dataset"] == slug and r["renderer"] == "deepscatter"
                ),
                float("nan"),
            )
            for slug in datasets
        ]
        mvt_b = [
            next(
                (
                    r["bytes_median"] / 1e6
                    for r in online_summary
                    if r["dataset"] == slug and r["renderer"] == "mvt_pmtiles"
                ),
                float("nan"),
            )
            for slug in datasets
        ]
        ax.bar([i - width / 2 for i in x], ds_b, width, label="Deepscatter")
        ax.bar([i + width / 2 for i in x], mvt_b, width, label="MVT PMTiles (lod_3)")
        ax.set_xticks(list(x))
        ax.set_xticklabels(datasets)
        ax.set_ylabel("Transferred bytes (MB, median)")
        ax.set_title(f"RQ2: cold transfer volume (LOD={LOD_LEVEL})")
        ax.legend()
        ax.set_yscale("log")
        ax.grid(True, axis="y", alpha=0.3)
        fig.tight_layout()
        p = figures_dir / "rq2_cold_transfer.png"
        fig.savefig(p, dpi=160)
        plt.close(fig)
        paths.append(p)

    return paths


def write_analysis(
    offline: list[dict],
    online_summary: list[dict],
    path: Path,
) -> None:
    lines = [
        "# RQ2 Analysis: Deepscatter vs deck.gl MVT (PMTiles)",
        "",
        f"Protocol: LOD step **{LOD_LEVEL}**, Deepscatter order **{DEEPSCATTER_ORDER}**, "
        "MVT uses precomputed PMTiles (not live SQL).",
        "",
        "Fairness note: LOD step 3 maps to Deepscatter `max_points=75_000` but MVT "
        "`rank_max` depends on zoom; cold-load measures asset fetch cost, not identical "
        "visual density.",
        "",
        "## Offline asset size",
        "",
        "| Dataset | Deepscatter ranked | MVT lod 1–6 | lod_3 only |",
        "|---------|-------------------|-------------|------------|",
    ]
    datasets = list(dict.fromkeys(r["dataset"] for r in offline))
    for slug in datasets:
        ds = next(r for r in offline if r["dataset"] == slug and r["renderer"] == "deepscatter")
        mvt = next(r for r in offline if r["dataset"] == slug and r["renderer"] == "mvt_pmtiles")
        lod3 = next(
            (r for r in offline if r["dataset"] == slug and r["renderer"] == "mvt_pmtiles_lod3_only"),
            None,
        )
        lod3_s = f"{lod3['bytes_on_disk']/1e6:.1f} MB" if lod3 else "—"
        lines.append(
            f"| {slug} | {ds['bytes_on_disk']/1e6:.1f} MB | {mvt['bytes_on_disk']/1e6:.1f} MB | {lod3_s} |"
        )
    lines += ["", "## Online cold load (median)", ""]
    if online_summary:
        lines.append("| Dataset | Renderer | Time (s) | Transfer (MB) |")
        lines.append("|---------|----------|----------|---------------|")
        for r in online_summary:
            lines.append(
                f"| {r['dataset']} | {r['renderer']} | {r['seconds_median']:.2f} | "
                f"{r['bytes_median']/1e6:.2f} |"
            )
    else:
        lines.append("_No online measurements (API unreachable)._")
    lines += [
        "",
        "## Interpretation",
        "",
        "Deepscatter ranked trees are substantially smaller on disk than the full "
        "PMTiles LOD ladder, because MVT archives duplicate spatial tiles across six "
        "LOD aggressiveness levels. Cold transfer for MVT lod_3 is dominated by the "
        "single archive size; Deepscatter overview fetches a shallow subset of feathers.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS))
    ap.add_argument("--api-base", default=os.environ.get("RQ2_API_BASE", "http://127.0.0.1:8000"))
    ap.add_argument("--repeats", type=int, default=REPEATS)
    ap.add_argument("--skip-online", action="store_true")
    args = ap.parse_args()
    datasets = tuple(args.datasets)

    root = out_dir()
    print("=== Offline asset sizes ===", flush=True)
    offline = measure_offline(datasets)
    write_csv(offline, root / "rq2_offline.csv")
    for r in offline:
        print(
            f"  {r['dataset']:12s} {r['renderer']:24s} {r['bytes_on_disk']/1e6:8.2f} MB",
            flush=True,
        )

    online_rows: list[dict] = []
    online_summary: list[dict] = []
    if not args.skip_online:
        print(f"\n=== Online cold load ({args.api_base}) ===", flush=True)
        online_rows = measure_online_http(args.api_base, datasets, args.repeats)
        write_csv(online_rows, root / "rq2_online.csv")
        online_summary = summarize_online(online_rows)
        write_csv(online_summary, root / "rq2_online_summary.csv")

    figures = plot_results(offline, online_summary, root / "figures")
    for p in figures:
        print(f"Wrote {p}", flush=True)

    analysis = root / "rq2_analysis.md"
    write_analysis(offline, online_summary, analysis)
    print(f"Wrote {analysis}", flush=True)

    meta = {
        "datasets": list(datasets),
        "lod_level": LOD_LEVEL,
        "deepscatter_order": DEEPSCATTER_ORDER,
        "repeats": args.repeats,
        "api_base": args.api_base,
        "skip_online": args.skip_online,
    }
    (root / "rq2_meta.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
