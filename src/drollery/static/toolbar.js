// The "Background jobs" button folds the panel below the toolbar open and shut. Delegated, so it keeps working
// after keepplaying.js swaps the side column.
document.addEventListener("click", function (e) {
  var b = e.target.closest && e.target.closest("[data-toggle]");
  if (!b) return;
  var p = document.getElementById(b.dataset.toggle);
  if (!p) return;
  p.hidden = !p.hidden;
  b.setAttribute("aria-expanded", String(!p.hidden));
});
