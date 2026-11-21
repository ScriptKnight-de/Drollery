// A visible "working" signal. A lookup asks another website and can take many seconds, and until the answer arrives the
// browser keeps showing the old page, so nothing seems to happen. Forms and links marked data-busy="message" put a
// spinner card with that message over the page as soon as they are used; after a few seconds it also counts the seconds.
(function () {
  var text = {};
  try { text = JSON.parse(document.getElementById("busy-text").textContent); } catch (e) {}
  var node = null, timer = null, started = 0;

  function el(tag, cls, content) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (content) e.textContent = content;
    return e;
  }
  function hide() {
    if (timer) clearInterval(timer);
    timer = null;
    if (node) node.remove();
    node = null;
    document.documentElement.removeAttribute("aria-busy");
  }
  function show(message, host) {
    hide();
    node = el("div", "busy" + (host ? " in-dialog" : ""));
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    var card = el("div", "busy-card"), msg = el("p", "busy-msg", message || text.loading || ""), hint = el("p", "busy-hint muted small", text.hint || ""), time = el("p", "busy-time muted small", "");
    card.appendChild(el("span", "busy-spin"));
    card.appendChild(msg); card.appendChild(hint); card.appendChild(time);
    node.appendChild(card);
    (host || document.body).appendChild(node);
    document.documentElement.setAttribute("aria-busy", "true");
    started = Date.now();
    timer = setInterval(function () {
      var s = Math.round((Date.now() - started) / 1000);
      time.textContent = s >= 2 ? (text.sec || "{n} s").replace("{n}", s) : "";
      if (s >= 10 && text.slow) hint.textContent = text.slow;
    }, 500);
  }
  window.drolleryBusy = { show: show, hide: hide };

  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (!f.hasAttribute || !f.hasAttribute("data-busy") || e.defaultPrevented) return;      // a confirmation box that was not answered yet
    show(f.getAttribute("data-busy"));
  });
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[data-busy]");
    if (!a || a.hasAttribute("data-popup") || e.defaultPrevented || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || a.target === "_blank") return;
    show(a.getAttribute("data-busy"));
  });
  window.addEventListener("pageshow", function (e) { if (e.persisted) hide(); });          // back to a page kept by the browser: no stale spinner
})();
