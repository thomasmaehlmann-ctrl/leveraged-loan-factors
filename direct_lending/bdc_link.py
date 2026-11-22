#!/usr/bin/env python3
"""
bdc_link.py

Builds the BDC position panel from the cleaned holdings (bdc_panel.py) with the current key normalization, and
links positions whose identifiers change from one quarter-end to the next.

Steps
    1. Position keys are recomputed from the identifiers (bdc_panel.norm_key), so that improvements of the
       normalization do not require reading the SEC data sets again.
    2. Positions are aggregated to BDC x key x currency x quarter-end.
    3. Linking: quarter by quarter, every position of a BDC that has no exact match in the previous quarter is
       compared with the previous quarter's positions of the same BDC and currency that were not continued. The
       most similar pair is linked if the key similarity is at least --min-sim and the principal changed by less
       than a factor of two; the new key is then mapped to the old one in all later quarters.

Input   bdc_out/bdc_holdings.parquet
Output  bdc_out/bdc_positions.parquet (column key = linked key, key_raw = key in that quarter)

Usage
    python bdc_link.py
    python bdc_link.py --min-sim 0.9
    python bdc_link.py --all-currencies      (also US dollar positions; takes much longer)
"""

import argparse
import difflib
import re
from pathlib import Path

import numpy as np
import pandas as pd

import bdc_panel as bpanel

STOP = {"INC", "LLC", "LP", "LTD", "LIMITED", "CORP", "CORPORATION", "CO", "HOLDINGS", "HOLDING", "THE", "AND", "&",
        "FIRST", "SECOND", "LIEN", "SENIOR", "SECURED", "LOAN", "LOANS", "TERM", "DEBT", "INDUSTRY", "INVESTMENT", "TYPE",
        "ASSET", "DELAYED", "DRAW", "REVOLVER", "REVOLVING", "UNITRANCHE", "FACILITY", "TRANCHE", "BIDCO", "TOPCO",
        "MIDCO", "HOLDCO", "GROUP", "SARL", "BV", "GMBH", "AB", "OY", "SPA", "SAS", "PLC", "SERVICES"}


def similarity(a: str, b: str) -> float:
    r = difflib.SequenceMatcher(None, a, b).ratio()
    ta, tb = set(a.split()) - STOP, set(b.split()) - STOP
    j = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    return max(r, j)


def drop_subtotals(h: pd.DataFrame, tol: float = 0.02) -> pd.DataFrame:
    """Subtotals that report a principal: the identifier is the beginning of other identifiers of the same
    filing, and its fair value equals the sum of their fair values (within tol)."""
    drop = []
    for adsh, g in h.groupby("adsh"):
        ids = g[["ident", "fv"]].sort_values("ident").to_numpy()
        n = len(ids)
        parent = [k + 1 < n and str(ids[k + 1][0]).startswith(str(ids[k][0])) and ids[k + 1][0] != ids[k][0]
                  for k in range(n)]
        for k, (i, fv) in enumerate(ids):
            tot, j = 0.0, k + 1
            while j < n and str(ids[j][0]).startswith(str(i)):
                if ids[j][0] != i and not parent[j]:       # sum of the lowest level only
                    tot += ids[j][1]
                j += 1
            if tot > 0 and abs(fv - tot) <= tol * abs(tot):
                drop.append((adsh, i))
    if not drop:
        return h
    m = pd.MultiIndex.from_frame(h[["adsh", "ident"]]).isin(drop)
    print(f"Subtotals with a principal removed: {m.sum():,}")
    return h[~m]


