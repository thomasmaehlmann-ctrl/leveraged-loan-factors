/* loanfactors.org – Analysis page. No external libraries, no network requests except data/factors.json. */
(function () {
  "use strict";
  var D = null;                       // loaded data
  var SVGNS = "http://www.w3.org/2000/svg";
  var C = { ink: "#1A2E4A", gold: "#B8972A", slate: "#586273", rule: "#D9DFE7", grey: "#A9B1BD" };
  var $ = function (id) { return document.getElementById(id); };

  // ------------------------------------------------------------------ helpers
  function key(f, w, h, l, rt) { return f + "|" + w + "|" + h + "|" + l + "|" + rt; }
  function mkey(w, l, rt) { return "market|" + w + "|" + l + "|" + rt; }
  function ym(d) { return d.slice(0, 7); }
  function fmt(x, d) { return (x === null || !isFinite(x)) ? "–" : x.toFixed(d === undefined ? 2 : d); }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(SVGNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceTicks(lo, hi, n) {
    if (hi === lo) { hi = lo + 1; }
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n)));
    var err = span / n / step;
    if (err >= 7.5) step *= 10; else if (err >= 3.5) step *= 5; else if (err >= 1.5) step *= 2;
    var t = [], v = Math.ceil(lo / step) * step;
    for (; v <= hi + 1e-9; v += step) t.push(Math.round(v / step) * step);
    return t;
  }

  // indices of dates within [from, to] (YYYY-MM)
  function rangeIdx(from, to) {
    var idx = [];
    D.dates.forEach(function (d, i) { var m = ym(d); if (m >= from && m <= to) idx.push(i); });
    return idx;
  }

  // statistics of y (optionally regressed on x), monthly decimal returns
  function stats(y, x) {
    var ys = [], xs = [];
    for (var i = 0; i < y.length; i++) {
      if (y[i] === null || (x && x[i] === null)) continue;
      ys.push(y[i]); if (x) xs.push(x[i]);
    }
    var n = ys.length, r = { n: n };
    if (n < 6) return r;
    var my = ys.reduce(function (a, b) { return a + b; }, 0) / n;
    var vy = ys.reduce(function (a, b) { return a + (b - my) * (b - my); }, 0) / (n - 1);
    r.mean = my * 12 * 100; r.vol = Math.sqrt(vy * 12) * 100; r.sharpe = r.vol > 0 ? r.mean / r.vol : null;
    if (x) {
      var mx = xs.reduce(function (a, b) { return a + b; }, 0) / n, sxx = 0, sxy = 0;
      for (i = 0; i < n; i++) { sxx += (xs[i] - mx) * (xs[i] - mx); sxy += (xs[i] - mx) * (ys[i] - my); }
      var b = sxx > 0 ? sxy / sxx : 0, a = my - b * mx, ss = 0;
      for (i = 0; i < n; i++) { var e = ys[i] - a - b * xs[i]; ss += e * e; }
      var s2 = ss / (n - 2), se = Math.sqrt(s2 * (1 / n + mx * mx / sxx));
      r.alpha = a * 12 * 100; r.beta = b; r.t = se > 0 ? a / se : null;
      r.ir = s2 > 0 ? (a * 12) / Math.sqrt(s2 * 12) : null;
    }
    return r;
  }

  function cumulative(r) {
    var out = [], c = 1, started = false;
    for (var i = 0; i < r.length; i++) {
      if (r[i] !== null) { c *= 1 + r[i]; started = true; }
      out.push(started ? (c - 1) * 100 : null);
    }
    return out;
  }

  function subset(arr, idx) { return idx.map(function (i) { return arr ? arr[i] : null; }); }

  // series for the current view: returns {factor, compare, x (regressor), labels}
  function viewSeries(f, w, h, l, rt, view, idx) {
    var s = D.s[key(f, w, h, l, rt)] || {}, m = (D.s[mkey(w, l, rt)] || {}).MKT;
    var bm = subset(s.BM, idx);
    if (view === "longonly") {
      return { y: subset(s.PREF, idx), y2: bm, x: bm,
               labels: ["Preferred quintile", "Benchmark"], colors: [C.ink, C.grey] };
    }
    var ls = subset(s.LS, idx);
    if (view === "adjusted") {
      var st = stats(ls, bm), b = st.beta || 0;
      var adj = ls.map(function (v, i) { return (v === null || bm[i] === null) ? null : v - b * bm[i]; });
      return { y: adj, y2: subset(m, idx), x: bm,
               labels: ["Long-short, benchmark-adjusted", "Market index"], colors: [C.ink, C.grey] };
    }
    return { y: ls, y2: subset(m, idx), x: bm, labels: ["Long-short", "Market index"], colors: [C.ink, C.grey] };
  }

  // ------------------------------------------------------------------ line chart
  function lineChart(box, dates, lines, labels, colors) {
    box.innerHTML = "";
    var W = box.clientWidth || 800, H = Math.max(260, Math.min(420, W * 0.5));
    var m = { l: 52, r: 16, t: 16, b: 34 }, w = W - m.l - m.r, h = H - m.t - m.b;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img",
                          "aria-label": "Cumulative return chart" }, box);
    var vals = [];
    lines.forEach(function (ln) { ln.forEach(function (v) { if (v !== null) vals.push(v); }); });
    if (!vals.length) { var t = el("text", { x: W / 2, y: H / 2, "text-anchor": "middle", fill: C.slate }, svg);
                        t.textContent = "No data for this selection and period."; return; }
    var lo = Math.min(0, Math.min.apply(null, vals)), hi = Math.max(0, Math.max.apply(null, vals));
    var pad = (hi - lo) * 0.06 || 1; lo -= pad; hi += pad;
    var X = function (i) { return m.l + (dates.length < 2 ? 0 : i / (dates.length - 1) * w); };
    var Y = function (v) { return m.t + (hi - v) / (hi - lo) * h; };
    niceTicks(lo, hi, 5).forEach(function (v) {
      el("line", { x1: m.l, x2: m.l + w, y1: Y(v), y2: Y(v), stroke: v === 0 ? C.slate : C.rule,
                   "stroke-width": v === 0 ? 1 : 0.8 }, svg);
      var tx = el("text", { x: m.l - 8, y: Y(v) + 4, "text-anchor": "end", "font-size": 12, fill: C.slate }, svg);
      tx.textContent = v + "%";
    });
    var lastYear = null, lastX = -1e9;
    dates.forEach(function (d, i) {
      var yr = d.slice(0, 4);
      if (d.slice(5, 7) === "01" || (i === 0 && dates.length < 13)) {
        if (yr !== lastYear && X(i) - lastX >= 44) {
          lastX = X(i);
          var tx = el("text", { x: X(i), y: H - 10, "text-anchor": "middle", "font-size": 12, fill: C.slate }, svg);
          tx.textContent = yr; lastYear = yr;
        }
      }
    });
    lines.slice().reverse().forEach(function (ln, jr) {
      var j = lines.length - 1 - jr, dstr = "", pen = false;
      ln.forEach(function (v, i) {
        if (v === null) { pen = false; return; }
        dstr += (pen ? "L" : "M") + X(i).toFixed(1) + "," + Y(v).toFixed(1); pen = true;
      });
      el("path", { d: dstr, fill: "none", stroke: colors[j], "stroke-width": j === 0 ? 2.2 : 2.6,
                   "stroke-opacity": j === 0 ? 1 : 0.7, "stroke-linejoin": "round" }, svg);
    });
    // hover
    var guide = el("line", { y1: m.t, y2: m.t + h, stroke: C.slate, "stroke-width": 0.8, visibility: "hidden" }, svg);
    var tip = document.createElement("div"); tip.className = "chart-tip"; tip.hidden = true; box.appendChild(tip);
    var overlay = el("rect", { x: m.l, y: m.t, width: w, height: h, fill: "transparent" }, svg);
    function move(ev) {
      var r = svg.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
      var i = Math.round((px - m.l) / w * (dates.length - 1)); i = Math.max(0, Math.min(dates.length - 1, i));
      guide.setAttribute("x1", X(i)); guide.setAttribute("x2", X(i)); guide.setAttribute("visibility", "visible");
      var html = "<b>" + ym(dates[i]) + "</b>";
      lines.forEach(function (ln, j) { html += "<br><span style='color:" + colors[j] + "'>●</span> " + labels[j] + ": " + fmt(ln[i], 1) + "%"; });
      tip.innerHTML = html; tip.hidden = false;
      var left = X(i) / W * r.width; tip.style.left = Math.min(left + 12, r.width - 220) + "px"; tip.style.top = "8px";
    }
    overlay.addEventListener("mousemove", move);
    overlay.addEventListener("mouseleave", function () { guide.setAttribute("visibility", "hidden"); tip.hidden = true; });
  }

  // ------------------------------------------------------------------ bar chart
  function barChart(box, items, unit) {
    box.innerHTML = "";
    var W = box.clientWidth || 800, rowH = 34, m = { l: 130, r: 70, t: 8, b: 8 };
    var H = m.t + m.b + rowH * items.length, w = W - m.l - m.r;
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, role: "img",
                          "aria-label": "Factor comparison chart" }, box);
    var vals = items.filter(function (it) { return it.v !== null && isFinite(it.v); }).map(function (it) { return it.v; });
    var lo = Math.min(0, Math.min.apply(null, vals.concat([0]))), hi = Math.max(0, Math.max.apply(null, vals.concat([0])));
    if (hi === lo) hi = lo + 1;
    var span = hi - lo; if (lo < 0) lo -= span * 0.12; if (hi > 0) hi += span * 0.12;   // room for value labels
    var X = function (v) { return m.l + (v - lo) / (hi - lo) * w; };
    el("line", { x1: X(0), x2: X(0), y1: m.t, y2: H - m.b, stroke: C.slate, "stroke-width": 1 }, svg);
    items.forEach(function (it, k) {
      var y = m.t + k * rowH;
      var lab = el("text", { x: m.l - 10, y: y + rowH / 2 + 4, "text-anchor": "end", "font-size": 13, fill: C.ink }, svg);
      lab.textContent = it.name;
      if (it.v === null || !isFinite(it.v)) {
        var na = el("text", { x: X(0) + 6, y: y + rowH / 2 + 4, "font-size": 12, fill: C.slate }, svg);
        na.textContent = "no data in period"; return;
      }
      var x0 = X(Math.min(0, it.v)), x1 = X(Math.max(0, it.v));
      el("rect", { x: x0, y: y + 6, width: Math.max(1, x1 - x0), height: rowH - 12,
                   fill: it.v >= 0 ? C.ink : C.grey }, svg);
      var vt = el("text", { x: it.v >= 0 ? x1 + 6 : x0 - 6, y: y + rowH / 2 + 4,
                            "text-anchor": it.v >= 0 ? "start" : "end", "font-size": 12, fill: C.slate }, svg);
      vt.textContent = fmt(it.v, 2) + unit;
    });
  }

  // ------------------------------------------------------------------ performance tab
  function readSpec(prefix) {
    return { w: $(prefix + "-w").value, h: $(prefix + "-h").value, l: $(prefix + "-l").value,
             rt: $(prefix + "-rt").value, view: $(prefix + "-view").value,
             from: $(prefix + "-from").value, to: $(prefix + "-to").value };
  }
  function shiftMonths(m, k) { var y = +m.slice(0, 4), mo = +m.slice(5, 7) - 1 + k;
    y += Math.floor(mo / 12); mo = ((mo % 12) + 12) % 12; return y + "-" + String(mo + 1).padStart(2, "0"); }

  function renderPerf() {
    var sp = readSpec("p"), f = $("p-factor").value;
    var idx = rangeIdx(sp.from, sp.to), dates = idx.map(function (i) { return D.dates[i]; });
    var v = viewSeries(f, sp.w, sp.h, sp.l, sp.rt, sp.view, idx);
    lineChart($("p-chart"), dates, [cumulative(v.y), cumulative(v.y2)], v.labels, v.colors);
    $("p-legend").innerHTML = v.labels.map(function (lb, j) {
      return "<span><i style='background:" + v.colors[j] + "'></i>" + lb + "</span>"; }).join("");
    // statistics: last 12 months, last 36 months, selected period (all ending at 'to')
    var cols = [["Last year", shiftMonths(sp.to, -11)], ["Last 3 years", shiftMonths(sp.to, -35)], ["Selected period", sp.from]];
    var res = cols.map(function (c) {
      var ix = rangeIdx(c[1], sp.to), vv = viewSeries(f, sp.w, sp.h, sp.l, sp.rt, sp.view, ix);
      return stats(vv.y, vv.x);
    });
    var rows = [["Average return (ann. %)", "mean", 2], ["Volatility (ann. %)", "vol", 2], ["Sharpe ratio", "sharpe", 2],
                ["Alpha vs. benchmark (ann. %)", "alpha", 2], ["t-stat of alpha", "t", 2],
                ["Beta vs. benchmark", "beta", 2], ["Information ratio", "ir", 2], ["Months", "n", 0]];
    var html = "<thead><tr><th>Statistic</th>" + cols.map(function (c) { return "<th>" + c[0] + "</th>"; }).join("") + "</tr></thead><tbody>";
    rows.forEach(function (r) {
      html += "<tr><td>" + r[0] + "</td>" + res.map(function (s) {
        var x = s[r[1]]; return "<td>" + (x === undefined ? "–" : fmt(x, r[2])) + "</td>"; }).join("") + "</tr>";
    });
    $("p-table").innerHTML = html + "</tbody>";
  }

  // ------------------------------------------------------------------ comparison tab
  function renderComp() {
    var sp = readSpec("c"), metric = $("c-metric").value, idx = rangeIdx(sp.from, sp.to);
    var unit = { mean: "%", sharpe: "", alpha: "%", t: "" }[metric];
    var items = D.factors.map(function (fc) {
      var vv = viewSeries(fc.code, sp.w, sp.h, sp.l, sp.rt, sp.view, idx), st = stats(vv.y, vv.x);
      return { name: fc.name, v: st[metric] === undefined ? null : st[metric], n: st.n };
    });
    items.sort(function (a, b) { return (b.v === null ? -1e9 : b.v) - (a.v === null ? -1e9 : a.v); });
    barChart($("c-chart"), items, unit);
  }

  // ------------------------------------------------------------------ setup
  function fillMonths() {
    var first = ym(D.dates[0]), last = ym(D.dates[D.dates.length - 1]);
    ["p", "c"].forEach(function (p) {
      [p + "-from", p + "-to"].forEach(function (id) { $(id).min = first; $(id).max = last; });
      $(p + "-from").value = first; $(p + "-to").value = last;
    });
  }
  function quick(prefix, months, render) {
    var last = ym(D.dates[D.dates.length - 1]), first = ym(D.dates[0]);
    $(prefix + "-to").value = last;
    $(prefix + "-from").value = months ? (shiftMonths(last, -(months - 1)) < first ? first : shiftMonths(last, -(months - 1))) : first;
    render();
  }
  function tabs() {
    document.querySelectorAll("[role=tab]").forEach(function (t) {
      t.addEventListener("click", function () {
        document.querySelectorAll("[role=tab]").forEach(function (o) {
          o.setAttribute("aria-selected", o === t ? "true" : "false");
          $(o.getAttribute("aria-controls")).hidden = o !== t;
        });
        if (!D) return;
        if (t.id === "tab-comp") renderComp(); else renderPerf();
      });
    });
  }

  function init(data) {
    D = data;
    var sel = $("p-factor");
    D.factors.forEach(function (fc) { var o = document.createElement("option"); o.value = fc.code; o.textContent = fc.name; sel.appendChild(o); });
    sel.value = "momentum";
    fillMonths();
    document.querySelectorAll("#panel-perf select, #panel-perf input").forEach(function (e) { e.addEventListener("change", renderPerf); });
    document.querySelectorAll("#panel-comp select, #panel-comp input").forEach(function (e) { e.addEventListener("change", renderComp); });
    document.querySelectorAll("[data-quick]").forEach(function (b) {
      b.addEventListener("click", function () {
        var p = b.getAttribute("data-panel"); quick(p, +b.getAttribute("data-quick"), p === "p" ? renderPerf : renderComp);
      });
    });
    var t; window.addEventListener("resize", function () { clearTimeout(t); t = setTimeout(function () {
      if (!$("panel-perf").hidden) renderPerf(); else renderComp(); }, 150); });
    $("a-version").textContent = "Data release v" + D.version + ", " + ym(D.dates[0]) + " to " + ym(D.dates[D.dates.length - 1]) + ".";
    renderPerf();
  }

  tabs();
  var fail = "The data could not be loaded. Please try again later.";
  if (location.protocol === "file:") fail = "The data cannot be loaded when the page is opened as a local file. " +
    "Start a local web server in the site folder (python -m http.server) and open http://localhost:8000/analysis.html.";
  fetch("data/factors.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(init)
    .catch(function () { $("p-chart").textContent = fail; $("c-chart").textContent = fail; });
})();
