// The library's one way in. Drop or choose files anywhere on the page, or paste a link; a panel then shows what was
// picked, suggests what it should become (separate items, an album or audiobook, a movie), asks for the details that
// type needs and uploads it with the progress bar of upload.js. Each type goes to the server route it always used.
(function () {
  var root = document.getElementById("uploader");
  if (!root || !window.drolleryUpload) return;
  var text = {};
  try { text = JSON.parse(document.getElementById("uploader-text").textContent); } catch (e) {}
  var zone = document.getElementById("uz"), pick = document.getElementById("uz-files"), url = document.getElementById("uz-url"), urlGo = document.getElementById("uz-url-go"),
      form = document.getElementById("uz-form"), title = document.getElementById("uz-title"), note = document.getElementById("uz-note"), types = document.getElementById("uz-types"),
      go = document.getElementById("uz-go"), progress = document.getElementById("uz-progress");
  var MB = 1048576, maxUpload = Number(root.dataset.maxUpload) * MB, maxMovie = Number(root.dataset.maxMovie) * MB;
  var AUDIO = /\.(mp3|m4a|m4b|aac|flac|ogg|oga|opus|wav)$/i, MOVIE_HINT = 300 * MB;
  var files = [], link = "", chosen = "", why = "";

  function kindOf(f) {
    var t = f.type || "";
    if (/\.zip$/i.test(f.name) || t === "application/zip" || t === "application/x-zip-compressed") return "zip";
    if (t.indexOf("audio/") === 0 || AUDIO.test(f.name)) return "audio";
    if (t.indexOf("video/") === 0) return "video";
    if (t.indexOf("image/") === 0) return "image";
    return "other";
  }
  function fmt(s, vars) { Object.keys(vars).forEach(function (k) { s = s.replace("{" + k + "}", vars[k]); }); return s; }
  function sizeOf(list) { return list.reduce(function (n, f) { return n + f.size; }, 0); }

  // which types the picked files can become, and the one to suggest
  function analyse() {
    var kinds = files.map(kindOf), has = function (k) { return kinds.indexOf(k) >= 0; }, count = function (k) { return kinds.filter(function (x) { return x === k; }).length; };
    var other = files.filter(function (f, i) { return kinds[i] === "other"; });
    var can = { items: false, album: false, movie: false }, why = "";
    if (other.length) { why = fmt(text.unsupported || "{name}", { name: other[0].name }); return { can: can, why: why, suggest: "" }; }
    can.items = !has("zip");
    can.album = (has("audio") || has("zip")) && kinds.every(function (k) { return k === "audio" || k === "zip" || k === "image"; }) && count("image") <= 1;
    can.movie = files.length === 1 && kinds[0] === "video";
    if (!can.items && !can.album && !can.movie) why = text.mixed || "";
    var suggest = "";
    if (can.album && (count("audio") >= 2 || has("zip"))) suggest = "album";
    else if (can.movie && files[0].size >= MOVIE_HINT) suggest = "movie";
    else if (can.items) suggest = "items";
    else suggest = can.album ? "album" : can.movie ? "movie" : "";
    return { can: can, why: why, suggest: suggest };
  }

  function tooLarge() {
    var type = chosen;
    if (type === "movie") return files.some(function (f) { return f.size > maxMovie; }) ? maxMovie : 0;
    if (type === "items") return files.some(function (f) { return f.size > maxUpload; }) ? maxUpload : 0;
    return 0;
  }

  function showType(type) {
    chosen = type;
    Array.prototype.forEach.call(form.querySelectorAll(".uz-fields"), function (g) {
      var on = g.dataset.for === type;
      g.hidden = !on;
      Array.prototype.forEach.call(g.querySelectorAll("input, textarea"), function (i) { i.disabled = !on; });
    });
    Array.prototype.forEach.call(types.querySelectorAll("input[name=uz-type]"), function (r) { r.checked = r.value === type; });
    var limit = type === "link" ? 0 : tooLarge();
    note.textContent = limit ? fmt(text.toolarge || "{max}", { max: window.drolleryUpload.size(limit) }) : why;      // too big, else why nothing fits
    note.hidden = !note.textContent;
    go.disabled = !type || !!limit;
  }

  function open() {
    form.hidden = false;
    zone.classList.add("picked");
    var first = form.querySelector("input[name=uz-type]:checked") || form.querySelector("button, input");
    if (first && first.focus) first.focus({ preventScroll: false });
  }
  function reset() {
    files = []; link = ""; chosen = "";
    form.hidden = true;
    zone.classList.remove("picked");
    progress.textContent = "";
    pick.value = ""; url.value = "";
    Array.prototype.forEach.call(form.querySelectorAll("[data-f]"), function (i) { if (i.type === "checkbox") i.checked = false; else i.value = ""; });
  }

  function onFiles(list) {
    list = Array.prototype.slice.call(list);
    if (!list.length) return;
    files = list; link = "";
    title.textContent = fmt(text.selected || "{n} · {size}", { n: files.length, size: window.drolleryUpload.size(sizeOf(files)) });
    var a = analyse();
    Array.prototype.forEach.call(types.querySelectorAll("label[data-type]"), function (l) {
      var t = l.dataset.type, input = l.querySelector("input");
      l.hidden = !a.can[t];
      input.disabled = !a.can[t];
      var badge = l.querySelector(".uz-badge");
      if (badge) badge.remove();
      if (t === a.suggest && Object.keys(a.can).filter(function (k) { return a.can[k]; }).length > 1) {
        var b = document.createElement("em"); b.className = "uz-badge"; b.textContent = text.suggested || "Suggested"; l.querySelector("b").appendChild(b);
      }
    });
    types.hidden = !a.suggest;
    why = a.why;
    showType(a.suggest);
    if (!a.suggest) go.disabled = true;
    open();
  }
  function onLink(value) {
    value = (value || "").trim();
    if (!/^https?:\/\/\S+$/i.test(value)) return;
    files = []; link = value;
    title.textContent = (text.link || "Link") + ": " + value;
    types.hidden = true;
    why = "";
    showType("link");
    open();
  }

  // choosing, dropping, pasting
  pick.addEventListener("change", function () { onFiles(pick.files); });
  urlGo.addEventListener("click", function () { onLink(url.value); });
  url.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); onLink(url.value); } });
  url.addEventListener("paste", function () { setTimeout(function () { onLink(url.value); }, 0); });
  document.getElementById("uz-change").addEventListener("click", function () { pick.value = ""; pick.click(); });
  document.getElementById("uz-cancel").addEventListener("click", reset);
  types.addEventListener("change", function (e) { if (e.target.name === "uz-type") showType(e.target.value); });

  var depth = 0;
  document.addEventListener("dragenter", function (e) { if (hasFiles(e)) { depth++; zone.classList.add("over"); } });
  document.addEventListener("dragleave", function (e) { if (hasFiles(e) && --depth <= 0) { depth = 0; zone.classList.remove("over"); } });
  document.addEventListener("dragover", function (e) { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", function (e) {
    depth = 0; zone.classList.remove("over");
    if (!hasFiles(e) || window.drolleryUpload.isBusy()) return;
    e.preventDefault();
    onFiles(e.dataTransfer.files);
  });
  function hasFiles(e) { return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], "Files") >= 0; }

  document.addEventListener("paste", function (e) {
    var t = e.target, typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    if (typing || window.drolleryUpload.isBusy() || !e.clipboardData) return;
    if (e.clipboardData.files && e.clipboardData.files.length) { e.preventDefault(); onFiles(e.clipboardData.files); return; }
    var s = (e.clipboardData.getData("text") || "").trim();
    if (/^https?:\/\/\S+$/i.test(s)) { e.preventDefault(); url.value = s; onLink(s); }
  });

  // sending
  function field(group, name) { var e = form.querySelector('.uz-fields[data-for="' + group + '"] [data-f="' + name + '"]'); return e ? (e.type === "checkbox" ? (e.checked ? "1" : "") : e.value) : ""; }
  function radio(name) { var r = form.querySelector("input[name=" + name + "]:checked"); return r ? r.value : ""; }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (go.disabled || window.drolleryUpload.isBusy()) return;
    var fd = new FormData(), target, label;
    if (chosen === "link") {
      target = "/add"; fd.append("url", link); label = link;
    } else if (chosen === "items") {
      target = "/add"; files.forEach(function (f) { fd.append("files", f, f.name); });
    } else if (chosen === "album") {
      target = "/albums";
      var cover = false;
      files.forEach(function (f) { if (kindOf(f) === "image" && !cover) { fd.append("cover", f, f.name); cover = true; } else fd.append("files", f, f.name); });
      ["title", "artist", "description", "tags", "lookup"].forEach(function (n) { fd.append(n, field("album", n)); });
      fd.append("subtype", radio("uz-album-subtype") || "album");
    } else if (chosen === "movie") {
      target = "/movies";
      fd.append("file", files[0], files[0].name);
      ["title", "original_title", "description", "tags", "lookup"].forEach(function (n) { fd.append(n, field("movie", n)); });
      fd.append("subtype", radio("uz-movie-subtype") || "movie");
    } else return;
    label = label || (files.length > 2 ? files.slice(0, 2).map(function (f) { return f.name; }).join(", ") + " +" + (files.length - 2) : files.map(function (f) { return f.name; }).join(", "));
    progress.textContent = "";
    window.drolleryUpload.send({
      url: target, data: fd, label: label, total: sizeOf(files), host: progress,
      lock: function () { form.classList.add("uploading"); },
      unlock: function () { form.classList.remove("uploading"); },
    });
  });
})();
