// Upload progress: a form marked data-upload is sent with a script instead of the browser's plain submit, so the bytes
// can be counted. A bar shows how much has gone, how fast and how long it will take; when the last byte is sent the
// server still has to store and check the file, which is shown too. Without scripts the form works as before.
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

  function build(names) {
    var p = el("div", "upload-panel"), head = el("div", "up-head"), bar = el("div", "up-bar"), fill = el("div", "up-fill"), cancel = el("button", "btn small", text.cancel || "Cancel");
    p.setAttribute("role", "status");
    p.setAttribute("aria-live", "polite");
    bar.setAttribute("role", "progressbar");
    bar.setAttribute("aria-valuemin", "0");
    bar.setAttribute("aria-valuemax", "100");
    bar.appendChild(fill);
    var title = el("b", "up-title", (text.uploading || "Uploading") + (names ? ": " + names : "")), pct = el("span", "up-pct", "0%");
    head.appendChild(title); head.appendChild(pct);
    var detail = el("p", "up-detail muted small", "");
    cancel.type = "button";
    p.appendChild(head); p.appendChild(bar); p.appendChild(detail);
    var foot = el("div", "up-foot"); foot.appendChild(cancel); p.appendChild(foot);
    document.body.appendChild(p);
    return { root: p, bar: bar, fill: fill, pct: pct, detail: detail, cancel: cancel, foot: foot, title: title };
  }

  function finish(ui, message, isError) {
    busy = false;
    ui.root.classList.remove("working");
    ui.root.classList.toggle("error", !!isError);
    ui.detail.textContent = message;
    ui.cancel.textContent = text.close || "Close";
    ui.cancel.onclick = function () { ui.root.remove(); };
  }

  function start(form, submitter) {
    var data;
    try { data = new FormData(form, submitter); } catch (e) { data = new FormData(form); }
    var names = [], total = 0;
    Array.prototype.forEach.call(form.querySelectorAll("input[type=file]"), function (i) {
      Array.prototype.forEach.call(i.files, function (f) { names.push(f.name); total += f.size; });
    });
    var label = names.length > 2 ? names.slice(0, 2).join(", ") + " +" + (names.length - 2) : names.join(", ");
    var ui = build(label), samples = [];
    ui.root.classList.add("working");
    form.classList.add("uploading");
    busy = true;
    xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.setRequestHeader("X-Drollery-Upload", "1");
    xhr.upload.onprogress = function (e) {
      var sent = e.lengthComputable ? e.loaded : 0, all = e.lengthComputable ? e.total : total, now = Date.now();
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
      if (xhr.status === 413) { form.classList.remove("uploading"); finish(ui, text.toolarge || "Too large", true); return; }
      if (type.indexOf("application/json") === 0) {
        try {
          var d = JSON.parse(xhr.responseText);
          if (d.redirect) { busy = false; location.href = d.redirect; return; }
        } catch (e) {}
      }
      if (xhr.status >= 200 && xhr.status < 300 || xhr.status === 422) {          // the form again, with what is wrong
        busy = false;
        document.open(); document.write(xhr.responseText); document.close();
        return;
      }
      form.classList.remove("uploading");
      finish(ui, text.failed || "The upload failed", true);
    };
    xhr.onerror = function () { form.classList.remove("uploading"); finish(ui, text.failed || "The upload failed", true); };
    xhr.onabort = function () { form.classList.remove("uploading"); finish(ui, text.cancelled || "Cancelled", false); };
    ui.cancel.onclick = function () { xhr.abort(); };
    xhr.send(data);
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.hasAttribute || !form.hasAttribute("data-upload") || busy) { if (busy && form.hasAttribute && form.hasAttribute("data-upload")) e.preventDefault(); return; }
    var picked = 0;
    Array.prototype.forEach.call(form.querySelectorAll("input[type=file]"), function (i) { picked += i.files.length; });
    if (!picked || !window.XMLHttpRequest || !window.FormData) return;               // nothing to count (a link, say): the plain submit does it
    e.preventDefault();
    start(form, e.submitter);
  });

  window.addEventListener("beforeunload", function (e) {
    if (!busy) return;
    e.preventDefault();
    e.returnValue = text.leave || "";
  });
})();
