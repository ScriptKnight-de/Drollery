// The search, the filters and the sort order stay in the address bar while you change them (without piling up history
// entries), so a reload, a bookmark or the back button brings the same view back.
(function () {
  var form = document.querySelector("form.toolbar");
  if (!form || !window.history || !history.replaceState) return;
  function sync() {
    var params = new URLSearchParams();
    new FormData(form).forEach(function (value, key) { if (value !== "") params.append(key, value); });
    var query = params.toString();
    history.replaceState(null, "", location.pathname + (query ? "?" + query : ""));
  }
  form.addEventListener("input", sync);
  form.addEventListener("change", sync);
})();
