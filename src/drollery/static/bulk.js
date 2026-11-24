// Selecting several tiles of the library and doing one thing to all of them.
// Tags are typed as chips (the same field as on an item); people are found with a search box that suggests the people who exist,
// and every pick becomes a chip with a cross.
// "Select" switches the mode on: a click on a tile then marks it instead of opening it (Shift marks a range, Space or Enter
// on a focused tile marks it, Esc leaves the mode). A bar at the bottom shows the count and the actions. The page without
// this script is the same page with links: nothing here is needed to use the library.
(function () {
  var toggle = document.getElementById("select-toggle"), bar = document.getElementById("bulkbar"), grid = document.getElementById("grid");
  if (!toggle || !bar || !grid) return;
  var form = document.getElementById("bulk-form"), params = document.getElementById("bulk-params");
  var selected = new Set(), last = null, on = false;
  var tagField = window.makeTagField ? window.makeTagField(document.getElementById("bulk-tag-fld"), document.getElementById("bulk-tags-in"), "bulk-tag-entry") : null;
  var people = peoplePicker();

  // ---- the people search: suggestions while typing, a chip for every pick
  function peoplePicker() {
    var wrap = document.getElementById("bulk-person-fld"), box = document.getElementById("bulk-person-field"), entry = document.getElementById("bulk-person-in"),
        list = document.getElementById("bulk-suggest"), store = form.elements.person_id;
    if (!wrap || !box || !entry || !list || !store) return null;
    var chosen = [], timer = null, seq = 0, ph = entry.getAttribute("placeholder") || "";
    var CROSS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M17 7 7 17M7 7l10 10"/></svg>';
    function close() { list.hidden = true; list.textContent = ""; entry.setAttribute("aria-expanded", "false"); }
    function marked() { for (var i = 0; i < list.children.length; i++) if (list.children[i].getAttribute("aria-selected") === "true") return i; return -1; }
    function mark(n) {
      var items = list.children;
      if (!items.length) return;
      n = (n + items.length) % items.length;
      for (var i = 0; i < items.length; i++) items[i].setAttribute("aria-selected", String(i === n));
      items[n].scrollIntoView({ block: "nearest" });
    }
    function draw() {
      box.querySelectorAll(".tagchip").forEach(function (c) { c.remove(); });
      chosen.forEach(function (p) {
        var chip = document.createElement("span"), word = document.createElement("span"), x = document.createElement("button");
        chip.className = "tagchip"; word.textContent = p.name;
        x.type = "button"; x.innerHTML = CROSS; x.title = wrap.dataset.remove.replace("{name}", p.name); x.setAttribute("aria-label", x.title);
        x.addEventListener("click", function () { chosen = chosen.filter(function (q) { return q.id !== p.id; }); draw(); entry.focus(); });
        chip.appendChild(word); chip.appendChild(x); box.insertBefore(chip, entry);
      });
      store.value = chosen.map(function (p) { return p.id; }).join(",");
      entry.placeholder = chosen.length ? "" : ph;
    }
    function add(p) {
      if (!chosen.some(function (q) { return q.id === p.id; })) chosen.push(p);
      entry.value = ""; close(); draw(); entry.focus();
    }
    function show(rows) {
      list.textContent = "";
      rows.forEach(function (r) {
        var li = document.createElement("li"), b = document.createElement("b");
        li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false"); li.dataset.id = r.id; li.dataset.name = r.name;
        b.textContent = r.name; li.appendChild(b);
        if (r.note) { var sm = document.createElement("small"); sm.textContent = r.note; li.appendChild(sm); }
        list.appendChild(li);
      });
      list.hidden = !rows.length;
      entry.setAttribute("aria-expanded", String(rows.length > 0));
    }
    entry.addEventListener("input", function () {
      var q = entry.value.trim();
      clearTimeout(timer);
      if (!q) { close(); return; }
      var mine = ++seq;
      timer = setTimeout(function () {
        fetch(wrap.dataset.lookup + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
          .then(function (r) { return r.ok ? r.json() : []; })
          .then(function (rows) {
            if (mine !== seq || entry.value.trim() !== q) return;
            show(rows.filter(function (r) { return !chosen.some(function (c) { return c.id === String(r.id); }); }));
            if (list.children.length) mark(0);                                      // the best match is ready: Enter takes it
          })
          .catch(close);
      }, 150);
    });
    entry.addEventListener("keydown", function (e) {
      var at = marked();
      if (e.key === "ArrowDown" && !list.hidden) { e.preventDefault(); mark(at + 1); }
      else if (e.key === "ArrowUp" && !list.hidden) { e.preventDefault(); mark(at < 0 ? -1 : at - 1); }
      else if (e.key === "Enter") {
        if (!list.hidden && at >= 0) { e.preventDefault(); add({ id: list.children[at].dataset.id, name: list.children[at].dataset.name }); }
        else if (entry.value.trim()) e.preventDefault();                           // typed text that is nobody: do not submit by accident
      }
      else if (e.key === "Escape" && !list.hidden) { e.preventDefault(); e.stopPropagation(); close(); }
      else if (e.key === "Backspace" && !entry.value && chosen.length) { chosen.pop(); draw(); }
    });
    list.addEventListener("mousedown", function (e) {
      var li = e.target.closest && e.target.closest("li");
      if (li) { e.preventDefault(); add({ id: li.dataset.id, name: li.dataset.name }); }
    });
    entry.addEventListener("blur", function () { setTimeout(close, 120); });
    box.addEventListener("click", function (e) { if (e.target === box) entry.focus(); });
    return { reset: function () { chosen = []; entry.value = ""; close(); draw(); }, count: function () { return chosen.length; }, entry: entry };
  }

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
    Array.prototype.forEach.call(params.querySelectorAll("[data-for]"), function (l) { l.hidden = true; });
    if (tagField) tagField.reset();
    if (people) people.reset();
  }

  function openParams(action) {
    closeParams();
    form.elements.action.value = action;
    Array.prototype.forEach.call(params.querySelectorAll("[data-for]"), function (l) { l.hidden = l.dataset.for.split(" ").indexOf(action) < 0; });
    params.hidden = false;
    var field = params.querySelector("[data-for]:not([hidden]) input[type=text], [data-for]:not([hidden]) select");
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
      delete form.dataset.confirm;                                       // no question: the message afterwards has an Undo button
      form.requestSubmit();
      return;
    }
    delete form.dataset.confirm;
    openParams(action);
  });

  form.addEventListener("submit", function (e) {                          // fill in what was chosen, then the browser sends it
    var act = form.elements.action.value;
    if ((act === "tag_add" || act === "tag_remove") && !form.elements.tags.value.trim() && tagField) { e.preventDefault(); tagField.entry.focus(); return; }
    if ((act === "person_add" || act === "person_remove") && people && !people.count()) { e.preventDefault(); people.entry.focus(); return; }
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
