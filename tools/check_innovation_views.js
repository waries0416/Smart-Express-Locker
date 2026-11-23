/* R2b 创新视图渲染 + 降级不白屏核对
 * 场景 A（在线）：切到管理端三个创新视图 / 触屏 AI 入口，断言渲染出真实数据。
 * 场景 B（降级）：CDP 拦截创新接口返回 500/404，断言页面出现降级提示且不白屏。
 * 用法： node tools/check_innovation_views.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9335;
const CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ""; r.on("data", (c) => (d += c)); r.on("end", () => res(d)); }).on("error", rej);
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
    let onRequest = null;
    ws.onopen = () => resolve({
      events,
      setInterceptor(fn) { onRequest = fn; },
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
      } else if (m.method === "Fetch.requestPaused") {
        const p = m.params;
        const fake = onRequest ? onRequest(p.request.url) : null;
        const mid = ++id;
        if (fake) {
          ws.send(JSON.stringify({ id: mid, method: "Fetch.fulfillRequest", params: {
            requestId: p.requestId, responseCode: fake.code,
            responseHeaders: [{ name: "Content-Type", value: "application/json" }],
            body: Buffer.from(JSON.stringify(fake.body || {})).toString("base64"),
          } }));
        } else {
          ws.send(JSON.stringify({ id: mid, method: "Fetch.continueRequest", params: { requestId: p.requestId } }));
        }
      } else if (m.method === "Runtime.exceptionThrown") {
        events.push("EXC: " + (m.params.exceptionDetails.exception?.description || "").split("\n")[0]);
      }
    };
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function evalJs(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

(async () => {
  const exe = CANDIDATES.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到浏览器"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "r2b-iv-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, name, extra) => {
    if (!ok) fail++;
    console.log(`${ok ? "OK" : "!!"} ${name}${extra ? "  " + extra : ""}`);
  };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable"); await c.send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

    // ---- 管理端登录 ----
    await c.send("Page.navigate", { url: BASE + "/admin/login" });
    await sleep(1200);
    await evalJs(c, `fetch('/api/auth/login',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'admin',password:'admin123'})}).then(r=>r.status)`, true);
    await c.send("Page.navigate", { url: BASE + "/admin/dashboard" });
    await sleep(2500);

    // ---- A. 在线：三个创新视图 ----
    console.log("\n=== A. 在线渲染（真实数据） ===");
    for (const v of [
      { view: "coords", loader: "loadCoords", probe: "document.querySelectorAll('#table-coords tbody tr, table tbody tr').length", label: "柜体坐标" },
      { view: "materials", loader: "loadMaterials", probe: "document.querySelectorAll('#table-materials tbody tr, table tbody tr').length", label: "备包装清单" },
      { view: "payments", loader: "loadPayments", probe: "document.querySelectorAll('#table-payments tbody tr').length", label: "支付流水" },
    ]) {
      const switched = await evalJs(c, `(function(){
        if (typeof switchView === 'function') { switchView('${v.view}'); return 'switchView'; }
        var el=document.querySelector('[data-view="${v.view}"]'); if(el){el.click();return 'click';}
        return 'none';
      })()`);
      await sleep(1800);
      const st = await evalJs(c, `(function(){
        var sec=document.getElementById('view-${v.view}');
        var txt=(sec? sec.innerText : (document.body.innerText||'')).replace(/\\s+/g,' ').trim();
        var rows=sec? sec.querySelectorAll('tbody tr').length : 0;
        var warn=sec? sec.querySelector('.admin-warn:not([hidden])') : null;
        return JSON.stringify({len:txt.length, rows:rows, sample:txt.slice(0,170),
          warn: warn? warn.innerText.replace(/\\s+/g,' ').trim().slice(0,80):''});
      })()`);
      let o = {}; try { o = JSON.parse(st); } catch (e) { o = { len: 0, rows: 0, sample: String(st) }; }
      R(o.len > 30, `管理端「${v.label}」渲染`, `switch=${switched} len=${o.len} rows=${o.rows}`);
      console.log(`     样本: ${String(o.sample).replace(/"/g, "'")}`);
      if (o.warn) console.log(`     提示条: ${o.warn}`);
    }

    // ---- B. 降级：拦截创新接口全返回 500 ----
    console.log("\n=== B. 降级（接口全部 500，断言不白屏且有提示） ===");
    c.setInterceptor((url) => {
      if (/\/api\/(pack-materials|courier\/packaging-tasks|pay\/records|cabinets\/nearby|ai\/|map\/config|location\/resolve)/.test(url)) {
        return { code: 500, body: { error: "服务端暂时不可用（压测降级模拟）", code: "INTERNAL_ERROR" } };
      }
      return null;
    });
    for (const v of [
      { view: "materials", loader: "loadMaterials", label: "备包装清单" },
      { view: "payments", loader: "loadPayments", label: "支付流水" },
    ]) {
      await evalJs(c, `(function(){
        if (typeof switchView === 'function') { switchView('${v.view}'); }
        try { if (typeof ${v.loader} === 'function') ${v.loader}(1); } catch(e) {}
        return 1;
      })()`);
      await sleep(2200);
      const st = await evalJs(c, `(function(){
        var sec=document.getElementById('view-${v.view}');
        var warn=sec? sec.querySelector('.admin-warn:not([hidden])') : null;
        var txt=sec? (sec.innerText||'').replace(/\\s+/g,' ').trim() : '';
        var bodyLen=(document.body.innerText||'').trim().length;
        return JSON.stringify({bodyLen:bodyLen, warn: warn? warn.innerText.replace(/\\s+/g,' ').trim().slice(0,100):'', textLen:txt.length, sample:txt.slice(0,120)});
      })()`);
      let o = {}; try { o = JSON.parse(st); } catch (e) { o = { bodyLen: 0, warn: "", textLen: 0 }; }
      const soft = /暂未|不可用|失败|稍后|错误|不可|暂不/.test(o.warn + o.sample);
      R(o.bodyLen > 100 && (o.warn.length > 0 || soft),
        `管理端「${v.label}」降级`, `bodyLen=${o.bodyLen} warn="${o.warn}" textLen=${o.textLen}`);
      console.log(`     降级视图样本: ${String(o.sample).replace(/"/g, "'")}`);
    }

    // ---- C. 触屏端 AI 入口降级 ----
    console.log("\n=== C. 触屏端 AI 入口（接口 500） ===");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(3000);
    const k = await evalJs(c, `(function(){
      var b=document.body.innerText||'';
      var entry=document.querySelector('.hae-btn');
      var entryTxt=entry? (entry.innerText||'').trim():'';
      if(typeof go==='function'){ go('ai-help'); }
      else if(entry){ entry.click(); }
      return JSON.stringify({bodyLen:b.trim().length, hasEntry:!!entry, entryTxt:entryTxt});
    })()`);
    let ko = {}; try { ko = JSON.parse(k); } catch (e) { ko = {}; }
    await sleep(1800);
    R(ko.bodyLen > 100 && ko.hasEntry, "触屏端 AI 入口存在且页面正常",
      `bodyLen=${ko.bodyLen} hasEntry=${ko.hasEntry} entryTxt="${ko.entryTxt}"`);

    const kAfter = await evalJs(c, `(function(){
      var s=document.getElementById('screen-ai-help');
      var active=s? s.classList.contains('active') : false;
      var t=s? (s.innerText||'').replace(/\\s+/g,' ').trim() : '';
      var log=document.getElementById('kaiLog');
      var hint=document.getElementById('kaiHint');
      return JSON.stringify({active:active, len:t.length, sample:t.slice(0,150),
        logMsgs: log? log.querySelectorAll('.kai-msg').length:0,
        hint: hint? (hint.innerText||'').trim().slice(0,80):''});
    })()`);
    let ka = {}; try { ka = JSON.parse(kAfter); } catch (e) { ka = {}; }
    R(ka.active && ka.len > 30, "触屏端 AI 屏可见且不白屏", `active=${ka.active} len=${ka.len} logMsgs=${ka.logMsgs}`);
    console.log(`     AI 屏样本: ${String(ka.sample).replace(/"/g, "'")}`);
    if (ka.hint) console.log(`     提示: ${ka.hint}`);

    if (c.events.length) {
      console.log("\nJS 异常:");
      c.events.slice(0, 6).forEach((e) => console.log("   " + e));
    } else {
      console.log("\n无未捕获 JS 异常");
    }
    c.close();
  } catch (e) {
    console.log("!! 异常:", e.message); fail++;
  } finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：创新视图渲染与降级全部通过");
  process.exit(fail ? 1 : 0);
})();
