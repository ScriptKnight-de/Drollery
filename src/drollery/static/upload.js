// Upload engine. send() uploads a FormData with a progress bar: how much has gone, how fast, how long it will take, and a
// Cancel button; when the last byte is sent the server still has to store and check the file, which is shown too.
// Forms marked data-upload use it automatically (their plain submit is replaced); the library's unified upload zone
// (uploader.js) calls send() directly. Without scripts the forms work as before.
(function () {
  var text = {};
  try { text = JSON.parse(document.getElementById("upload-text").textContent); } catch (e) {}
  var panel = null, xhr = null, busy = false;

  function size(n) {
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return (i > 1 ? n.toFixed(1) : Math.round(n)) + " " + u[i];
  }
  function span(seconds) {
    seconds = Math.max(1, Math.round(seconds));
    if (seconds < 90) return (text.sec || "{n} s").replace("{n}", seconds);
    if (seconds < 5400) return (text.min || "{n} min").replace("{n}", Math.round(seconds / 60));
    return (text.hour || "{n} h").replace("{n}", (seconds / 3600).toFixed(1));
  }
  function el(tag, cls, content) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (content) e.textContent = content;
    return e;
  }

  function build(label, host) {
    var p = el("div", "upload-panel" + (host ? " inline" : "")), head = el("div", "up-head"), bar = el("div", "up-bar"), fill = el("div", "up-fill"), cancel = el("button", "btn small", text.cancel || "Cancel");
    p.setAttribute("role", "status");
    p.setAttribute("aria-live", "polite");
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.appendChild(fill);
    var title = el("b", "up-title", (text.uploading || "Uploading") + (label ? ": " + label : "")), pct = el("span", "up-pct", "0%");
    head.appendChild(title); head.appendChild(pct);
    var detail = el("p", "up-detail muted small", "");
    cancel.type = "button";
    p.appendChild(head); p.appendChild(bar); p.appendChild(detail);
    var foot = el("div", "up-foot"); foot.appendChild(cancel); p.appendChild(foot);
    (host || document.body).appendChild(p);
    return { root: p, bar: bar, fill: fill, pct: pct, detail: detail, cancel: cancel, foot: foot, title: title };
  }

  function finish(ui, message, isError, unlock) {
    busy = false;
    if (unlock) unlock();
    ui.root.classList.remove("working");
    ui.root.classList.toggle("error", !!isError);
    ui.detail.textContent = message;
    ui.cancel.textContent = text.close || "Close";
    ui.cancel.onclick = function () { ui.root.remove(); };
  }

  // A link is downloaded by a background job. The bar follows that job (percent when the site tells it, else a moving stripe)
  // and opens the new item when it is done; leaving the page does not stop the download.
  function follow(ui, jobId, o) {
    var poll, gone = false;
    busy = false;
    if (o.unlock) o.unlock();
    ui.root.classList.remove("processing");
    ui.root.classList.add("working", "waiting");
    ui.title.textContent = (text.downloading || "Downloading") + (o.label ? ": " + o.label : "");
    ui.pct.textContent = "";
    ui.detail.textContent = text.waiting || "Waiting for its turn";
    ui.cancel.textContent = text.hide || "Hide";
    ui.cancel.onclick = function () { gone = true; clearTimeout(poll); ui.root.remove(); };
    function end(message, isError) {
      ui.root.classList.remove("working", "waiting");
      ui.root.classList.toggle("error", !!isError);
      ui.detail.textContent = message;
      ui.cancel.textContent = text.close || "Close";
      ui.cancel.onclick = function () { ui.root.remove(); };
    }
    function tick() {
      if (gone) return;
      var r = new XMLHttpRequest();
      r.open("GET", "/jobs/" + jobId + "/status");
      r.onload = function () {
        var d = {};
        try { d = JSON.parse(r.responseText); } catch (e) {}
        if (r.status === 200 && d.status === "done") {
          ui.fill.style.width = "100%"; ui.pct.textContent = "100%";
          ui.detail.textContent = text.opening || "…";
          location.href = d.item_id ? "/items/" + d.item_id : "/";
          return;
        }
        if (r.status === 200 && d.status === "failed") { end((text.dlfailed || "The download failed") + (d.error ? ": " + d.error : ""), true); return; }
        if (r.status === 200) {
          var running = d.status === "running", pct = running && d.progress != null ? Math.round(d.progress) : null;
          ui.root.classList.toggle("waiting", pct === null);
          if (pct !== null) { ui.fill.style.width = pct + "%"; ui.pct.textContent = pct + "%"; ui.bar.setAttribute("aria-valuenow", String(pct)); }
          ui.detail.textContent = d.attempts > 1 ? (text.again || "The first try failed, trying again") : running ? (text.fetching || "Downloading in the background, you can leave this page") : (text.waiting || "Waiting for its turn");
        }
        poll = setTimeout(tick, 1500);
      };
      r.onerror = function () { poll = setTimeout(tick, 3000); };
      r.send();
    }
    tick();
  }

  // o: { url, data (FormData), label, total (bytes, fallback), host (element for an inline bar), lock(), unlock() }
  function send(o) {
    var ui = build(o.label, o.host), samples = [];
    ui.root.classList.add("working");
    if (o.lock) o.lock();
    busy = true;
    xhr = new XMLHttpRequest();
    xhr.open("POST", o.url);
    xhr.setRequestHeader("X-Drollery-Upload", "1");
    xhr.upload.onprogress = function (e) {
      var sent = e.lengthComputable ? e.loaded : 0, all = e.lengthComputable ? e.total : (o.total || 0), now = Date.now();
      samples.push([now, sent]);
      while (samples.length > 2 && now - samples[0][0] > 4000) samples.shift();      // speed over the last few seconds
      var first = samples[0], rate = now > first[0] ? (sent - first[1]) / ((now - first[0]) / 1000) : 0;
      var pct = all ? Math.min(100, Math.floor(sent / all * 100)) : 0;
      ui.fill.style.width = pct + "%"; ui.pct.textContent = pct + "%";
      ui.bar.setAttribute("aria-valuenow", String(pct));
      var line = (text.of || "{sent} of {total}").replace("{sent}", size(sent)).replace("{total}", size(all));
      if (rate > 0) line += " · " + size(rate) + "/s" + (sent < all ? " · " + (text.left || "{time} left").replace("{time}", span((all - sent) / rate)) : "");
      ui.detail.textContent = line;
    };
    xhr.upload.onload = function () {
      ui.fill.style.width = "100%"; ui.pct.textContent = "100%";
      ui.root.classList.add("processing");
      ui.detail.textContent = text.processing || "Processing…";
    };
    xhr.onload = function () {
      var type = xhr.getResponseHeader("content-type") || "";
      if (xhr.status === 413) { finish(ui, text.toolarge || "Too large", true, o.unlock); return; }
      if (type.indexOf("application/json") === 0) {
        try {
          var d = JSON.parse(xhr.responseText);
          if (d.redirect) { busy = false; ui.detail.textContent = text.opening || "…"; location.href = d.redirect; return; }
          if (d.job) { follow(ui, d.job, o); return; }                           // a link: the download goes on in the background, the bar follows it
        } catch (e) {}
      }
      if (xhr.status >= 200 && xhr.status < 300 || xhr.status === 422) {          // the form again, with what is wrong
        busy = false;
        document.open(); document.write(xhr.responseText); document.close();
        return;
      }
      finish(ui, text.failed || "The upload failed", true, o.unlock);
    };
    xhr.onerror = function () { finish(ui, text.failed || "The upload failed", true, o.unlock); };
    xhr.onabort = function () { finish(ui, text.cancelled || "Cancelled", false, o.unlock); };
    ui.cancel.onclick = function () { xhr.abort(); };
    xhr.send(o.data);
    return ui;
  }
  window.drolleryUpload = { send: send, size: size, isBusy: function () { return busy; } };

  // forms marked data-upload: send them with the engine
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.hasAttribute || !form.hasAttribute("data-upload")) return;
    if (busy) { e.preventDefault(); return; }
    var names = [], total = 0;
    Array.prototype.forEach.call(form.querySelectorAll("input[type=file]"), function (i) {
      Array.prototype.forEach.call(i.files, function (f) { names.push(f.name); total += f.size; });
    });
    if (!names.length || !window.XMLHttpRequest || !window.FormData) return;           // nothing to count (a link, say): the plain submit does it
    e.preventDefault();
    var data;
    try { data = new FormData(form, e.submitter); } catch (err) { data = new FormData(form); }
    var label = names.length > 2 ? names.slice(0, 2).join(", ") + " +" + (names.length - 2) : names.join(", ");
    send({ url: form.action, data: data, label: label, total: total,
           lock: function () { form.classList.add("uploading"); }, unlock: function () { form.classList.remove("uploading"); } });
  });

  window.addEventListener("beforeunload", function (e) {
    if (!busy) return;
    e.preventDefault();
    e.returnValue = text.leave || "";
  });
})();
