#!/usr/bin/env python3
"""
describe_panel.py

Descriptive statistics of the N-PORT loan panel for Table 2.1 (and an annual Table 2.2) of the methods paper.

Inputs (pipeline outputs in --dir)
    rekeyed/                          cleaned individual holdings (from nport_rekey.py), optional
    loan_monthly_stm_cer.parquet      monthly loan panel (from nport_loan_returns.py)
    loan_characteristics_M.parquet    universe, returns and exits (from loan_characteristics.py)

Outputs (in --out-dir)
    table2_1.csv / table2_1.md        summary statistics (Table 2.1)
    table2_2_by_year.csv / .md        statistics by calendar year (Table 2.2)

Usage
    python describe_panel.py
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def month_end(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize() + pd.offsets.MonthEnd(0)


def holdings_stats(rk: Path) -> dict:
    """Fund- and holding-level statistics from the cleaned individual holdings (DuckDB, out-of-core)."""
    import duckdb
    src = f"read_parquet('{rk.as_posix()}/**/*.parquet', hive_partitioning = true)"
    con = duckdb.connect()
    per_month = con.execute(f"""
        SELECT CAST(MONTH_END AS DATE) AS m, count(DISTINCT FUND_KEY) AS funds, count(*) AS holdings
        FROM {src} WHERE PRICE_PLAUSIBLE AND NOT IS_UNFUNDED_OR_REVOLVER GROUP BY 1 ORDER BY 1""").df()
    keys = con.execute(f"""
        SELECT KEY_TYPE, count(*) AS holdings, count(DISTINCT LOAN_KEY) AS loans,
               sum(CURRENCY_VALUE) AS market_value, median(CURRENCY_VALUE) AS median_holding_value,
               count(DISTINCT FUND_KEY) AS funds
        FROM {src} WHERE PRICE_PLAUSIBLE AND NOT IS_UNFUNDED_OR_REVOLVER GROUP BY 1""").df()
    lx = con.execute(f"""
        SELECT lx_source, count(DISTINCT LOAN_KEY) AS loans
        FROM {src} WHERE KEY_TYPE = 'LX' AND PRICE_PLAUSIBLE GROUP BY 1""").df()
    total_funds = con.execute(f"SELECT count(DISTINCT FUND_KEY) FROM {src}").fetchone()[0]
    # report dates per fund and calendar year; only full calendar years and funds reporting in both
    # the first and the last quarter of the year (avoids counting fund launches and liquidations)
    fy = con.execute(f"""
        WITH d AS (SELECT DISTINCT FUND_KEY, CAST(MONTH_END AS DATE) AS m FROM {src}),
             y AS (SELECT FUND_KEY, year(m) AS yr, count(*) AS n_dates,
                          min(month(m)) AS first_m, max(month(m)) AS last_m FROM d GROUP BY 1, 2)
        SELECT * FROM y
        WHERE yr > (SELECT min(year(m)) FROM d) AND yr < (SELECT max(year(m)) FROM d)
          AND first_m <= 3 AND last_m >= 10""").df()
    con.close()
    keys["share_holdings"] = keys["holdings"] / keys["holdings"].sum()
    keys["share_loans"] = keys["loans"] / keys["loans"].sum()
    keys["share_value"] = keys["market_value"] / keys["market_value"].sum()
    lx["share"] = lx["loans"] / lx["loans"].sum()
    return {"per_month": per_month, "keys": keys, "lx": lx, "total_funds": total_funds, "fund_years": fy}


def main() -> None:
    ap = argparse.ArgumentParser(description="Descriptive statistics of the N-PORT loan panel")
    ap.add_argument("--dir", default="nport_out")
    ap.add_argument("--out-dir", default="paper_tables")
    args = ap.parse_args()
    base, out = Path(args.dir), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    def add(label, value):
        rows.append({"statistic": label, "value": value})

    # ---------------------------------------------------------------- holdings
    rk = base / "rekeyed"
    if rk.exists():
        h = holdings_stats(rk)
        pm = h["per_month"]
        add("Funds reporting loan holdings, total", f"{h['total_funds']:,}")
        add("Funds reporting loan holdings per month (median / min / max)",
            f"{pm['funds'].median():,.0f} / {pm['funds'].min():,} / {pm['funds'].max():,}")
        add("Loan holdings per month (median)", f"{pm['holdings'].median():,.0f}")
        fy = h["fund_years"]
        if len(fy):
            add(f"Report dates per fund and year, full years {fy['yr'].min()}–{fy['yr'].max()} (median / mean)",
                f"{fy['n_dates'].median():.0f} / {fy['n_dates'].mean():.1f}")
            add("  share of fund-years with exactly 4 / 5–11 / 12 report dates",
                f"{(fy['n_dates'] == 4).mean():.1%} / {fy['n_dates'].between(5, 11).mean():.1%} / "
                f"{(fy['n_dates'] >= 12).mean():.1%}")
            by_y = fy.groupby("yr")["n_dates"].agg(["count", "mean", lambda x: (x >= 12).mean()])
            by_y.columns = ["fund_years", "mean_report_dates", "share_12"]
            print("\nReport dates per fund and calendar year:")
            print(by_y.round(2).to_string())
        print("Key types (holdings, loans, market value):")
        print(h["keys"].round(3).to_string(index=False))
        print("\nOrigin of LoanX IDs (share of loans):")
        print(h["lx"].round(3).to_string(index=False))
        for r in h["keys"].itertuples():
            add(f"Key type {r.KEY_TYPE}: share of holdings / loans / market value",
                f"{r.share_holdings:.1%} / {r.share_loans:.1%} / {r.share_value:.1%}")
            add(f"Key type {r.KEY_TYPE}: median holding value (USD) / funds",
                f"{r.median_holding_value:,.0f} / {r.funds:,}")
        for r in h["lx"].itertuples():
            add(f"LoanX IDs from {r.lx_source}: share of LX loans", f"{r.share:.1%}")
    else:
        print(f"Note: {rk} not found, holding-level statistics skipped.")

    # ---------------------------------------------------------------- loan panel
    mp = pd.read_parquet(base / "loan_monthly_stm_cer.parquet",
                         columns=["LOAN_KEY", "MONTH_END", "key_type", "n_funds", "price", "any_default"])
    mp["MONTH_END"] = month_end(mp["MONTH_END"])
    mp = mp[mp["key_type"] != "NM"]
    ch = pd.read_parquet(base / "loan_characteristics_M.parquet",
                         columns=["LOAN_KEY", "MONTH_END", "universe", "n_funds", "price", "margin", "stm",
                                  "ret", "exit_row", "key_type", "value_total"])
    ch["MONTH_END"] = month_end(ch["MONTH_END"])
    obs = ch[~ch["exit_row"].fillna(False).astype(bool)]
    u = obs[obs["universe"].fillna(False).astype(bool)]
    mat = pd.read_parquet(base / "loan_monthly_stm_cer.parquet", columns=["LOAN_KEY", "MONTH_END", "maturity"])
    mat["MONTH_END"] = month_end(mat["MONTH_END"])
    u = u.merge(mat, on=["LOAN_KEY", "MONTH_END"], how="left")
    u["years_left"] = (pd.to_datetime(u["maturity"]) - u["MONTH_END"]).dt.days / 365.25

    add("Sample period (price months)", f"{mp['MONTH_END'].min():%B %Y} – {mp['MONTH_END'].max():%B %Y}")
    add("Identified loans, total", f"{mp['LOAN_KEY'].nunique():,}")
    per_m = mp.groupby("MONTH_END")["LOAN_KEY"].nunique()
    add("Identified loans with a price per month (median / min / max)",
        f"{per_m.median():,.0f} / {per_m.min():,} / {per_m.max():,}")
    uni_m = u.groupby("MONTH_END")["LOAN_KEY"].nunique()
    add("Loans in the investable universe, total", f"{u['LOAN_KEY'].nunique():,}")
    add("Loans in the investable universe per month (median / min / max)",
        f"{uni_m.median():,.0f} / {uni_m.min():,} / {uni_m.max():,}")
    add("Funds per loan, universe (median / mean)", f"{u['n_funds'].median():.0f} / {u['n_funds'].mean():.1f}")
    add("Price, universe (median)", f"{u['price'].median():.2f}")
    add("Margin, universe (median, %)", f"{u['margin'].median():.2f}")
    add("Spread-to-maturity, universe (median, %)", f"{u['stm'].median():.2f}")
    add("Remaining maturity, universe (median, years)", f"{u['years_left'].median():.1f}")
    add("Market value held by funds per loan, universe (median, USD million)", f"{u['value_total'].median() / 1e6:.1f}")
    add("Share of LoanX keys among universe loans", f"{(u.drop_duplicates('LOAN_KEY')['key_type'] == 'LX').mean():.1%}")

    # share of universe loan-months with a next-month return
    obs = obs.sort_values(["LOAN_KEY", "MONTH_END"])
    g = obs.groupby("LOAN_KEY")
    nxt = g["ret"].shift(-1).where(g["MONTH_END"].shift(-1) == obs["MONTH_END"] + pd.offsets.MonthEnd(1))
    has_next = nxt[obs["universe"].fillna(False).astype(bool)].notna()
    add("Universe loan-months with a return in the next month", f"{has_next.mean():.1%}")

    # exits and repayment assumption
    last = ch.groupby("LOAN_KEY")["MONTH_END"].max()
    end = ch["MONTH_END"].max()
    exits = last[last <= end - pd.DateOffset(months=6)]
    n_rep = ch.loc[ch["exit_row"].fillna(False).astype(bool), "LOAN_KEY"].nunique()
    add("Loans leaving the panel permanently", f"{len(exits):,}")
    add("  of which with assumed repayment at par", f"{n_rep:,} ({n_rep / max(len(exits), 1):.0%})")

    # ---------------------------------------------------------------- by year (Table 2.2)
    mp["year"] = mp["MONTH_END"].dt.year
    mp = mp.sort_values(["LOAN_KEY", "MONTH_END"])
    first_def = mp[mp["any_default"].fillna(False).astype(bool)].groupby("LOAN_KEY")["MONTH_END"].min()
    yr = []
    for y, gy in mp.groupby("year"):
        loans = gy["LOAN_KEY"].unique()
        new_def = ((first_def.dt.year == y) & first_def.index.isin(loans)).sum()
        uy = u[u["MONTH_END"].dt.year == y]
        yr.append({"year": y, "months": gy["MONTH_END"].nunique(),
                   "loans_with_price": len(loans),
                   "universe_loans_per_month": uy.groupby("MONTH_END")["LOAN_KEY"].nunique().median(),
                   "funds_per_loan_median": uy["n_funds"].median(),
                   "price_median": uy["price"].median(),
                   "stm_median_pct": uy["stm"].median(),
                   "new_defaults": int(new_def), "default_rate": new_def / len(loans)})
    by_year = pd.DataFrame(yr)
    if rk.exists():
        fy = h["per_month"].assign(year=pd.to_datetime(h["per_month"]["m"]).dt.year).groupby("year")["funds"].median()
        by_year["funds_per_month"] = by_year["year"].map(fy)

    # ---------------------------------------------------------------- output
    t1 = pd.DataFrame(rows)
    t1.to_csv(out / "table2_1.csv", index=False)
    by_year.to_csv(out / "table2_2_by_year.csv", index=False)
    md1 = "| Statistic | Value |\n|---|---|\n" + "\n".join(f"| {r.statistic} | {r.value} |" for r in t1.itertuples())
    (out / "table2_1.md").write_text(md1 + "\n", encoding="utf-8")
    fmt = by_year.copy()
    fmt["default_rate"] = fmt["default_rate"].map("{:.2%}".format)
    for c in ["price_median", "stm_median_pct"]:
        fmt[c] = fmt[c].map("{:.2f}".format)
    md2 = ("| " + " | ".join(fmt.columns) + " |\n|" + "---|" * len(fmt.columns) + "\n" +
           "\n".join("| " + " | ".join(str(v) for v in r) + " |" for r in fmt.itertuples(index=False)))
    (out / "table2_2_by_year.md").write_text(md2 + "\n", encoding="utf-8")
    pd.set_option("display.width", 200)
    print("\n=== Table 2.1 ===")
    print(t1.to_string(index=False))
    print("\n=== Table 2.2: by calendar year ===")
    print(fmt.to_string(index=False))
    print(f"\nSaved in: {out}")


if __name__ == "__main__":
    main()
