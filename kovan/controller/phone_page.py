"""Telefon/tablet için tarayıcıda çalışan KOVAN worker sayfası.

Sayfa gizli bilgi içermez. Eşleştirme kodu QR adresinin # kısmında gelir ve
kullanıldıktan sonra adres çubuğundan silinir.
"""

PHONE_CSP = (
    "default-src 'self'; script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; worker-src blob:; connect-src 'self'; "
    "img-src data:; base-uri 'none'; form-action 'none'"
)

PHONE_HTML = r'''<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0e1116">
<title>KOVAN • Telefon</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:#0e1116; color:#e6e9ef; min-height:100vh; }
  main { max-width:460px; margin:0 auto; padding:24px 18px 40px; }
  .brand { font-size:26px; font-weight:800; letter-spacing:.5px; color:#f6b73c; }
  .sub { color:#8b95a5; margin:2px 0 22px; }
  .card { background:#151a22; border:1px solid #232c39; border-radius:16px; padding:18px; margin-bottom:14px; }
  input { width:100%; font-size:26px; letter-spacing:4px; text-align:center; text-transform:uppercase;
          padding:14px; border-radius:12px; border:1px solid #2a3340; background:#0f141b; color:#e6e9ef; }
  button { width:100%; margin-top:12px; padding:14px; font-size:17px; font-weight:700; border:none;
           border-radius:12px; background:#f6b73c; color:#1a1405; }
  button.ghost { background:#222b38; color:#e6e9ef; font-weight:600; }
  .row { display:flex; align-items:center; gap:10px; }
  .dot { width:12px; height:12px; border-radius:50%; background:#8b95a5; flex:none; }
  .dot.ok { background:#3ecf8e; } .dot.busy { background:#4aa3ff; } .dot.bad { background:#ef5b5b; }
  .stats { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:14px; }
  .stat { background:#0f141b; border-radius:12px; padding:12px; }
  .stat b { display:block; font-size:24px; } .stat span { color:#8b95a5; font-size:13px; }
  .hint { color:#8b95a5; font-size:14px; }
  #msg { color:#ef5b5b; min-height:1.4em; margin-top:10px; }
  pre { background:#0f141b; border-radius:12px; padding:12px; font-size:12px; color:#8b95a5;
        max-height:180px; overflow:auto; white-space:pre-wrap; margin:14px 0 0; }
  [hidden] { display:none !important; }
</style>
</head>
<body>
<main>
  <div class="brand">&#11041; KOVAN</div>
  <div class="sub">Bu telefonu hesaplama kümesine kat</div>

  <section id="pairView" class="card" hidden>
    <p>Bilgisayardaki KOVAN penceresinde <b>Cihaz bağla</b> sayfasında görünen kodu yaz.</p>
    <input id="code" placeholder="ABCD-EFGH" maxlength="9" autocomplete="off" autocapitalize="characters" spellcheck="false">
    <button id="pairBtn">Bağlan</button>
  </section>

  <section id="runView" hidden>
    <div class="card">
      <div class="row"><span id="dot" class="dot"></span><b id="state">Başlıyor…</b></div>
      <div class="stats">
        <div class="stat"><b id="done">0</b><span>Tamamlanan görev</span></div>
        <div class="stat"><b id="current">—</b><span>Şu anki görev</span></div>
      </div>
      <p class="hint" id="devline"></p>
    </div>
    <p class="hint">Görevlerin çalışması için bu sayfayı <b>açık tut</b> ve ekranın kapanmasına izin verme.
       Ekran kapanırsa görev başka cihaza verilir.</p>
    <button id="leaveBtn" class="ghost">Bağlantıyı kes</button>
    <pre id="log"></pre>
  </section>
  <p id="msg"></p>
</main>
<script>
"use strict";
var CAPS = ["pi_monte_carlo", "prime_count"];

var WORKER_SRC = `
function mulberry32(a) {
  return function () {
    a = (a + 0x6D2B79F5) | 0;
    var t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function piMonteCarlo(samples, seed) {
  var rnd = mulberry32(seed), inside = 0;
  for (var i = 0; i < samples; i++) {
    var x = rnd(), y = rnd();
    if (x * x + y * y <= 1) inside++;
  }
  return inside;
}
function primeCount(start, stop) {
  var limit = Math.floor(Math.sqrt(stop)) + 1;
  var small = new Uint8Array(limit + 1).fill(1);
  small[0] = 0; if (limit >= 1) small[1] = 0;
  for (var i = 2; i * i <= limit; i++) {
    if (small[i]) for (var j = i * i; j <= limit; j += i) small[j] = 0;
  }
  var seg = new Uint8Array(stop - start).fill(1);
  for (var p = 2; p <= limit; p++) {
    if (!small[p]) continue;
    var first = Math.max(p * p, Math.ceil(start / p) * p);
    for (var m = first; m < stop; m += p) seg[m - start] = 0;
  }
  for (var n = 0; n < 2; n++) if (n >= start && n < stop) seg[n - start] = 0;
  var c = 0;
  for (var k = 0; k < seg.length; k++) c += seg[k];
  return c;
}
onmessage = function (e) {
  var d = e.data, t0 = Date.now();
  try {
    var result;
    if (d.type === "pi_monte_carlo") {
      result = { inside: piMonteCarlo(d.payload.samples, d.payload.seed), samples: d.payload.samples };
    } else if (d.type === "prime_count") {
      result = { count: primeCount(d.payload.start, d.payload.stop), start: d.payload.start, stop: d.payload.stop };
    } else {
      throw new Error("Desteklenmeyen görev: " + d.type);
    }
    result.elapsed_seconds = Math.round((Date.now() - t0)) / 1000;
    postMessage({ id: d.id, ok: true, result: result });
  } catch (err) {
    postMessage({ id: d.id, ok: false, error: String(err && err.message || err) });
  }
};
`;

var LS = {
  get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
  del: function (k) { try { localStorage.removeItem(k); } catch (e) {} }
};
function $(id) { return document.getElementById(id); }
function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
function randomHex(n) {
  var out = "";
  try {
    var a = new Uint8Array(n); crypto.getRandomValues(a);
    for (var i = 0; i < n; i++) out += (a[i] % 16).toString(16);
    return out;
  } catch (e) {
    for (var j = 0; j < n; j++) out += Math.floor(Math.random() * 16).toString(16);
    return out;
  }
}

var state = { token: LS.get("kovan_token"), deviceId: LS.get("kovan_device"),
              done: 0, stop: false, running: false, worker: null, seq: 0, beatTimer: null };

function showMsg(t) { $("msg").textContent = t || ""; }
function setState(text, kind) { $("state").textContent = text; $("dot").className = "dot " + (kind || ""); }
function log(line) {
  var el = $("log"); var lines = (el.textContent ? el.textContent.split("\n") : []);
  lines.push(new Date().toLocaleTimeString() + "  " + line);
  el.textContent = lines.slice(-30).join("\n");
}

function deviceType() {
  var ua = navigator.userAgent || "";
  if (/iPad|Tablet/i.test(ua) || (/Android/i.test(ua) && !/Mobile/i.test(ua))) return "tablet";
  return "phone";
}
function osInfo() {
  var ua = navigator.userAgent || "", m = ua.match(/Android\s([\d.]+)/);
  if (m) return ["Android", m[1]];
  m = ua.match(/OS ([\d_]+) like Mac OS X/);
  if (m) return ["iOS", m[1].replace(/_/g, ".")];
  return [null, null];
}
async function readBattery() {
  try {
    if (navigator.getBattery) {
      var b = await navigator.getBattery();
      return { level: Math.round(b.level * 100), charging: !!b.charging };
    }
  } catch (e) {}
  return { level: null, charging: null };
}
async function buildReport() {
  var os = osInfo(), b = await readBattery(), cores = navigator.hardwareConcurrency;
  return {
    device_id: state.deviceId, hostname: null,
    operating_system: os[0], os_version: os[1], architecture: null, processor_name: null,
    cpu_cores: cores >= 1 ? cores : null, cpu_usage: null, total_ram: null, available_ram: null,
    gpu_information: null, supported_capabilities: CAPS, device_type: deviceType(),
    battery_level: b.level, is_charging: b.charging, thermal_status: null
  };
}

function api(path, body) {
  return fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json", "X-Device-Token": state.token || "" },
    body: JSON.stringify(body || {}) });
}

function ensureWorker() {
  if (state.worker) return state.worker;
  var blob = new Blob([WORKER_SRC], { type: "text/javascript" });
  state.worker = new Worker(URL.createObjectURL(blob));
  return state.worker;
}
function compute(task) {
  return new Promise(function (resolve, reject) {
    var id = ++state.seq, w = ensureWorker();
    w.onmessage = function (e) {
      if (e.data.id !== id) return;
      if (e.data.ok) resolve(e.data.result); else reject(new Error(e.data.error));
    };
    w.onerror = function (e) { reject(new Error(e.message || "worker hatası")); };
    w.postMessage({ id: id, type: task.task_type, payload: task.payload });
  });
}

function showView(name) {
  $("pairView").hidden = name !== "pair";
  $("runView").hidden = name !== "run";
}
function unpair(message) {
  state.stop = true; state.token = null;
  LS.del("kovan_token");
  if (state.beatTimer) { clearInterval(state.beatTimer); state.beatTimer = null; }
  showView("pair"); showMsg(message || "");
}

async function beat() {
  try {
    var r = await api("/workers/heartbeat", { device: await buildReport() });
    if (r.status === 401) unpair("Eşleştirme geçersiz. Yeni kodla tekrar bağlan.");
  } catch (e) { /* ağ hatası: sonraki turda yeniden denenir */ }
}

async function submit(task, success, result, error) {
  var res = await api("/workers/tasks/" + task.id + "/result", {
    lease_id: task.lease_id, success: success, result: result,
    error: error ? String(error).slice(0, 1000) : null, retryable: false });
  if (res.ok && success) { state.done++; $("done").textContent = String(state.done); }
  if (res.status === 409) log("Sonuç reddedildi (süre dolmuş olabilir)");
}
async function runTask(task) {
  setState("Görev #" + task.id + " çalışıyor", "busy");
  $("current").textContent = "#" + task.id;
  try {
    var result = await compute(task);
    await submit(task, true, result, null);
    log("#" + task.id + " " + task.task_type + " tamam (" + result.elapsed_seconds + " sn)");
  } catch (e) {
    await submit(task, false, null, e.message || e);
    log("#" + task.id + " hata: " + (e.message || e));
  }
  $("current").textContent = "—";
}

async function mainLoop() {
  if (state.running) return;
  state.running = true; state.stop = false;
  showView("run"); showMsg("");
  $("devline").textContent = "Cihaz kimliği: " + state.deviceId;
  setState("Bağlandı", "ok");
  await beat();
  state.beatTimer = setInterval(beat, 5000);
  while (!state.stop) {
    try {
      var res = await api("/workers/claim");
      if (res.status === 401) { unpair("Eşleştirme geçersiz. Yeni kodla tekrar bağlan."); break; }
      if (res.status === 200) { await runTask(await res.json()); continue; }
      setState("Görev bekleniyor", "ok");
    } catch (e) {
      setState("Bilgisayara ulaşılamıyor", "bad");
    }
    await sleep(1000);
  }
  state.running = false;
}

async function pair(code) {
  showMsg("");
  for (var attempt = 0; attempt < 2; attempt++) {
    if (!state.deviceId) { state.deviceId = "phone-" + randomHex(6); LS.set("kovan_device", state.deviceId); }
    var res = await fetch("/workers/pair", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: code, device: await buildReport() }) });
    if (res.status === 200) {
      var data = await res.json();
      state.token = data.token; LS.set("kovan_token", data.token);
      mainLoop(); return true;
    }
    if (res.status === 409) { state.deviceId = null; LS.del("kovan_device"); continue; }
    showMsg(res.status === 429 ? "Çok fazla deneme. Bir dakika bekle." : "Kod geçersiz veya süresi dolmuş.");
    return false;
  }
  return false;
}

function init() {
  var m = (location.hash || "").match(/c=([A-Za-z0-9-]+)/);
  if (m) { try { history.replaceState(null, "", location.pathname); } catch (e) {} }
  $("pairBtn").onclick = function () { pair($("code").value); };
  $("leaveBtn").onclick = function () { unpair("Bağlantı kesildi."); };
  if (state.token && state.deviceId) { mainLoop(); return; }
  showView("pair");
  if (m) { $("code").value = m[1]; pair(m[1]); }
}
if (typeof document !== "undefined" && document.getElementById) init();
</script>
</body>
</html>
'''
