/* BUG1 真实用户路径复现：触屏端输入取件码 → 点取件 → 触发超时缴费 → 检查二维码
 *
 * 严格模拟用户操作：不直接调用 startPay()，而是走 UI：
 *   #pickupInput 输入取件码 → submitPickup() → 后端 402 → startPay() → 弹层
 * 全程录制网络请求（pay/create / pay/{id}）、DOM 状态、JS 异常。
 *
 * 用法： node tools/repro_user_path.js [baseUrl] [pickupCode] [--login]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const CODE = process.argv[3] || "641497";
const DO_LOGIN = process.argv.includes("--login");
const PORT = 9350;
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
    let id = 0;
    const pend = new Map();
    const netlog = [];   // 网络日志
    const errors = [];   // JS 异常
    ws.onopen = () => resolve({
      netlog, errors,
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
        return;
      }
      if (m.method === "Network.requestWillBeSent") {
        const rq = m.params.request;
        if (/\/api\//.test(rq.url)) {
          netlog.push({ phase: "req", url: rq.url.replace(BASE, ""), method: rq.method,
                        body: (rq.postData || "").slice(0, 200), ts: Date.now() });
        }
      } else if (m.method === "Network.responseReceived") {
        const rs = m.params.response;
        if (/\/api\//.test(rs.url)) {
          netlog.push({ phase: "res", url: rs.url.replace(BASE, ""), status: rs.status, ts: Date.now() });
        }
      } else if (m.method === "Runtime.exceptionThrown") {
        errors.push((m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text || "").split("\n").slice(0, 3).join(" | "));
      } else if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
        errors.push("console.error: " + (m.params.args[0]?.value || "").toString().slice(0, 200));
      }
    };
  });
}

async function ej(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) {
    return { __err: (r.exceptionDetails.exception?.description || r.exceptionDetails.text || "").slice(0, 300) };
  }
  return r.result.value;
}

(async () => {
  const exe = CAND.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "repro-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  const outDir = path.resolve(__dirname, "..", "..", "frontend-verify");
  fs.mkdirSync(outDir, { recursive: true });

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable");
    await c.send("Runtime.enable");
    await c.send("Network.enable");
    await c.send("Emulation.setDeviceMetricsOverride",
      { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    console.log(`\n===== 复现用户真实路径（取件码 ${CODE}，登录态=${DO_LOGIN ? "已登录" : "未登录"}）=====\n`);

    // ── 打开触屏端（模拟用户看到的第一屏）
    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2500);

    if (DO_LOGIN) {
      const li = await ej(c, `(async function(){
        var r = await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({role:'USER',phone:'15800000001'})});
        var j = await r.json();
        if(j.token){ sessionStorage.setItem('kiosk_token', j.token);
                     sessionStorage.setItem('kiosk_identity', JSON.stringify(j.identity)); }
        return JSON.stringify({ok:!!j.token, name:j.identity?j.identity.name:null});
      })()`, true);
      console.log(`[登录] ${li}`);
      await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
      await sleep(2500);
    }

    // ── 记录点：清空网络日志，开始走用户操作
    const markStart = c.netlog.length;

    // 步骤 1：把取件码填进输入框（真实 DOM 操作）
    const fill = await ej(c, `(function(){
      var inp = document.getElementById('pickupInput');
      if(!inp) return JSON.stringify({ok:false, err:'找不到取件码输入框 #pickupInput'});
      inp.value = '${CODE}';
      inp.dispatchEvent(new Event('input', {bubbles:true}));
      return JSON.stringify({ok:true, value:inp.value,
        placeholder: inp.getAttribute('placeholder')});
    })()`);
    console.log(`[步骤1 输入取件码] ${fill}`);

    // 步骤 2：点「取件」按钮（用户真实点击）
    const click = await ej(c, `(function(){
      // 优先找真实的取件按钮（onclick=submitPickup 或包含"取件"文案）
      var btns = [].slice.call(document.querySelectorAll('button'));
      var target = btns.find(function(b){
        var oc = (b.getAttribute('onclick')||'');
        return /submitPickup/.test(oc);
      }) || btns.find(function(b){
        return /取件/.test((b.innerText||'').trim());
      });
      if(!target) return JSON.stringify({ok:false, err:'找不到取件按钮',
        buttons: btns.map(function(b){return (b.innerText||'').trim().slice(0,12);}).slice(0,20)});
      var label = (target.innerText||'').trim();
      target.click();
      return JSON.stringify({ok:true, clicked: label});
    })()`);
    console.log(`[步骤2 点击取件] ${click}`);

    // 等待后端 402 → startPay → create 落地
    await sleep(5000);

    // 步骤 3：检查弹层与二维码 DOM
    const dom = await ej(c, `(function(){
      var modal = document.getElementById('payModal');
      var cv = document.getElementById('payQrCanvas');
      var icon = document.getElementById('payQrIcon');
      var box = document.getElementById('payQrBox');
      var jump = document.getElementById('payJump');
      var tag = document.getElementById('payProviderTag');
      var note = document.getElementById('payProviderNote');
      var prog = document.getElementById('payProgress');
      var desc = document.getElementById('payDesc');
      var amt = document.getElementById('payAmount');
      var dark = 0, hasPixels = false;
      if (cv && cv.width > 0) {
        try {
          var d = cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
          for (var i=0;i<d.length;i+=4) if (d[i] < 128) dark++;
          hasPixels = dark > 100;
        } catch(e) { dark = -1; }
      }
      return JSON.stringify({
        modalShown: modal ? modal.classList.contains('show') : null,
        canvasHidden: cv ? cv.hidden : 'no-element',
        canvasW: cv ? cv.width : 0,
        canvasH: cv ? cv.height : 0,
        hasPixels: hasPixels,
        darkPixels: dark,
        iconHidden: icon ? icon.hidden : 'no-element',
        boxClass: box ? box.className : '',
        jumpHidden: jump ? jump.hidden : 'no-element',
        jumpHref: (jump && !jump.hidden) ? (jump.getAttribute('href')||'').slice(0,70) : '',
        providerTag: tag ? tag.textContent : '',
        providerNote: note ? note.textContent : '',
        progress: prog ? prog.textContent : '',
        desc: desc ? desc.textContent : '',
        amount: amt ? amt.textContent : ''
      });
    })()`);
    console.log(`\n[步骤3 弹层状态]\n${dom}\n`);

    // ── 输出完整网络日志（这是"是否调用 create"的铁证）
    const net = c.netlog.slice(markStart);
    console.log(`===== 网络日志（点击后 ${net.length} 条）=====`);
    net.forEach((n) => {
      if (n.phase === "req") {
        console.log(`  → ${n.method.padEnd(4)} ${n.url}${n.body ? "  body=" + n.body : ""}`);
      } else {
        console.log(`  ← ${String(n.status).padEnd(4)} ${n.url}`);
      }
    });

    const createReq = net.find((n) => n.phase === "req" && /\/pay\/create/.test(n.url));
    const createRes = net.find((n) => n.phase === "res" && /\/pay\/create/.test(n.url));
    const pollReq = net.filter((n) => n.phase === "req" && /\/pay\/\d+$/.test(n.url));
    console.log(`\n===== 关键判定 =====`);
    console.log(`  pay/create 请求: ${createReq ? "✅ 已发出  body=" + createReq.body : "❌ 未发出"}`);
    console.log(`  pay/create 响应: ${createRes ? createRes.status : "(无)"}`);
    console.log(`  pay/{id} 轮询次数: ${pollReq.length}`);
    console.log(`  JS 异常数: ${c.errors.length}`);
    c.errors.slice(0, 5).forEach((e) => console.log(`    !! ${e}`));

    // ── 截图
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    const shotPath = path.join(outDir, `repro-user-path-${CODE}.png`);
    fs.writeFileSync(shotPath, Buffer.from(shot.data, "base64"));
    console.log(`\n  截图: frontend-verify/repro-user-path-${CODE}.png`);

    // ── 把结论落成 JSON，便于后续比对
    const report = {
      code: CODE, login: DO_LOGIN,
      createCalled: !!createReq, createBody: createReq ? createReq.body : null,
      createStatus: createRes ? createRes.status : null,
      pollCount: pollReq.length, jsErrors: c.errors,
      dom: (() => { try { return JSON.parse(dom); } catch (e) { return dom; } })(),
      netlog: net,
    };
    fs.writeFileSync(path.join(outDir, `repro-user-path-${CODE}.json`),
      JSON.stringify(report, null, 2), "utf8");

    c.close();
  } catch (e) {
    console.log("!! 异常:", e.message);
  } finally {
    try { proc.kill(); } catch (e) {}
  }
})();
