// The player's shape comes from the film itself: once the browser knows the real size (it also knows about a turned
// phone video), the page's guess from the stored size is corrected, so the frame never changes shape when it plays.
// A film whose picture the browser cannot decode (a codec it lacks) still plays its sound and keeps showing the preview
// picture. That is said out loud instead of leaving the person to wonder.
(function () {
  Array.prototype.forEach.call(document.querySelectorAll(".frame video"), function (v) {
    function fit() {
      if (v.videoWidth && v.videoHeight) v.style.setProperty("--ar", (v.videoWidth / v.videoHeight).toFixed(4));
      else if (v.readyState >= 1 && v.dataset.nopicture && !document.querySelector(".video-problem")) {
        var note = document.createElement("p");
        note.className = "note error video-problem";
        note.setAttribute("role", "status");
        note.textContent = v.dataset.nopicture;
        v.closest(".frame").insertAdjacentElement("afterend", note);
      }
    }
    if (v.readyState >= 1) fit();
    v.addEventListener("loadedmetadata", fit);
  });
})();
