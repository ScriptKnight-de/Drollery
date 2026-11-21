// Saving on an item or album page must not interrupt what is playing. A reload would stop it, so forms in the right-hand
// column (#side) are sent in the background and only that column is replaced with the server's new version; the player
// and the track list on the left are never touched. A form with data-reload (delete) behaves normally, and anything
// unexpected falls back to a normal page load, so the page can never show something other than what the server holds.
(function () {
  var side = document.getElementById("side");
  if (!side || !window.fetch || !window.DOMParser) return;

  function replaceFlash(doc) {
    var main = document.querySelector("main");
    var old = main.querySelector(":scope > .note");
    if (old) old.remove();
    var fresh = doc.querySelector("main > .note");
    if (fresh) main.insertBefore(document.importNode(fresh, true), main.firstChild);
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (e.defaultPrevented || !side.contains(form) || form.hasAttribute("data-reload") || String(form.method).toLowerCase() !== "post") return;
    e.preventDefault();
    var data = new FormData(form);
    if (e.submitter && e.submitter.name) data.append(e.submitter.name, e.submitter.value);
    var buttons = form.querySelectorAll("button[type=submit]");
    buttons.forEach(function (b) { b.disabled = true; });
    fetch(form.action, { method: "POST", body: data, credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("status " + r.status);
      return r.text().then(function (html) { return { html: html, url: r.url }; });
    }).then(function (res) {
      var doc = new DOMParser().parseFromString(res.html, "text/html"), fresh = doc.getElementById("side");
      if (!fresh || new URL(res.url).pathname !== location.pathname) { location.href = res.url; return; }   // sent elsewhere, e.g. to sign in again
      side.innerHTML = fresh.innerHTML;
      try { sessionStorage.removeItem("drollery.scroll"); } catch (err) {}      // the page did not reload, so no scroll position is waiting for it
      document.title = doc.title;
      replaceFlash(doc);
      if (window.initTagField) window.initTagField();
      if (window.initSharePanel) window.initSharePanel();
    }).catch(function () { location.reload(); });
  });
})();
