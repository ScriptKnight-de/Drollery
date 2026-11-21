// Plays the tracks of an album one after another. Needs #player (audio), #now and #tracklist with [data-track] rows.
(function () {
  var audio = document.getElementById("player"), now = document.getElementById("now");
  if (!audio || !now) return;
  var label = now.dataset.label || "", rows = Array.prototype.slice.call(document.querySelectorAll("#tracklist [data-track]")), cur = -1;
  function mark() {
    rows.forEach(function (r, k) {
      r.classList.toggle("playing", k === cur);
      r.querySelector(".play").setAttribute("aria-pressed", String(k === cur && !audio.paused));
    });
    now.textContent = "";
    if (cur >= 0) { var b = document.createElement("b"); b.textContent = rows[cur].dataset.title; now.append(label + ": ", b); }
  }
  function start(i) { if (i < 0 || i >= rows.length) return; cur = i; audio.src = rows[i].dataset.src; audio.play(); mark(); }
  rows.forEach(function (r, i) {
    r.querySelector(".play").addEventListener("click", function () {
      if (i !== cur) start(i); else if (audio.paused) audio.play(); else audio.pause();
    });
  });
  audio.addEventListener("play", mark); audio.addEventListener("pause", mark);
  audio.addEventListener("ended", function () { if (cur + 1 < rows.length) start(cur + 1); else mark(); });
})();
