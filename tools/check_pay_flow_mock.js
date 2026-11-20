/* 支付状态机闭环验证（mock 模式）：create → mock-succeed → 轮询 SUCCESS → 放行
 * mock 模式下 mock-succeed 才被允许，可完整验证「只有 SUCCESS 才放行」。
 * 用法： node tools/check_pay_flow_mock.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9342;
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
    let id = 0; const pend = new Map();
    ws.onopen = () => resolve({
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
      }
    };
  });
}
async function ej(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) return { __err: (r.exceptionDetails.exception?.description || r.exceptionDetails.text) };
  return r.result.value;
}

(async () => {
  const exe = CAND.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "paymock-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, n, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${n}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable");

    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2000);

    // 注入用户 token + 管理员 Cookie，并强制 mock 通道建单
    const prep = await ej(c, `(async function(){
      var r = await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({role:'USER',phone:'15800000001'})});
      var j = await r.json();
      if(!j.token) return JSON.stringify({ok:false});
      sessionStorage.setItem('kiosk_token', j.token);
      await fetch('/api/auth/login',{method:'POST',credentials:'include',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:'admin',password:'admin123'})});
      var pr = await fetch('/api/m/packages',{headers:{Authorization:'Bearer '+j.token}});
      var pk = await pr.json();
      var list = (pk.pending||[]).concat(pk.history||[]);
      return JSON.stringify({ok:true, packageId: list.length? list[0].package_id : null, token:j.token});
    })()`, true);
    let p = {}; try { p = JSON.parse(prep); } catch (e) {}
    R(p.ok && p.packageId, "准备登录态", `pkg=${p.packageId}`);
    if (!p.ok) throw new Error("准备失败");

    // 直接建 mock 单（admin 身份可为任意包裹建 mock 单）
    const mk = await ej(c, `(async function(){
      var r = await fetch('/api/pay/create',{method:'POST',credentials:'include',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({biz_type:'OVERTIME', biz_id:${p.packageId}, provider:'mock'})});
      var j = await r.json();
      return JSON.stringify({status:r.status, payId:j.pay_id, mock:j.mock,
        label:j.provider_label, qr:j.qr_code_url, redirect:!!j.redirect_url, err:j.error||null});
    })()`, true);
    let mkp = {}; try { mkp = JSON.parse(mk); } catch (e) {}
    console.log(`     建 mock 单: ${mk}`);
    R(mkp.status === 200 && mkp.payId, "mock 模式建单成功", `payId=${mkp.payId}`);
    R(mkp.mock === true && /模拟/.test(mkp.label || ""), "mock 标识由服务端下发",
      `mock=${mkp.mock} label="${mkp.label}"`);
    R(!mkp.qr, "mock 单不返回 qr_code_url（符合契约）", `qr=${JSON.stringify(mkp.qr)}`);

    // 用前端轮询逻辑验证：先 PENDING 不放行，再置成功，验证放行
    const flow = await ej(c, `(async function(){
      var payId = ${mkp.payId};
      // 模拟 kiosk 的 payState，直接调用 pollPayOnce 的核心判定：查状态
      var r1 = await fetch('/api/pay/' + payId, {credentials:'include'});
      var j1 = await r1.json();
      var meta1 = payStatusMeta(j1.status);
      var paidBefore = payIsSuccess(j1.status);

      // 置为成功
      var r2 = await fetch('/api/pay/' + payId + '/mock-succeed', {method:'POST', credentials:'include',
        headers:{'Content-Type':'application/json'}, body:'{}'});
      var j2 = await r2.json();

      var r3 = await fetch('/api/pay/' + payId, {credentials:'include'});
      var j3 = await r3.json();
      var paidAfter = payIsSuccess(j3.status);
      return JSON.stringify({
        before: j1.status, beforeCn: meta1.cn, paidBefore: paidBefore,
        succeedStatus: r2.status, succeedBody: JSON.stringify(j2).slice(0,100),
        after: j3.status, paidAfter: paidAfter,
        qrInGet: 'qr_code_url' in j3
      });
    })()`, true);
    let f = {}; try { f = JSON.parse(flow); } catch (e) {}
    console.log(`     状态流转: ${JSON.stringify(f)}`);
    R(f.before === "PENDING" && f.paidBefore === false,
      "PENDING 状态判定为未支付（不放行）", `before=${f.before}(${f.beforeCn})`);
    R(f.succeedStatus === 200, "mock 模式下 mock-succeed 可用", `HTTP ${f.succeedStatus}`);
    R(f.after === "SUCCESS" && f.paidAfter === true,
      "SUCCESS 状态判定为已支付（放行）", `after=${f.after}`);
    R(f.qrInGet === false, "GET /api/pay/{id} 不含 qr_code_url（契约事实已确认）");

    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：支付状态机（mock 闭环）全部通过");
  process.exit(fail ? 1 : 0);
})();
