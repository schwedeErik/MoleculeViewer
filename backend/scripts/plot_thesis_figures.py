"""Render the thesis evaluation figures from the stored result tables.

Reads the CSVs written by ``eval_rq1.py``, ``eval_rq1_large.py`` and
``eval_rq2.py`` (no recomputation) and writes print-ready PNGs:

* RQ1: one three-panel figure per metric (ZINC 10k, ZINC 250k, ChEMBL).
  Ranked order vs. shuffled order; for the two larger libraries the shuffled
  curve is the mean of ten seeds with a +-1 std band. Dotted vertical lines
  mark the Deepscatter full-view budgets (5k, 20k, 75k points).
* RQ2: asset size, cold-load time and transfer volume.

Run from ``backend/``::

    python -m scripts.plot_thesis_figures                      # writes data/eval_*/figures/
    python -m scripts.plot_thesis_figures --copy-to ../../latex_thesis/gfx
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DATA = Path(__file__).resolve().parents[2] / "data"

DATASETS = [("zinc10k", "ZINC 10k"), ("zinc250k", "ZINC 250k"), ("chembl13m", "ChEMBL 1.3M")]
BUDGETS = (5_000, 20_000, 75_000)
RANKED = dict(color="#1f5fa8", marker="o", ms=3, lw=1.6, label="ranked")
SHUFFLED = dict(color="#d9822b", marker="s", ms=3, lw=1.4, ls="--", label="shuffled")

RQ1_METRICS = {
    "fill_max": ("max. fill distance $h_{\\max}$", "lower is better"),
    "fill_mean": ("mean fill distance", "lower is better"),
    "cluster_coverage": ("cluster coverage", "higher is better"),
    "redundancy_nn_tanimoto": ("redundancy (NN Tanimoto)", "lower is better"),
    "scaffolds_per_point": ("scaffolds per point", "higher is better"),
}

plt.rcParams.update(
    {
        "font.size": 8.5,
        "axes.titlesize": 9,
        "axes.labelsize": 8.5,
        "legend.fontsize": 7.5,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": 300,
    }
)


def load_rq1() -> tuple[pd.DataFrame, pd.DataFrame]:
    base = pd.read_csv(DATA / "eval_rq1" / "rq1_metrics.csv")
    large = pd.read_csv(DATA / "eval_rq1_large" / "rq1_large_metrics.csv")
    large = large[~large["dataset"].str.contains("bridge")]
    return base, large


def _budget_lines(ax, kmax: float) -> None:
    for b in BUDGETS:
        if b < kmax:
            ax.axvline(b, color="0.6", lw=0.7, ls=":", zorder=0)


def plot_rq1_metric(base: pd.DataFrame, large: pd.DataFrame, metric: str, out: Path) -> None:
    ylabel, hint = RQ1_METRICS[metric]
    fig, axes = plt.subplots(1, 3, figsize=(6.3, 2.55), layout="constrained")
    for ax, (slug, title) in zip(axes, DATASETS):
        d = base[(base["dataset"] == slug)].dropna(subset=[metric])
        d = d[d["k"] < d["n"]] if metric in ("fill_max", "fill_mean") else d
        r = d[d["order"] == "ranked"].sort_values("k")
        ax.plot(r["k"], r[metric], **RANKED)
        sm = large[(large["dataset"] == slug) & (large["order"] == "shuffled_mean")].dropna(subset=[metric])
        if not sm.empty:
            sm = sm.sort_values("k")
            lab = dict(SHUFFLED, label="shuffled: mean of 10 seeds (band: $\\pm$1 std)")
            ax.plot(sm["k"], sm[metric], **lab)
            std = sm.get(f"{metric}_std")
            if std is not None and std.notna().any():
                ax.fill_between(sm["k"], sm[metric] - std, sm[metric] + std, color=SHUFFLED["color"], alpha=0.2, lw=0)
        else:
            s = d[d["order"] == "shuffled"].sort_values("k")
            ax.plot(s["k"], s[metric], **dict(SHUFFLED, label="shuffled: seed 42"))
        if metric == "redundancy_nn_tanimoto":
            ax.axvline(2_000, color="0.35", lw=0.8, ls="-.", zorder=0)
        ax.set_xscale("log")
        ax.set_title(title)
        ax.set_xlabel("prefix size $k$")
        ax.grid(alpha=0.25, which="major")
        _budget_lines(ax, r["k"].max() if not r.empty else 1e9)
    axes[0].set_ylabel(f"{ylabel}\n({hint})")
    handles, labels = [], []
    for ax in (axes[0], axes[1]):
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in labels:
                handles.append(h)
                labels.append(l)
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    fig.savefig(out)
    plt.close(fig)


def plot_rq1_relative_gain(base: pd.DataFrame, large: pd.DataFrame, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.2, 2.4), constrained_layout=True)
    colors = {"zinc10k": "#2a9d8f", "zinc250k": "#1f5fa8", "chembl13m": "#8e44ad"}
    for slug, title in DATASETS:
        r = base[(base["dataset"] == slug) & (base["order"] == "ranked")].set_index("k")["fill_mean"]
        sm = large[(large["dataset"] == slug) & (large["order"] == "shuffled_mean")].set_index("k")["fill_mean"]
        if sm.empty:
            sm = base[(base["dataset"] == slug) & (base["order"] == "shuffled")].set_index("k")["fill_mean"]
        n = int(base[base["dataset"] == slug]["n"].iloc[0])
        ks = sorted(k for k in r.index.intersection(sm.index) if k < n)
        gain = [(sm[k] - r[k]) / sm[k] * 100 for k in ks]
        ax.plot(ks, gain, marker="o", ms=3, lw=1.5, color=colors[slug], label=title)
    ax.axhline(0, color="0.2", lw=0.8)
    lo, hi = ax.get_ylim()
    ax.axhspan(lo, 0, color="0.9", zorder=0)
    ax.set_ylim(lo, hi)
    ax.text(0.6, 0.04, "random order better", transform=ax.transAxes, ha="center", fontsize=7, color="0.35")
    ax.text(0.99, 0.94, "ranked order better", transform=ax.transAxes, ha="right", va="top", fontsize=7, color="0.35")
    _budget_lines(ax, 1e9)
    ax.set_xscale("log")
    ax.set_xlabel("prefix size $k$")
    ax.set_ylabel("ranked advantage in\nmean fill distance (%)")
    ax.grid(alpha=0.25)
    ax.legend(frameon=False, loc="lower left")
    fig.savefig(out)
    plt.close(fig)


def plot_rq2(out_dir: Path) -> list[Path]:
    off = pd.read_csv(DATA / "eval_rq2" / "rq2_offline.csv")
    on = pd.read_csv(DATA / "eval_rq2" / "rq2_online_summary.csv")
    labels = [t for _, t in DATASETS]
    x = np.arange(len(DATASETS))
    outs = []

    def size(slug, renderer):
        return off[(off["dataset"] == slug) & (off["renderer"] == renderer)]["bytes_on_disk"].iloc[0] / 1e6

    fig, ax = plt.subplots(figsize=(5.2, 2.4), constrained_layout=True)
    series = [
        ("deepscatter", "Deepscatter tree (all LOD steps)", "#1f5fa8"),
        ("mvt_pmtiles_lod3_only", "MVT archive, LOD step 3", "#e9a35a"),
        ("mvt_pmtiles", "MVT archives, LOD steps 1–6", "#b5651d"),
    ]
    w = 0.26
    for i, (ren, lab, col) in enumerate(series):
        vals = [size(s, ren) for s, _ in DATASETS]
        bars = ax.bar(x + (i - 1) * w, vals, w, label=lab, color=col)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v * 1.12, f"{v:.1f}" if v < 10 else f"{v:.0f}", ha="center", fontsize=6.5)
    ax.set_yscale("log")
    ax.set_ylim(0.2, 5000)
    ax.set_xticks(x, labels)
    ax.set_ylabel("size on disk (MB, log scale)")
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    p = out_dir / "rq2_asset_size.png"
    fig.savefig(p)
    plt.close(fig)
    outs.append(p)

    def online(slug, renderer, col):
        return on[(on["dataset"] == slug) & (on["renderer"] == renderer)][col].iloc[0]

    for name, col, scale, ylabel, logy in [
        ("rq2_cold_load_time.png", "seconds_median", 1000, "median transfer time (ms)", False),
        ("rq2_cold_transfer.png", "bytes_median", 1e-6, "transferred (MB, log scale)", True),
    ]:
        fig, ax = plt.subplots(figsize=(5.2, 2.3), constrained_layout=True)
        for i, (ren, lab, c) in enumerate(
            [("deepscatter", "Deepscatter (complete tree)", "#1f5fa8"), ("mvt_pmtiles", "MVT (complete LOD-3 archive)", "#e9a35a")]
        ):
            vals = [online(s, ren, col) * scale for s, _ in DATASETS]
            err = None
            if col == "seconds_median":
                err = [online(s, ren, "seconds_stdev") * scale for s, _ in DATASETS]
            bars = ax.bar(x + (i - 0.5) * 0.36, vals, 0.36, yerr=err, capsize=2, label=lab, color=c)
            for j, (b, v) in enumerate(zip(bars, vals)):
                top = v * 1.15 if logy else v + (err[j] if err else 0) + 15
                ax.text(b.get_x() + b.get_width() / 2, top, f"{v:.0f}" if v >= 10 else f"{v:.1f}", ha="center", fontsize=6.5)
        if logy:
            ax.set_yscale("log")
            ax.set_ylim(0.2, 1000)
        ax.set_xticks(x, labels)
        ax.set_ylabel(ylabel)
        ax.legend(frameon=False, fontsize=7, loc="upper left")
        p = out_dir / name
        fig.savefig(p)
        plt.close(fig)
        outs.append(p)
    return outs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--copy-to", type=Path, help="Also copy the PNGs into <dir>/eval_rq1 and <dir>/eval_rq2")
    args = ap.parse_args()

    base, large = load_rq1()
    rq1_dir = DATA / "eval_rq1" / "figures"
    rq2_dir = DATA / "eval_rq2" / "figures"
    rq1_dir.mkdir(parents=True, exist_ok=True)
    rq2_dir.mkdir(parents=True, exist_ok=True)

    rq1 = []
    for metric in RQ1_METRICS:
        p = rq1_dir / f"rq1_{metric}.png"
        plot_rq1_metric(base, large, metric, p)
        rq1.append(p)
    p = rq1_dir / "rq1_relative_fill_gain.png"
    plot_rq1_relative_gain(base, large, p)
    rq1.append(p)
    rq2 = plot_rq2(rq2_dir)

    for p in rq1 + rq2:
        print("wrote", p)
    if args.copy_to:
        for p in rq1:
            shutil.copy2(p, args.copy_to / "eval_rq1" / p.name)
        for p in rq2:
            shutil.copy2(p, args.copy_to / "eval_rq2" / p.name)
        print("copied to", args.copy_to)


if __name__ == "__main__":
    main()
