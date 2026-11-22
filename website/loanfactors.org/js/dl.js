/* loanfactors.org – direct lending pages: key figures and tables of OpenDL US (data/dl.json, attribute data-dl)
   and OpenDL Europe (data/dl_eu.json, attribute data-eu) */
(function () {
  "use strict";
  function fmt(v, d) { return v === null || v === undefined || isNaN(v) ? "–" : Number(v).toFixed(d === undefined ? 2 : d); }
  function pct(v, d) { var x = fmt(v, d); return x === "–" ? x : x + "%"; }
  function fill(attr, vals, d) {
    document.querySelectorAll("[" + attr + "]").forEach(function (el) {
      var x = vals[el.getAttribute(attr)];
      if (x !== undefined && x !== null && x !== "" && x !== "–" && x !== "NaN") el.textContent = x;
    });
    document.querySelectorAll("[" + attr + "-href=doi]").forEach(function (a) { if (d.doi) a.href = "https://doi.org/" + d.doi; });
  }
  function qtable(id, d) {
    var t = document.getElementById(id);
    if (!t) return;
    var h = "<thead><tr><th>Quarter</th><th>Main index</th><th>Income</th><th>Price</th><th>Value-weighted</th><th>Managers</th><th>Loans</th></tr></thead><tbody>";
    d.quarters.forEach(function (q) {
      h += "<tr><td>" + q.q + "</td><td>" + pct(q.ew) + "</td><td>" + pct(q.ew_income) + "</td><td>" + pct(q.ew_price) +
           "</td><td>" + pct(q.vw) + "</td><td>" + q.managers + "</td><td>" + Number(q.positions).toLocaleString("en-US") + "</td></tr>";
    });
    t.innerHTML = h + "</tbody>";
  }
  function get(url) { return fetch(url).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }

  get("data/dl.json").then(function (d) {
    var k = d.key, v = d.validation || {}, ew = v.ew_managers || {}, vw = v.vw_all || {};
    fill("data-dl", {
      version: d.version, start: d.start, end: d.end, last_quarter: d.last_quarter,
      last_q: pct(k.last_quarter_pct), t4q: pct(k.t4q_pct), ann: pct(k.annualized_pct), vol: pct(k.vol_pct),
      managers: k.managers, positions: Number(k.positions).toLocaleString("en-US"), funds: k.funds,
      mv: "$" + fmt(k.market_value_bn, 1) + "bn", largest: k.largest_share_pct + "%",
      na_ex: pct(k.non_accrual_ex_pct), b90_ex: pct(k.below90_ex_pct), recovery: fmt(k.recovery_pct, 1),
      corr_vw: fmt(vw.corr_total), corr_ew: fmt(ew.corr_total), corr_inc: fmt(vw.corr_income),
      diff_ew: fmt(ew.mean_abs_diff_calendar_year_pp, 1), beta: fmt(ew.dimson_beta_on_leveraged_loan_market), doi: d.doi
    }, d);
    qtable("dl-q", d);
    var b = document.getElementById("dl-b");
    if (b) {
      var g = "<thead><tr><th>Quarter-end</th><th>Non-accruals<br>ex Cliffwater</th><th>Marked &lt; 90<br>ex Cliffwater</th>" +
              "<th>Non-accruals<br>all</th><th>Marked &lt; 90<br>all</th><th>Realized<br>(4 quarters)</th><th>Unrealized<br>(4 quarters)</th></tr></thead><tbody>";
      d.barometer.forEach(function (q) {
        g += "<tr><td>" + q.q + "</td><td>" + pct(q.non_accrual_pct_ex_largest) + "</td><td>" + pct(q.marked_below_90_pct_ex_largest) +
             "</td><td>" + pct(q.non_accrual_pct) + "</td><td>" + pct(q.marked_below_90_pct) + "</td><td>" + pct(q.realized_t4q_pct) +
             "</td><td>" + pct(q.unrealized_t4q_pct) + "</td></tr>";
      });
      b.innerHTML = g + "</tbody>";
    }
  }).catch(function () {});

  get("data/dl_eu.json").then(function (d) {
    var k = d.key, v = d.validation || {}, vw = v.vw_all || {}, fl = v.vw_first_lien || {},
        nb = v.same_loan_nport_vs_bdc_same_manager || {};
    fill("data-eu", {
      version: d.version, start: d.start, end: d.end, last_quarter: d.last_quarter,
      last_q: pct(k.last_quarter_pct), t4q: pct(k.t4q_pct), ann: pct(k.annualized_pct), vol: pct(k.vol_pct),
      managers: k.managers, positions: Number(k.positions).toLocaleString("en-US"), bdcs: k.bdcs,
      mv: "$" + fmt(k.market_value_bn, 1) + "bn", largest: k.largest_share_pct + "%",
      eur: k.share_eur_pct + "%", gbp: k.share_gbp_pct + "%", b90: pct(k.below90_pct, 1), b80: pct(k.below80_pct, 1),
      corr_vw: fmt(vw.corr_esdi), diff_vw: fmt(vw.diff_esdi_pp_pa, 1), corr_fl: fmt(fl.corr_esdi),
      diff_fl: fmt(fl.diff_esdi_pp_pa, 2), nb_med: fmt(nb.median_abs_diff, 2),
      nb_w1: nb.within_1pt !== undefined ? Math.round(nb.within_1pt * 100) + "%" : "–", doi: d.doi
    }, d);
    qtable("eu-q", d);
    var b = document.getElementById("eu-b");
    if (b) {
      var g = "<thead><tr><th>Quarter-end</th><th>Marked &lt; 80</th><th>Marked &lt; 90</th><th>Marked &lt; 90<br>ex largest manager</th>" +
              "<th>Realized<br>(4 quarters)</th><th>Unrealized<br>(4 quarters)</th></tr></thead><tbody>";
      d.barometer.forEach(function (q) {
        g += "<tr><td>" + q.q + "</td><td>" + pct(q.marked_below_80_pct) + "</td><td>" + pct(q.marked_below_90_pct) + "</td><td>" +
             pct(q.marked_below_90_pct_ex_largest) + "</td><td>" + pct(q.realized_t4q_pct) + "</td><td>" + pct(q.unrealized_t4q_pct) + "</td></tr>";
      });
      b.innerHTML = g + "</tbody>";
    }
  }).catch(function () {});
})();
