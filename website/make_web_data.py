#!/usr/bin/env python3
"""
make_web_data.py

Creates data/factors.json for the Analysis page of loanfactors.org from a database release.
The browser loads this one file and computes all charts and statistics itself.

Also writes data/leaderboard.json for "Factors to watch" on the homepage: all factors ranked by the
alpha of the preferred quintile against the factor-specific benchmark over the last 12 months
(equal-weighted, holding period 1 month, no lag, excess returns).

Content of factors.json: for every factor and specification (weighting, holding, lag, return type) the monthly
returns of the long-short portfolio (LS), the preferred quintile (PREF) and the factor-specific
benchmark (BM), plus the market index (MKT) per weighting, lag and return type.

Usage
    python make_web_data.py --release releases/loanfactors_v2026.11 --site loanfactors.org
"""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Factors to watch (homepage): main specification, last 12 months
LB_SPEC = {"weighting": "ew", "holding": 1, "lag": 0, "return_type": "excess"}
LB_MONTHS = 12


def alpha_stats(y: np.ndarray, x: np.ndarray) -> dict:
    """OLS of y on x (monthly decimals): annualized alpha in %, t-stat, information ratio."""
    n = len(y)
    mx, my = x.mean(), y.mean()
    sxx = ((x - mx) ** 2).sum()
    b = ((x - mx) * (y - my)).sum() / sxx if sxx > 0 else 0.0
    a = my - b * mx
    e = y - a - b * x
    s2 = (e ** 2).sum() / (n - 2)
    se = np.sqrt(s2 * (1 / n + mx ** 2 / sxx)) if sxx > 0 else np.nan
    return {"alpha": a * 12 * 100, "t": a / se if se > 0 else None,
            "ir": (a * 12) / np.sqrt(s2 * 12) if s2 > 0 else None, "beta": b}


def main() -> None:
    ap = argparse.ArgumentParser(description="Data file for the Analysis page")
    ap.add_argument("--release", required=True, help="release folder with factor_returns.csv")
    ap.add_argument("--site", default="loanfactors.org", help="website folder (data/ is written there)")
    args = ap.parse_args()

    rel = Path(args.release)
    fr = pd.read_csv(rel / "factor_returns.csv")
    defs = pd.read_csv(rel / "factor_definitions.csv").fillna("")
    meta = json.loads((rel / "metadata.json").read_text(encoding="utf-8"))

    dates = sorted(fr["date"].unique())
    pos = {d: i for i, d in enumerate(dates)}
    pref = dict(zip(defs["factor"], defs["preferred"]))

    def arr(g: pd.DataFrame) -> list:
        out = [None] * len(dates)
        for d, r in zip(g["date"], g["ret"]):
            out[pos[d]] = round(float(r), 6)
        return out

    series = {}
    for (f, w, h, l, rt), g in fr.groupby(["factor", "weighting", "holding", "lag", "return_type"]):
        if f == "market":
            series[f"market|{w}|{l}|{rt}"] = {"MKT": arr(g[g["portfolio"] == "MKT"])}
            continue
        p = pref.get(f, "")
        series[f"{f}|{w}|{h}|{l}|{rt}"] = {
            "LS": arr(g[g["portfolio"] == "LS"]),
            "PREF": arr(g[g["portfolio"] == p]),
            "BM": arr(g[g["portfolio"] == "BM"]),
        }

    factors = [{"code": r.factor, "name": r.name, "preferred": r.preferred}
               for r in defs.itertuples() if r.factor != "market"]
    out = {"version": meta.get("version", ""), "doi": meta.get("doi", ""),
           "dates": dates, "factors": factors, "s": series}
    # ---- leaderboard: alpha of the preferred quintile against the factor-specific benchmark
    end = dates[-1]
    start = dates[max(0, len(dates) - LB_MONTHS)]
    rows = []
    for fc in factors:
        g = fr[(fr["factor"] == fc["code"]) & (fr["weighting"] == LB_SPEC["weighting"])
               & (fr["holding"] == LB_SPEC["holding"]) & (fr["lag"] == LB_SPEC["lag"])
               & (fr["return_type"] == LB_SPEC["return_type"]) & (fr["date"] >= start)]
        p = g.pivot(index="date", columns="portfolio", values="ret")
        if fc["preferred"] not in p or "BM" not in p:
            continue
        d = p[[fc["preferred"], "BM"]].dropna()
        if len(d) < 10:
            continue
        st = alpha_stats(d[fc["preferred"]].to_numpy(), d["BM"].to_numpy())
        rows.append({"code": fc["code"], "name": fc["name"], "months": len(d),
                     "alpha": round(st["alpha"], 2), "t": round(st["t"], 2) if st["t"] is not None else None,
                     "ir": round(st["ir"], 2) if st["ir"] is not None else None})
    rows.sort(key=lambda r: r["alpha"], reverse=True)
    leaderboard = {"version": meta.get("version", ""), "start": start[:7], "end": end[:7],
                   "spec": LB_SPEC, "rows": rows}

    target = Path(args.site) / "data"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "factors.json"
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"{path}: {len(series)} series, {len(dates)} months, {path.stat().st_size / 1e6:.2f} MB")
    # ---- meta: release information shown on all pages (filled in by js/meta.js)
    ret_months = pd.to_datetime(pd.Series(dates))
    val = meta.get("validation", {})
    meta_out = {"version": meta.get("version", ""), "doi": meta.get("doi", ""),
                "start": f"{ret_months.min():%b %Y}", "end": f"{ret_months.max():%b %Y}",
                "start_long": f"{ret_months.min():%B %Y}", "end_long": f"{ret_months.max():%B %Y}",
                "index_corr": str(val.get("corr_with_morningstar_lsta_lli", "")),
                "index_period": str(val.get("period", ""))}
    if "zenodo." in meta_out["doi"]:
        rec = meta_out["doi"].split("zenodo.")[-1]
        meta_out["files_csv"] = f"https://zenodo.org/records/{rec}/files/factor_returns.csv?download=1"
    (target / "meta.json").write_text(json.dumps(meta_out, indent=1), encoding="utf-8")
    print(f"{target / 'meta.json'}: release v{meta_out['version']}, {meta_out['start']} to {meta_out['end']}")
    lb = target / "leaderboard.json"
    lb.write_text(json.dumps(leaderboard, indent=1), encoding="utf-8")
    print(f"{lb}: factors to watch, {leaderboard['start']} to {leaderboard['end']}")


if __name__ == "__main__":
    main()
