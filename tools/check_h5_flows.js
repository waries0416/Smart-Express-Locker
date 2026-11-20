/* R2b H5 端核对：AI 问答 / 推荐卡片 / 地图找柜降级 / 支付模拟标识
 * 用法： node tools/check_h5_flows.js [baseUrl]
 */
const http = require("http");
const path = require("path");
const fs = require("fs");
const os = require("os");
const { spawn } = require("child_process");

const BASE = process.argv[2] || "http://127.0.0.1:5099";
const PHONE = process.env.TEST_PHONE || ('139' + String(Date.now()).slice(-8));
const PORT = 9336;
const CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
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
    let interceptor = null;
    ws.onopen = () => resolve({
      events,
      setInterceptor(fn) { interceptor = fn; },
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
        const fake = interceptor ? interceptor(p.request.url) : null;
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
    "--no-default-browser-check", "--user-data-dir=" + path.join(os.tmpdir(), "r2b-h5-" + Date.now()), "about:blank",
  ], { stdio: "ignore" });

  let fail = 0;
  const R = (ok, name, extra) => { if (!ok) fail++; console.log(`${ok ? "OK" : "!!"} ${name}${extra ? "  " + extra : ""}`); };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter((x) => x.type === "page");
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable"); await c.send("Runtime.enable");
    await c.send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
    await c.send("Emulation.setDeviceMetricsOverride", { width: 500, height: 900, deviceScaleFactor: 1, mobile: true });

    // 登录 H5（演示环境验证码直接显示）
    await c.send("Page.navigate", { url: BASE + "/m/" });
    await sleep(2500);

    const loginSt = await evalJs(c, `(function(){
      var btn=[].slice.call(document.querySelectorAll('button')).filter(function(b){
        return /获取验证码/.test(b.innerText||'');});
      var ph=document.querySelector('input[type=tel],input[placeholder*="手机"]');
      return JSON.stringify({hasBtn:btn.length>0, hasPhone:!!ph, len:(document.body.innerText||'').trim().length});
    })()`);
    let lo = {}; try { lo = JSON.parse(loginSt); } catch (e) {}
    R(lo.hasBtn && lo.hasPhone, "H5 登录页正常", `hasBtn=${lo.hasBtn} hasPhone=${lo.hasPhone}`);

    // 用触屏端 kiosk-login 拿 USER token 注入 localStorage（不走短信验证码，避免 60s 限流）
    const tokenResp = await evalJs(c, `(async function(){
      try{
      var phone = ${JSON.stringify(PHONE)};
      var r=await fetch('/api/auth/kiosk-login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role:'USER',phone:phone})});
      var j=await r.json();
      if(j.token){localStorage.setItem('m_token',j.token);}
      return JSON.stringify({phone:phone, status:r.status, hasToken:!!j.token,
        identity:j.identity||null, body:JSON.stringify(j).slice(0,140)});
      }catch(e){ return JSON.stringify({thrown:String(e)}); }
    })()`, true);
    let to = {}; try { to = JSON.parse(tokenResp); } catch (e) { to = { raw: String(tokenResp) }; }
    console.log(`     登录: ${JSON.stringify(to)}`);

    await c.send("Page.navigate", { url: BASE + "/m/" });
    await sleep(3000);

    const homeSt = await evalJs(c, `(function(){
      var t=(document.body.innerText||'').replace(/\\s+/g,' ').trim();
      return JSON.stringify({len:t.length, sample:t.slice(0,200)});
    })()`);
    let ho = {}; try { ho = JSON.parse(homeSt); } catch (e) {}
    R(ho.len > 100, "H5 登录后首页正常", `len=${ho.len}`);
    console.log(`     首页样本: ${String(ho.sample).slice(0,160)}`);

    // ---- AI 问答 ----
    console.log("\n=== AI 问答 + 推荐卡片 ===");
    const aiSt = await evalJs(c, `(async function(){
      try{
        var r = await MApi.aiChat('玻璃杯怎么包装？', 's_test');
        return JSON.stringify({ok:true, source:r.source, degraded:!!r.degraded,
          reason:r.degraded_reason||null, replyLen:(r.reply||'').length, sid:r.session_id||null});
      }catch(e){ return JSON.stringify({ok:false, err:(e&&e.message)||String(e), status:e&&e.status}); }
    })()`, true);
    let ao = {}; try { ao = JSON.parse(aiSt); } catch (e) { ao = { ok: false, err: String(aiSt) }; }
    R(ao.ok && ao.replyLen > 0, "H5 AI 问答接口可用（降级到规则也 200）",
      `source=${ao.source} degraded=${ao.degraded} reason="${ao.reason}" replyLen=${ao.replyLen}`);

    const recSt = await evalJs(c, `(async function(){
      try{
        var r = await MApi.aiRecommend('一个玻璃杯和两本书');
        return JSON.stringify({ok:true, source:r.source, degraded:!!r.degraded,
          size_type:r.size_type, steps:(r.packaging||[]).length,
          materials:(r.materials||[]).length, notice:(r.notice||'').slice(0,40),
          forbidden:(r.forbidden||[]).length, sensitive:(r.sensitive||[]).length});
      }catch(e){ return JSON.stringify({ok:false, err:(e&&e.message)||String(e)}); }
    })()`, true);
    let ro = {}; try { ro = JSON.parse(recSt); } catch (e) { ro = { ok: false }; }
    R(ro.ok && ro.steps > 0, "H5 AI 包装推荐可用",
      `source=${ro.source} degraded=${ro.degraded} size=${ro.size_type} steps=${ro.steps} mats=${ro.materials} notice="${ro.notice}"`);

    // ---- 地图找柜降级（无 Key 场景，真实后端 configured=false） ----
    console.log("\n=== 地图找柜降级（服务端未配置 Key） ===");
    const mapSt = await evalJs(c, `(async function(){
      try{
        var cfg = await MApi.mapConfig();
        var nb = await MApi.nearbyCabinets({lat:39.9087,lng:116.3975});
        return JSON.stringify({ok:true, configured:cfg&&cfg.configured, jsKey:!!(cfg&&cfg.js_key),
          secCode:!!(cfg&&cfg.security_js_code), count:(nb.cabinets||[]).length,
          degraded:!!(nb&&nb.degraded), sorted_by:nb&&nb.sorted_by,
          first:(nb.cabinets||[])[0]?{code:nb.cabinets[0].cabinet_code, dist:nb.cabinets[0].distance_m, rec:nb.cabinets[0].recommended}:null});
      }catch(e){ return JSON.stringify({ok:false, err:(e&&e.message)||String(e)}); }
    })()`, true);
    let mo = {}; try { mo = JSON.parse(mapSt); } catch (e) { mo = { ok: false }; }
    R(mo.ok && mo.count > 0, "H5 附近柜接口可用",
      `configured=${mo.configured} jsKey=${mo.jsKey} secCode=${mo.secCode} count=${mo.count} sorted_by=${mo.sorted_by} first=${JSON.stringify(mo.first)}`);

    // 打开地图页签，确认降级 UI
    const mvSt = await evalJs(c, `(function(){
      var tabs=[].slice.call(document.querySelectorAll('[data-tab]'));
      var t=tabs.filter(function(x){return /附近|地图|找柜/.test(x.innerText||'');});
      if(t.length){t[0].click();}
      return JSON.stringify({clicked:t.length, label:t.length?(t[0].innerText||'').trim().slice(0,20):''});
    })()`);
    let mvi = {}; try { mvi = JSON.parse(mvSt); } catch (e) {}
    await sleep(3000);
    const mvAfter = await evalJs(c, `(function(){
      var fb=document.getElementById('mapFallback');
      var box=document.getElementById('amapBox');
      var why=document.getElementById('mapFallbackWhy');
      var sketch=document.getElementById('mfSketch');
      return JSON.stringify({
        fallbackVisible: fb? !fb.hidden : null,
        amapVisible: box? !box.hidden : null,
        why: why? (why.innerText||'').replace(/\\s+/g,' ').trim().slice(0,100):'',
        sketch: sketch? (sketch.innerText||'').replace(/\\s+/g,' ').trim().slice(0,80):'',
        bodyLen:(document.body.innerText||'').trim().length
      });
    })()`);
    let ma = {}; try { ma = JSON.parse(mvAfter); } catch (e) {}
    console.log(`     切换: ${JSON.stringify(mvi)}`);
    R(ma.bodyLen > 100, "H5 地图页不白屏", `bodyLen=${ma.bodyLen} fallback=${ma.fallbackVisible} amap=${ma.amapVisible}`);
    console.log(`     降级提示: ${ma.why}`);
    console.log(`     示意图: ${ma.sketch}`);

    // ---- 支付：mock 标识 + 只信服务端 ----
    console.log("\n=== 支付标识（mock 明示） ===");
    const paySt = await evalJs(c, `(async function(){
      try{
        var pk = await MApi.packages();
        var list = (pk && pk.pending) ? pk.pending.concat(pk.history || []) : (pk.data || pk || []);
        var p = list.filter(function(x){return x.pkg_status==='STORED'||x.pkg_status==='EXPIRED'||x.status==='STORED'||x.status==='EXPIRED';})[0]||list[0];
        if(!p) return JSON.stringify({ok:false,err:'该账号无包裹', keys:Object.keys(pk||{})});
        var pid = p.package_id;
        var c = await MApi.payCreate('OVERTIME', pid, 'mock');
        var s = await MApi.payStatus(c.pay_id);
        return JSON.stringify({ok:true, pay_id:c.pay_id, createAmount:c.amount, createMock:c.mock,
          provider_label:c.provider_label, createStatus:c.status,
          queryStatus:s.status, queryAmount:s.amount, queryLabel:s.provider_label,
          meta: payStatusMeta(s.status).cn});
      }catch(e){ return JSON.stringify({ok:false, err:(e&&e.message)||String(e), status:e&&e.status, code:e&&e.data&&e.data.code}); }
    })()`, true);
    let po = {}; try { po = JSON.parse(paySt); } catch (e) { po = { ok: false, err: String(paySt) }; }
    if (po.ok) {
      R(po.createMock === true && /模拟/.test(po.provider_label || ""),
        "支付单 mock 明示", `label="${po.provider_label}" mock=${po.createMock} amount=${po.createAmount}`);
      R(po.queryAmount === po.createAmount, "金额以服务端返回值一致",
        `create=${po.createAmount} query=${po.queryAmount} status=${po.queryStatus}(${po.meta})`);
    } else {
      R(false, "支付创建", JSON.stringify(po).slice(0, 200));
    }

    if (c.events.length) {
      console.log("\nJS 异常:"); c.events.slice(0, 6).forEach((e) => console.log("   " + e));
    } else console.log("\n无未捕获 JS 异常");
    c.close();
  } catch (e) { console.log("!! 异常:", e.message); fail++; }
  finally { try { proc.kill(); } catch (e) {} }

  console.log(fail ? `\n结果：${fail} 项未通过` : "\n结果：H5 流程全部通过");
  process.exit(fail ? 1 : 0);
})();
