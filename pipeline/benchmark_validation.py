#!/usr/bin/env python3
"""
benchmark_validation.py

Compares the N-PORT benchmark with the Morningstar LSTA US Leveraged Loan Index
(Bloomberg: SPBDAL Index, total return index levels, month-end), as in
Exhibit A1 of the JPM paper.

Benchmark variants (total return; return in t of loans that were in the universe in t-1)
    EW universe      equal-weighted, universe as in the factor analysis
                     (price between min(20% quantile, 80) and 105, remaining maturity > 120 days)
    VW universe      weighted by the market value of fund holdings (12-month average)
    EW LX only       equal-weighted, loans with LoanX ID only
    EW all prices    equal-weighted, without price filter (like the index, incl. distressed loans)

Statistics
    correlation of monthly returns, mean return and volatility p.a., tracking error,
    beta on the index, Dimson beta (index at t and t-1) as indication of smoothed valuations,
    annual returns, chart of cumulative returns

Usage
    python benchmark_validation.py --index S_P_LL_Index.csv      (.xlsx also possible)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm


def month_end(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize() + pd.offsets.MonthEnd(0)


def parse_number(s: pd.Series) -> pd.Series:
    """Numbers also in German format (2.925,44 or 2925,44)."""
    s = s.astype(str).str.strip().str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    both = s.str.contains(",") & s.str.contains(r"\.")
    s = s.where(~both, s.str.replace(".", "", regex=False))
    thousands_only = s.str.fullmatch(r"\d{1,3}(\.\d{3})+")
    s = s.where(~thousands_only, s.str.replace(".", "", regex=False))
    return pd.to_numeric(s.str.replace(",", ".", regex=False), errors="coerce")


def parse_date(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    d = pd.to_datetime(s, format="%d.%m.%Y", errors="coerce")
    for fmt in ("%Y-%m-%d", "%d.%m.%y", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        rest = d.isna()
        if rest.any():
            d.loc[rest] = pd.to_datetime(s[rest], format=fmt, errors="coerce")
    return d


def load_index(path: str) -> pd.Series:
    """Reads the first date column and the index levels next to it (Excel or CSV)."""
    if Path(path).suffix.lower() == ".csv":
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
        sep = ";" if head.count(";") >= head.count(",") / 2 else ("\t" if "\t" in head else ",")
        raw = pd.read_csv(path, header=None, sep=sep, dtype=str, encoding_errors="replace")
        to_date, to_num = parse_date, parse_number
    else:
        raw = pd.read_excel(path, header=None)
        to_date = lambda x: pd.to_datetime(x, errors="coerce")
        to_num = lambda x: pd.to_numeric(x, errors="coerce")
    for j in range(raw.shape[1] - 1):
        dates = to_date(raw.iloc[:, j])
        vals = to_num(raw.iloc[:, j + 1])
        ok = dates.notna() & vals.notna()
        if ok.sum() >= 12:
            s = pd.Series(vals[ok].values, index=month_end(dates[ok]))
            s = s[~s.index.duplicated(keep="last")].sort_index()
            print(f"Index: {len(s)} monthly values from {s.index.min():%Y-%m} to {s.index.max():%Y-%m}")
            return s.pct_change().rename("Index")
    raise SystemExit("No date and value column found in the file.")


def shifted(df: pd.DataFrame, col: str, k: int) -> pd.Series:
    g = df.groupby("LOAN_KEY")
    ok = g["MONTH_END"].shift(k) == df["MONTH_END"] - pd.offsets.MonthEnd(k)
    return g[col].shift(k).where(ok)


def build_benchmarks(base: Path) -> pd.DataFrame:
    df = pd.read_parquet(base / "loan_monthly_stm_cer.parquet",
                         columns=["LOAN_KEY", "MONTH_END", "key_type", "price", "maturity",
                                  "total_return", "return_outlier", "margin_plausible"])
    df["MONTH_END"] = month_end(df["MONTH_END"])
    df["maturity"] = pd.to_datetime(df["maturity"], errors="coerce")
    pv = pd.read_parquet(base / "loan_price_panel_v2.parquet", columns=["LOAN_KEY", "MONTH_END", "value_total"])
    pv["MONTH_END"] = month_end(pv["MONTH_END"])
    df = df.merge(pv, on=["LOAN_KEY", "MONTH_END"], how="left")
    df = df[df["key_type"] != "NM"].sort_values(["LOAN_KEY", "MONTH_END"]).reset_index(drop=True)

    # universe at time t (formation), return in t+1
    lower = df.groupby("MONTH_END")["price"].transform(lambda s: s.quantile(0.20)).clip(upper=80)
    days_left = (df["maturity"] - df["MONTH_END"]).dt.days
    df["uni"] = df["price"].between(lower, 105) & (days_left > 120) & df["margin_plausible"].fillna(False)
    df["any_price"] = df["price"].notna() & (days_left > 120)

    # weight: market value of fund holdings, average of the last 12 months
    w = (df.set_index("MONTH_END").groupby("LOAN_KEY")["value_total"]
           .rolling("366D", min_periods=1).mean().reset_index().rename(columns={"value_total": "w"}))
    df = df.merge(w, on=["LOAN_KEY", "MONTH_END"], how="left")

    tr = df["total_return"].where(~df["return_outlier"].fillna(False))
    df["r_next"] = shifted(df.assign(tr=tr), "tr", -1)
    df["date"] = df["MONTH_END"] + pd.offsets.MonthEnd(1)

    def ew(mask):
        d = df[mask & df["r_next"].notna()]
        return d.groupby("date")["r_next"].mean()

    def vw(mask):
        d = df[mask & df["r_next"].notna() & (df["w"] > 0)]
        rw = (d["r_next"] * d["w"]).groupby(d["date"]).sum()
        return rw / d.groupby("date")["w"].sum()

    out = pd.DataFrame({
        "EW universe": ew(df["uni"]),
        "VW universe": vw(df["uni"]),
        "EW LX only": ew(df["uni"] & (df["key_type"] == "LX")),
        "EW all prices": ew(df["any_price"]),
    })
    n = df[df["uni"] & df["r_next"].notna()].groupby("date").size().rename("Loans (EW universe)")
    return out.join(n)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare the N-PORT benchmark with the LSTA index")
    ap.add_argument("--index", required=True, help="Excel or CSV file with date and index level")
    ap.add_argument("--dir", default="nport_out")
    args = ap.parse_args()

    base = Path(args.dir)
    idx = load_index(args.index)
    bm = build_benchmarks(base)
    data = bm.join(idx, how="inner").dropna(subset=["Index", "EW universe"])
    print(f"Common period: {data.index.min():%Y-%m} to {data.index.max():%Y-%m} ({len(data)} months), "
          f"median {data['Loans (EW universe)'].median():.0f} loans per month\n")

    rows = {}
    series = ["Index", "EW universe", "VW universe", "EW LX only", "EW all prices"]
    for c in series:
        d = data[[c]].join(data[["Index"]], rsuffix="_idx").dropna() if c != "Index" else data[["Index"]].dropna()
        if c == "Index":
            rows[c] = {"Return p.a. (%)": d["Index"].mean() * 12 * 100,
                       "Volatility p.a. (%)": d["Index"].std() * np.sqrt(12) * 100,
                       "Correlation with index": 1.0}
            continue
        r = {"Return p.a. (%)": d[c].mean() * 12 * 100,
             "Volatility p.a. (%)": d[c].std() * np.sqrt(12) * 100,
             "Correlation with index": d[c].corr(d["Index"])}
        if c != "Index":
            r["Tracking error p.a. (%)"] = (d[c] - d["Index"]).std() * np.sqrt(12) * 100
            r["Beta"] = sm.OLS(d[c], sm.add_constant(d["Index"])).fit().params.iloc[1]
            dl = pd.concat([d[c], d["Index"], d["Index"].shift(1).rename("lag")], axis=1).dropna()
            dim = sm.OLS(dl[c], sm.add_constant(dl[["Index", "lag"]])).fit()
            r["Beta on index(t)"] = dim.params["Index"]
            r["Beta on index(t-1)"] = dim.params["lag"]
            r["Dimson beta"] = dim.params["Index"] + dim.params["lag"]
            r["Correlation with index(t-1)"] = d[c].corr(d["Index"].shift(1))
        rows[c] = r
    tab = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    print("=== Monthly returns: N-PORT benchmarks vs. Morningstar LSTA US Leveraged Loan Index ===")
    print(tab.round(3).to_string(na_rep=""))

    ann = (1 + data[series]).groupby(data.index.year).prod() - 1
    cnt = data.groupby(data.index.year).size()
    ann = (ann * 100).round(2)
    ann["Months"] = cnt
    print("\n=== Annual returns (%), common months only ===")
    print(ann.to_string())

    print("\n=== Crisis months 2020 (%) ===")
    print((data.loc["2020-02":"2020-06", series] * 100).round(2).to_string())

    out_dir = base / "validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    data.to_csv(out_dir / "benchmark_vs_index_monthly.csv")
    tab.to_csv(out_dir / "benchmark_vs_index_stats.csv")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5))
        styles = {"Index": ("black", 2.2), "EW universe": ("tab:red", 1.4), "VW universe": ("tab:blue", 1.2),
                  "EW LX only": ("tab:green", 1.2), "EW all prices": ("tab:orange", 1.2)}
        labels_en = {"Index": "Morningstar LSTA US Leveraged Loan Index",
                     "EW universe": "N-PORT benchmark, equal-weighted",
                     "VW universe": "N-PORT benchmark, value-weighted",
                     "EW LX only": "N-PORT benchmark, equal-weighted, LoanX IDs only",
                     "EW all prices": "N-PORT benchmark, equal-weighted, all prices"}
        for c, (col, lw) in styles.items():
            ax.plot(data.index, ((1 + data[c].fillna(0)).cumprod() - 1) * 100, color=col, lw=lw,
                    label=labels_en[c])
        ax.set_ylabel("Cumulative total return (%)")
        ax.set_title("N-PORT benchmark vs. Morningstar LSTA US Leveraged Loan Index")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "benchmark_vs_index.png", dpi=150)
    except ImportError:
        pass
    print(f"\nResults saved in: {out_dir}")


if __name__ == "__main__":
    main()
