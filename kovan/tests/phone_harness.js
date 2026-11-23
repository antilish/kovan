// Telefon sayfasının gerçek JavaScript'ini Node içinde çalıştırır.
// Kullanım: node phone_harness.js <controller_url> <eslestirme_kodu>
const vm = require("vm");
const nodeCrypto = require("crypto");

const [base, code] = process.argv.slice(2);

(async () => {
  const html = await (await fetch(base + "/phone")).text();
  const source = html.match(/<script>([\s\S]*?)<\/script>/)[1];

  const elements = {};
  const el = (id) =>
    elements[id] ||
    (elements[id] = { id, hidden: false, textContent: "", value: "", className: "", onclick: null });

  const blobs = new Map();
  let blobCount = 0;
  class Blob { constructor(parts) { this.src = parts.join(""); } }
  const URLShim = { createObjectURL(blob) { const u = "blob:" + ++blobCount; blobs.set(u, blob.src); return u; } };

  class Worker {
    constructor(url) {
      this.onmessage = null;
      this.onerror = null;
      this.ctx = { postMessage: (d) => setImmediate(() => this.onmessage && this.onmessage({ data: d })) };
      vm.createContext(this.ctx);
      vm.runInContext(blobs.get(url), this.ctx);
    }
    postMessage(d) { setImmediate(() => this.ctx.onmessage({ data: d })); }
  }

  const store = new Map();
  const sandbox = {
    document: { getElementById: el },
    location: { hash: "#c=" + code, pathname: "/phone" },
    history: { replaceState() {} },
    navigator: { userAgent: "Mozilla/5.0 (Linux; Android 9; SM-G960F) Mobile Safari", hardwareConcurrency: 8 },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: (k) => store.delete(k),
    },
    fetch: (path, opts) => fetch(base + path, opts),
    Blob, URL: URLShim, Worker,
    crypto: nodeCrypto.webcrypto,
    setTimeout, clearTimeout, setInterval, clearInterval, console,
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  console.log("phone page started");
})().catch((err) => { console.error(err); process.exit(1); });
