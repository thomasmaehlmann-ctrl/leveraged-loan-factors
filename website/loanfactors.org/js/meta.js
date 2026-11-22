/* loanfactors.org – fills release information (version, sample period, DOI) from data/meta.json.
   Elements: <span data-meta="key">fallback</span>; links with data-meta-href="doi" get the DOI URL. */
(function () {
  "use strict";
  fetch("data/meta.json").then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
    .then(function (m) {
      document.querySelectorAll("[data-meta]").forEach(function (el) {
        var v = m[el.getAttribute("data-meta")];
        if (v) el.textContent = v;
      });
      document.querySelectorAll("[data-meta-href=doi]").forEach(function (a) {
        if (m.doi) a.href = "https://doi.org/" + m.doi;
      });
      document.querySelectorAll("[data-meta-href=files_csv]").forEach(function (a) {
        if (m.files_csv) a.href = m.files_csv;
      });
    })
    .catch(function () { /* keep the fallback text */ });
})();
