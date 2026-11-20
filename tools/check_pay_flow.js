/* BUG1 支付状态机验证：create → mock-succeed → 轮询到 SUCCESS → 放行回调
 * 用真实后端跑完整闭环，确认「只有 SUCCESS 才放行」。
 * 用法： node tools/check_pay_flow.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9341;
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
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "payflow-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, n, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${n}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    // 后台管理端登录（用于 mock-succeed），并注入 kiosk 用户 token
    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2000);
    const prep = await ej(c, `(async function(){
      // 用户 token（触屏端身份）
      var r = await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({role:'USER',phone:'15800000001'})});
      var j = await r.json();
      if(!j.token) return JSON.stringify({ok:false,err:'user login failed'});
      sessionStorage.setItem('kiosk_token', j.token);
      // 管理员 Cookie（mock-succeed 需要 admin）
      var ar = await fetch('/api/auth/login',{method:'POST',credentials:'include',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:'admin',password:'admin123'})});
      var aj = await ar.json();
      // 取包裹
      var pr = await fetch('/api/m/packages',{headers:{Authorization:'Bearer '+j.token}});
      var pk = await pr.json();
      var list = (pk.pending||[]).concat(pk.history||[]);
      return JSON.stringify({ok:true, user:j.identity.name, admin:aj.user?aj.user.role:'?',
        packageId: list.length? list[0].package_id : null});
    })()`, true);
    let p = {}; try { p = JSON.parse(prep); } catch (e) { p = { ok: false }; }
    R(p.ok && p.packageId, "准备登录态与包裹", `user=${p.user} admin=${p.admin} pkg=${p.packageId}`);
    if (!p.ok) throw new Error("准备失败");

    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2500);

    // 触发支付，注册放行回调
    await ej(c, `(function(){
      window.__paidCb = false;
      startPay([${p.packageId}], '¥1.00', function(){ window.__paidCb = true; });
      return 1;
    })()`);
    await sleep(3000);

    const st1 = await ej(c, `JSON.stringify({
      payId: payState && payState.payId,
      status: document.getElementById('payProgress').textContent,
      paid: window.__paidCb
    })`);
    let s1 = {}; try { s1 = JSON.parse(st1); } catch (e) {}
    R(!!s1.payId, "已创建支付单", `payId=${s1.payId}`);
    R(s1.paid === false, "支付未完成时不放行", `回调已触发=${s1.paid} 状态="${s1.status}"`);

    // 管理端把该单置为成功
    const ms = await ej(c, `(async function(){
      var r = await fetch('/api/pay/${s1.payId}/mock-succeed', {method:'POST', credentials:'include',
        headers:{'Content-Type':'application/json'}, body:'{}'});
      var j = await r.json();
      return JSON.stringify({status:r.status, resp:JSON.stringify(j).slice(0,150)});
    })()`, true);
    let mres = {}; try { mres = JSON.parse(ms); } catch (e) {}
    console.log(`     mock-succeed: HTTP ${mres.status} ${mres.resp || ""}`);

    // 等待轮询到 SUCCESS（轮询间隔 2s）
    await sleep(6000);
    const st2 = await ej(c, `(function(){
      var prog = document.getElementById('payProgress');
      var modal = document.getElementById('payModal');
      return JSON.stringify({
        paid: window.__paidCb,
        progress: prog ? prog.textContent : '',
        progressCls: prog ? prog.className : '',
        modalShown: modal ? modal.classList.contains('show') : null
      });
    })()`);
    let s2 = {}; try { s2 = JSON.parse(st2); } catch (e) {}
    R(s2.paid === true, "轮询到 SUCCESS 后触发放行回调", `progress="${s2.progress}" paid=${s2.paid}`);
    R(/支付成功|✅/.test(s2.progress || ""), "界面明确提示支付成功", `"${s2.progress}"`);
    R(s2.modalShown === false, "支付成功后弹层自动关闭", `modalShown=${s2.modalShown}`);

    // 二次确认：服务端状态确实成功
    const verify = await ej(c, `(async function(){
      var r = await fetch('/api/pay/${s1.payId}', {credentials:'include'});
      var j = await r.json();
      return JSON.stringify({status:j.status, amount:j.amount, mock:j.mock, label:j.provider_label});
    })()`, true);
    let v = {}; try { v = JSON.parse(verify); } catch (e) {}
    R(v.status === "SUCCESS", "服务端支付单状态为 SUCCESS", JSON.stringify(v));

    // 验证：GET /pay/{id} 不返回 qr_code_url（契约事实）
    const noQr = await ej(c, `(async function(){
      var r = await fetch('/api/pay/${s1.payId}', {credentials:'include'});
      var j = await r.json();
      return JSON.stringify({hasQr: 'qr_code_url' in j, hasRedirect: 'redirect_url' in j, keys:Object.keys(j).length});
    })()`, true);
    console.log(`     GET /pay/{id} 字段检查: ${noQr}`);

    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：支付状态机闭环全部通过");
  process.exit(fail ? 1 : 0);
})();
