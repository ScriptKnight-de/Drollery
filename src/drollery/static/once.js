// A second click or Enter on a form that is already on its way must not send it again (two people, two albums, two uploads).
// The page is replaced when the answer comes, so the guard only has to hold for a few seconds; forms that htmx sends are left alone.
(function () {
  var sent = new WeakMap();
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || form.tagName !== "FORM" || (form.method || "").toLowerCase() !== "post") return;
    if (form.hasAttribute("hx-post") || form.hasAttribute("data-reload") || form.hasAttribute("data-many")) return;
    var now = Date.now();
    if (sent.has(form) && now - sent.get(form) < 5000) { e.preventDefault(); return; }
    setTimeout(function () { if (!e.defaultPrevented) sent.set(form, Date.now()); }, 0);
  }, false);
  window.addEventListener("pageshow", function () { sent = new WeakMap(); });      // back button: the form is usable again
})();
