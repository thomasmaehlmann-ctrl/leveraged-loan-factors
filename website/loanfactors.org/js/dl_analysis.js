/* loanfactors.org – interactive analysis of the Registered Fund Direct Lending Index.
   Reads data/dl_series.json; everything runs in the browser. */
(function () {
  "use strict";
  var COLORS = ["#1A2E4A", "#B8972A", "#3F7FA6", "#9AA4B2", "#7A4E8C", "#2E8B57", "#C0504D", "#5C6BC0", "#8D6E63", "#26A69A"];
  var COMP = { total: "Total return", income: "Income", price: "Price return", realized: "Realized gains/losses",
               unrealized: "Unrealized gains/losses", accretion: "Accretion of discounts" };
  var VIEWS = { cum: "Cumulative (value of 100)", q: "Quarterly returns", r4: "Rolling four quarters" };
  var D, app = document.getElementById("dl-app");
  if (!app) return;

  function el(tag, attrs, html) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
    if (html !== undefined) e.innerHTML = html;
    return e;
  }
  function f2(x, d) { return x === null || x === undefined || isNaN(x) ? "–" : x.toFixed(d === undefined ? 2 : d); }
  function pct(x, d) { return x === null || x === undefined || isNaN(x) ? "–" : f2(x, d) + "%"; }
  function select(label, opts, value, groups) {
    var w = el("label", null, label), s = el("select");
    if (groups) {
      groups.forEach(function (g) {
        var og = el("optgroup", { label: g.name });
        g.items.forEach(function (o) { var op = el("option", { value: o[0] }, o[1]); og.appendChild(op); });
        s.appendChild(og);
      });
    } else {
      opts.forEach(function (o) { s.appendChild(el("option", { value: o[0] }, o[1])); });
    }
    s.value = value; w.appendChild(s); w.sel = s; return w;
  }

  /* ---------- statistics ---------- */
  function slice(arr, i0, i1) { return arr.slice(i0, i1 + 1); }
  function transform(vals, view) {          // vals in % per quarter
    var out = [], c = 100, k;
    if (view === "cum") { out.push(100); vals.forEach(function (v) { c = v === null ? c : c * (1 + v / 100); out.push(c); }); return out; }
    if (view === "q") return vals.slice();
    for (k = 0; k < vals.length; k++) {
      if (k < 3) { out.push(null); continue; }
      var p = 1, ok = true;
      for (var j = k - 3; j <= k; j++) { if (vals[j] === null) ok = false; else p *= 1 + vals[j] / 100; }
      out.push(ok ? (p - 1) * 100 : null);
    }
    return out;
  }
  function stats(vals, comp, ll) {
    var v = vals.filter(function (x) { return x !== null; }), n = v.length;
    if (!n) return {};
    var mean = v.reduce(function (a, b) { return a + b; }, 0) / n;
    var sd = Math.sqrt(v.reduce(function (a, b) { return a + (b - mean) * (b - mean); }, 0) / Math.max(n - 1, 1));
    var ann = comp === "total" ? (Math.pow(v.reduce(function (a, b) { return a * (1 + b / 100); }, 1), 4 / n) - 1) * 100 : mean * 4;
    var r = { n: n, ann: ann, vol: sd * 2, worst: Math.min.apply(null, v), best: Math.max.apply(null, v) };
    if (ll) {
      var xs = [], ys = [];
      vals.forEach(function (y, i) { if (y !== null && ll[i] !== null && ll[i] !== undefined) { xs.push(ll[i]); ys.push(y); } });
      if (xs.length >= 6) {
        var mx = xs.reduce(function (a, b) { return a + b; }, 0) / xs.length, my = ys.reduce(function (a, b) { return a + b; }, 0) / ys.length;
        var sxy = 0, sxx = 0, syy = 0;
        xs.forEach(function (x, i) { sxy += (x - mx) * (ys[i] - my); sxx += (x - mx) * (x - mx); syy += (ys[i] - my) * (ys[i] - my); });
        r.beta = sxy / sxx; r.corr = sxy / Math.sqrt(sxx * syy);
      }
    }
    return r;
  }

  /* ---------- chart (SVG) ---------- */
  function chart(box, labels, series, opt) {
    box.innerHTML = "";
    var W = 900, H = 330, L = 56, R = 16, T = 14, B = 34;
    var all = [];
    series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && !isNaN(v)) all.push(v); }); });
    if (!all.length) { box.textContent = "No data for this selection."; return; }
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    if (opt.bars || opt.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    var pad = (hi - lo) * 0.08 || 1; lo -= pad; hi += pad;
    var raw = (hi - lo) / 5, mag = Math.pow(10, Math.floor(Math.log(raw) / Math.LN10)), nrm = raw / mag;
    var nstep = (nrm < 1.5 ? 1 : nrm < 3 ? 2 : nrm < 7 ? 5 : 10) * mag;
    lo = Math.floor(lo / nstep) * nstep; hi = Math.ceil(hi / nstep) * nstep;
    var n = labels.length, x = function (i) { return L + (n === 1 ? (W - L - R) / 2 : i * (W - L - R) / (n - 1)); };
    if (opt.bars) x = function (i) { return L + (i + 0.5) * (W - L - R) / n; };
    var y = function (v) { return T + (hi - v) / (hi - lo) * (H - T - B); };
    var svg = '<svg viewBox="0 0 ' + W + " " + H + '" width="100%" role="img" aria-label="Chart">';
    var dec = nstep >= 1 ? 0 : nstep >= 0.1 ? 1 : 2;
    for (var v = lo; v <= hi + nstep / 2; v += nstep) {
      if (Math.abs(v) < nstep / 1e6) v = 0;
      var yy = y(v);
      svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="#D9DFE7"/>';
      svg += '<text x="' + (L - 8) + '" y="' + (yy + 4) + '" text-anchor="end" font-size="12" fill="#586273">' + f2(v, dec) + "</text>";
    }
    if (lo < 0 && hi > 0) svg += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y(0) + '" y2="' + y(0) + '" stroke="#586273"/>';
    var every = Math.max(1, Math.ceil(n / 9));
    labels.forEach(function (lab, i) {
      if (i % every === 0 || (i === n - 1 && (n - 1) % every >= every / 2)) svg += '<text x="' + x(i) + '" y="' + (H - 10) + '" text-anchor="middle" font-size="12" fill="#586273">' + lab + "</text>";
    });
    if (opt.bars) {
      var bw = (W - L - R) / n / (series.length + 0.6);
      series.forEach(function (s, k) {
        s.values.forEach(function (v, i) {
          if (v === null || isNaN(v)) return;
          var x0 = x(i) - bw * series.length / 2 + k * bw, y0 = y(Math.max(v, 0)), h = Math.abs(y(v) - y(0));
          svg += '<rect x="' + x0 + '" y="' + y0 + '" width="' + (bw * 0.92) + '" height="' + Math.max(h, 0.5) + '" fill="' + s.color + '"/>';
        });
      });
    } else {
      series.forEach(function (s) {
        var d = "", pen = false;
        s.values.forEach(function (v, i) {
          if (v === null || isNaN(v)) { pen = false; return; }
          d += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true;
        });
        svg += '<path d="' + d + '" fill="none" stroke="' + s.color + '" stroke-width="' + (s.width || 2) + '"' + (s.dash ? ' stroke-dasharray="6 4"' : "") + "/>";
      });
    }
    svg += '<line class="hover" x1="0" x2="0" y1="' + T + '" y2="' + (H - B) + '" stroke="#586273" stroke-dasharray="3 3" visibility="hidden"/>';
    svg += '<rect class="hit" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '" fill="transparent"/></svg>';
    var wrap = el("div", { class: "chart" }); wrap.innerHTML = svg; box.appendChild(wrap);
    var leg = el("div", { class: "legend" });
    series.forEach(function (s) { leg.appendChild(el("span", null, '<i style="background:' + s.color + '"></i>' + s.name)); });
    box.insertBefore(leg, wrap);
    var tip = el("div", { class: "chart-tip" }); tip.style.display = "none"; wrap.appendChild(tip);
    var svgEl = wrap.querySelector("svg"), hov = svgEl.querySelector(".hover");
    svgEl.querySelector(".hit").addEventListener("mousemove", function (ev) {
      var rect = svgEl.getBoundingClientRect(), px = (ev.clientX - rect.left) * W / rect.width, best = 0, bd = 1e9;
      for (var i = 0; i < n; i++) { var dd = Math.abs(x(i) - px); if (dd < bd) { bd = dd; best = i; } }
      hov.setAttribute("x1", x(best)); hov.setAttribute("x2", x(best)); hov.setAttribute("visibility", "visible");
      var h = "<b>" + labels[best] + "</b>";
      series.forEach(function (s) { h += "<br>" + s.name + ": " + f2(s.values[best], opt.dec === undefined ? 2 : opt.dec) + (opt.unit || ""); });
      tip.innerHTML = h; tip.style.display = "block";
      var left = (ev.clientX - rect.left) + 14; if (left > rect.width - 220) left -= 240;
      tip.style.left = left + "px"; tip.style.top = "10px";
    });
    svgEl.querySelector(".hit").addEventListener("mouseleave", function () { tip.style.display = "none"; hov.setAttribute("visibility", "hidden"); });
  }

  /* ---------- helpers on the data ---------- */
  function groups() {
    var g = {}, order = [];
    Object.keys(D.series).forEach(function (k) {
      var s = D.series[k]; if (!g[s.group]) { g[s.group] = []; order.push(s.group); }
      g[s.group].push([k, s.label]);
    });
    return order.map(function (o) { return { name: o, items: g[o] }; });
  }
  function quarters() { return D.series.ew_managers.q; }
  function aligned(key, comp) {
    var s = D.series[key], m = {};
    if (!s[comp]) return quarters().map(function () { return null; });
    s.q.forEach(function (q, i) { m[q] = s[comp][i]; });
    return quarters().map(function (q) { return m[q] === undefined ? null : m[q]; });
  }
  function llAligned() { return D.ll_market ? quarters().map(function (q) { return D.ll_market[q] === undefined ? null : D.ll_market[q]; }) : null; }
  function periodControls(onchange) {
    var qs = quarters().map(function (q, i) { return [String(i), q]; });
    var a = select("From", qs, "0"), b = select("To", qs, String(qs.length - 1));
    a.sel.addEventListener("change", onchange); b.sel.addEventListener("change", onchange);
    return [a, b];
  }
  function viewLabels(view, i0, i1) {
    var q = slice(quarters(), i0, i1);
    if (view === "cum") { return [i0 > 0 ? quarters()[i0 - 1] : prevQ(quarters()[0])].concat(q); }
    return q;
  }

  /* ---------- panel 1: index ---------- */
  function panelIndex(p) {
    var c = el("div", { class: "controls" });
    var sSer = select("Series", null, "ew_managers", groups());
    var sComp = select("Component", Object.keys(COMP).map(function (k) { return [k, COMP[k]]; }), "total");
    var sView = select("View", Object.keys(VIEWS).map(function (k) { return [k, VIEWS[k]]; }), "cum");
    var per = periodControls(draw);
    var llw = el("label", { class: "check" }, '<input type="checkbox" checked> Leveraged loan market');
    [sSer, sComp, sView, per[0], per[1]].forEach(function (x) { c.appendChild(x); });
    if (D.ll_market) c.appendChild(llw);
    p.appendChild(c);
    var note = el("p", { class: "small" }); p.appendChild(note);
    var box = el("div", { class: "chart-box" }); p.appendChild(box);
    var tw = el("div", { class: "table-wrap" }), tb = el("table", { class: "stats" }); tw.appendChild(tb); p.appendChild(tw);
    [sSer.sel, sComp.sel, sView.sel].forEach(function (s) { s.addEventListener("change", draw); });
    llw.querySelector("input").addEventListener("change", draw);
    function draw() {
      var key = sSer.sel.value, comp = sComp.sel.value, view = sView.sel.value;
      var i0 = +per[0].sel.value, i1 = +per[1].sel.value; if (i1 < i0) { var t = i0; i0 = i1; i1 = t; }
      var vals = slice(aligned(key, comp), i0, i1);
      var avail = vals.some(function (v) { return v !== null; });
      note.textContent = avail ? "" : "This component is not available for the selected series (the split into realized and unrealized returns is published for value-weighted indices).";
      var ser = [{ name: D.series[key].label + " – " + COMP[comp], color: COLORS[0], values: transform(vals, view), width: 2.4 }];
      var llv = llAligned(), useLL = D.ll_market && llw.querySelector("input").checked && comp === "total";
      if (useLL) ser.push({ name: "Leveraged loan market", color: COLORS[3], values: transform(slice(llv, i0, i1), view), dash: true });
      chart(box, viewLabels(view, i0, i1), ser, { bars: view === "q", unit: view === "cum" ? "" : "%", dec: view === "cum" ? 1 : 2 });
      var st = stats(vals, comp, comp === "total" && llv ? slice(llv, i0, i1) : null);
      var inc = stats(slice(aligned(key, "income"), i0, i1), "income"), pr = stats(slice(aligned(key, "price"), i0, i1), "price");
      tb.innerHTML = "<thead><tr><th>Statistic</th><th>Value</th></tr></thead><tbody>" +
        "<tr><td>Quarters</td><td>" + (st.n || "–") + "</td></tr>" +
        "<tr><td>" + (comp === "total" ? "Annualized return" : "Average per year") + "</td><td>" + pct(st.ann) + "</td></tr>" +
        "<tr><td>Income per year</td><td>" + pct(inc.ann) + "</td></tr>" +
        "<tr><td>Price return per year</td><td>" + pct(pr.ann) + "</td></tr>" +
        "<tr><td>Volatility per year</td><td>" + pct(st.vol) + "</td></tr>" +
        "<tr><td>Worst quarter</td><td>" + pct(st.worst) + "</td></tr>" +
        "<tr><td>Best quarter</td><td>" + pct(st.best) + "</td></tr>" +
        (st.corr !== undefined ? "<tr><td>Correlation with leveraged loan market</td><td>" + f2(st.corr) + "</td></tr>" +
          "<tr><td>Beta on leveraged loan market (same quarter)</td><td>" + f2(st.beta) + "</td></tr>" : "") + "</tbody>";
    }
    draw();
  }

  /* ---------- panel 2: compare ---------- */
  function panelCompare(p) {
    var c = el("div", { class: "controls" });
    var sComp = select("Component", [["total", COMP.total], ["income", COMP.income], ["price", COMP.price]], "total");
    var sView = select("View", Object.keys(VIEWS).map(function (k) { return [k, VIEWS[k]]; }), "cum");
    var per = periodControls(draw);
    [sComp, sView, per[0], per[1]].forEach(function (x) { c.appendChild(x); });
    p.appendChild(c);
    var picks = el("div", { class: "picks" });
    var preset = { ew_managers: 1, vw_all: 1, vw_ex_largest: 1 };
    groups().forEach(function (g) {
      var fs = el("fieldset"); fs.appendChild(el("legend", null, g.name));
      g.items.forEach(function (it) {
        var lab = el("label", null, '<input type="checkbox" value="' + it[0] + '"' + (preset[it[0]] ? " checked" : "") + "> " + it[1]);
        lab.querySelector("input").addEventListener("change", draw); fs.appendChild(lab);
      });
      picks.appendChild(fs);
    });
    p.appendChild(picks);
    var box = el("div", { class: "chart-box" }); p.appendChild(box);
    var tw = el("div", { class: "table-wrap" }), tb = el("table", { class: "stats" }); tw.appendChild(tb); p.appendChild(tw);
    [sComp.sel, sView.sel].forEach(function (s) { s.addEventListener("change", draw); });
    function draw() {
      var comp = sComp.sel.value, view = sView.sel.value, i0 = +per[0].sel.value, i1 = +per[1].sel.value;
      if (i1 < i0) { var t = i0; i0 = i1; i1 = t; }
      var keys = Array.prototype.map.call(picks.querySelectorAll("input:checked"), function (x) { return x.value; }).slice(0, COLORS.length);
      var ser = [], rows = "";
      keys.forEach(function (k, j) {
        var vals = slice(aligned(k, comp), i0, i1), st = stats(vals, comp);
        ser.push({ name: D.series[k].label, color: COLORS[j], values: transform(vals, view), width: k === "ew_managers" ? 2.6 : 1.8 });
        rows += "<tr><td>" + D.series[k].label + "</td><td>" + pct(st.ann) + "</td><td>" + pct(st.vol) + "</td><td>" + pct(st.worst) + "</td><td>" + (st.n || "–") + "</td></tr>";
      });
      chart(box, viewLabels(view, i0, i1), ser, { bars: false, zero: view !== "cum", unit: view === "cum" ? "" : "%", dec: view === "cum" ? 1 : 2 });
      tb.innerHTML = "<thead><tr><th>Series</th><th>" + (comp === "total" ? "Annualized" : "Per year") + "</th><th>Volatility</th><th>Worst quarter</th><th>Quarters</th></tr></thead><tbody>" + rows + "</tbody>";
    }
    draw();
  }

  /* ---------- panel 3: credit health ---------- */
  function panelCredit(p) {
    var B = D.barometer, keys = Object.keys(B.metrics);
    var c = el("div", { class: "controls" });
    var sMet = select("Indicator", keys.map(function (k) { return [k, B.metrics[k].label]; }), keys[0]);
    c.appendChild(sMet); p.appendChild(c);
    var expl = el("p", { class: "small" }); p.appendChild(expl);
    var box = el("div", { class: "chart-box" }); p.appendChild(box);
    var tw = el("div", { class: "table-wrap" }), tb = el("table", { class: "stats" }); tw.appendChild(tb); p.appendChild(tw);
    var TXT = {
      non_accrual_pct: "Loans that no longer pay interest (coupon reported as zero), weighted by estimated cost.",
      marked_below_90_pct: "Loans valued below 90 per 100 of principal, weighted by estimated cost.",
      pik_pct: "Loans flagged as paying interest in kind, weighted by principal.",
      amended_pik_pct: "Loans newly switched to payment in kind while valued below 96 and still paying interest.",
      realized_t4q_pct: "Realized losses relative to estimated cost over the last four quarters, value-weighted index.",
      unrealized_t4q_pct: "Unrealized changes in valuations over the last four quarters, value-weighted index."
    };
    sMet.sel.addEventListener("change", draw);
    function draw() {
      var m = B.metrics[sMet.sel.value], ser = [];
      if (m.ex) ser.push({ name: D.ex_label || "Without Cliffwater", color: COLORS[0], values: m.ex, width: 2.4 });
      ser.push({ name: m.ex ? "All managers" : "Value-weighted index", color: COLORS[1], values: m.all });
      expl.textContent = TXT[sMet.sel.value] || "";
      chart(box, B.q, ser, { zero: true, unit: "%", dec: 2 });
      var rows = "";
      for (var i = B.q.length - 1; i >= 0; i--) rows += "<tr><td>" + B.q[i] + "</td>" + (m.ex ? "<td>" + pct(m.ex[i]) + "</td>" : "") + "<td>" + pct(m.all[i]) + "</td></tr>";
      tb.innerHTML = "<thead><tr><th>Quarter-end</th>" + (m.ex ? "<th>" + (D.ex_label || "Without Cliffwater") + "</th><th>All managers</th>" : "<th>Value</th>") + "</tr></thead><tbody>" + rows + "</tbody>";
    }
    draw();
  }

  /* label of the quarter before "Qn YYYY" (base point of cumulative views) */
  function prevQ(l) {
    var m = /^Q(\d) (\d{4})$/.exec(l || "");
    if (!m) return "start";
    var q = +m[1] - 1, y = +m[2];
    if (q === 0) { q = 4; y -= 1; }
    return "Q" + q + " " + y;
  }
  /* ---------- region and tabs ---------- */
  var REGIONS = { europe: ["OpenDL Europe", "data/dl_eu_series.json"], "us-bdc": ["OpenDL US BDC", "data/dl_usbdc_series.json"],
                  us: ["OpenDL US", "data/dl_series.json"] };
  var h0 = (location.hash || "").replace("#", "");
  var region = REGIONS[h0] ? h0 : "europe";
  function build() {
    app.innerHTML = "";
    var rc = el("div", { class: "controls region" });
    var rs = select("Index", Object.keys(REGIONS).map(function (k) { return [k, REGIONS[k][0]]; }), region);
    rs.sel.addEventListener("change", function () {
      region = rs.sel.value;
      try { history.replaceState(null, "", "#" + region); } catch (e) { location.hash = region; }
      load();
    });
    rc.appendChild(rs);
    app.appendChild(rc);
    var tabs = el("div", { class: "tabs", role: "tablist" }), panels = [];
    [["Index", panelIndex], ["Compare series", panelCompare], ["Credit health", panelCredit]].forEach(function (t, i) {
      var b = el("button", { role: "tab", "aria-selected": i === 0 ? "true" : "false" }, t[0]);
      var p = el("div", { role: "tabpanel" }); if (i) p.hidden = true;
      b.addEventListener("click", function () {
        tabs.querySelectorAll("[role=tab]").forEach(function (x) { x.setAttribute("aria-selected", "false"); });
        panels.forEach(function (x) { x.hidden = true; });
        b.setAttribute("aria-selected", "true"); p.hidden = false;
        if (!p.built) { t[1](p); p.built = true; }
      });
      tabs.appendChild(b); panels.push(p);
      if (i === 0) { t[1](p); p.built = true; }
    });
    app.appendChild(tabs); panels.forEach(function (p) { app.appendChild(p); });
  }
  function load() {
    fetch(REGIONS[region][1]).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { D = d; build(); })
    .catch(function () {
      app.innerHTML = '<p class="small">The data could not be loaded. If you opened this file directly from disk, ' +
        "please use a local web server (python -m http.server).</p>";
    });
  }
  load();
})();
