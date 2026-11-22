// The player's shape comes from the film itself: once the browser knows the real size (it also knows about a turned
// phone video), the page's guess from the stored size is corrected, so the frame never changes shape when it plays.
(function () {
  Array.prototype.forEach.call(document.querySelectorAll(".frame video"), function (v) {
    function fit() { if (v.videoWidth && v.videoHeight) v.style.setProperty("--ar", (v.videoWidth / v.videoHeight).toFixed(4)); }
    if (v.readyState >= 1) fit();
    v.addEventListener("loadedmetadata", fit);
  });
})();
