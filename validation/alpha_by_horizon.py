#!/usr/bin/env python3
"""
alpha_by_horizon.py

Alpha by month after portfolio formation (event-time analysis), as in Figure IA.3 of the FAJ paper.

For every factor and every k = 1 ... K, the portfolio is formed at t and only the return in
month t+k is evaluated (a single cohort, no overlapping portfolios). This shows in which month
after formation the premium arises and how quickly it decays.

Per factor and k:
    CAPM alpha and Dimson alpha (benchmark at t, t-1, t-2) of the preferred portfolio against
    the benchmark (all sorted loans), annualized in bp, Newey-West t-statistics (lag 3),
    plus the long-short return (preferred minus opposite)

By default, all k of a factor are restricted to the same return months, so that differences
between the k do not depend on the sample period (disable with --no-common).

Requirement: factor_portfolios.py in the same folder (functions and factor definitions).

Usage
    python alpha_by_horizon.py                    (k = 1 ... 12, equal-weighted)
    python alpha_by_horizon.py --max-k 6 --weighting vw_cap
"""

import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "pipeline"))   # pipeline modules (repository layout)

from factor_portfolios import FACTORS, nw, portfolio_returns

warnings.filterwarnings("ignore", message="invalid value encountered in sqrt")


def alphas(p: pd.Series, bm: pd.Series, ppy: int, lags: int) -> dict:
    d = pd.concat([p.rename("p"), bm.rename("b")], axis=1).dropna()
    capm = nw(d["p"], d["b"], lags)
    dl = pd.concat([d["p"], d["b"], d["b"].shift(1).rename("b1"), d["b"].shift(2).rename("b2")], axis=1).dropna()
    dim = sm.OLS(dl["p"].values, sm.add_constant(dl[["b", "b1", "b2"]].values)).fit(
        cov_type="HAC", cov_kwds={"maxlags": lags})
    return {"alpha": capm.params[0] * ppy * 1e4, "t_alpha": capm.tvalues[0],
            "dimson_alpha": dim.params[0] * ppy * 1e4, "t_dimson": dim.tvalues[0],
            "months": len(d)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Alpha by month after portfolio formation")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--max-k", type=int, default=12, help="last month after formation (default 12)")
    ap.add_argument("--ret", choices=["ret", "ret_paper"], default="ret")
    ap.add_argument("--weighting", choices=["ew", "vw", "vw_cap"], default="ew")
    ap.add_argument("--exit", choices=["impute", "none"], default="impute")
    ap.add_argument("--quantiles", type=int, default=5)
    ap.add_argument("--no-common", action="store_true",
                    help="do not restrict to common return months per factor")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    ppy, lags, step, q = 12, 3, 1, args.quantiles
    base = Path(args.dir)
    df = pd.read_parquet(base / "loan_characteristics_M.parquet")
    df["MONTH_END"] = pd.to_datetime(df["MONTH_END"])
    if "exit_row" in df and args.exit == "none":
        df = df[~df["exit_row"].fillna(False).astype(bool)]
    df = df.sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)
    out_dir = Path(args.out_dir) if args.out_dir else base / "alpha_by_horizon"
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Return: {args.ret} | Weighting: {args.weighting} | Exits: {args.exit} | "
          f"k = 1 ... {args.max_k} | common months per factor: {not args.no_common}")

    rows = []
    for name, (col, direction) in FACTORS.items():
        if col not in df or not df.loc[df["universe"], col].notna().any():
            continue
        best, worst = (q, 1) if direction == 1 else (1, q)
        series = {}
        for k in range(1, args.max_k + 1):
            pr = portfolio_returns(df, col, q, step, 1, args.ret, lag=k - 1, weighting=args.weighting)
            if pr.empty or best not in pr or worst not in pr:
                continue
            series[k] = pr[[best, worst, "BM"]].dropna()
        if not series:
            continue
        if not args.no_common:
            common = set.intersection(*(set(s.index) for s in series.values()))
            series = {k: s.loc[sorted(common)] for k, s in series.items()}
        for k, s in series.items():
            if len(s) < 24:
                continue
            r = alphas(s[best], s["BM"], ppy, lags)
            ls = s[best] - s[worst]
            t_ls = nw(ls, None, lags).tvalues[0]
            rows.append({"factor": name, "k": k, **r,
                         "long_short": ls.mean() * ppy * 1e4, "t_long_short": t_ls})

    res = pd.DataFrame(rows)
    res.to_csv(out_dir / f"alpha_by_horizon_{args.weighting}.csv", index=False)
    pd.set_option("display.width", 220)

    def pivot(val, tval):
        a = res.pivot(index="factor", columns="k", values=val).reindex(
            [f for f in FACTORS if f in res["factor"].unique()])
        t = res.pivot(index="factor", columns="k", values=tval).reindex(a.index)
        return a.round(0).astype("Int64").astype(str) + " (" + t.round(1).astype(str) + ")"

    print("\n=== Dimson alpha p.a. in bp (t-stat) by month k after portfolio formation ===")
    print(pivot("dimson_alpha", "t_dimson").to_string())
    print("\n=== CAPM alpha p.a. in bp (t-stat) ===")
    print(pivot("alpha", "t_alpha").to_string())
    print("\n=== Long-short p.a. in bp (t-stat) ===")
    print(pivot("long_short", "t_long_short").to_string())
    months = res.groupby("factor")["months"].first().reindex(
        [f for f in FACTORS if f in res["factor"].unique()])
    print("\nReturn months per factor (same for all k):")
    print(months.to_string())

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        for name in [f for f in FACTORS if f in res["factor"].unique()]:
            d = res[res["factor"] == name].sort_values("k")
            ax.plot(d["k"], d["dimson_alpha"], marker="o", lw=1.4, ms=3, label=name)
        ax.axhline(0, color="black", lw=0.8)
        ax.set_xlabel("Month after portfolio formation")
        ax.set_ylabel("Dimson alpha (bp p.a.)")
        ax.set_title(f"Factor alpha by month after formation ({args.weighting})")
        ax.set_xticks(range(1, args.max_k + 1))
        ax.legend(fontsize=8, ncol=3)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / f"alpha_by_horizon_{args.weighting}.png", dpi=150)
    except ImportError:
        pass
    print(f"\nResults saved in: {out_dir}")


if __name__ == "__main__":
    main()
