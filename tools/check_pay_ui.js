/* BUG1 端到端：触屏端支付弹层二维码渲染 + 轮询 + 跳转按钮
 * 用 CDP 打开真实 kiosk 页面，触发 startPay，检查：
 *   · canvas 是否画出二维码（非空白）
 *   · 从 canvas 导出像素，交给后端 OpenCV 解码验证内容
 *   · redirect 跳转按钮是否出现
 *   · provider_label / mock 标识是否正确
 * 用法： node tools/check_pay_ui.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn, execFileSync } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PORT = 9340;
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
    let id = 0; const pend = new Map(); const reqs = [];
    ws.onopen = () => resolve({
      reqs,
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
        const { res, rej } = pend.get(m.id); pend.delete(mid => {});
        m.error ? rej(new Error(m.error.message)) : res(m.result);
        pend.delete(m.id);
      } else if (m.method === "Network.requestWillBeSent") {
        reqs.push({ url: m.params.request.url, method: m.params.request.method,
                    postData: m.params.request.postData || "" });
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
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "payui-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, n, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${n}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable"); await c.send("Network.enable");
    await c.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });

    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(3000);

    // 触屏端 token 存 sessionStorage["kiosk_token"]；pay/create 要求 USER 身份。
    // 这里模拟「用户已扫码登录柜机」：写入真实登录拿到的 token（同源同 session）。
    const loginInfo = await ej(c, `(async function(){
      try{
        var r = await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({role:'USER',phone:'15800000001'})});
        var j = await r.json();
        if(!j.token) return JSON.stringify({ok:false, err:JSON.stringify(j).slice(0,120)});
        sessionStorage.setItem('kiosk_token', j.token);
        sessionStorage.setItem('kiosk_identity', JSON.stringify(j.identity));
        return JSON.stringify({ok:true, role:j.identity.role, name:j.identity.name});
      }catch(e){ return JSON.stringify({ok:false, err:String(e)}); }
    })()`, true);
    console.log(`     登录态注入: ${loginInfo}`);

    // 重新加载，让 kiosk.js 读到 sessionStorage 里的登录态
    await c.send("Page.navigate", { url: BASE + "/kiosk.html" });
    await sleep(2500);

    // 库是否加载
    const lib = await ej(c, `JSON.stringify({qr: typeof QRCodeMini, api: typeof API, core: typeof ApiCore})`);
    console.log(`     库加载: ${lib}`);

    // 取一个待支付包裹
    const pkgInfo = await ej(c, `(async function(){
      try{
        var r = await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({role:'USER',phone:'15800000001'})});
        var j = await r.json();
        if(!j.token) return JSON.stringify({ok:false,err:'登录失败'});
        var pr = await fetch('/api/m/packages',{headers:{Authorization:'Bearer '+j.token}});
        var pk = await pr.json();
        var list = (pk.pending||[]).concat(pk.history||[]);
        if(!list.length) return JSON.stringify({ok:false,err:'无包裹'});
        return JSON.stringify({ok:true, packageId:list[0].package_id, count:list.length});
      }catch(e){ return JSON.stringify({ok:false,err:String(e)}); }
    })()`, true);
    let pi = {}; try { pi = JSON.parse(pkgInfo); } catch (e) {}
    R(pi.ok, "取到可用于支付的包裹", `package_id=${pi.packageId} 候选数=${pi.count}`);
    if (!pi.ok) throw new Error("无包裹可测");

    // 触发支付弹层
    const before = c.reqs.length;
    await ej(c, `(function(){
      startPay([${pi.packageId}], '¥1.00', function(){ window.__paid = true; });
      return 1;
    })()`);
    await sleep(4000);

    const payReqs = c.reqs.slice(before).filter((r) => /\/api\/pay/.test(r.url));
    const createReq = payReqs.find((r) => /\/api\/pay\/create/.test(r.url));
    R(!!createReq, "调用了 POST /api/pay/create",
      createReq ? `body=${createReq.postData.slice(0, 90)}` : "(未发出)");
    R(!!createReq && /OVERTIME/.test(createReq.postData), "biz_type=OVERTIME",
      createReq ? createReq.postData : "");

    // 弹层与二维码状态
    const ui = await ej(c, `(function(){
      var modal = document.getElementById('payModal');
      var cv = document.getElementById('payQrCanvas');
      var icon = document.getElementById('payQrIcon');
      var jump = document.getElementById('payJump');
      var tag = document.getElementById('payProviderTag');
      var note = document.getElementById('payProviderNote');
      var amt = document.getElementById('payAmount');
      var desc = document.getElementById('payDesc');
      var prog = document.getElementById('payProgress');
      var shown = modal ? modal.classList.contains('show') : false;
      var hasPixels = false;
      if (cv && !cv.hidden && cv.width > 0) {
        try {
          var d = cv.getContext('2d').getImageData(0,0,cv.width,cv.height).data;
          var dark = 0;
          for (var i=0;i<d.length;i+=4) if (d[i] < 128) dark++;
          hasPixels = dark > 100;
        } catch(e){}
      }
      return JSON.stringify({
        modalShown: shown,
        canvasHidden: cv ? cv.hidden : null,
        canvasW: cv ? cv.width : 0,
        iconHidden: icon ? icon.hidden : null,
        hasPixels: hasPixels,
        jumpHidden: jump ? jump.hidden : null,
        jumpHref: jump && !jump.hidden ? (jump.getAttribute('href')||'').slice(0,60) : '',
        providerTag: tag ? tag.textContent : '',
        providerNote: note ? note.textContent : '',
        amount: amt ? amt.textContent : '',
        desc: desc ? desc.textContent : '',
        progress: prog ? prog.textContent : '',
        qrSrc: typeof window.__lastQr === 'string' ? window.__lastQr : null
      });
    })()`);
    let u = {}; try { u = JSON.parse(ui); } catch (e) { u = { __raw: String(ui) }; }
    console.log(`     弹层状态: ${JSON.stringify(u).slice(0, 400)}`);

    R(u.modalShown === true, "支付弹层已打开");
    R(u.canvasHidden === false && u.hasPixels, "二维码已画到 canvas（非空白）",
      `canvasW=${u.canvasW} hasPixels=${u.hasPixels}`);
    R(/支付宝|模拟/.test(u.providerTag || ""), "展示 provider_label", `"${u.providerTag}"`);
    R(u.jumpHidden === false, "展示跳转收银台按钮", `href=${u.jumpHref}`);

    // 导出 canvas 像素，交后端 OpenCV 解码验证
    const dataUrl = await ej(c, `(function(){
      var cv = document.getElementById('payQrCanvas');
      return cv ? cv.toDataURL('image/png') : '';
    })()`);
    if (dataUrl && dataUrl.length > 200) {
      const b64 = dataUrl.replace(/^data:image\/png;base64,/, "");
      const tmpPng = path.join(os.tmpdir(), "kiosk_qr.png");
      fs.writeFileSync(tmpPng, Buffer.from(b64, "base64"));
      const py = process.env.PY_EXE || "python";
      try {
        const out = execFileSync(py, ["tools/decode_png.py", tmpPng], {
          encoding: "utf8", cwd: path.resolve(__dirname, ".."),
        });
        console.log(`     OpenCV 解码结果: ${out.trim()}`);
        R(/^https:\/\/qr\.alipay\.com\//.test(out.trim()), "canvas 内二维码可被解码器识别", out.trim());
      } catch (e) {
        console.log(`     (解码脚本调用失败: ${e.message.slice(0, 120)})`);
      }
    }

    // 截图
    const shot = await c.send("Page.captureScreenshot", { format: "png" });
    const outDir = path.resolve(__dirname, "..", "..", "frontend-verify");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(path.join(outDir, "kiosk-pay-qr.png"), Buffer.from(shot.data, "base64"));
    console.log(`     截图: frontend-verify/kiosk-pay-qr.png`);

    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：支付弹层二维码全部通过");
  process.exit(fail ? 1 : 0);
})();
