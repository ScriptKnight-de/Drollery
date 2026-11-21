// The share panel: the "custom" duration fields, and the share buttons on track rows that pick that track in the panel.
(function () {
  var sel = document.getElementById("sh-preset"), box = document.getElementById("sh-custom");
  if (sel && box) { var sync = function () { box.hidden = sel.value !== "custom"; }; sel.addEventListener("change", sync); sync(); }
  var what = document.getElementById("sh-track");
  document.querySelectorAll("[data-share-track]").forEach(function (b) {
    b.addEventListener("click", function () {
      if (what) what.value = b.dataset.shareTrack;
      var panel = document.getElementById("share");
      if (panel) { panel.scrollIntoView({ behavior: "smooth", block: "start" }); if (what) what.focus({ preventScroll: true }); }
    });
  });
})();
