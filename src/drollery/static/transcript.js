// The transcript button on a track row opens a popup with what is said in that track. The text is fetched when it is
// needed, so the page does not carry every transcript, and the words that were searched for are marked.
(function () {
  var dlg = document.getElementById("transcript-dialog");
  if (!dlg || !dlg.showModal) return;
  var title = document.getElementById("tr-title"), body = document.getElementById("tr-text"), copy = document.getElementById("tr-copy");

  function show(trackId) {
    title.textContent = "";
    body.textContent = "…";
    copy.dataset.copy = "";
    copy.hidden = true;
    if (!dlg.open) dlg.showModal();
    var url = "/albums/" + dlg.dataset.item + "/track/" + trackId + "/transcript?q=" + encodeURIComponent(dlg.dataset.q || "");
    fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error(String(r.status));
      return r.json();
    }).then(function (d) {
      title.textContent = d.title;
      if (d.text) { body.innerHTML = d.html; copy.dataset.copy = d.text; copy.hidden = false; }      // html is escaped by the server
      else body.textContent = dlg.dataset.empty;
      body.scrollTop = 0;
      var first = body.querySelector("mark");
      if (first) first.scrollIntoView({ block: "center" });
    }).catch(function () { body.textContent = dlg.dataset.error; });
  }

  var nativeLightDismiss = "closedBy" in HTMLDialogElement.prototype;      // the dialog has closedby="any"; older browsers need the script for the backdrop
  document.addEventListener("click", function (e) {
    var open = e.target.closest && e.target.closest("[data-transcript]");
    if (open) { show(open.dataset.transcript); return; }
    if ((!nativeLightDismiss && e.target === dlg) || (e.target.closest && e.target.closest("[data-close]") && dlg.contains(e.target))) dlg.close();   // the backdrop or the close button
  });
})();
