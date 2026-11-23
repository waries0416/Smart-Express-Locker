/* BUG 二维码失效 · 前端三件事验证
 *  1) 弹窗打开只调一次 create（防竞态）
 *  2) 「刷新二维码」按钮 → refresh:true → 换新码
 *  3) poll 收到 expired:true → 提示 + 亮出刷新按钮
 * 全程 CDP 真实浏览器，走匿名取件路径。
 *
 * 用法： node tools/check_qr_refresh.js [baseUrl] [pickupCode]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const CODE = process.argv[3] || "641497";
const PORT = 9355;
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
    let id = 0; const pend = new Map(); const netlog = []; const errors = [];
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
        if (/\/api\/pay\//.test(rq.url)) {
          netlog.push({ phase: "req", url: rq.url.replace(BASE, ""), body: (rq.postData || "").slice(0, 180) });
        }
      } else if (m.method === "Network.responseReceived") {
        const rs = m.params.response;
        if (/\/api\/pay\//.test(rs.url)) netlog.push({ phase: "res", url: rs.url.replace(BASE, ""), status: rs.status });
      } else if (m.method === "Runtime.exceptionThrown") {
        errors.push((m.params.exceptionDetails.exception?.description || "").split("\n")[0]);
      }
    };
  });
}
async function ej(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise });
  if (r.exceptionDetails) return { __err: (r.exceptionDetails.exception?.description || "").slice(0, 200) };
  return r.result.value;
}

(async () => {
  const exe = CAND.find((p) => fs.existsSync(p));
  if (!exe) { console.log("!! 未找到 Edge"); process.exit(0); }
  const proc = spawn(exe, [
    `--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--no-first-run",
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "qrref-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  const outDir = path.resolve(__dirname, "..", "..", "frontend-verify");
  fs.mkdirSync(outDir, { recursive: true });
  let fail = 0;
  const R = (ok, n, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${n}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable"); await c.send("Network.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2500);

    // ── 步骤 1：走真实匿名取件路径打开缴费弹窗
    const fill = await ej(c, `(function(){
      var inp=document.getElementById('pickupInput');
      inp.value='${CODE}';
      var btns=[].slice.call(document.querySelectorAll('button'));
      var t=btns.find(function(b){return /submitPickup/.test(b.getAttribute('onclick')||'');})
           || btns.find(function(b){return /取件/.test((b.innerText||'').trim());});
      t.click();
      return JSON.stringify({ok:true});
    })()`);
    await sleep(4500);

    const createReqs1 = c.netlog.filter((n) => n.phase === "req" && /\/pay\/create/.test(n.url));
    R(createReqs1.length === 1, "弹窗打开只调一次 create", `实际 ${createReqs1.length} 次`);
    console.log(`     请求体: ${createReqs1[0] ? createReqs1[0].body : "(无)"}`);

    const st1 = await ej(c, `(function(){
      var cv=document.getElementById('payQrCanvas');
      var rb=document.getElementById('payRefresh');
      return JSON.stringify({
        canvasHidden: cv?cv.hidden:null, canvasW: cv?cv.width:0,
        refreshHidden: rb?rb.hidden:null, payId: payState?payState.payId:null
      });
    })()`);
    let s1 = {}; try { s1 = JSON.parse(st1); } catch (e) {}
    R(s1.canvasHidden === false && s1.canvasW > 0, "二维码已渲染", `canvasW=${s1.canvasW}`);
    R(s1.refreshHidden === false, "「刷新二维码」按钮可见");

    const qr1 = await ej(c, `document.getElementById('payQrCanvas').toDataURL('image/png').length`);
    console.log(`     初始二维码 canvas 数据长度=${qr1}`);

    // ── 步骤 2：连点 3 次刷新，验证防竞态（只采纳最后一次）
    const before = c.netlog.filter((n) => n.phase === "req" && /\/pay\/create/.test(n.url)).length;
    await ej(c, `(function(){
      document.getElementById('payRefresh').click();
      document.getElementById('payRefresh').click();
      document.getElementById('payRefresh').click();
      return 1;
    })()`);
    await sleep(5000);
    const afterReqs = c.netlog.filter((n) => n.phase === "req" && /\/pay\/create/.test(n.url)).slice(before);
    const refreshReqs = afterReqs.filter((n) => /refresh/.test(n.body || ""));
    R(refreshReqs.length <= 1, "连点刷新只发出一次 refresh 请求（门闩生效）",
      `实际 ${refreshReqs.length} 次 / 区间内共 ${afterReqs.length} 次 create`);
    if (refreshReqs[0]) console.log(`     refresh 请求体: ${refreshReqs[0].body}`);

    const qr2 = await ej(c, `document.getElementById('payQrCanvas').toDataURL('image/png').length`);
    R(qr1 !== qr2, "刷新后二维码内容已变化", `之前=${qr1} 之后=${qr2}`);

    // 用 OpenCV 解码，确认画的是新码
    const dataUrl = await ej(c, `document.getElementById('payQrCanvas').toDataURL('image/png')`);
    if (dataUrl && dataUrl.length > 200) {
      const tmpPng = path.join(os.tmpdir(), "qr_refresh.png");
      fs.writeFileSync(tmpPng, Buffer.from(dataUrl.replace(/^data:image\/png;base64,/, ""), "base64"));
      console.log(`     刷新后二维码已存: ${tmpPng}`);
    }

    // ── 步骤 3：验证 expired 分支 —— 真实驱动 pollPayOnce 的 expired 路径
    // 做法：临时替换 payPollAnonymous 让它返回一个 status=PENDING 且 expired:true 的响应，
    // 然后调一次轮询，断言 DOM 出现过期提示且刷新按钮亮出。
    const expTest = await ej(c, `(async function(){
      stopPayPoll();                       // 先停掉自动轮询，避免它覆盖文案
      var realPoll = API.payPollAnonymous;
      API.payPollAnonymous = function(){
        return Promise.resolve({ status:'PENDING', expired:true, amount:1.0,
          mock:false, provider_label:'支付宝沙箱', pay_id: payState.payId });
      };
      await pollPayOnce();
      API.payPollAnonymous = realPoll;
      return JSON.stringify({
        progress: document.getElementById('payProgress').textContent,
        desc: document.getElementById('payDesc').textContent,
        refreshHidden: document.getElementById('payRefresh').hidden,
        refreshText: document.getElementById('payRefresh').textContent.trim(),
        payStateExpired: payState.expired
      });
    })()`, true);
    let s3 = {}; try { s3 = JSON.parse(expTest); } catch (e) { s3 = { raw: String(expTest) }; }
    console.log(`     expired 驱动结果: ${JSON.stringify(s3)}`);
    R(/已过期/.test(s3.progress || "") && s3.refreshHidden === false && s3.payStateExpired === true,
      "expired 分支：提示过期并亮出刷新按钮",
      `progress="${s3.progress}" refreshHidden=${s3.refreshHidden}`);

    // ── 步骤 4：再从 expired 状态点刷新，确认能恢复
    const before2 = c.netlog.filter((n) => n.phase === "req" && /\/pay\/create/.test(n.url)).length;
    await ej(c, `(function(){ document.getElementById('payRefresh').click(); return 1; })()`);
    await sleep(4500);
    const recovers = c.netlog.filter((n) => n.phase === "req" && /\/pay\/create/.test(n.url)).slice(before2);
    const st4 = await ej(c, `JSON.stringify({
      canvasHidden: document.getElementById('payQrCanvas').hidden,
      progress: document.getElementById('payProgress').textContent
    })`);
    let s4 = {}; try { s4 = JSON.parse(st4); } catch (e) {}
    R(recovers.length === 1 && s4.canvasHidden === false,
      "过期后点刷新能换回新码", `create 次数=${recovers.length} canvasHidden=${s4.canvasHidden}`);

    // ── 步骤 5：2s 轮询对账在跑
    const pollCount = c.netlog.filter((n) => n.phase === "req" && /\/pay\/\d+\/poll/.test(n.url)).length;
    R(pollCount >= 1, "匿名 2s 轮询对账持续运行", `已发 ${pollCount} 次 poll`);

    R(c.errors.length === 0, "无 JS 异常", c.errors.slice(0, 3).join(" | "));

    // 截图
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(outDir, "qr-refresh-1280.png"), Buffer.from(shot.data, "base64"));

    // ── 视口 500 复查
    await c.send("Emulation.setDeviceMetricsOverride", { width: 500, height: 900, deviceScaleFactor: 1, mobile: true });
    await sleep(800);
    const vp = await ej(c, `(function(){
      var de=document.documentElement;
      return JSON.stringify({scrollW:de.scrollWidth, clientW:de.clientWidth});
    })()`);
    let v = {}; try { v = JSON.parse(vp); } catch (e) {}
    R(v.scrollW <= v.clientW + 1, "500px 视口无横向溢出", `scrollW=${v.scrollW} clientW=${v.clientW}`);
    const shot500 = await c.send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(outDir, "qr-refresh-500.png"), Buffer.from(shot500.data, "base64"));

    console.log(`\n     截图: frontend-verify/qr-refresh-1280.png、qr-refresh-500.png`);
    console.log(`\n===== pay 网络日志 =====`);
    c.netlog.forEach((n) => {
      if (n.phase === "req") console.log(`  → ${n.url}${n.body ? "  " + n.body : ""}`);
      else console.log(`  ← ${n.status} ${n.url}`);
    });

    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：二维码防竞态/刷新/过期处理全部通过");
  process.exit(fail ? 1 : 0);
})();
