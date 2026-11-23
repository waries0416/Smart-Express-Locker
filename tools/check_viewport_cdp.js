/* R2b 视口溢出核对（无 playwright 版）
 * 驱动本机 Edge/Chrome 的 CDP，按目标视口打开页面并量横向溢出。
 * 用法： node tools/check_viewport_cdp.js
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const PORT = 9333;

const CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
];

const TARGETS = [
  { name: "mobile-500", file: "frontend/mobile/index.html", w: 500, h: 900 },
  { name: "mobile-390", file: "frontend/mobile/index.html", w: 390, h: 844 },
  { name: "kiosk-1280x900", file: "frontend/kiosk.html", w: 1280, h: 900 },
  { name: "admin-1440x900", file: "frontend/admin.html", w: 1440, h: 900 },
];

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => {
      let d = "";
      r.on("data", (c) => (d += c));
      r.on("end", () => res(d));
    }).on("error", rej);
  });
}

async function waitDevtools() {
  for (let i = 0; i < 60; i++) {
    try {
      const v = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/version`));
      return v;
    } catch (e) { await new Promise((r) => setTimeout(r, 300)); }
  }
  throw new Error("DevTools 端口未就绪");
}

// 极简 CDP 客户端（node 内置 WebSocket：node>=22）
function cdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pend = new Map();
    ws.onopen = () => resolve({
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id;
          pend.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      close() { try { ws.close(); } catch (e) {} },
    });
    ws.onerror = (e) => reject(new Error("WS 连接失败"));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && pend.has(msg.id)) {
        const { res, rej } = pend.get(msg.id);
        pend.delete(msg.id);
        msg.error ? rej(new Error(msg.error.message)) : res(msg.result);
      }
    };
  });
}

(async () => {
  const exe = CANDIDATES.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge/Chrome，跳过视口核对"); process.exit(0); }
  console.log("浏览器:", exe);

  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`,
    "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--allow-file-access-from-files",
    "--user-data-dir=" + path.join(require("os").tmpdir(), "r2b-cdp-" + Date.now()),
    "about:blank",
  ], { stdio: "ignore" });

  let bad = 0;
  try {
    await waitDevtools();
    for (const t of TARGETS) {
      const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`))
        .filter((p) => p.type === "page");
      const page = pages[0];
      const c = await cdp(page.webSocketDebuggerUrl);
      try {
        await c.send("Page.enable");
        await c.send("Runtime.enable");
        await c.send("Emulation.setDeviceMetricsOverride", {
          width: t.w, height: t.h, deviceScaleFactor: 1, mobile: t.name.startsWith("mobile"),
        });
        const url = "file:///" + path.join(ROOT, t.file).replace(/\\/g, "/");
        await c.send("Page.navigate", { url });
        await new Promise((r) => setTimeout(r, 1800));
        const expr = `(function(){
          var de=document.documentElement, over=[];
          document.querySelectorAll('body *').forEach(function(el){
            var r=el.getBoundingClientRect();
            if(r.width>0 && r.right>de.clientWidth+1){
              over.push({tag:el.tagName, cls:(el.className||'').toString().slice(0,40), right:Math.round(r.right)});
            }
          });
          return JSON.stringify({scrollW:de.scrollWidth, clientW:de.clientWidth,
            bodyH:document.body.scrollHeight, n:over.length, over:over.slice(0,6)});
        })()`;
        const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true });
        const info = JSON.parse(r.result.value);
        const hz = info.scrollW > info.clientW + 1;
        if (hz) bad++;
        console.log(`${hz ? "!!" : "OK"} ${t.name.padEnd(16)} scrollW=${info.scrollW} clientW=${info.clientW} bodyH=${info.bodyH}`);
        if (info.n) info.over.forEach((o) => console.log(`     overflow(${info.n}): <${o.tag}> .${o.cls} right=${o.right}`));
      } finally { c.close(); }
    }
  } catch (e) {
    console.log("!! 核对异常:", e.message);
    bad++;
  } finally {
    try { proc.kill(); } catch (e) {}
  }
  console.log(bad ? `\n结果：${bad} 个视口存在横向溢出` : "\n结果：全部视口无横向溢出");
  process.exit(bad ? 1 : 0);
})();
