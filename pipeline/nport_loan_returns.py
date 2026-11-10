#!/usr/bin/env python3
"""
nport_loan_returns.py
=====================

Builds a monthly panel with price, implied margin, spread-to-maturity (STM) and
excess returns from loan_price_panel(_v2).parquet (output of nport_loans.py / nport_rekey.py).

Definitions (in percent p.a. or decimal returns)
------------------------------------------------
  coupon c_t       = annualized interest rate reported in N-PORT (median across funds)
  base rate b      = reference rate, e.g. 3M USD LIBOR until mid-2023, then 3M Term SOFR
  Margin_t         = c_t - b_{t-lag}          (lag = 1 month as proxy for the last reset;
                                                with a binding floor the margin includes the floor benefit)
  T_t              = remaining maturity in years, capped at --life (default 3 years), at least 0.25
  STM_t            = Margin_t + (100 - P_t) / T_t
  TR_t             = (P_t - P_{t-k} + c_{t-k}*k/12) / P_{t-k}     k = 1 (month) or 3 (quarter),
                                                                 only for directly consecutive periods
  CER_t            = TR_t - sum(b_{t-1} ... b_{t-k}) / 12 / 100   (excess return over the base rate)
  SD_t             = spread duration: modified duration of the assumed cash flows
                     (quarterly coupon b_t + Margin_t constant, 100 at T_t), discounted with
                     y = b_t + STM_t; the interest rate risk of a floater is ~0, while its
                     spread risk roughly equals the (assumed) maturity
  DTS_t            = SD_t * STM_t (duration times spread, in % or bp)

Base rate
---------
Either pass a CSV with monthly values (--base-csv), e.g. from Bloomberg:
US0003M Index (3M LIBOR) until 06/2023, then TSFR3M Index (3M Term SOFR).
Format: two columns, date and rate in percent (e.g. 2023-01-31, 4.81).
Daily values are also accepted and are averaged by month.
Without --base-csv the 3M T-bill rate (FRED TB3MS) is used; with --base-source sofr the freely
available 90-day average SOFR (FRED) is used, plus 26.161 bp until June 2023 (ISDA spread
adjustment for 3M LIBOR). This is the variant used for the public database.

Universe
--------
Default (--filter-level loan): a loan belongs to the universe if it is held by --min-funds or
more funds in at least one month (syndicated loan); thinly reported months in which only one
fund reports are then kept. With --filter-level month the filter is applied per loan-month.

Output: monthly panel and (unless --no-quarterly) a quarterly panel based only on March,
June, September and December, with quarterly returns.

Example
-------
    python nport_loan_returns.py --panel nport_out/loan_price_panel_v2.parquet \\
        --base-source sofr --min-funds 2 --csv
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path

import numpy as np
import pandas as pd
import requests

PANEL_COLS = ["LOAN_KEY", "MONTH_END", "price_median", "coupon_median", "n_funds",
              "maturity", "issuer_name", "issue_title", "loanx_id", "key_type", "any_default", "any_pik"]


def month_end(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s).dt.normalize() + pd.offsets.MonthEnd(0)


def parse_dates(s: pd.Series) -> pd.Series:
    """ISO dates (2025-05-01) first, then German format (31.05.2025)."""
    s = s.astype(str).str.strip()
    d = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%m/%d/%Y"):
        rest = d.isna()
        if not rest.any():
            break
        d.loc[rest] = pd.to_datetime(s[rest], format=fmt, errors="coerce")
    return d


LIBOR_SOFR_SPREAD = 0.26161   # ISDA spread adjustment 3M USD LIBOR -> SOFR, in percentage points
LIBOR_END = "2023-06-30"      # until then leveraged loans mostly referenced LIBOR


def load_sofr_libor() -> pd.Series:
    """Freely available base rate: 90-day average SOFR (New York Fed, via FRED),
    plus 26.161 bp until June 2023 as approximation of 3M USD LIBOR. Monthly average in %."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=SOFR90DAYAVG"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df.iloc[:, :2]
    df.columns = ["date", "rate"]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["rate"] = pd.to_numeric(df["rate"], errors="coerce")
    df = df.dropna()
    df["MONTH_END"] = month_end(df["date"])
    base = df.groupby("MONTH_END")["rate"].mean()
    base[base.index <= pd.Timestamp(LIBOR_END)] += LIBOR_SOFR_SPREAD
    print(f"Base rate: 90-day average SOFR (FRED SOFR90DAYAVG), + {LIBOR_SOFR_SPREAD:.5f} pp until {LIBOR_END}; "
          f"{len(base)} months from {base.index.min():%Y-%m} to {base.index.max():%Y-%m}")
    return base


