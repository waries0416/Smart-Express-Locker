/* R2b 三端页面渲染 + 降级不白屏核对
 * 用本机 Edge 的 CDP 打开真实后端页面，采集：
 *   · body 纯文本长度（白屏判据）、DOM 节点数
 *   · 未捕获 JS 异常（pageerror / console error）
 *   · 关键区块是否渲染出内容
 * 用法： node tools/check_pages_cdp.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9334;
const OUT = path.resolve(__dirname, "..", "..", "frontend-verify");
fs.mkdirSync(OUT, { recursive: true });

const CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

const PAGES = [
  { name: "mobile", url: BASE + "/m/", w: 500, h: 900 },
  { name: "kiosk", url: BASE + "/kiosk.html", w: 1280, h: 900 },
  { name: "admin", url: BASE + "/admin/dashboard", w: 1440, h: 900, login: true },
];

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ""; r.on("data", (c) => (d += c)); r.on("end", () => res(d)); })
      .on("error", rej);
  });
}
async function waitDevtools() {
  for (let i = 0; i < 60; i++) {
    try { return JSON.parse(await get(`http://127.0.0.1:${PORT}/json/version`)); }
    catch (e) { await new Promise((r) => setTimeout(r, 300)); }
  }
  throw new Error("DevTools 未就绪");
}
function cdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map(); const events = [];
    ws.onopen = () => resolve({
      events,
      send(method, params = {}) {
        return new Promise((res, rej) => {
          const mid = ++id; pend.set(mid, { res, rej });
          ws.send(JSON.stringify({ id: mid, method, params }));
        });
      },
      close() { try { ws.close(); } catch (e) {} },
    });
    ws.onerror = () => reject(new Error("WS 失败"));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pend.has(m.id)) {
        const { res, rej } = pend.get(m.id); pend.delete(m.id);
        m.error ? rej(new Error(m.error.message)) : res(m.result);
      } else if (m.method === "Runtime.exceptionThrown") {
        events.push("EXC: " + (m.params.exceptionDetails.exception?.description
          || m.params.exceptionDetails.text || "").split("\n")[0]);
      } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
        events.push("CONSOLE: " + (m.params.args[0]?.value || m.params.args[0]?.description || "").toString().slice(0, 120));
      }
    };
  });
}

(async () => {
  const exe = CANDIDATES.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge/Chrome"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu",
    "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
    "--user-data-dir=" + path.join(os.tmpdir(), "r2b-page-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let bad = 0;
  try {
    await waitDevtools();
    for (const p of PAGES) {
      const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
      const c = await cdp(pages[0].webSocketDebuggerUrl);
      try {
        await c.send("Page.enable");
        await c.send("Runtime.enable");
        await c.send("Network.enable");
        await c.send("Emulation.setDeviceMetricsOverride",
          { width: p.w, height: p.h, deviceScaleFactor: 1, mobile: p.name === "mobile" });

        if (p.login) {
          // 管理端是 HttpOnly Cookie 会话：先在页面上下文里 fetch 登录，Cookie 由浏览器接管
          await c.send("Page.navigate", { url: BASE + "/admin/login" });
          await new Promise((r) => setTimeout(r, 1500));
          await c.send("Runtime.evaluate", {
            expression: `fetch('/api/auth/login',{method:'POST',credentials:'include',
              headers:{'Content-Type':'application/json'},
              body:JSON.stringify({username:'admin',password:'admin123'})}).then(r=>r.status)`,
            awaitPromise: true, returnByValue: true,
          });
        }
        await c.send("Page.navigate", { url: p.url });
        await new Promise((r) => setTimeout(r, 3500));

        const expr = `(function(){
          var de=document.documentElement;
          var txt=(document.body.innerText||'').replace(/\\s+/g,' ').trim();
          var vis={
            amapBox: !!document.getElementById('amapBox') && !document.getElementById('amapBox').hidden,
            mapFallback: !!document.getElementById('mapFallback') && !document.getElementById('mapFallback').hidden,
            chatBox: !!document.getElementById('aiChatList') || !!document.getElementById('aiReply'),
            payBox: !!document.getElementById('payAmount'),
            viewPayments: !!document.getElementById('view-payments')
          };
          return JSON.stringify({
            title: document.title,
            textLen: txt.length,
            nodes: document.getElementsByTagName('*').length,
            scrollW: de.scrollWidth, clientW: de.clientWidth,
            sample: txt.slice(0, 180),
            vis: vis
          });
        })()`;
        const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true });
        const info = JSON.parse(r.result.value);
        const blank = info.textLen < 40;
        const hz = info.scrollW > info.clientW + 1;
        const exc = c.events.filter((e) => e.startsWith("EXC"));
        if (blank || exc.length) bad++;
        console.log(`${blank ? "!!白屏" : "OK"} ${p.name.padEnd(7)} textLen=${info.textLen} nodes=${info.nodes} scrollW=${info.scrollW}/${info.clientW}${hz ? " ⚠横向溢出" : ""}`);
        console.log(`     可见区块: ${JSON.stringify(info.vis)}`);
        console.log(`     文本样本: ${info.sample.replace(/"/g, "'")}`);
        if (c.events.length) c.events.slice(0, 5).forEach((e) => console.log(`     ${e}`));
        else console.log("     无 JS 异常");

        // 截图存档
        const shot = await c.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
        fs.writeFileSync(path.join(OUT, p.name + ".png"), Buffer.from(shot.data, "base64"));
      } finally { c.close(); }
    }
  } catch (e) {
    console.log("!! 异常:", e.message); bad++;
  } finally { try { proc.kill(); } catch (e) {} }
  console.log(bad ? `\n结果：${bad} 个页面有问题` : "\n结果：三端页面均正常渲染、无未捕获异常");
  process.exit(bad ? 1 : 0);
})();
