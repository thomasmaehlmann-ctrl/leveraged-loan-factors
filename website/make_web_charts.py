#!/usr/bin/env python3
"""
make_web_charts.py

Creates the two charts for loanfactors.org as SVG files in the site's img/ folder:

    img/benchmark_vs_index.svg   Figure 1: N-PORT benchmark (equal-weighted) vs. Morningstar LSTA index
    img/alpha_by_horizon.svg     Figure 2: Dimson alpha by month after portfolio formation

Inputs (outputs of the pipeline)
    nport_out/validation/benchmark_vs_index_monthly.csv      from benchmark_validation.py
    nport_out/alpha_by_horizon/alpha_by_horizon_ew.csv       from alpha_by_horizon.py

Usage
    python make_web_charts.py --site loanfactors.org
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

INK, GOLD, SLATE, RULE = "#1A2E4A", "#B8972A", "#586273", "#D9DFE7"
FACTOR_STYLE = {          # factors shown in Figure 2 and their colours
    "Momentum": INK,
    "IVOL": GOLD,
    "Illiquidity": "#3F7FA6",
    "Low Risk": "#9AA4B2",
}


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(RULE)
    ax.tick_params(colors=SLATE, labelsize=10)
    ax.yaxis.label.set_color(SLATE)
    ax.xaxis.label.set_color(SLATE)
    ax.grid(axis="y", color=RULE, lw=0.8)
    ax.set_axisbelow(True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Charts for loanfactors.org")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--site", default="loanfactors.org", help="folder of the website (img/ is written there)")
    args = ap.parse_args()
    base, img = Path(args.dir), Path(args.site) / "img"
    img.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "path"})

    # Figure 1
    d = pd.read_csv(base / "validation" / "benchmark_vs_index_monthly.csv", index_col=0, parse_dates=True)
    d = d[["Index", "EW universe"]].dropna()
    cum = ((1 + d).cumprod() - 1) * 100
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.plot(cum.index, cum["Index"], color=SLATE, lw=3.2, alpha=0.45,
            label="Morningstar LSTA US Leveraged Loan Index")
    ax.plot(cum.index, cum["EW universe"], color=INK, lw=1.6, label="N-PORT benchmark (equal-weighted)")
    ax.set_ylabel("Cumulative total return (%)")
    style(ax)
    ax.legend(frameon=False, fontsize=10, loc="upper left", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(img / "benchmark_vs_index.svg")
    plt.close(fig)

    # Figure 2
    a = pd.read_csv(base / "alpha_by_horizon" / "alpha_by_horizon_ew.csv")
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for name, colour in FACTOR_STYLE.items():
        g = a[a["factor"] == name].sort_values("k")
        if len(g):
            ax.plot(g["k"], g["dimson_alpha"], color=colour, lw=2, marker="o", ms=4, label=name)
    ax.axhline(0, color=SLATE, lw=0.8)
    ax.set_xlabel("Month after portfolio formation")
    ax.set_ylabel("Dimson alpha (bp p.a.)")
    ax.set_xticks(range(1, int(a["k"].max()) + 1))
    style(ax)
    ax.legend(frameon=False, fontsize=10, ncol=4, loc="upper left", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(img / "alpha_by_horizon.svg")
    plt.close(fig)
    print(f"Charts written to {img}")


if __name__ == "__main__":
    main()
