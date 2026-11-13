#!/usr/bin/env python3
"""
markit_comparison.py

Compares the N-PORT data with IHS Markit dealer quotes over the overlapping period on three levels.

1. Loan level: loans with the same LoanX ID in both sources, month-end prices and monthly total
   returns. How close are fund fair values to Markit mid quotes, and do they move in the same month?
2. Benchmark level: equal-weighted total return index of the matched loans from both sources.
3. Factor level: the same factor definitions applied to both sources (factor_returns.parquet from
   factor_portfolios.py): correlation of long-short returns, mean returns and Dimson alphas.

Inputs
    <nport-dir>/loan_monthly_stm_cer.parquet,   <markit-dir>/loan_monthly_stm_cer.parquet
    <nport-results>/factor_returns.parquet,     <markit-results>/factor_returns.parquet

Usage
    python markit_comparison.py --start 2019-10 --end 2022-09
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "pipeline"))   # pipeline modules (repository layout)

from factor_portfolios import FACTORS, nw, stats


def load_monthly(path: Path) -> pd.DataFrame:
    d = pd.read_parquet(path, columns=["LOAN_KEY", "MONTH_END", "key_type", "price", "total_return", "return_outlier",
                                       "n_funds"])
    d["MONTH_END"] = pd.to_datetime(d["MONTH_END"]) + pd.offsets.MonthEnd(0)
    d = d[d["key_type"] == "LX"]
    d["tr"] = d["total_return"].where(~d["return_outlier"].fillna(False))
    return d[["LOAN_KEY", "MONTH_END", "price", "tr", "n_funds"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="N-PORT vs. Markit comparison")
    ap.add_argument("--nport-dir", default="nport_out")
    ap.add_argument("--markit-dir", default="markit_out")
    ap.add_argument("--nport-results", default="nport_out/factor_results_M")
    ap.add_argument("--markit-results", default="markit_out/factor_results_M")
    ap.add_argument("--start", default="2019-10")
    ap.add_argument("--end", default="2022-09")
    ap.add_argument("--out-dir", default="markit_comparison")
    args = ap.parse_args()
    t0, t1 = pd.Timestamp(args.start) + pd.offsets.MonthEnd(0), pd.Timestamp(args.end) + pd.offsets.MonthEnd(0)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pd.set_option("display.width", 200)

    # ------------------------------------------------------------- 1. loan level
    n = load_monthly(Path(args.nport_dir) / "loan_monthly_stm_cer.parquet")
    m = load_monthly(Path(args.markit_dir) / "loan_monthly_stm_cer.parquet")
    n, m = n[n["MONTH_END"].between(t0, t1)], m[m["MONTH_END"].between(t0, t1)]
    j = n.merge(m, on=["LOAN_KEY", "MONTH_END"], suffixes=("_np", "_mk"))
    j["diff"] = j["price_np"] - j["price_mk"]
    cover = j.groupby("MONTH_END").size() / n.groupby("MONTH_END").size()

    print(f"=== 1. Loan level ({args.start} to {args.end}) ===")
    print(f"Matched loan-months: {len(j):,}; loans: {j['LOAN_KEY'].nunique():,}; "
          f"median per month: {j.groupby('MONTH_END').size().median():.0f}")
    print(f"Share of N-PORT LX loans with a Markit quote (median per month): {cover.median():.1%}")
    print(f"Price difference N-PORT minus Markit mid (points): mean {j['diff'].mean():.3f}, "
          f"median {j['diff'].median():.3f}, mean absolute {j['diff'].abs().mean():.3f}")
    print(f"Share within 0.25 / 0.5 / 1 point: {(j['diff'].abs() <= .25).mean():.1%} / "
          f"{(j['diff'].abs() <= .5).mean():.1%} / {(j['diff'].abs() <= 1).mean():.1%}")
    print(f"Correlation of price levels: {j['price_np'].corr(j['price_mk']):.3f}")

    r = j.dropna(subset=["tr_np", "tr_mk"]).sort_values(["LOAN_KEY", "MONTH_END"]).copy()
    print(f"Monthly returns, pooled correlation: {r['tr_np'].corr(r['tr_mk']):.3f} ({len(r):,} loan-months)")
    xs = r.groupby("MONTH_END").apply(lambda g: g["tr_np"].corr(g["tr_mk"]) if len(g) > 10 else np.nan,
                                      include_groups=False)
    print(f"Cross-sectional correlation per month: median {xs.median():.3f}")
    g = r.groupby("LOAN_KEY")
    r["tr_mk_lag"] = g["tr_mk"].shift(1).where(g["MONTH_END"].shift(1) + pd.offsets.MonthEnd(1) == r["MONTH_END"])
    rr = r.dropna(subset=["tr_mk_lag"]).copy()
    fit = sm.OLS(rr["tr_np"], sm.add_constant(rr[["tr_mk", "tr_mk_lag"]])).fit(
        cov_type="cluster", cov_kwds={"groups": rr["MONTH_END"].astype("int64")})
    print(f"N-PORT return on Markit return t and t-1: beta(t) {fit.params['tr_mk']:.3f} "
          f"(t {fit.tvalues['tr_mk']:.1f}), beta(t-1) {fit.params['tr_mk_lag']:.3f} (t {fit.tvalues['tr_mk_lag']:.1f})")

    # agreement by number of reporting N-PORT funds
    bins, labels = [0, 2, 5, 10, np.inf], ["1-2", "3-5", "6-10", ">10"]
    j["funds_group"] = pd.cut(j["n_funds_np"], bins=bins, labels=labels)
    r["funds_group"] = pd.cut(r["n_funds_np"], bins=bins, labels=labels)
    rr["funds_group"] = pd.cut(rr["n_funds_np"], bins=bins, labels=labels)
    rows = []
    for gname, gj in j.groupby("funds_group", observed=True):
        gr = rr[rr["funds_group"] == gname]
        b = sm.OLS(gr["tr_np"], sm.add_constant(gr[["tr_mk", "tr_mk_lag"]])).fit().params if len(gr) > 30 else None
        rows.append({"funds": gname, "loan_months": len(gj), "mean_diff": gj["diff"].mean(),
                     "mean_abs_diff": gj["diff"].abs().mean(), "within_1pt": (gj["diff"].abs() <= 1).mean(),
                     "return_corr": r.loc[r["funds_group"] == gname, ["tr_np", "tr_mk"]].corr().iloc[0, 1],
                     "beta_t": b["tr_mk"] if b is not None else np.nan,
                     "beta_t1": b["tr_mk_lag"] if b is not None else np.nan})
    byf = pd.DataFrame(rows).set_index("funds")
    print("\nAgreement by number of reporting N-PORT funds:")
    print(byf.round(3).to_string())
    byf.to_csv(out / "agreement_by_funds.csv")

    # ------------------------------------------------------------- 2. benchmark level
    ew = r.groupby("MONTH_END")[["tr_np", "tr_mk"]].mean()
    print("\n=== 2. Equal-weighted index of the matched loans (total return) ===")
    print(f"Months: {len(ew)}; correlation {ew['tr_np'].corr(ew['tr_mk']):.3f}; tracking error "
          f"{(ew['tr_np'] - ew['tr_mk']).std() * np.sqrt(12) * 100:.2f}% p.a.")
    print(f"Mean return p.a.: N-PORT {ew['tr_np'].mean() * 1200:.2f}%, Markit {ew['tr_mk'].mean() * 1200:.2f}%; "
          f"volatility p.a.: N-PORT {ew['tr_np'].std() * np.sqrt(12) * 100:.2f}%, "
          f"Markit {ew['tr_mk'].std() * np.sqrt(12) * 100:.2f}%")
    ew.to_csv(out / "benchmark_matched_loans.csv")

    # ------------------------------------------------------------- 3. factor level
    fn = pd.read_parquet(Path(args.nport_results) / "factor_returns.parquet")
    fm = pd.read_parquet(Path(args.markit_results) / "factor_returns.parquet")
    rows = []
    for hold in sorted(set(fn["hold"]) & set(fm["hold"])):
        for name, (_col, direction) in FACTORS.items():
            a = fn[(fn["factor"] == name) & (fn["hold"] == hold)].pivot(index="date", columns="portfolio", values="return")
            b = fm[(fm["factor"] == name) & (fm["hold"] == hold)].pivot(index="date", columns="portfolio", values="return")
            if a.empty or b.empty:
                continue
            best = "5" if direction == 1 else "1"
            idx = a.index.intersection(b.index)
            idx = idx[(idx >= t0) & (idx <= t1)]
            if len(idx) < 12:
                continue
            a, b = a.loc[idx], b.loc[idx]
            sa, sb = stats(a[best], a["BM"], 12, 3), stats(b[best], b["BM"], 12, 3)
            rows.append({
                "holding": hold, "factor": name, "months": len(idx),
                "corr_LS": a["LS"].corr(b["LS"]), "corr_preferred": a[best].corr(b[best]),
                "LS_nport_bp": a["LS"].mean() * 1.2e5, "LS_markit_bp": b["LS"].mean() * 1.2e5,
                "t_LS_nport": nw(a["LS"], None, 3).tvalues[0], "t_LS_markit": nw(b["LS"], None, 3).tvalues[0],
                "dimson_alpha_nport_bp": sa["Dimson alpha p.a. (bp)"], "t_dimson_nport": sa["t Dimson alpha"],
                "dimson_alpha_markit_bp": sb["Dimson alpha p.a. (bp)"], "t_dimson_markit": sb["t Dimson alpha"],
            })
    res = pd.DataFrame(rows)
    res.to_csv(out / "factor_comparison.csv", index=False)
    print("\n=== 3. Factors: same definitions on both sources, common months ===")
    for hold, g in res.groupby("holding"):
        print(f"\nHolding period {hold} month(s):")
        print(g.drop(columns="holding").set_index("factor").round(2).to_string())

    # chart: cumulative long-short returns, holding period 1
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        names = [f for f in FACTORS if f in set(res.loc[res["holding"] == 1, "factor"])]
        cols = 3
        fig, axes = plt.subplots(int(np.ceil(len(names) / cols)), cols, figsize=(12, 3.2 * np.ceil(len(names) / cols)),
                                 squeeze=False)
        for ax, name in zip(axes.flat, names):
            for src, f, colour in [("N-PORT", fn, "#1A2E4A"), ("Markit", fm, "#B8972A")]:
                s = f[(f["factor"] == name) & (f["hold"] == 1) & (f["portfolio"] == "LS")].set_index("date")["return"]
                s = s[(s.index >= t0) & (s.index <= t1)]
                ax.plot(s.index, ((1 + s).cumprod() - 1) * 100, color=colour, lw=1.6, label=src)
            ax.set_title(name, fontsize=11)
            ax.axhline(0, color="#999", lw=0.6)
            ax.tick_params(labelsize=8)
        for ax in list(axes.flat)[len(names):]:
            ax.axis("off")
        axes.flat[0].legend(fontsize=8, frameon=False)
        fig.suptitle("Cumulative long-short returns (%): N-PORT vs. Markit, holding period 1 month", fontsize=12)
        fig.tight_layout()
        fig.savefig(out / "factor_comparison_ls.png", dpi=150)
    except ImportError:
        pass
    print(f"\nResults saved in: {out}")


if __name__ == "__main__":
    main()
