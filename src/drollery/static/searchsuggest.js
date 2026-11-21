// The search bar offers matching tags and people while you type. Picking one filters the library by it; typing on
// still searches the text as before. Arrow keys move through the suggestions, Enter opens the marked one, Escape closes.
(function () {
  var input = document.getElementById("q");
  if (!input || !input.dataset.suggest) return;
  var field = input.closest(".field"), list = document.createElement("ul"), timer = null, seq = 0;
  list.className = "suggest"; list.setAttribute("role", "listbox"); list.hidden = true;
  field.appendChild(list);

  function links() { return list.querySelectorAll("a"); }
  function close() { list.hidden = true; list.textContent = ""; input.setAttribute("aria-expanded", "false"); }
  function mark(n) {
    var a = links();
    if (!a.length) return;
    n = (n + a.length) % a.length;
    a.forEach(function (x, i) { x.setAttribute("aria-selected", String(i === n)); });
    a[n].scrollIntoView({ block: "nearest" });
  }
  function marked() {
    var a = links();
    for (var i = 0; i < a.length; i++) if (a[i].getAttribute("aria-selected") === "true") return i;
    return -1;
  }
  function kind() { var k = document.querySelector(".seg input:checked"); return k && k.value ? "&kind=" + encodeURIComponent(k.value) : ""; }
  function head(text) { var li = document.createElement("li"); li.className = "grp"; li.setAttribute("role", "presentation"); li.textContent = text; list.appendChild(li); }
  function row(href, build) {
    var li = document.createElement("li"), a = document.createElement("a");
    li.setAttribute("role", "presentation"); a.href = href; a.setAttribute("role", "option"); a.setAttribute("aria-selected", "false");
    build(a); li.appendChild(a); list.appendChild(li);
  }
  function small(a, text) { if (!text) return; var s = document.createElement("small"); s.textContent = text; a.appendChild(s); }

  function show(d) {
    list.textContent = "";
    if (d.tags.length) {
      head(input.dataset.tagsLabel);
      d.tags.forEach(function (t) {
        row("/?tag=" + encodeURIComponent(t.tag) + kind(), function (a) {
          var b = document.createElement("b"); b.textContent = "#" + t.tag; a.appendChild(b); small(a, String(t.n));
        });
      });
    }
    if (d.people.length) {
      head(input.dataset.peopleLabel);
      d.people.forEach(function (p) {
        row("/?person=" + p.id + kind(), function (a) {
          var av = document.createElement("span"); av.className = "avatar"; av.setAttribute("aria-hidden", "true");
          if (p.picture) { var im = document.createElement("img"); im.src = p.picture; im.alt = ""; av.appendChild(im); } else av.textContent = p.name.charAt(0).toUpperCase();
          var b = document.createElement("b"); b.textContent = p.name;
          a.appendChild(av); a.appendChild(b); small(a, p.note);
        });
      });
    }
    var any = d.tags.length + d.people.length > 0;
    list.hidden = !any;
    input.setAttribute("aria-expanded", String(any));
  }

  input.addEventListener("input", function () {
    var q = input.value.trim(), mine = ++seq;
    clearTimeout(timer);
    if (!q) { close(); return; }
    timer = setTimeout(function () {
      fetch(input.dataset.suggest + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : { tags: [], people: [] }; })
        .then(function (d) { if (mine === seq && input.value.trim() === q) show(d); })
        .catch(close);
    }, 150);
  });
  input.addEventListener("keydown", function (e) {
    var at = marked();
    if (e.key === "ArrowDown" && !list.hidden) { e.preventDefault(); mark(at + 1); }
    else if (e.key === "ArrowUp" && !list.hidden) { e.preventDefault(); mark(at < 0 ? -1 : at - 1); }
    else if (e.key === "Enter" && at >= 0 && !list.hidden) { e.preventDefault(); location.href = links()[at].href; }
    else if (e.key === "Escape" && !list.hidden) { e.preventDefault(); close(); }
  });
  list.addEventListener("mousedown", function (e) { e.preventDefault(); });          // keep the focus in the search field
  document.addEventListener("mousedown", function (e) { if (!field.contains(e.target)) close(); });
  input.addEventListener("focus", function () { if (input.value.trim() && !list.children.length) input.dispatchEvent(new Event("input")); });
})();
