// Your tags: every word becomes a small black chip with a red round cross. Without scripts the plain field above still works.
// initTagField() can be called again after part of the page was replaced (see keepplaying.js). makeTagField() does the work for any
// wrapper and input (the selection bar on the library page uses it too) and returns { reset }.
function makeTagField(fld, store, entryId) {
  if (!fld || !store || store.type === "hidden") return null;
  var removeText = fld.dataset.remove, ph = store.getAttribute("placeholder") || "", tags = [], box = document.createElement("div"), entry = document.createElement("input");
  var CROSS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 7 7 17M7 7l10 10"/></svg>';
  function clean(w) { return w.trim().replace(/^#+/, "").toLowerCase().replace(/\s+/g, "-").slice(0, 40); }
  function sync() { store.value = tags.join(" "); }
  function draw() {
    box.querySelectorAll(".tagchip").forEach(function (c) { c.remove(); });
    entry.placeholder = tags.length ? "" : ph;
    tags.forEach(function (t) {
      var chip = document.createElement("span"), word = document.createElement("span"), x = document.createElement("button");
      chip.className = "tagchip"; word.textContent = t;
      x.type = "button"; x.innerHTML = CROSS; x.title = removeText.replace("{tag}", t); x.setAttribute("aria-label", x.title);
      x.addEventListener("click", function () { tags.splice(tags.indexOf(t), 1); sync(); draw(); entry.focus(); });
      chip.appendChild(word); chip.appendChild(x); box.insertBefore(chip, entry);
    });
  }
  function add(raw) {
    var added = false;
    raw.split(/[\s,]+/).forEach(function (w) { w = clean(w); if (w && tags.indexOf(w) < 0) { tags.push(w); added = true; } });
    if (added) { sync(); draw(); }
  }
  store.value.split(/\s+/).forEach(function (w) { w = clean(w); if (w && tags.indexOf(w) < 0) tags.push(w); });
  entry.type = "text"; entry.id = entryId; entry.className = "tag-entry"; entry.autocomplete = "off";
  box.className = "tagfield"; box.appendChild(entry);
  store.type = "hidden"; store.removeAttribute("placeholder");
  store.parentNode.insertBefore(box, store);
  fld.querySelector("label").htmlFor = entryId;
  box.addEventListener("click", function (e) { if (e.target === box) entry.focus(); });
  entry.addEventListener("keydown", function (e) {
    if ((e.key === " " || e.key === ",") && !entry.value.trim()) e.preventDefault();                     // no leading spaces
    else if ((e.key === " " || e.key === "," || e.key === "Enter") && entry.value.trim()) { e.preventDefault(); add(entry.value); entry.value = ""; }
    else if (e.key === "Backspace" && !entry.value && tags.length) { tags.pop(); sync(); draw(); }
  });
  entry.addEventListener("input", function () { if (/[\s,]/.test(entry.value.trim())) { add(entry.value); entry.value = ""; } });   // typing or pasting several words
  entry.addEventListener("blur", function () { if (entry.value.trim()) { add(entry.value); entry.value = ""; } });
  store.form.addEventListener("submit", function () { if (entry.value.trim()) { add(entry.value); entry.value = ""; } sync(); });
  sync(); draw();
  return { reset: function () { tags.length = 0; entry.value = ""; sync(); draw(); }, entry: entry };
}
function initTagField() { makeTagField(document.getElementById("tag-fld"), document.getElementById("tags-in"), "tag-entry"); }
initTagField();
