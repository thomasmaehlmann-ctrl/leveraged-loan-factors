#!/usr/bin/env python3
"""
make_dl_web.py

Data file and charts for the direct lending section of loanfactors.org, from a release of the
Registered Fund Direct Lending Index (dl_export.py).

Outputs (in the site folder)
    data/dl.json              key figures, quarterly returns, credit barometer and release information
    img/dl_index.svg          cumulative value of the three indices (and the leveraged loan market, optional)
    img/dl_barometer.svg      non-accruals and loans marked below 90 (all managers and without Cliffwater)

OpenDL Europe (--eu-release): data/dl_eu.json, data/dl_eu_series.json, img/dl_eu_index.svg,
img/dl_eu_barometer.svg, and with both releases img/dl_overview.svg (main indices of Europe and the US).

Usage
    python make_dl_web.py --release releases/dlindex_v2026.12 --eu-release releases/opendl_europe_v2026.12
                          --site loanfactors.org [--ll-release releases/loanfactors_v2026.12]
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

INK, GOLD, SLATE, RULE, BLUE, GREY = "#1A2E4A", "#B8972A", "#586273", "#D9DFE7", "#3F7FA6", "#9AA4B2"
LABELS = {"ew_managers": "Main index (equal-weighted managers)", "vw_all": "Value-weighted",
          "vw_ex_largest": "Value-weighted ex Cliffwater"}


def qlab(d: pd.Timestamp) -> str:
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(RULE)
    ax.tick_params(colors=SLATE, labelsize=10)
    ax.grid(axis="y", color=RULE, linewidth=0.8)
    ax.set_axisbelow(True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Web data and charts for the direct lending index")
    ap.add_argument("--release", default=None, help="release of OpenDL US (dl_export.py)")
    ap.add_argument("--eu-release", default=None, help="release of OpenDL Europe (eu_export.py)")
    ap.add_argument("--us-bdc-release", default=None, help="release of OpenDL US BDC (us_bdc_export.py)")
    ap.add_argument("--site", default="loanfactors.org")
    ap.add_argument("--ll-release", default=None)
    args = ap.parse_args()
    site = Path(args.site)
    (site / "data").mkdir(parents=True, exist_ok=True)
    (site / "img").mkdir(parents=True, exist_ok=True)
    if args.eu_release:
        eu_web(Path(args.eu_release), site, Path(args.release) if args.release else None)
    if args.us_bdc_release:
        usbdc_web(Path(args.us_bdc_release), site)
        if args.eu_release and args.release:
            overview_chart(site, Path(args.eu_release), Path(args.us_bdc_release), Path(args.release))
    if not args.release:
        return
    rel = Path(args.release)

    meta = json.loads((rel / "metadata.json").read_text(encoding="utf-8"))
    r = pd.read_csv(rel / "dl_index_returns.csv", parse_dates=["date"])
    bar = pd.read_csv(rel / "dl_credit_barometer.csv", parse_dates=["date"])
    uni = pd.read_csv(rel / "dl_universe_stats.csv", parse_dates=["date"])

    # ---- key figures of the main index
    m = r[r["index"] == "ew_managers"].set_index("date").sort_index()
    last_q = m.index.max()
    t4 = (1 + m["total"].tail(4)).prod() - 1
    ann = (1 + m["total"]).prod() ** (4 / len(m)) - 1
    vw = r[r["index"] == "vw_all"].set_index("date").sort_index()
    lb = bar.set_index("date").sort_index().iloc[-1]
    lu = uni.set_index("date").sort_index().iloc[-1]
    doi = meta.get("doi", "")
    data = {
        "version": meta.get("version", ""), "doi": doi,
        "files_url": (f"https://zenodo.org/records/{doi.split('zenodo.')[-1]}" if "zenodo." in doi else ""),
        "start": qlab(pd.Timestamp(meta["first_return_quarter"])),
        "end": qlab(pd.Timestamp(meta["last_return_quarter"])),
        "last_quarter": f"Q{(last_q.month - 1) // 3 + 1} {last_q.year}",
        "key": {"last_quarter_pct": round(m["total"].iloc[-1] * 100, 2), "t4q_pct": round(t4 * 100, 2),
                "annualized_pct": round(ann * 100, 2), "vol_pct": round(m["total"].std() * 200, 2),
                "managers": int(m["managers"].iloc[-1]), "positions": int(lu["positions"]),
                "funds": int(lu["funds"]), "market_value_bn": round(float(lu["market_value_usd_bn"]), 1),
                "largest_share_pct": round(float(lu["largest_manager_share"]) * 100),
                "non_accrual_ex_pct": round(float(lb["non_accrual_pct_ex_largest"]), 2),
                "below90_ex_pct": round(float(lb["marked_below_90_pct_ex_largest"]), 2),
                "recovery_pct": meta["specification"]["recovery_estimate_pct_of_par"]},
        "validation": meta.get("validation", {}),
        "quarters": [
            {"q": f"Q{(d.month - 1) // 3 + 1} {d.year}",
             "ew": round(m.loc[d, "total"] * 100, 2), "ew_income": round(m.loc[d, "income"] * 100, 2),
             "ew_price": round(m.loc[d, "price"] * 100, 2),
             "vw": round(vw.loc[d, "total"] * 100, 2) if d in vw.index else None,
             "managers": int(m.loc[d, "managers"]), "positions": int(m.loc[d, "positions"])}
            for d in m.index[::-1]],
        "barometer": [
            {"q": f"Q{(d.month - 1) // 3 + 1} {d.year}",
             **{k: (None if pd.isna(v) else round(float(v), 2)) for k, v in row.items()}}
            for d, row in bar.set_index("date").sort_index().iloc[::-1].iterrows()],
    }
    (site / "data" / "dl.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    # ---- series for the interactive analysis page (data/dl_series.json)
    ql = lambda d: qlab(pd.Timestamp(d))
    def clean(x):
        return None if pd.isna(x) else round(float(x) * 100, 4)
    series = {}
    for code, lab in LABELS.items():
        s_ = r[r["index"] == code].set_index("date").sort_index()
        series[code] = {"label": lab.replace("Main index (equal-weighted managers)", "Main index"), "group": "Published indices",
                        "q": [ql(d) for d in s_.index],
                        **{c: [clean(v) for v in s_[c]] for c in ["total", "income", "accretion", "price", "realized", "unrealized"]}}
    vf = rel / "dl_index_variants.csv"
    VLAB = {"recovery_60": "recovery 60%", "recovery_50": "recovery 50%", "min_positions_5": "min. 5 loans per manager",
            "min_positions_20": "min. 20 loans per manager", "repayment_90": "repayment threshold 90",
            "repayment_97": "repayment threshold 97", "distress_70": "distress threshold 70",
            "distress_90": "distress threshold 90", "interval_funds_only": "interval funds only"}
    if vf.exists():
        v = pd.read_csv(vf, parse_dates=["date"])
        order = {k: i for i, k in enumerate(VLAB)}
        v["_o"] = v["variant"].map(order).fillna(99)
        v = v.sort_values(["index", "_o", "date"])
        for (ic, _o, vn), g in v.groupby(["index", "_o", "variant"], sort=True):
            g = g.set_index("date").sort_index()
            series[f"{ic}__{vn}"] = {"label": f"{'Main index' if ic == 'ew_managers' else 'Value-weighted'}: {VLAB.get(vn, vn)}",
                                     "group": "Sensitivity: " + ("main index" if ic == "ew_managers" else "value-weighted"),
                                     "q": [ql(d) for d in g.index],
                                     **{c: [clean(x) for x in g[c]] for c in ["total", "income", "price"]}}
    ll = None
    if args.ll_release:
        fr = pd.read_csv(Path(args.ll_release) / "factor_returns.csv", parse_dates=["date"])
        mk = fr.query("portfolio == 'MKT' and weighting == 'ew' and holding == 1 and lag == 0 "
                      "and return_type == 'total'").drop_duplicates("date").set_index("date")["ret"].sort_index()
        llq = (1 + mk).groupby(mk.index + pd.offsets.QuarterEnd(0)).prod() - 1
        ll = {ql(d): round(float(x) * 100, 4) for d, x in llq.items()}
    bb = bar.set_index("date").sort_index()
    BLAB = {"non_accrual_pct": "Non-accruals (% of cost)", "marked_below_90_pct": "Loans marked below 90 (% of cost)",
            "pik_pct": "PIK (% of par)", "amended_pik_pct": "Amended PIK (% of par)",
            "realized_t4q_pct": "Realized gains/losses, last 4 quarters (%)",
            "unrealized_t4q_pct": "Unrealized gains/losses, last 4 quarters (%)"}
    baro = {"q": [ql(d) for d in bb.index], "metrics": {}}
    for c, lab in BLAB.items():
        if c in bb:
            ex = c + "_ex_largest"
            baro["metrics"][c] = {"label": lab, "all": [None if pd.isna(x) else round(float(x), 3) for x in bb[c]],
                                  "ex": ([None if pd.isna(x) else round(float(x), 3) for x in bb[ex]] if ex in bb else None)}
    uu = uni.set_index("date").sort_index()
    universe = {"q": [ql(d) for d in uu.index], **{c: [None if pd.isna(x) else round(float(x), 4) for x in uu[c]]
                for c in ["positions", "funds", "managers", "market_value_usd_bn", "largest_manager_share"] if c in uu}}
    (site / "data" / "dl_series.json").write_text(
        json.dumps({"series": series, "ll_market": ll, "barometer": baro, "universe": universe}), encoding="utf-8")

    # ---- chart 1: cumulative value
    fig, ax = plt.subplots(figsize=(9, 4.2))
    style(ax)
    colours = {"ew_managers": INK, "vw_all": GOLD, "vw_ex_largest": BLUE}
    for code, col in colours.items():
        s = r[r["index"] == code].set_index("date").sort_index()["total"]
        cum = pd.concat([pd.Series([100.0], index=[s.index[0] - pd.offsets.QuarterEnd(1)]), 100 * (1 + s).cumprod()])
        ax.plot(cum.index, cum.values, color=col, lw=2.4 if code == "ew_managers" else 1.6, label=LABELS[code])
    if args.ll_release:
        fr = pd.read_csv(Path(args.ll_release) / "factor_returns.csv", parse_dates=["date"])
        mk = fr.query("portfolio == 'MKT' and weighting == 'ew' and holding == 1 and lag == 0 "
                      "and return_type == 'total'").drop_duplicates("date").set_index("date")["ret"].sort_index()
        llq = (1 + mk).groupby(mk.index + pd.offsets.QuarterEnd(0)).prod() - 1
        start = r["date"].min() - pd.offsets.QuarterEnd(1)
        llq = llq[(llq.index > start) & (llq.index <= r["date"].max())]
        cum = pd.concat([pd.Series([100.0], index=[start]), 100 * (1 + llq).cumprod()])
        ax.plot(cum.index, cum.values, color=GREY, lw=1.4, ls="--", label="Leveraged loan market (N-PORT, for comparison)")
    ax.set_ylabel("Value of 100 invested", color=SLATE, fontsize=10)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_index.svg", format="svg")
    plt.close(fig)

    # ---- chart 2: barometer
    b = bar.set_index("date").sort_index().dropna(subset=["non_accrual_pct"])
    fig, axs = plt.subplots(1, 2, figsize=(9, 3.4))
    for ax, (c_all, c_ex, title) in zip(axs, [("non_accrual_pct", "non_accrual_pct_ex_largest", "Non-accruals (% of cost)"),
                                              ("marked_below_90_pct", "marked_below_90_pct_ex_largest",
                                               "Loans marked below 90 (% of cost)")]):
        style(ax)
        ax.plot(b.index, b[c_ex], color=INK, lw=2.2, label="Without Cliffwater")
        ax.plot(b.index, b[c_all], color=GOLD, lw=1.6, label="All managers")
        ax.set_title(title, color=INK, fontsize=11, loc="left")
        ax.set_ylim(bottom=0)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    axs[0].legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_barometer.svg", format="svg")
    plt.close(fig)
    print(f"Written: {site / 'data' / 'dl.json'}, {site / 'data' / 'dl_series.json'}, "
          f"{site / 'img' / 'dl_index.svg'}, {site / 'img' / 'dl_barometer.svg'}")


EU_LABELS = {"ew_managers": "Main index (equal-weighted managers)", "vw_all": "Value-weighted",
             "vw_ex_largest": "Value-weighted ex largest manager", "vw_first_lien": "First lien (value-weighted)",
             "vw_eur": "EUR loans (value-weighted)", "vw_gbp": "GBP loans (value-weighted)"}
EU_VARIANTS = {"repayment_80": "repayment threshold 80", "observed_coupons": "observed coupons only"}


def cum(s: pd.Series) -> pd.Series:
    s = s.sort_index()
    return pd.concat([pd.Series([100.0], index=[s.index[0] - pd.offsets.QuarterEnd(1)]), 100 * (1 + s).cumprod()])


def eu_web(rel: Path, site: Path, us_rel: Path | None) -> None:
    """Data files and charts for OpenDL Europe (and the overview chart of both indices)."""
    meta = json.loads((rel / "metadata.json").read_text(encoding="utf-8"))
    r = pd.read_csv(rel / "opendl_europe_returns.csv", parse_dates=["date"])
    sub = pd.read_csv(rel / "opendl_europe_subindices.csv", parse_dates=["date"])
    var = pd.read_csv(rel / "opendl_europe_variants.csv", parse_dates=["date"])
    bar = pd.read_csv(rel / "opendl_europe_barometer.csv", parse_dates=["date"]).set_index("date").sort_index()
    uni = pd.read_csv(rel / "opendl_europe_universe.csv", parse_dates=["date"]).set_index("date").sort_index()
    m = r[r["index"] == "ew_managers"].set_index("date").sort_index()
    vw = r[r["index"] == "vw_all"].set_index("date").sort_index()
    lu, lb = uni.iloc[-1], bar.iloc[-1]
    val = meta.get("validation", {})
    doi = meta.get("doi", "")
    data = {
        "version": meta.get("version", ""), "doi": doi, "start": qlab(m.index.min()), "end": qlab(m.index.max()),
        "last_quarter": qlab(m.index.max()),
        "key": {"last_quarter_pct": round(m["total"].iloc[-1] * 100, 2),
                "t4q_pct": round(((1 + m["total"].tail(4)).prod() - 1) * 100, 2),
                "annualized_pct": round(((1 + m["total"]).prod() ** (4 / len(m)) - 1) * 100, 2),
                "vol_pct": round(m["total"].std() * 200, 2), "managers": int(m["managers"].iloc[-1]),
                "positions": int(lu["positions"]), "bdcs": int(lu["bdcs"]),
                "market_value_bn": round(float(lu["market_value_usd_bn"]), 1),
                "largest_share_pct": round(float(lu["largest_manager_share"]) * 100),
                "share_eur_pct": round(float(lu["share_eur"]) * 100), "share_gbp_pct": round(float(lu["share_gbp"]) * 100),
                "below90_pct": round(float(lb["marked_below_90_pct"]), 1),
                "below80_pct": round(float(lb["marked_below_80_pct"]), 1)},
        "validation": val,
        "quarters": [{"q": qlab(d), "ew": round(m.loc[d, "total"] * 100, 2), "ew_income": round(m.loc[d, "income"] * 100, 2),
                      "ew_price": round(m.loc[d, "price"] * 100, 2),
                      "vw": round(vw.loc[d, "total"] * 100, 2) if d in vw.index else None,
                      "managers": int(m.loc[d, "managers"]), "positions": int(m.loc[d, "positions"])}
                     for d in m.index[::-1]],
        "barometer": [{"q": qlab(d), **{k: (None if pd.isna(v) else round(float(v), 2)) for k, v in row.items()}}
                      for d, row in bar.iloc[::-1].iterrows()],
    }
    (site / "data" / "dl_eu.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def clean(x):
        return None if pd.isna(x) else round(float(x) * 100, 4)
    series = {}
    for code in ["ew_managers", "vw_all", "vw_ex_largest"]:
        s_ = r[r["index"] == code].set_index("date").sort_index()
        series[code] = {"label": EU_LABELS[code].replace("Main index (equal-weighted managers)", "Main index"),
                        "group": "Published indices", "q": [qlab(d) for d in s_.index],
                        **{c: [clean(v) for v in s_[c]] for c in ["total", "income", "accretion", "price", "realized", "unrealized"]}}
    for code, g in sub.groupby("series"):
        g = g.set_index("date").sort_index()
        series[code] = {"label": EU_LABELS.get(code, code), "group": "Sub-indices", "q": [qlab(d) for d in g.index],
                        **{c: [clean(v) for v in g[c]] for c in ["total", "income", "price"]}}
    for (vn, ic), g in var.groupby(["variant", "index"]):
        g = g.set_index("date").sort_index()
        series[f"{ic}__{vn}"] = {"label": f"{'Main index' if ic == 'ew_managers' else 'Value-weighted'}: {EU_VARIANTS.get(vn, vn)}",
                                 "group": "Sensitivity", "q": [qlab(d) for d in g.index],
                                 **{c: [clean(x) for x in g[c]] for c in ["total", "income", "price"]}}
    blab = {"marked_below_80_pct": "Loans marked below 80 (% of cost)", "marked_below_90_pct": "Loans marked below 90 (% of cost)",
            "realized_t4q_pct": "Realized gains/losses, last 4 quarters (%)",
            "unrealized_t4q_pct": "Unrealized gains/losses, last 4 quarters (%)"}
    baro = {"q": [qlab(d) for d in bar.index], "metrics": {}}
    for c, lab in blab.items():
        if c in bar:
            ex = c + "_ex_largest"
            baro["metrics"][c] = {"label": lab, "all": [None if pd.isna(x) else round(float(x), 3) for x in bar[c]],
                                  "ex": ([None if pd.isna(x) else round(float(x), 3) for x in bar[ex]] if ex in bar else None)}
    universe = {"q": [qlab(d) for d in uni.index],
                **{c: [None if pd.isna(x) else round(float(x), 4) for x in uni[c]]
                   for c in ["positions", "bdcs", "managers", "market_value_usd_bn", "largest_manager_share"] if c in uni}}
    (site / "data" / "dl_eu_series.json").write_text(
        json.dumps({"series": series, "ll_market": None, "barometer": baro, "universe": universe,
                    "ex_label": "Without the largest manager"}), encoding="utf-8")

    # ---- charts
    fig, ax = plt.subplots(figsize=(9, 4.2))
    style(ax)
    for code, col, lw in [("ew_managers", INK, 2.4), ("vw_all", GOLD, 1.6), ("vw_first_lien", BLUE, 1.6)]:
        s_ = (r[r["index"] == code] if code in r["index"].values else sub[sub["series"] == code]).set_index("date")["total"]
        c_ = cum(s_)
        ax.plot(c_.index, c_.values, color=col, lw=lw, label=EU_LABELS[code])
    ax.set_ylabel("Value of 100 invested", color=SLATE, fontsize=10)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_eu_index.svg", format="svg")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.4))
    style(ax)
    ax.plot(bar.index, bar["marked_below_90_pct"], color=INK, lw=2.2, label="Marked below 90")
    ax.plot(bar.index, bar["marked_below_80_pct"], color=GOLD, lw=1.6, label="Marked below 80")
    ax.set_title("Loans marked below 90 and below 80 (% of cost)", color=INK, fontsize=11, loc="left")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_eu_barometer.svg", format="svg")
    plt.close(fig)

    if us_rel is not None and (us_rel / "dl_index_returns.csv").exists():
        us = pd.read_csv(us_rel / "dl_index_returns.csv", parse_dates=["date"])
        us = us[us["index"] == "ew_managers"].set_index("date")["total"].sort_index()
        start = m.index.min()
        fig, ax = plt.subplots(figsize=(9, 4.0))
        style(ax)
        for s_, lab, col in [(m["total"], "OpenDL Europe", INK), (us[us.index >= start], "OpenDL US", GOLD)]:
            c_ = cum(s_)
            ax.plot(c_.index, c_.values, color=col, lw=2.3, label=lab)
        ax.set_ylabel("Value of 100 invested", color=SLATE, fontsize=10)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        ax.legend(frameon=False, fontsize=10, loc="upper left")
        fig.tight_layout()
        fig.savefig(site / "img" / "dl_overview.svg", format="svg")
        plt.close(fig)
    print(f"Written: data/dl_eu.json, data/dl_eu_series.json, img/dl_eu_index.svg, img/dl_eu_barometer.svg"
          f"{', img/dl_overview.svg' if us_rel else ''}")


def usbdc_web(rel: Path, site: Path) -> None:
    """Data files and charts for OpenDL US BDC."""
    meta = json.loads((rel / "metadata.json").read_text(encoding="utf-8"))
    r = pd.read_csv(rel / "opendl_us_bdc_returns.csv", parse_dates=["date"])
    sub = pd.read_csv(rel / "opendl_us_bdc_subindices.csv", parse_dates=["date"])
    var = pd.read_csv(rel / "opendl_us_bdc_variants.csv", parse_dates=["date"])
    bar = pd.read_csv(rel / "opendl_us_bdc_barometer.csv", parse_dates=["date"]).set_index("date").sort_index()
    uni = pd.read_csv(rel / "opendl_us_bdc_universe.csv", parse_dates=["date"]).set_index("date").sort_index()
    m = r[r["index"] == "ew_managers"].set_index("date").sort_index()
    vw = r[r["index"] == "vw_all"].set_index("date").sort_index()
    lu, lb = uni.iloc[-1], bar.iloc[-1]
    data = {
        "version": meta.get("version", ""), "doi": meta.get("doi", ""), "start": qlab(m.index.min()),
        "end": qlab(m.index.max()), "last_quarter": qlab(m.index.max()),
        "key": {"last_quarter_pct": round(m["total"].iloc[-1] * 100, 2),
                "t4q_pct": round(((1 + m["total"].tail(4)).prod() - 1) * 100, 2),
                "annualized_pct": round(((1 + m["total"]).prod() ** (4 / len(m)) - 1) * 100, 2),
                "vol_pct": round(m["total"].std() * 200, 2), "managers": int(m["managers"].iloc[-1]),
                "positions": int(lu["positions"]), "bdcs": int(lu["bdcs"]),
                "market_value_bn": round(float(lu["market_value_usd_bn"]), 1),
                "largest_share_pct": round(float(lu["largest_manager_share"]) * 100),
                "below90_pct": round(float(lb["marked_below_90_pct"]), 1),
                "below80_pct": round(float(lb["marked_below_80_pct"]), 1)},
        "validation": meta.get("validation", {}),
        "quarters": [{"q": qlab(d), "ew": round(m.loc[d, "total"] * 100, 2), "ew_income": round(m.loc[d, "income"] * 100, 2),
                      "ew_price": round(m.loc[d, "price"] * 100, 2),
                      "vw": round(vw.loc[d, "total"] * 100, 2) if d in vw.index else None,
                      "managers": int(m.loc[d, "managers"]), "positions": int(m.loc[d, "positions"])}
                     for d in m.index[::-1]],
        "barometer": [{"q": qlab(d), **{k: (None if pd.isna(v) else round(float(v), 2)) for k, v in row.items()}}
                      for d, row in bar.iloc[::-1].iterrows()],
    }
    (site / "data" / "dl_usbdc.json").write_text(json.dumps(data, indent=1), encoding="utf-8")

    def clean(x):
        return None if pd.isna(x) else round(float(x) * 100, 4)
    labels = {"ew_managers": "Main index", "vw_all": "Value-weighted", "vw_ex_largest": "Value-weighted ex largest manager"}
    series = {}
    for code, lab in labels.items():
        s_ = r[r["index"] == code].set_index("date").sort_index()
        series[code] = {"label": lab, "group": "Published indices", "q": [qlab(d) for d in s_.index],
                        **{c: [clean(v) for v in s_[c]] for c in ["total", "income", "accretion", "price", "realized", "unrealized"]}}
    for code, g in sub.groupby("series"):
        g = g.set_index("date").sort_index()
        series[code] = {"label": "First lien (value-weighted)", "group": "Sub-indices", "q": [qlab(d) for d in g.index],
                        **{c: [clean(v) for v in g[c]] for c in ["total", "income", "price"]}}
    vnames = {"repayment_80": "repayment threshold 80", "observed_coupons": "observed coupons only"}
    for (vn, ic), g in var.groupby(["variant", "index"]):
        g = g.set_index("date").sort_index()
        series[f"{ic}__{vn}"] = {"label": f"{'Main index' if ic == 'ew_managers' else 'Value-weighted'}: {vnames.get(vn, vn)}",
                                 "group": "Sensitivity", "q": [qlab(d) for d in g.index],
                                 **{c: [clean(x) for x in g[c]] for c in ["total", "income", "price"]}}
    blab = {"marked_below_80_pct": "Loans marked below 80 (% of cost)", "marked_below_90_pct": "Loans marked below 90 (% of cost)",
            "realized_t4q_pct": "Realized gains/losses, last 4 quarters (%)",
            "unrealized_t4q_pct": "Unrealized gains/losses, last 4 quarters (%)"}
    baro = {"q": [qlab(d) for d in bar.index], "metrics": {}}
    for c, lab in blab.items():
        if c in bar:
            ex = c + "_ex_largest"
            baro["metrics"][c] = {"label": lab, "all": [None if pd.isna(x) else round(float(x), 3) for x in bar[c]],
                                  "ex": ([None if pd.isna(x) else round(float(x), 3) for x in bar[ex]] if ex in bar else None)}
    universe = {"q": [qlab(d) for d in uni.index],
                **{c: [None if pd.isna(x) else round(float(x), 4) for x in uni[c]]
                   for c in ["positions", "bdcs", "managers", "market_value_usd_bn", "largest_manager_share"] if c in uni}}
    (site / "data" / "dl_usbdc_series.json").write_text(
        json.dumps({"series": series, "ll_market": None, "barometer": baro, "universe": universe,
                    "ex_label": "Without the largest manager"}), encoding="utf-8")

    fig, ax = plt.subplots(figsize=(9, 4.2))
    style(ax)
    for code, col, lw, lab in [("ew_managers", INK, 2.4, "Main index (equal-weighted managers)"),
                               ("vw_all", GOLD, 1.6, "Value-weighted")]:
        c_ = cum(r[r["index"] == code].set_index("date")["total"])
        ax.plot(c_.index, c_.values, color=col, lw=lw, label=lab)
    c_ = cum(sub.set_index("date")["total"])
    ax.plot(c_.index, c_.values, color=BLUE, lw=1.6, label="First lien (value-weighted)")
    ax.set_ylabel("Value of 100 invested", color=SLATE, fontsize=10)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=9.5, loc="upper left")
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_usbdc_index.svg", format="svg")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 3.4))
    style(ax)
    ax.plot(bar.index, bar["marked_below_90_pct"], color=INK, lw=2.2, label="Marked below 90")
    ax.plot(bar.index, bar["marked_below_80_pct"], color=GOLD, lw=1.6, label="Marked below 80")
    ax.set_title("Loans marked below 90 and below 80 (% of cost)", color=INK, fontsize=11, loc="left")
    ax.set_ylim(bottom=0)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_usbdc_barometer.svg", format="svg")
    plt.close(fig)
    print("Written: data/dl_usbdc.json, data/dl_usbdc_series.json, img/dl_usbdc_index.svg, img/dl_usbdc_barometer.svg")


def overview_chart(site: Path, eu_rel: Path, usb_rel: Path, us_rel: Path) -> None:
    """Cumulative main indices of OpenDL Europe, OpenDL US BDC and OpenDL US from the start of the BDC indices."""
    eu = pd.read_csv(eu_rel / "opendl_europe_returns.csv", parse_dates=["date"])
    ub = pd.read_csv(usb_rel / "opendl_us_bdc_returns.csv", parse_dates=["date"])
    us = pd.read_csv(us_rel / "dl_index_returns.csv", parse_dates=["date"])
    e = eu[eu["index"] == "ew_managers"].set_index("date")["total"].sort_index()
    b = ub[ub["index"] == "ew_managers"].set_index("date")["total"].sort_index()
    u = us[us["index"] == "ew_managers"].set_index("date")["total"].sort_index()
    start = e.index.min()
    fig, ax = plt.subplots(figsize=(9, 4.0))
    style(ax)
    for s_, lab, col in [(e, "OpenDL Europe", INK), (b[b.index >= start], "OpenDL US BDC", BLUE),
                         (u[u.index >= start], "OpenDL US", GOLD)]:
        c_ = cum(s_)
        ax.plot(c_.index, c_.values, color=col, lw=2.2, label=lab)
    ax.set_ylabel("Value of 100 invested", color=SLATE, fontsize=10)
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    fig.tight_layout()
    fig.savefig(site / "img" / "dl_overview.svg", format="svg")
    plt.close(fig)
    print("Written: img/dl_overview.svg (three indices)")


if __name__ == "__main__":
    main()
