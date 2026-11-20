#!/usr/bin/env python3
"""
eu_diag.py

Diagnostics for the European index: which BDCs and positions cause low prices, extreme price changes and
distressed exits?

    1. Share of fair value marked below 90 by BDC (latest quarter-end), with the median price
    2. The 30 largest positions marked below 80 in the latest quarter-end (identifier, currency, principal,
       fair value in USD, exchange rate, price)
    3. The 30 largest absolute position returns (all, including exits and distressed positions)
    4. Exits that are not treated as repayments, by BDC
    5. Price paths of the positions behind the largest returns

Input   bdc_out/bdc_positions.parquet, eu_out/eu_position_returns.parquet
Output  eu_out/diag_low_prices.csv, eu_out/diag_extreme_returns.csv

Usage
    python eu_diag.py
"""

from pathlib import Path

import pandas as pd


def main() -> None:
    pd.set_option("display.width", 230)
    pd.set_option("display.max_colwidth", 70)
    p = pd.read_parquet("bdc_out/bdc_positions.parquet")
    p = p[p["dl_bdc"] & p["eu_ccy"] & p["month_end"].dt.month.isin([3, 6, 9, 12])
          & ~p["instrument"].isin(["bond", "equipment", "revolver", "delayed_draw"])]
    n = p.groupby("month_end").size()
    last = p[p["month_end"] == n[n >= 0.5 * n.max()].index.max()]

    # 1. low prices by BDC
    g = last.groupby("name")
    t = pd.DataFrame({"positions": g.size(), "fv_usd_mn": g["fv_usd"].sum() / 1e6,
                      "median_price": g["price"].median(),
                      "share_below_90": last[last["price"] < 90].groupby("name")["fv_usd"].sum() / g["fv_usd"].sum()})
    t["share_below_90"] = t["share_below_90"].fillna(0)
    print(f"=== 1. Prices by BDC, quarter-end {pd.Timestamp(last['month_end'].iloc[0]).date()} ===")
    print(t.sort_values("share_below_90", ascending=False).head(20).round(2).to_string())

    # 2. largest positions below 80
    low = last[last["price"] < 80].sort_values("fv_usd", ascending=False)
    cols = ["name", "ccy", "instrument", "par", "fv_usd", "fv_local", "price", "coupon", "ident"]
    low[cols].to_csv("eu_out/diag_low_prices.csv", index=False)
    print("\n=== 2. Largest positions marked below 80 ===")
    print(low[cols].head(30).assign(par=lambda x: (x["par"] / 1e6).round(2), fv_usd=lambda x: (x["fv_usd"] / 1e6).round(2),
                                    fv_local=lambda x: (x["fv_local"] / 1e6).round(2), ident=lambda x: x["ident"].str[:70])
          .round(2).to_string(index=False))

    # 3. extreme returns
    r = pd.read_parquet("eu_out/eu_position_returns.parquet")
    r["abs"] = r["total"].abs()
    r["price"] = r["p0"] * (1 + r["price_ret"])
    if "manager" not in r and "manager0" in r:
        r["manager"] = r["manager0"]
    ext = r.sort_values("abs", ascending=False).head(30)
    ext.to_csv("eu_out/diag_extreme_returns.csv", index=False)
    print("\n=== 3. Largest absolute position returns ===")
    print(ext[["month_end", "manager", "borrower", "p0", "price", "total", "exit", "distress"]]
          .assign(borrower=lambda x: x["borrower"].str[:60]).round({"p0": 2, "price": 2, "total": 3}).to_string(index=False))

    # 4. exits not treated as repayments
    ex = r[r["exit"]]
    ex = ex.assign(repaid=ex["price"].ge(99.99))
    e = ex.groupby("manager").agg(exits=("repaid", "size"), not_repaid=("repaid", lambda x: (~x).sum()),
                                  median_last_mark=("p0", "median"))
    print("\n=== 4. Exits by manager (not repaid = last mark below 95 or distressed) ===")
    print(e.sort_values("not_repaid", ascending=False).head(15).round(2).to_string())

    # 5. price paths behind the largest returns
    print("\n=== 5. Price paths of the five largest returns (BDC position panel) ===")
    for _, x in ext.head(5).iterrows():
        k, c = x["borrower"].rsplit("|", 1)
        path = p[(p["cik"].astype(str) == str(x["FUND_KEY"])) & (p["key"] == k) & (p["ccy"] == c)] \
            .sort_values("month_end")[["month_end", "par", "fv_usd", "price", "key_raw"]]
        print(f"\n{x['manager']}  {k[:80]} ({c})")
        print(path.assign(par=lambda y: (y["par"] / 1e6).round(2), fv_usd=lambda y: (y["fv_usd"] / 1e6).round(2),
                          key_raw=lambda y: y["key_raw"].str[:70]).round({"price": 2}).to_string(index=False))


if __name__ == "__main__":
    main()
