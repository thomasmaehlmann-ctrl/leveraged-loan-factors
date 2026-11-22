/* loanfactors.org – "Factors to watch" on the homepage. Loads only data/leaderboard.json. */
(function () {
  "use strict";
  var box = document.getElementById("ftw-table"), period = document.getElementById("ftw-period");
  if (!box) return;
  function fmt(x) { return (x === null || x === undefined || !isFinite(x)) ? "–" : x.toFixed(2); }
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function label(ym) { return months[+ym.slice(5, 7) - 1] + " " + ym.slice(0, 4); }
  fetch("data/leaderboard.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (d) {
      period.textContent = label(d.start) + " to " + label(d.end);
      var html = "<thead><tr><th>Rank</th><th>Factor</th><th>Alpha (ann. %)</th><th>t-stat</th><th>Information ratio</th></tr></thead><tbody>";
      d.rows.forEach(function (r, i) {
        html += "<tr><td>" + (i + 1) + "</td><td>" + r.name + "</td><td>" + fmt(r.alpha) + "</td><td>" +
                fmt(r.t) + "</td><td>" + fmt(r.ir) + "</td></tr>";
      });
      box.innerHTML = html + "</tbody>";
    })
    .catch(function () { box.innerHTML = "<tbody><tr><td>The current figures could not be loaded.</td></tr></tbody>"; });
})();