def load_base(path: str | None, source: str = "tbill") -> pd.Series:
    if not path and source == "sofr":
        return load_sofr_libor()
    if path:
        if not Path(path).exists():
            raise SystemExit(f"Base rate file not found: {Path(path).resolve()}")
        # detect separator automatically (also German Excel: semicolon, decimal comma)
        df = pd.read_csv(path, sep=None, engine="python", dtype=str)
    else:
        print("WARNING: no --base-csv given, using the 3M T-bill rate (FRED TB3MS) as substitute.")
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS"
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
    df = df.iloc[:, :2]
    df.columns = ["date", "rate"]
    df["date"] = parse_dates(df["date"])
    df["rate"] = pd.to_numeric(df["rate"].astype(str).str.replace(",", ".", regex=False),
                               errors="coerce")
    df = df.dropna()
    df["MONTH_END"] = month_end(df["date"])
    base = df.groupby("MONTH_END")["rate"].mean()
    print(f"Base rate: {len(base)} months from {base.index.min():%Y-%m} to {base.index.max():%Y-%m}")
    if base.max() < 0.3:  # given as decimal (0.05 instead of 5)
        base = base * 100
    return base


def spread_duration(T: pd.Series, coupon: pd.Series, y: pd.Series, freq: int = 4) -> pd.Series:
    """Modified spread duration (years) of a floater with constant coupon over T years.

    T: maturity in years, coupon and y in % p.a. Vectorized over all rows.
    """
    T = T.to_numpy(float)
    c = coupon.to_numpy(float) / 100 / freq * 100      # coupon per period on 100 notional
    yy = y.to_numpy(float) / 100
    n = np.ceil(T * freq - 1e-9)
    n_max = int(np.nanmax(n)) if np.isfinite(n).any() else 0
    pv = np.zeros_like(T)
    tpv = np.zeros_like(T)
    for k in range(1, n_max + 1):
        t = T - (n - k) / freq                          # payment dates, possibly with a short first period
        active = k <= n
        cf = c + np.where(k == n, 100.0, 0.0)
        df = (1 + yy / freq) ** (-freq * t)
        v = np.where(active, cf * df, 0.0)
        pv += v
        tpv += np.where(active, t * v, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = tpv / pv / (1 + yy / freq)
    return pd.Series(sd, index=coupon.index)


def add_metrics(df: pd.DataFrame, base: pd.Series, args) -> pd.DataFrame:
    """Margin, STM, spread duration, DTS (independent of the return frequency)."""
    df = df.copy()
    df["base"] = df["MONTH_END"].map(base)
    df["base_lag"] = (df["MONTH_END"] - pd.offsets.MonthEnd(args.reset_lag)).map(base)
    df["margin"] = df["coupon"] - df["base_lag"]
    df["margin_plausible"] = df["margin"].between(0, 20)
    years_left = (df["maturity"] - df["MONTH_END"]).dt.days / 365.25
    T = years_left.clip(lower=0.25)
    if args.life > 0:
        T = T.clip(upper=args.life)
    df["T_years"] = T
    df["stm"] = df["margin"] + (100 - df["price"]) / T
    df.loc[~df["margin_plausible"], "stm"] = np.nan
    df["stm_bp"] = df["stm"] * 100

    ok = df["stm"].notna() & df["base"].notna() & df["T_years"].notna()
    df["spread_duration"] = np.nan
    if ok.any():
        sub = df.loc[ok]
        df.loc[ok, "spread_duration"] = spread_duration(
            sub["T_years"], sub["base"] + sub["margin"], sub["base"] + sub["stm"]).to_numpy()
    df["dts"] = df["spread_duration"] * df["stm"]
    return df


def add_returns(df: pd.DataFrame, base: pd.Series, step: int) -> pd.DataFrame:
    """Total return and excess return over step months (1 = month, 3 = quarter)."""
    df = df.sort_values(["LOAN_KEY", "MONTH_END"]).copy()
    g = df.groupby("LOAN_KEY")
    prev_month = g["MONTH_END"].shift(1)
    prev_price = g["price"].shift(1)
    prev_coupon = g["coupon"].shift(1)
    consecutive = prev_month + pd.offsets.MonthEnd(step) == df["MONTH_END"]
    df["is_consecutive"] = consecutive

    income = prev_coupon.fillna(df["coupon"]) * step / 12
    df["total_return"] = np.where(consecutive, (df["price"] - prev_price + income) / prev_price, np.nan)
    rf = sum((df["MONTH_END"] - pd.offsets.MonthEnd(k)).map(base) for k in range(1, step + 1))
    df["rf"] = rf / 12 / 100
    df["cer"] = df["total_return"] - df["rf"]
    df["return_outlier"] = df["total_return"].abs() > (0.5 if step == 1 else 0.75)
    return df


OUT_COLS = ["LOAN_KEY", "MONTH_END", "issuer_name", "issue_title", "loanx_id", "key_type",
            "n_funds", "price", "coupon", "base", "base_lag", "margin", "T_years",
            "stm", "stm_bp", "spread_duration", "dts", "total_return", "rf", "cer",
            "is_consecutive", "margin_plausible", "return_outlier",
            "any_default", "any_pik", "maturity"]


def summarize(out: pd.DataFrame, label: str, n_last: int) -> None:
    print(f"\n=== Summary {label} ===")
    print(f"Observations:                {len(out):,}")
    print(f"Unique loans:                {out['LOAN_KEY'].nunique():,}")
    print(f"Share with prior price:      {out['is_consecutive'].mean():.1%}")
    print(f"Share with plausible margin: {out['margin_plausible'].mean():.1%}")
    clean = out[~out["return_outlier"]]
    summary = out.groupby("MONTH_END").agg(
        loans=("LOAN_KEY", "nunique"),
        with_return=("cer", lambda s: s.notna().sum()),
        price=("price", "median"),
        margin=("margin", "median"),
        stm_bp=("stm_bp", "median"),
        sd=("spread_duration", "median"),
    )
    summary["cer_ew"] = clean.groupby("MONTH_END")["cer"].mean()
    summary["cer_median"] = clean.groupby("MONTH_END")["cer"].median()
    print(f"\nPer period (median, last {n_last}; excess return without outliers):")
    print(summary.tail(n_last).round(4).to_string())


def main() -> None:
    ap = argparse.ArgumentParser(description="Panel with price, STM, spread duration and excess returns")
    ap.add_argument("--panel", default="nport_out/loan_price_panel.parquet")
    ap.add_argument("--base-csv", default=None, help="base rate (date, rate in %%)")
    ap.add_argument("--base-source", choices=["tbill", "sofr"], default="tbill",
                    help="without --base-csv: tbill = 3M T-bill (FRED TB3MS), "
                         "sofr = 90-day average SOFR (FRED), + ISDA spread 26.161 bp until 06/2023")
    ap.add_argument("--min-funds", type=int, default=2, help="minimum number of holding funds")
    ap.add_argument("--filter-level", choices=["loan", "month"], default="loan",
                    help="fund filter per loan (at least once) or per loan-month")
    ap.add_argument("--life", type=float, default=3.0,
                    help="assumed maturity in years for STM (0 = actual remaining maturity)")
    ap.add_argument("--reset-lag", type=int, default=1, help="months of base rate lag for the margin")
    ap.add_argument("--out", default="nport_out/loan_monthly_stm_cer.parquet")
    ap.add_argument("--out-quarterly", default="nport_out/loan_quarterly_stm_cer.parquet")
    ap.add_argument("--no-quarterly", action="store_true", help="do not create the quarterly panel")
    ap.add_argument("--csv", action="store_true", help="also save as CSV")
    args = ap.parse_args()

    df = pd.read_parquet(args.panel, columns=PANEL_COLS)
    n0 = len(df)

    # --- Universe: no numbered small loans, fund filter per loan or per month
    df = df[~df["issuer_name"].fillna("").str.match(r"^\d{6,}")]
    if args.filter_level == "loan":
        mx = df.groupby("LOAN_KEY")["n_funds"].max()
        df = df[df["LOAN_KEY"].isin(mx.index[mx >= args.min_funds])]
    else:
        df = df[df["n_funds"] >= args.min_funds]
    print(f"Observations: {n0:,} -> {len(df):,} after filter "
          f"(n_funds >= {args.min_funds} per {'loan (in at least one month)' if args.filter_level == 'loan' else 'loan-month'})")

    df["MONTH_END"] = month_end(df["MONTH_END"])
    df["maturity"] = pd.to_datetime(df["maturity"], errors="coerce")
    df = df.rename(columns={"price_median": "price", "coupon_median": "coupon"})
    if df["coupon"].median() < 0.5:  # decimal instead of percent
        df["coupon"] = df["coupon"] * 100

    base = load_base(args.base_csv, args.base_source)
    df = add_metrics(df, base, args)
    missing = df["base_lag"].isna().mean()
    if missing > 0:
        print(f"Note: the base rate is missing for {missing:.1%} of observations.")

    # --- Monthly panel
    monthly = add_returns(df, base, step=1)[OUT_COLS]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    monthly.to_parquet(args.out, index=False)
    if args.csv:
        monthly.to_csv(Path(args.out).with_suffix(".csv"), index=False)
    summarize(monthly, "monthly", 12)

    # --- Quarterly panel (quarter-end months only)
    if not args.no_quarterly:
        q = df[df["MONTH_END"].dt.month.isin([3, 6, 9, 12])]
        quarterly = add_returns(q, base, step=3)[OUT_COLS]
        quarterly.to_parquet(args.out_quarterly, index=False)
        if args.csv:
            quarterly.to_csv(Path(args.out_quarterly).with_suffix(".csv"), index=False)
        summarize(quarterly, "quarterly", 8)


if __name__ == "__main__":
    main()
