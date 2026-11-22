// A GIF on a tile shows its still frame and plays while the pointer is on the tile (or the tile has the keyboard focus).
// The file of the GIF is only fetched then. People whose system asks for less motion keep the still frame.
(function () {
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  function picture(e) { var tile = e.target.closest && e.target.closest(".tile"); return tile && tile.querySelector("img[data-play]"); }
  function play(e) {
    var img = picture(e);
    if (!img || (calm && calm.matches) || img.dataset.still) return;
    img.dataset.still = img.getAttribute("src");
    img.src = img.dataset.play;
  }
  function stop(e) {
    var img = picture(e);
    if (!img || !img.dataset.still) return;
    var tile = img.closest(".tile");
    if (e.relatedTarget && tile.contains(e.relatedTarget)) return;            // moving inside the tile is not leaving it
    img.src = img.dataset.still;
    delete img.dataset.still;
  }
  document.addEventListener("mouseover", play);
  document.addEventListener("mouseout", stop);
  document.addEventListener("focusin", play);
  document.addEventListener("focusout", stop);
})();
