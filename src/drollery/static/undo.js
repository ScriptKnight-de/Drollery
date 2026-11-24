// The Undo button that comes with a deleted item goes away after a minute, the time the server keeps it (trash.py).
(function () {
  var form = document.querySelector("form[data-undo]");
  if (form) setTimeout(function () { form.remove(); }, 60000);
})();
