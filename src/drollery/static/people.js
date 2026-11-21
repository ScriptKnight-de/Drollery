// The people field on an item: typing a name suggests people who already exist (picking one adds them), and the
// "New person" button carries what was typed into the popup. Delegated, so it keeps working after keepplaying.js
// swaps the side column.
(function () {
  var timer = null, seq = 0;

  function parts(form) {
    return { form: form, input: form.querySelector(".person-in"), id: form.querySelector("[name=person_id]"),
             list: form.querySelector(".suggest"), add: form.querySelector(".person-new") };
  }
  function close(p) { p.list.hidden = true; p.list.textContent = ""; p.input.setAttribute("aria-expanded", "false"); }
  function mark(p, n) {
    var items = p.list.children;
    if (!items.length) return;
    n = (n + items.length) % items.length;
    for (var i = 0; i < items.length; i++) items[i].setAttribute("aria-selected", i === n);
    items[n].scrollIntoView({ block: "nearest" });
  }
  function current(p) {
    for (var i = 0; i < p.list.children.length; i++) if (p.list.children[i].getAttribute("aria-selected") === "true") return i;
    return -1;
  }
  function choose(p, li) {
    p.input.value = li.dataset.name;
    p.id.value = li.dataset.id;
    close(p);
    p.form.requestSubmit();
  }
  function show(p, rows) {
    p.list.textContent = "";
    rows.forEach(function (r) {
      var li = document.createElement("li"), b = document.createElement("b");
      li.setAttribute("role", "option"); li.setAttribute("aria-selected", "false");
      li.dataset.id = r.id; li.dataset.name = r.name;
      b.textContent = r.name; li.appendChild(b);
      if (r.note) { var s = document.createElement("small"); s.textContent = r.note; li.appendChild(s); }
      p.list.appendChild(li);
    });
    p.list.hidden = !rows.length;
    p.input.setAttribute("aria-expanded", String(rows.length > 0));
  }

  document.addEventListener("input", function (e) {
    if (!e.target.classList || !e.target.classList.contains("person-in")) return;
    var p = parts(e.target.closest(".person-add")), q = e.target.value.trim();
    p.id.value = "";
    if (p.add) p.add.href = p.add.href.split("&name=")[0] + (q ? "&name=" + encodeURIComponent(q) : "");
    clearTimeout(timer);
    if (!q) { close(p); return; }
    var mine = ++seq;
    timer = setTimeout(function () {
      fetch(p.form.dataset.lookup + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) { if (mine === seq && e.target.value.trim() === q) show(p, rows); })
        .catch(function () { close(p); });
    }, 150);
  });

  document.addEventListener("keydown", function (e) {
    if (!e.target.classList || !e.target.classList.contains("person-in")) return;
    var p = parts(e.target.closest(".person-add")), at = current(p);
    if (e.key === "ArrowDown" && !p.list.hidden) { e.preventDefault(); mark(p, at + 1); }
    else if (e.key === "ArrowUp" && !p.list.hidden) { e.preventDefault(); mark(p, at < 0 ? -1 : at - 1); }
    else if (e.key === "Enter" && at >= 0 && !p.list.hidden) { e.preventDefault(); choose(p, p.list.children[at]); }
    else if (e.key === "Escape" && !p.list.hidden) { e.preventDefault(); e.stopPropagation(); close(p); }
  });

  document.addEventListener("mousedown", function (e) {
    var li = e.target.closest && e.target.closest(".suggest li");
    if (li) { e.preventDefault(); choose(parts(li.closest(".person-add")), li); return; }
    document.querySelectorAll(".person-add").forEach(function (f) { if (!f.contains(e.target)) close(parts(f)); });
  });
})();
