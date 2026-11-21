// Sound cards: the big round button on a card plays the sound right there, one sound at a time. The title under it
// still opens the item. Delegated, so cards that arrive later (search, more pages) work too.
(function () {
  var audio = new Audio(), current = null;
  audio.preload = "none";

  function buttons() { return document.querySelectorAll(".sound-play"); }
  function paint() {
    buttons().forEach(function (b) {
      var mine = current && b.dataset.src === current;
      var playing = mine && !audio.paused;
      b.setAttribute("aria-pressed", String(!!playing));
      b.classList.toggle("on", !!mine);
      b.classList.toggle("playing", !!playing);
      if (!mine) b.style.setProperty("--p", "0");
    });
  }
  function progress() {
    if (!current || !audio.duration) return;
    var pct = Math.min(100, (audio.currentTime / audio.duration) * 100);
    buttons().forEach(function (b) { if (b.dataset.src === current) b.style.setProperty("--p", pct.toFixed(1)); });
  }

  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest(".sound-play");
    if (!b) return;
    e.preventDefault();
    if (current === b.dataset.src && !audio.ended) {
      if (audio.paused) audio.play(); else audio.pause();
    } else {
      current = b.dataset.src;
      audio.src = current;
      audio.currentTime = 0;
      audio.play();
    }
    paint();
  });

  audio.addEventListener("play", paint);
  audio.addEventListener("pause", paint);
  audio.addEventListener("timeupdate", progress);
  audio.addEventListener("ended", function () { buttons().forEach(function (b) { b.style.setProperty("--p", "0"); }); paint(); });
  audio.addEventListener("error", function () { current = null; paint(); });
  document.body.addEventListener("htmx:afterSwap", paint);     // a search or another page of cards replaced the buttons
})();
