// Selecting several tiles of the library and doing one thing to all of them.
// "Select" switches the mode on: a click on a tile then marks it instead of opening it (Shift marks a range, Space or Enter
// on a focused tile marks it, Esc leaves the mode). A bar at the bottom shows the count and the actions. The page without
// this script is the same page with links: nothing here is needed to use the library.
(function () {
  var toggle = document.getElementById("select-toggle"), bar = document.getElementById("bulkbar"), grid = document.getElementById("grid");
  if (!toggle || !bar || !grid) return;
  var form = document.getElementById("bulk-form"), params = document.getElementById("bulk-params");
  var selected = new Set(), last = null, on = false;

  function tiles() { return Array.prototype.slice.call(grid.querySelectorAll(".tile[data-id]")); }
  function fill(template, values) { return template.replace(/\{(\w+)\}/g, function (m, k) { return k in values ? values[k] : m; }); }

  function paint() {
    var shown = 0;
    tiles().forEach(function (t) {
      var is = selected.has(t.dataset.id);
      t.classList.toggle("selected", is);
      if (on) { t.setAttribute("role", "checkbox"); t.setAttribute("aria-checked", String(is)); }
      else { t.removeAttribute("role"); t.removeAttribute("aria-checked"); }
      if (is) shown++;
    });
    var text = selected.size === shown ? bar.dataset.count : bar.dataset.shown;      // some chosen tiles may be filtered out of view
    document.getElementById("bulk-count").textContent = fill(text, { n: selected.size, m: shown });
    Array.prototype.forEach.call(bar.querySelectorAll("[data-bulk]"), function (b) { b.disabled = selected.size === 0; });
    document.getElementById("bulk-none").disabled = selected.size === 0;
  }

  function mode(next) {
    on = next;
    document.body.classList.toggle("selecting", on);
    toggle.setAttribute("aria-pressed", String(on));
    bar.hidden = !on;
    if (!on) { selected.clear(); last = null; closeParams(); }
    paint();
  }

  function mark(tile, shift) {
    var id = tile.dataset.id, all = tiles();
    if (shift && last && last !== id) {                                  // a range, in the order the tiles are on the page
      var a = all.findIndex(function (t) { return t.dataset.id === last; }), b = all.indexOf(tile);
      if (a >= 0 && b >= 0) { all.slice(Math.min(a, b), Math.max(a, b) + 1).forEach(function (t) { selected.add(t.dataset.id); }); paint(); return; }
    }
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    last = id;
    paint();
  }

  function closeParams() {
    params.hidden = true;
    Array.prototype.forEach.call(params.querySelectorAll("label[data-for]"), function (l) { l.hidden = true; });
    Array.prototype.forEach.call(params.querySelectorAll("input[name=tags], select[name=person_id]"), function (f) { f.required = false; });
  }

  function openParams(action) {
    closeParams();
    form.elements.action.value = action;
    Array.prototype.forEach.call(params.querySelectorAll("label[data-for]"), function (l) { l.hidden = l.dataset.for.split(" ").indexOf(action) < 0; });
    form.elements.tags.required = action === "tag_add" || action === "tag_remove";
    form.elements.person_id.required = action === "person_add" || action === "person_remove";
    params.hidden = false;
    var field = params.querySelector("label:not([hidden]) input, label:not([hidden]) select");
    if (field) field.focus();
  }

  toggle.addEventListener("click", function () { mode(!on); });
  document.getElementById("bulk-done").addEventListener("click", function () { mode(false); });
  document.getElementById("bulk-none").addEventListener("click", function () { selected.clear(); last = null; paint(); });
  document.getElementById("bulk-all").addEventListener("click", function () { tiles().forEach(function (t) { selected.add(t.dataset.id); }); paint(); });
  document.getElementById("bulk-cancel").addEventListener("click", closeParams);

  bar.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-bulk]");
    if (!b || !selected.size) return;
    var action = b.dataset.bulk;
    if (action === "delete") {
      closeParams();
      form.elements.action.value = "delete";
      form.dataset.confirm = selected.size === 1 ? bar.dataset.deleteOne : fill(bar.dataset.deleteMany, { n: selected.size });
      form.requestSubmit();                                              // the page's own confirmation window asks first
      return;
    }
    delete form.dataset.confirm;
    openParams(action);
  });

  form.addEventListener("submit", function () {                           // fill in what was chosen, then the browser sends it
    form.elements.ids.value = Array.from(selected).join(",");
    form.elements.next.value = location.pathname + location.search;
    if (form.elements.action.value !== "delete") delete form.dataset.confirm;
  });

  // in the mode, a tile is marked instead of opened or played; this runs before the tile's own handlers
  document.addEventListener("click", function (e) {
    if (!on) return;
    var tile = e.target.closest && e.target.closest(".tile[data-id]");
    if (!tile || !grid.contains(tile)) return;
    e.preventDefault();
    e.stopPropagation();
    mark(tile, e.shiftKey);
  }, true);

  document.addEventListener("keydown", function (e) {
    if (!on) return;
    if (e.key === "Escape" && !document.querySelector("dialog[open]")) { mode(false); return; }
    if ((e.key === " " || e.key === "Enter") && e.target.classList && e.target.classList.contains("tile") && grid.contains(e.target)) {
      e.preventDefault();
      mark(e.target, e.shiftKey);
    }
  });

  document.body.addEventListener("htmx:afterSettle", paint);              // more tiles or another search: mark the ones that are chosen
  paint();
})();