def fix_currency(h: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """Correct mislabeled loan currencies. Principal and cost are reported in the same unit, cost in USD at
    historical rates, so cost_usd / principal is close to the USD value of one unit of the true currency.
    If the tagged currency is clearly inconsistent with this ratio (relative error > 15%) and another currency
    fits well (< 8%), the holding is assigned to that currency; fair value in local currency and price are
    recomputed."""
    h = h.reset_index(drop=True)
    ratio = h["cost"] / h["principal"]
    cands = ["USD"] + sorted(set(fx["ccy"]))
    fx = fx.sort_values("date")
    rates = {}
    for c in cands:
        if c == "USD":
            rates[c] = pd.Series(1.0, index=h.index)
            continue
        f = fx[fx["ccy"] == c][["date", "usd_per_ccy"]].rename(columns={"date": "ddate", "usd_per_ccy": c})
        m = pd.merge_asof(h[["ddate"]].reset_index().sort_values("ddate"), f, on="ddate", direction="backward")
        rates[c] = m.set_index("index")[c].reindex(h.index)
    err = pd.DataFrame({c: (ratio / (0.98 * rates[c]) - 1).abs() for c in cands}).fillna(np.inf)
    tagged = h["ccy"].where(h["ccy"].isin(cands), "USD")
    err_tag = pd.Series([err.at[i, c] if c in err.columns else np.nan for i, c in zip(h.index, tagged)], index=h.index)
    best = err.idxmin(axis=1)
    best_err = err.min(axis=1).replace(np.inf, np.nan)
    err_tag = err_tag.replace(np.inf, np.nan)
    fix = ratio.notna() & (err_tag > 0.15) & (best_err < 0.08) & (best != tagged)
    # a USD tag is only replaced if cost clearly exceeds principal (a loan in GBP, EUR or CHF tagged as USD);
    # a low ratio of cost to principal is common for USD loans (discounts, partially drawn tranches)
    fix &= ~tagged.eq("USD") | ((ratio > 1.15) & best.isin(["GBP", "EUR", "CHF"]))
    if fix.any():
        print(f"Currency corrected for {fix.sum():,} holdings; most frequent changes:")
        print((tagged[fix] + " -> " + best[fix]).value_counts().head(8).to_string())
        h.loc[fix, "ccy"] = best[fix]
        h.loc[fix, "usd_per_ccy"] = [rates[c].at[i] for i, c in zip(h.index[fix], best[fix])]
        h.loc[fix, "fv_local"] = h.loc[fix, "fv"] / h.loc[fix, "usd_per_ccy"]
        h.loc[fix, "price"] = h.loc[fix, "fv_local"] / h.loc[fix, "principal"] * 100
        h.loc[fix, "eu_ccy"] = h.loc[fix, "ccy"].isin(bpanel.EU_CCY)
    h["ccy_fixed"] = fix
    return h


def tokens(key: str) -> list[str]:
    return [t.replace(".", "") for t in key.split() if t.replace(".", "")]


def distinctive(pos: pd.DataFrame) -> pd.Series:
    """Words of a key that occur in few keys of the same BDC and quarter (names rather than industries,
    headings or instrument descriptions)."""
    out = pd.Series(index=pos.index, dtype=object)
    grp = pos["ccy"].isin(bpanel.EU_CCY) if "ccy" in pos else pd.Series(True, index=pos.index)
    for _, g in pos.groupby([pos["cik"], pos["month_end"], grp]):
        toks = g["key"].map(lambda k: set(tokens(k)) - STOP)
        df = pd.Series([t for s in toks for t in s]).value_counts()
        lim = max(2, min(0.05 * len(g), 10))
        out.loc[g.index] = toks.map(lambda s: frozenset(t for t in s if df.get(t, 0) <= lim))
    return out


def aggregate(h: pd.DataFrame) -> pd.DataFrame:
    v = h[~h["unfunded"] & h["price"].between(1, 150)].copy()
    v["nonaccrual"] = v["ident"].str.contains(r"Non[- ]?Accru", case=False)
    # coupon and spread stated in the identifier (many BDCs do not tag InvestmentInterestRate)
    txt_rate = v["ident"].str.extract(r"(?:Interest Rate|Current Coupon|Coupon|Cash Rate)\D{0,12}?(\d{1,2}\.\d{1,3})\s*%",
                                      flags=re.I, expand=False).astype(float)
    sp = v["ident"].str.extract(r"(?:SOFR|SONIA|EURIBOR|EUIBOR|SARON|STIBOR|NIBOR|CIBOR|\b[SENLC]{1,3})\s*\+\s*"
                                r"(\d{1,4}(?:\.\d{1,3})?)\s*(%|bps)?", flags=re.I)
    spread = sp[0].astype(float)
    spread = np.where(sp[1].str.lower().eq("bps") | (spread > 25), spread / 100, spread)
    v["rate_src"] = np.where(v["rate"].notna(), "tag", np.where(txt_rate.notna(), "text", np.where(
        pd.notna(spread), "spread", "none")))
    v["rate"] = v["rate"].where(v["rate"].notna(), txt_rate / 100)
    v["spread"] = spread
    v["spread_w"] = v["spread"] * v["principal"]
    v["spread_par"] = np.where(v["spread"].notna(), v["principal"], 0.0)
    v["rate_w"] = v["rate"] * v["principal"]
    v["rate_par"] = np.where(v["rate"].notna(), v["principal"], 0.0)
    v["pik"] = v["ident"].str.contains(r"\bPIK\b|Payment[- ]in[- ]Kind", case=False)
    pos = v.groupby(["cik", "name", "manager", "dl_bdc", "month_end", "key", "ccy"], as_index=False).agg(
        par=("principal", "sum"), fv_usd=("fv", "sum"), fv_local=("fv_local", "sum"), cost_usd=("cost", "sum"),
        rate_w=("rate_w", "sum"), rate_par=("rate_par", "sum"), instrument=("instrument", lambda x: x.mode().iat[0]),
        eu_ccy=("eu_ccy", "max"), eu_borrower=("eu_borrower", "max"), n_tranches=("ident", "size"),
        ident=("ident", "first"), nonaccrual=("nonaccrual", "max"), pik=("pik", "max"),
        spread_w=("spread_w", "sum"), spread_par=("spread_par", "sum"), rate_src=("rate_src", "first"))
    pos["price"] = pos["fv_local"] / pos["par"] * 100
    pos["coupon"] = np.where(pos["rate_par"] > 0, pos["rate_w"] / pos["rate_par"], np.nan)
    pos["coupon"] = np.where(pos["coupon"] < 1, pos["coupon"] * 100, pos["coupon"])
    pos["spread"] = np.where(pos["spread_par"] > 0, pos["spread_w"] / pos["spread_par"], np.nan)
    return pos.drop(columns=["rate_w", "rate_par", "spread_w", "spread_par"])


def link(pos: pd.DataFrame, min_sim: float) -> tuple[pd.DataFrame, int]:
    pos = pos.copy()
    pos["key_raw"] = pos["key"]
    pos["dist"] = distinctive(pos)
    mapping: dict[tuple, str] = {}                 # (cik, ccy, raw key) -> linked key
    n_links = 0
    qs = sorted(pos["month_end"].unique())
    last_by_cik: dict = {}                          # latest earlier observation of each BDC
    for q in qs:
        idx = pos.index[pos["month_end"] == q]
        cur = pos.loc[idx]
        keys = [mapping.get((c, y, k), k) for c, y, k in zip(cur["cik"], cur["ccy"], cur["key_raw"])]
        pos.loc[idx, "key"] = keys
        if last_by_cik:
            cur = pos.loc[idx]
            for (cik, ccy), g in cur.groupby(["cik", "ccy"]):
                lp = last_by_cik.get(cik)
                if lp is None or (pd.Timestamp(q) - pd.Timestamp(lp[0])).days > 200:
                    continue
                prev = lp[1]
                p = prev[prev["ccy"] == ccy]
                if p.empty:
                    continue
                gone = p[~p["key"].isin(set(g["key"]))]
                new = g[~g["key"].isin(set(p["key"]))]
                if gone.empty or new.empty:
                    continue
                cand = []
                # candidate pairs: share at least one distinctive word (inverted index); small groups: all pairs
                inv: dict[str, list[int]] = {}
                gone_rows = list(gone.itertuples(index=False))
                for j, ro in enumerate(gone_rows):
                    for t in (ro.dist or ()):
                        inv.setdefault(t, []).append(j)
                for i, rn in new.iterrows():
                    if len(gone_rows) <= 50:
                        js = range(len(gone_rows))
                    else:
                        js = sorted({j for t in (rn["dist"] or ()) for j in inv.get(t, ())})
                    for j in js:
                        ro = gone_rows[j]._asdict()
                        ratio = rn["par"] / ro["par"] if ro["par"] else np.inf
                        s = similarity(rn["key"], ro["key"])
                        dn, do = rn["dist"], ro["dist"]
                        t = len(dn & do) / min(len(dn), len(do)) if (dn and do) else 0.0
                        ddtl = "delayed_draw" in (rn["instrument"], ro["instrument"])
                        lo, hi = (0.2, 5.0) if (t == 1.0 or ddtl) else (0.5, 2.0)
                        if not (lo <= ratio <= hi):
                            continue
                        if t >= 0.75:              # overlap of distinctive words (names)
                            s = max(s, 0.85 + 0.1 * t)
                        if s >= min_sim:
                            cand.append((s, i, ro["key"], rn["key_raw"]))
                used_new, used_old = set(), set()
                for s, i, old_key, raw in sorted(cand, reverse=True):
                    if i in used_new or old_key in used_old:
                        continue
                    used_new.add(i)
                    used_old.add(old_key)
                    pos.loc[i, "key"] = old_key
                    mapping[(cik, ccy, raw)] = old_key
                    n_links += 1
        cur = pos.loc[idx, ["cik", "ccy", "key", "par", "dist", "instrument"]]
        for cik, g in cur.groupby("cik"):
            last_by_cik[cik] = (q, g)
    # positions that now share a key within the same quarter are combined
    agg = {"par": "sum", "fv_usd": "sum", "fv_local": "sum", "cost_usd": "sum", "n_tranches": "sum",
           "instrument": "first", "eu_ccy": "max", "eu_borrower": "max", "ident": "first", "key_raw": "first",
           "coupon": "mean", "nonaccrual": "max", "pik": "max", "spread": "mean", "rate_src": "first"}
    pos = pos.groupby(["cik", "name", "manager", "dl_bdc", "month_end", "key", "ccy"], as_index=False).agg(agg)
    pos["price"] = pos["fv_local"] / pos["par"] * 100
    return pos, n_links


def tracking(pos: pd.DataFrame, region: str = "europe") -> pd.DataFrame:
    sel = pos["eu_ccy"] if region == "europe" else pos["ccy"].eq("USD")
    q = pos[pos["dl_bdc"] & sel & pos["month_end"].dt.month.isin([3, 6, 9, 12])]
    qs = sorted(q["month_end"].unique())
    rows = []
    for a, b in zip(qs[:-1], qs[1:]):
        A, B = q[q["month_end"] == a], q[q["month_end"] == b]
        A = A[A["cik"].isin(B["cik"])]
        nb = set(zip(B["cik"], B["key"], B["ccy"]))
        f = [(c, k, y) in nb for c, k, y in zip(A["cik"], A["key"], A["ccy"])]
        rows.append({"quarter": pd.Timestamp(a).date(), "positions": len(A), "found_next": int(sum(f)),
                     "share": np.mean(f) if f else np.nan})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-key and link BDC positions")
    ap.add_argument("--dir", default="bdc_out")
    ap.add_argument("--min-sim", type=float, default=0.85)
    ap.add_argument("--all-currencies", action="store_true",
                    help="link positions in all currencies (slow); default: European currencies only")
    args = ap.parse_args()
    d = Path(args.dir)
    pd.set_option("display.width", 200)

    h = pd.read_parquet(d / "bdc_holdings.parquet")
    h = drop_subtotals(h)
    fxf = d / "fx_quarter_end.csv"
    if fxf.exists():
        h = fix_currency(h, pd.read_csv(fxf, parse_dates=["date"]))
    h["key"] = h["ident"].map(bpanel.norm_key)
    pos = aggregate(h)
    before = tracking(pos)
    sel = pd.Series(True, index=pos.index) if args.all_currencies else pos["eu_ccy"]
    linked, n = link(pos[sel & pos["dl_bdc"]], args.min_sim)
    rest = pos[~(sel & pos["dl_bdc"])].assign(key_raw=lambda x: x["key"])
    out = pd.concat([linked, rest], ignore_index=True)
    out.to_parquet(d / "bdc_positions.parquet", index=False)
    after = tracking(out)
    t = before.merge(after, on="quarter", suffixes=("_exact", "_linked"))
    print(f"Links between renamed positions: {n:,}")
    print("\n=== Tracking of European-currency positions (share found again next quarter) ===")
    print(t[["quarter", "positions_exact", "share_exact", "positions_linked", "share_linked"]].round(3).to_string(index=False))
    if args.all_currencies:
        tu = tracking(pos, "us").merge(tracking(out, "us"), on="quarter", suffixes=("_exact", "_linked"))
        print("\n=== Tracking of US dollar positions ===")
        print(tu[["quarter", "positions_exact", "share_exact", "share_linked"]].round(3).to_string(index=False))
    print(f"\nSaved: {d}/bdc_positions.parquet")


if __name__ == "__main__":
    main()
