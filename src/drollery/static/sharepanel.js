// The share panel: the "custom" duration fields, and the share buttons on track rows that pick that track in the panel.
// Everything looks the elements up when it is needed, so the panel can be replaced (see keepplaying.js).
(function () {
  function sync() {
    var sel = document.getElementById("sh-preset"), box = document.getElementById("sh-custom");
    if (sel && box) box.hidden = sel.value !== "custom";
  }
  document.addEventListener("change", function (e) { if (e.target && e.target.id === "sh-preset") sync(); });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-share-track]");
    if (!b) return;
    var what = document.getElementById("sh-track"), panel = document.getElementById("share");
    if (what) what.value = b.dataset.shareTrack;
    if (panel) { panel.scrollIntoView({ behavior: "smooth", block: "start" }); if (what) what.focus({ preventScroll: true }); }
  });
  window.initSharePanel = sync;
  sync();
})();
