/* BUG2 核对：H5 寄件表单寄件人地址字段
 * 1) 字段是否渲染、分组标题是否可见
 * 2) 填写后提交，抓取实际发出的 send-order 请求体，确认字段随单提交
 * 3) 不填地址时仍能提交（不阻断原流程）
 * 用法： node tools/check_sender_address.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9337;
const CAND = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let d = ""; r.on("data", (c) => (d += c)); r.on("end", () => res(d)); }).on("error", rej);
  });
}
async function waitDevtools() {
  for (let i = 0; i < 60; i++) {
    try { return JSON.parse(await get(`http://127.0.0.1:${PORT}/json/version`)); }
    catch (e) { await sleep(300); }
  }
  throw new Error("DevTools 未就绪");
}
function cdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0; const pend = new Map(); const reqs = []; const persisted = [];
    ws.onopen = () => resolve({
      reqs, persisted,
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
      } else if (m.method === "Network.requestWillBeSent") {
        const rq = m.params.request;
        if (/send-order/.test(rq.url)) reqs.push({ method: rq.method, body: rq.postData || "" });
      } else if (m.method === "Network.responseReceived") {
        if (/send-order/.test(m.params.response.url)) persisted.push(m.params.response.status);
      }
    };
  });
}
async function ej(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise });
  return r.exceptionDetails ? { __err: r.exceptionDetails.text } : r.result.value;
}

(async () => {
  const exe = CAND.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "bug2-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, n, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${n}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable"); await c.send("Network.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 500, height: 900, deviceScaleFactor: 1, mobile: true });

    await c.send("Page.navigate", { url: BASE + "/m/" });
    await sleep(2200);
    // 登录注入 token
    const tk = await ej(c, `(async function(){
      var r=await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({role:'USER',phone:'15800000001'})});
      var j=await r.json(); if(j.token) localStorage.setItem('m_token',j.token); return j.token||'';})()`, true);
    console.log(`token: ${String(tk).slice(0, 24)}...`);
    await c.send("Page.navigate", { url: BASE + "/m/" });
    await sleep(2800);

    // ---- 1. 字段渲染 ----
    const st = await ej(c, `(function(){
      var s=document.getElementById('screen-send');
      var a=document.getElementById('sendSenderAddress');
      var n=document.getElementById('sendSenderName');
      var ra=document.getElementById('sendRecipientAddress');
      var titles=[].slice.call(s?s.querySelectorAll('.field-group-title'):[]).map(function(x){return x.innerText.trim();});
      return JSON.stringify({hasAddr:!!a, hasName:!!n, hasRecipAddr:!!ra, titles:titles,
        addrRequired: a? a.required : null, addrMax: a? a.maxLength : null,
        namePrefill: n? n.value : null});
    })()`);
    let o = {}; try { o = JSON.parse(st); } catch (e) { o = {}; }
    R(o.hasAddr, "寄件表单有「寄件人地址」输入框", `maxlength=${o.addrMax} required=${o.addrRequired}`);
    R(o.hasRecipAddr, "寄件表单有「收件人地址」输入框（对称）");
    R(Array.isArray(o.titles) && o.titles.length >= 2, "寄件人/收件人分组标题可见", JSON.stringify(o.titles));
    R(o.namePrefill === "卢秀华" || (o.namePrefill || "").length > 0, "寄件人姓名默认预填账号姓名", `"${o.namePrefill}"`);
    R(o.addrRequired === false, "地址为非必填（不阻断原流程）", `required=${o.addrRequired}`);

    // ---- 2. 切到寄件页并填写提交（带地址） ----
    await ej(c, `(function(){ var t=document.querySelector('[data-tab="send"]'); if(t) t.click(); return 1; })()`);
    await sleep(1200);
    const filled = await ej(c, `(function(){
      document.getElementById('sendSenderAddress').value = '阳光花园小区 3 栋 502 室';
      document.getElementById('sendRecipientName').value = '王测试';
      document.getElementById('sendRecipientPhone').value = '13900005678';
      document.getElementById('sendRecipientAddress').value = '北京市朝阳区建国路 88 号';
      document.getElementById('sendNote').value = 'BUG2 浏览器实测';
      // 选一个有空闲小件的柜体
      var sel=document.getElementById('sendCabinet');
      var pick=null;
      for (var i=0;i<sel.options.length;i++){ if(/CAB-026|CAB-024|CAB-019|CAB-020/.test(sel.options[i].textContent)){pick=sel.options[i].value;break;} }
      if(pick) sel.value=pick;
      document.getElementById('sendSize').value='SMALL';
      document.getElementById('sendWeight').value='1';
      return JSON.stringify({cabinet:sel.value, cabText: sel.options[sel.selectedIndex]?sel.options[sel.selectedIndex].textContent:'',
        addr:document.getElementById('sendSenderAddress').value});
    })()`);
    console.log(`     填写: ${filled}`);

    const res20 = await ej(c, `(function(){ document.getElementById('btnSend').click(); return 1; })()`);
    await sleep(3500);

    const sent = c.reqs.filter((r) => /send-order/.test(""));
    const bodySent = c.reqs.length ? c.reqs[c.reqs.length - 1].body : "";
    let parsed = {}; try { parsed = JSON.parse(bodySent); } catch (e) {}
    R(!!bodySent, "点击「下单并开柜」确实发出了 send-order 请求", `请求数=${c.reqs.length}`);
    R(parsed.sender_address === "阳光花园小区 3 栋 502 室",
      "请求体携带 sender_address", `sender_address="${parsed.sender_address}"`);
    R(parsed.recipient_address === "北京市朝阳区建国路 88 号",
      "请求体携带 recipient_address", `recipient_address="${parsed.recipient_address}"`);
    console.log(`     请求体: ${bodySent.slice(0, 260)}`);

    const ui = await ej(c, `(function(){
      var r=document.getElementById('sendResult');
      var e=document.getElementById('sendErr');
      return JSON.stringify({resultVisible: r? !r.hidden : null, code: document.getElementById('srCode')?.textContent,
        err: e? e.textContent : '', bodyLen:(document.body.innerText||'').trim().length});
    })()`);
    let uiO = {}; try { uiO = JSON.parse(ui); } catch (e) {}
    R(uiO.resultVisible === true && uiO.err === "", "带地址下单成功（页面显示揽收码）",
      `code=${uiO.code} err="${uiO.err}"`);

    // ---- 3. 不填地址回归 ----
    c.reqs.length = 0;
    await ej(c, `(function(){
      document.getElementById('sendSenderAddress').value = '';
      document.getElementById('sendRecipientAddress').value = '';
      document.getElementById('sendRecipientPhone').value = '13900005679';
      document.getElementById('sendNote').value = 'BUG2 无地址回归';
      return 1;
    })()`);
    await ej(c, `(function(){ document.getElementById('btnSend').click(); return 1; })()`);
    await sleep(3500);
    const body2 = c.reqs.length ? c.reqs[c.reqs.length - 1].body : "";
    let p2 = {}; try { p2 = JSON.parse(body2); } catch (e) {}
    R(!!body2 && p2.sender_address === null, "不填地址时字段为 null 且请求照常发出",
      `sender_address=${JSON.stringify(p2.sender_address)} recipient_address=${JSON.stringify(p2.recipient_address)}`);
    const ui2 = await ej(c, `(function(){
      var r=document.getElementById('sendResult'); var e=document.getElementById('sendErr');
      return JSON.stringify({resultVisible: r? !r.hidden : null, code: document.getElementById('srCode')?.textContent, err: e? e.textContent:''});
    })()`);
    let u2 = {}; try { u2 = JSON.parse(ui2); } catch (e) {}
    R(u2.resultVisible === true && u2.err === "", "无地址仍能正常下单（原流程未被破坏）",
      `code=${u2.code} err="${u2.err}"`);

    console.log(`\n     send-order 响应状态: ${JSON.stringify(c.persisted)}`);

    // 截图存档
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    const outDir = path.resolve(__dirname, "..", "..", "frontend-verify");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, "send-form-address.png"), Buffer.from(shot.data, "base64"));
    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：寄件人地址字段全部通过");
  process.exit(fail ? 1 : 0);
})();
