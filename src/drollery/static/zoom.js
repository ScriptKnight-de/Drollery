// A bigger view of a picture or a video, in a window of its own.
//  - a picture on a page opens full size in the window; a click on it switches between "fits the screen" and "real size"
//    (then the window scrolls)
//  - the Enlarge button of a video moves the player itself into the window, so it plays on where it was and goes back when
//    the window closes
(function () {
  var dlg = document.getElementById("zoom-dialog");
  if (!dlg || !dlg.showModal) return;
  var stage = dlg.querySelector(".bigview-stage"), moved = null;

  function open(node) {
    stage.textContent = "";
    stage.appendChild(node);
    stage.scrollTo(0, 0);
    dlg.showModal();
  }

  document.addEventListener("click", function (e) {
    if (e.defaultPrevented) return;
    var close = e.target.closest("[data-zoom-close]");
    if (close) { dlg.close(); return; }
    var full = e.target.closest(".bigview-stage img");
    if (full) { full.classList.toggle("full"); return; }
    var img = e.target.closest(".frame img");
    if (img) {
      var big = document.createElement("img");
      big.src = img.currentSrc || img.src;
      big.alt = img.alt;
      open(big);
      return;
    }
    var button = e.target.closest("[data-enlarge]");
    var video = button && button.parentNode.querySelector("video");
    if (video) {
      moved = { video: video, mark: document.createComment("player") };
      video.parentNode.insertBefore(moved.mark, video);
      open(video);
      video.focus();
    }
  });

  dlg.addEventListener("close", function () {
    if (moved) {                                                   // the player goes back where it was, still playing if it was
      moved.mark.parentNode.insertBefore(moved.video, moved.mark);
      moved.mark.remove();
      moved = null;
    }
    stage.textContent = "";
  });
})();
