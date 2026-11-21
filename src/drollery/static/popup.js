// Links marked data-popup open in a window on top of the page instead of leaving it. The page inside is the normal
// page, shown without the header (the server notices it is framed). When it ends up back on the item, the window
// closes and this page reloads to show what changed.
(function () {
  var dlg = document.getElementById("popup-dialog");
  if (!dlg || !dlg.showModal) return;
  var frame = document.getElementById("pp-frame"), title = document.getElementById("pp-title");

  function mark(on) { document.cookie = "drollery_embed=" + (on ? "1" : "") + "; path=/; SameSite=Lax" + (on ? "" : "; max-age=0"); }
  mark(false);

  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("[data-popup]");
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.button === 0) {
      e.preventDefault();
      title.textContent = link.dataset.popup;
      frame.title = link.dataset.popup;
      mark(true);
      frame.src = link.href;
      dlg.showModal();
      if (window.drolleryBusy) window.drolleryBusy.show(link.dataset.busy || dlg.dataset.loading, dlg);      // until the page inside has arrived
      return;
    }
    if (e.target === dlg || (e.target.closest && e.target.closest("[data-close]") && dlg.contains(e.target))) dlg.close();
  });
  frame.addEventListener("load", function () {
    if (frame.getAttribute("src") !== "about:blank" && window.drolleryBusy) window.drolleryBusy.hide();
  });
  dlg.addEventListener("close", function () { mark(false); if (window.drolleryBusy) window.drolleryBusy.hide(); frame.src = "about:blank"; });
  window.addEventListener("message", function (e) {
    if (e.origin !== location.origin || e.source !== frame.contentWindow || e.data !== "drollery-done") return;
    mark(false);
    location.reload();
  });
})();
