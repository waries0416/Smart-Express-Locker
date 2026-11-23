// 演示视频录制器：用 CDP 驱动真实浏览器，按讲稿分镜表执行真实操作并抓帧。
//
// 为什么这么做（而不是 OBS 录屏）：
//   本机无 OBS、无 ffmpeg 命令行工具（ffmpeg 由 imageio-ffmpeg 提供二进制）。
//   但 Edge/Chrome 自带 CDP，可以 Page.captureScreenshot 逐帧抓取**真实渲染画面**。
//   抓到的是系统此刻的真实输出，不是静态幻灯片拼接——操作（输入、点击、切页）
//   全部打到真实后端接口，页面内容由服务端返回数据驱动。
//
// 用法：
//   node quality/video/record_demo.js --out quality/logs/video-shots --fps 4
//
// 产出：
//   <out>/<场景序号>_<名称>/frames/f_00001.png ...
//   <out>/<场景序号>_<名称>/concat.txt     （带每帧时长的 concat 清单）
//   <out>/manifest.json                     （每段的起止、帧数、操作日志）
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");

function arg(name, dflt) {
  const i = process.argv.indexOf("--" + name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

const BASE = arg("base", "http://127.0.0.1:5000");
const OUT = path.resolve(arg("out", "quality/logs/video-shots"));
const FPS = parseInt(arg("fps", "4"), 10);
const ONLY = arg("only", "");
const W = 1920;
const H = 1080;
const BROWSER =
  arg("browser", "") ||
  (fs.existsSync("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe")
    ? "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
    : "C:\\Users\\31189\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe");

const PORT = parseInt(arg("port", "9421"), 10);
const FRAME_MS = Math.max(60, Math.round(1000 / FPS));
// 节奏系数：静音演示视频里观众要读字幕，操作与停留都比"真人手速"更慢。
// PACE=2 表示所有 sleep 翻倍；HOLD 是每个场景结束后的额外停留。
const PACE = parseFloat(arg("pace", "1"));
const HOLD = parseInt(arg("hold", "0"), 10);
const rawSleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sleep = (ms) => rawSleep(Math.round(ms * PACE));

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
  for (let i = 0; i < 80; i++) {
    try {
      return JSON.parse(await get(`http://127.0.0.1:${PORT}/json/version`));
    } catch (e) {
      await sleep(300);
    }
  }
  throw new Error("DevTools 未就绪");
}

function cdp(wsUrl) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    let id = 0;
    const pend = new Map();
    const events = [];
    ws.onopen = () =>
      resolve({
        events,
        send(method, params = {}) {
          return new Promise((res, rej) => {
            const mid = ++id;
            pend.set(mid, { res, rej });
            ws.send(JSON.stringify({ id: mid, method, params }));
          });
        },
        close() {
          try {
            ws.close();
          } catch (e) {}
        },
      });
    ws.onerror = () => reject(new Error("WS 失败"));
    ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id && pend.has(m.id)) {
        const { res, rej } = pend.get(m.id);
        pend.delete(m.id);
        m.error ? rej(new Error(m.error.message)) : res(m.result);
      } else if (m.method) {
        events.push(m);
      }
    };
  });
}

async function evalJs(c, expr, awaitPromise = false) {
  const r = await c.send("Runtime.evaluate", {
    expression: expr,
    awaitPromise,
    returnByValue: true,
    userGesture: true,
    awaitPromise: !!awaitPromise,
  });
  if (r.exceptionDetails) {
    return { __error: r.exceptionDetails.text };
  }
  return r.result ? r.result.value : undefined;
}

// ---------------------------------------------------------------------------
// 帧采集器：在后台以固定间隔抓帧，操作在此期间照常进行
// ---------------------------------------------------------------------------
function makeRecorder(c) {
  let dir = null;
  let frames = [];
  let timer = null;
  let busy = false;
  let stopFlag = false;
  let t0 = 0;

  return {
    async start(name) {
      dir = path.join(OUT, name, "frames");
      fs.rmSync(path.join(OUT, name), { recursive: true, force: true });
      fs.mkdirSync(dir, { recursive: true });
      frames = [];
      stopFlag = false;
      t0 = Date.now();

      const tick = async () => {
        if (stopFlag || busy) return;
        busy = true;
        try {
          // 超时保护：支付弹窗带 backdrop-filter 模糊背景时，
          // Page.captureScreenshot 偶发长时间不返回；不设超时会把 busy
          // 永久卡在 true，之后一帧都录不到（实测踩过）。
          const shot = await Promise.race([
            c.send("Page.captureScreenshot", {
              format: "png",
              captureBeyondViewport: false,
              optimizeForSpeed: true,
            }),
            new Promise((_, rej) =>
              setTimeout(() => rej(new Error("screenshot timeout")), 2500)
            ),
          ]);
          const file = path.join(
            dir,
            `f_${String(frames.length).padStart(5, "0")}.png`
          );
          fs.writeFileSync(file, Buffer.from(shot.data, "base64"));
          frames.push({ file, ms: Date.now() - t0 });
        } catch (e) {
          // 抓帧失败/超时不中断录制，跳过这一帧
        } finally {
          busy = false;
        }
      };
      timer = setInterval(tick, FRAME_MS);
      await tick();
      return { dir, frames };
    },

    async stop() {
      stopFlag = true;
      if (timer) clearInterval(timer);
      timer = null;
      // 等最后一帧写完
      for (let i = 0; i < 40 && busy; i++) await sleep(50);
      return { frames, dir };
    },
  };
}

function writeConcat(frames, dirName) {
  const listPath = path.join(OUT, dirName, "concat.txt");
  const lines = [];
  for (let i = 0; i < frames.length; i++) {
    const dur =
      i === frames.length - 1
        ? 1 / FPS
        : Math.max(1 / 60, (frames[i + 1].ms - frames[i].ms) / 1000);
    lines.push(`file '${frames[i].file.replace(/\\/g, "/")}'`);
    lines.push(`duration ${dur.toFixed(4)}`);
  }
  if (frames.length) {
    lines.push(`file '${frames[frames.length - 1].file.replace(/\\/g, "/")}'`);
  }
  fs.writeFileSync(listPath, lines.join("\n"), "utf-8");
  return listPath;
}

// ---------------------------------------------------------------------------
// 真实操作原语
// ---------------------------------------------------------------------------
async function goto(c, url, waitMs = 1800) {
  await c.send("Page.navigate", { url });
  await sleep(waitMs);
}

async function typeText(c, selector, text, perCharMs = 90) {
  // 真实逐字符输入：先聚焦，再用 Input.insertText 逐字送入
  await evalJs(
    c,
    `(function(){var e=document.querySelector(${JSON.stringify(selector)});
      if(!e) return 'no-el'; e.focus(); if('value' in e) e.value='';
      return 'ok';})()`
  );
  for (const ch of text) {
    await c.send("Input.insertText", { text: ch });
    await sleep(perCharMs);
  }
}

async function click(c, selector) {
  const box = await evalJs(
    c,
    `(function(){var e=document.querySelector(${JSON.stringify(selector)});
      if(!e) return null; var r=e.getBoundingClientRect();
      return {x:r.left+r.width/2, y:r.top+r.height/2, w:r.width, h:r.height};})()`
  );
  if (!box || box.__error || box.w === undefined) return false;
  await c.send("Input.dispatchMouseEvent", {
    type: "mouseMoved",
    x: Math.round(box.x),
    y: Math.round(box.y),
  });
  await sleep(120);
  await c.send("Input.dispatchMouseEvent", {
    type: "mousePressed",
    x: Math.round(box.x),
    y: Math.round(box.y),
    button: "left",
    clickCount: 1,
  });
  await sleep(80);
  await c.send("Input.dispatchMouseEvent", {
    type: "mouseReleased",
    x: Math.round(box.x),
    y: Math.round(box.y),
    button: "left",
    clickCount: 1,
  });
  return true;
}

async function moveTo(c, x, y) {
  await c.send("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
}

// ---------------------------------------------------------------------------
// 演示数据就绪检查 + 动态取件码
//
// 坑：reset_demo_data.py 设计上**不会**把 PICKED 改回 STORED（否则会出现
// "已取件却还在柜里" 的矛盾数据）。所以连续录几轮之后，讲稿里写死的
// 549548 / 878905 会被取走，录制出来就是"取件失败·该包裹已取走"。
// 这里在开录前查一次真实可用码，既用于操作，也写进产出清单，
// 保证视频里演示的是**当下真实可用**的取件码，而不是脚本假设的码。
// ---------------------------------------------------------------------------
let DEMO = { stored: null, expired: null };

async function loadDemoCodes(c) {
  const r = await evalJs(
    c,
    `(async()=>{
      const r = await fetch('/api/business/pending');
      if(!r.ok) return {ok:false,status:r.status};
      const j = await r.json();
      return {ok:true, data:j};
    })()`,
    true
  );
  return r;
}

async function queryDemoPackages(c) {
  // 查后台包裹列表（管理员会话），拿到当前真实可演示的取件码。
  // 接口形态（backend/entities.py 的 _list）：{total, page, size, data:[...]}
  //
  // 这里踩过两个坑，都记下来：
  //  坑1 不分页全量拉（size=200）拿不到目标件 —— 库里 310 条包裹，
  //      STORED 的只有 2 条且在末页。所以按 status 过滤分别查。
  //  坑2 柜机首页当前选中的是 CAB-001，取件接口会校验"取件码是否属于当前柜体"，
  //      拿 CAB-002 的码去 CAB-001 输，会返回 409「该取件码不属于当前柜体」。
  //      所以必须只挑**当前柜体**的包裹。
  const CAB_CODE = await evalJs(c, "window.CURRENT_CABINET_CODE || null");
  const r = await evalJs(
    c,
    `(async()=>{
      const login = await fetch('/api/auth/login',{method:'POST',
        credentials:'include',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({username:'admin',password:'admin123'})});
      if(!login.ok) return {ok:false,step:'login',status:login.status};

      const cabinets = await (await fetch('/api/cabinets?page=1&size=100',
        {credentials:'include'})).json();
      const byId = {};
      (cabinets.data || []).forEach(c => { byId[c.cabinet_id] = c.cabinet_code; });

      const get = async (status) => {
        const r = await fetch('/api/packages?page=1&size=50&status='+status,
          {credentials:'include'});
        if(!r.ok) return [];
        const j = await r.json();
        return (j.data || []).filter(x => x.pickup_code && x.direction !== 'SEND');
      };
      const tag = (arr) => arr.map(x => ({
        code: x.pickup_code, pid: x.package_id,
        cabinet: byId[x.cabinet_id] || ('#'+x.cabinet_id),
      }));
      return {
        ok: true,
        stored: tag(await get('STORED')),
        expired: tag((await get('EXPIRED')).filter(x => !Number(x.overtime_fee_paid))),
      };
    })()`,
    true
  );
  return r;
}

// 平滑移动鼠标（让画面有"人在操作"的观感，而不是瞬移）
async function glide(c, from, to, steps = 18, stepMs = 40) {
  for (let i = 1; i <= steps; i++) {
    const x = Math.round(from[0] + ((to[0] - from[0]) * i) / steps);
    const y = Math.round(from[1] + ((to[1] - from[1]) * i) / steps);
    await moveTo(c, x, y);
    await sleep(stepMs);
  }
}

async function h5Login(c, phone = "15800000001", role = "user") {
  // 真实走手机端登录。注意：send-code 有 60 秒限流，连续录多个手机场景时
  // 第二次会拿到 429 —— 实测踩过这个坑：登录静默失败，后来的所有帧都停在登录页。
  // 这里显式处理 429：等待剩余冷却后重试一次，仍失败则明确抛出，让场景报错而不是伪造画面。
  const attempt = async () =>
    evalJs(
      c,
      `(async()=>{
        const p=${JSON.stringify(phone)}, role=${JSON.stringify(role)};
        const s=await fetch('/api/m/auth/send-code',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({phone:p,role:role})});
        const sj=await s.json();
        if(!sj.dev_code) return {ok:false,step:'send-code',status:s.status,
                                 err:sj.error||'', retryAfter:60};
        const l=await fetch('/api/m/auth/login',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({phone:p,code:sj.dev_code,role:role})});
        const lj=await l.json();
        if(!lj.token) return {ok:false,step:'login',status:l.status,body:lj};
        const key = lj.token_key || 'm_token';
        localStorage.setItem(key, lj.token);
        localStorage.setItem('m_identity', JSON.stringify(lj.identity||null));
        return {ok:true, key:key, name:(lj.identity||{}).name,
                tokenLen:lj.token.length, status:l.status};
      })()`,
      true
    );

  let r = await attempt();
  if (!r || !r.ok) {
    // 限流：等冷却结束再试一次
    const waitMs = 62000;
    console.log(`   [login] 失败(${r && r.status})，等待限流冷却 ${waitMs / 1000}s 后重试`);
    await rawSleep(waitMs);
    r = await attempt();
  }
  if (!r || !r.ok) {
    throw new Error(`H5 登录失败: ${JSON.stringify(r)}`);
  }
  return r;
}

// 确保已登录：若 localStorage 里没有 token，就走一次真实登录
async function ensureLoggedIn(c, phone = "15800000001", role = "user") {
  const has = await evalJs(c, `!!localStorage.getItem('m_token')`);
  if (has) return { reused: true };
  const r = await h5Login(c, phone, role);
  // 重新加载让页面按 token 恢复会话
  await c.send("Page.reload", {});
  await sleep(2800);
  const ok = await evalJs(c, `!!localStorage.getItem('m_token')`);
  if (!ok) throw new Error("登录后 token 仍未生效");
  return { reused: false, ...r };
}

// ---------------------------------------------------------------------------
// 分镜脚本（对应讲稿第三节「演示视频分镜」）
// ---------------------------------------------------------------------------
const SCENES = [
  {
    id: "01_kiosk_home",
    title: "柜机首页：扫码与输码双入口",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      await goto(c, BASE + "/", 2600);
      // 鼠标缓慢划过二维码区与取件码输入区
      await glide(c, [300, 700], [820, 420], 22, 55);
      await sleep(600);
      await glide(c, [820, 420], [1180, 560], 16, 55);
      await sleep(700);
      // 真实点一下取件码输入框，出现光标
      await click(c, "#homeCodeInput");
      await sleep(1200);
    },
  },
  {
    id: "02_admin_302",
    title: "未登录访问后台被服务端 302 拦回",
    run: async (c, rec) => {
      await goto(c, BASE + "/", 900);
      // 真实导航到受保护页：由服务端 302 到登录页
      const nav = await c.send("Page.navigate", { url: BASE + "/admin/dashboard" });
      await sleep(2600);
      const fin = nav.frameId || "";
      const loc = await evalJs(c, "location.pathname");
      const status = await evalJs(
        c,
        `(async()=>{const r=await fetch('/admin/dashboard',{redirect:'manual'});
          return r.status;})()`,
        true
      );
      await sleep(900);
      // 真实逐字输入账号密码（登录页默认已填 admin/admin123，先清空再打字以体现"人在操作"）
      await evalJs(
        c,
        `(function(){var u=document.getElementById('username');
          if(u) u.value=''; var p=document.getElementById('password');
          if(p) p.value=''; return true;})()`
      );
      await typeText(c, "#username", "admin", 80);
      await sleep(300);
      await typeText(c, "#password", "admin123", 70);
      await sleep(900);
      return { landedAt: loc, directStatus: status };
    },
  },
  {
    id: "03_admin_dashboard",
    title: "管理端看板：指标卡与种子数据一致",
    run: async (c, rec) => {
      await goto(c, BASE + "/admin/login", 1500);
      await evalJs(
        c,
        `(async()=>{const r=await fetch('/api/auth/login',{method:'POST',
          credentials:'include',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({username:'admin',password:'admin123'})});
          return r.status;})()`,
        true
      );
      await goto(c, BASE + "/admin/dashboard", 3400);
      await sleep(1600);
      // 鼠标划过指标卡
      await glide(c, [350, 180], [1500, 180], 26, 55);
      await sleep(900);
      await glide(c, [1500, 180], [900, 620], 18, 55);
      await sleep(1500);
    },
  },
  {
    id: "04_kiosk_pickup",
    title: "柜机取件：输码 → 开柜引导",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      if (!DEMO.stored) throw new Error("开录前没有拿到可用的待取件码");
      await goto(c, BASE + "/", 2400);
      await click(c, "#homeCodeInput");
      await sleep(400);
      // 逐字输入**当下真实可用**的取件码（不是讲稿里写死的旧码）
      await typeText(c, "#homeCodeInput", DEMO.stored.code, 140);
      await sleep(800);
      await click(c, "#homeCodeBtn");
      await sleep(3200);
      return { pickedCode: DEMO.stored.code };
    },
  },
  {
    id: "05_kiosk_expired",
    title: "超时件先 402 拦截 → 支付 → 自动开柜",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      if (!DEMO.expired) throw new Error("开录前没有拿到超时未缴的取件码");
      await goto(c, BASE + "/", 2400);
      await click(c, "#homeCodeInput");
      await sleep(400);
      await typeText(c, "#homeCodeInput", DEMO.expired.code, 140);
      await sleep(800);
      await click(c, "#homeCodeBtn");
      // 402 → 前端弹支付层
      await sleep(3200);
      // 停留，让人看清 ¥1.00 与「模拟支付」
      await sleep(2400);
      // 真实点"确认支付"
      const paid = await evalJs(
        c,
        `(function(){
          var b=[...document.querySelectorAll('button')]
            .find(function(x){return /确认支付|立即支付|我已支付/.test(x.textContent);});
          if(b){b.click(); return 'clicked';} return 'no-btn';})()`
      );
      await sleep(3600);
      return { expiredCode: DEMO.expired.code, payClick: paid };
    },
  },
  {
    id: "06_mobile_login",
    title: "手机端登录与待取列表",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: 540, height: 1080, deviceScaleFactor: 1, mobile: true,
      });
      await goto(c, BASE + "/m/", 2200);
      // 真实逐字输入手机号
      await click(c, "#loginPhone");
      await sleep(300);
      await typeText(c, "#loginPhone", "15800000001", 60);
      await sleep(500);
      await click(c, "#btnSendCode");
      await sleep(2200);
      // 页面把 dev_code 回显到 #loginHint 并自动填进 #loginCode
      const hintInfo = await evalJs(
        c,
        `(function(){return {hint:(document.getElementById('loginHint')||{}).textContent||'',
                          code:(document.getElementById('loginCode')||{}).value||''};})()`
      );
      const hintText = (hintInfo && hintInfo.hint) || "";
      const codeInInput = (hintInfo && hintInfo.code) || "";
      let used = "none";
      if (/限流|60 秒|请 60/.test(hintText) || !codeInInput) {
        // 被限流：先展示限流提示这一真实状态，再等待冷却后由脚本走真实接口登录
        console.log("   [login] 触发限流，等待冷却后重试");
        await sleep(2000);
        await h5Login(c, "15800000001", "user");
        await c.send("Page.reload", {});
        await sleep(3000);
        used = "rate-limited-then-api";
      } else {
        used = "typed-from-hint";
        await click(c, "#loginCode");
        await sleep(250);
        // 输入框里已有自动填入的值，这里清空后逐字重打，体现真实输入动作
        await evalJs(c, `(function(){var e=document.getElementById('loginCode'); if(e) e.value=''; return true;})()`);
        await typeText(c, "#loginCode", codeInInput, 110);
        await sleep(600);
        await click(c, "#btnLogin");
        await sleep(3200);
      }
      return { codeSource: used, hint: hintText.slice(0, 60) };
    },
  },
  {
    id: "07_mobile_ai",
    title: "AI 包装推荐：模型只起草，降级仍可用",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: 540, height: 1080, deviceScaleFactor: 1, mobile: true,
      });
      await goto(c, BASE + "/m/", 2200);
      // 复用已登录会话（token 存 localStorage，跨场景保留），避免触发 60s 限流
      await ensureLoggedIn(c);
      // 真实点底部「助手」Tab
      await click(c, '.tab[data-tab="ai"]');
      await sleep(2000);
      // 真实逐字输入物品描述
      await click(c, "#aiDesc");
      await sleep(300);
      await typeText(c, "#aiDesc", "一个玻璃杯和两本书", 95);
      await sleep(700);
      await click(c, "#btnAiRecommend");
      await sleep(3400);
    },
  },
  {
    id: "08_mobile_map",
    title: "地图找柜：无 Key 也不白屏",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: 540, height: 1080, deviceScaleFactor: 1, mobile: true,
      });
      await goto(c, BASE + "/m/", 2200);
      // 复用已登录会话（token 存 localStorage，跨场景保留），避免触发 60s 限流
      await ensureLoggedIn(c);
      await click(c, '.tab[data-tab="map"]');
      await sleep(2800);
      // 切一次排序，展示列表重排
      const sorted = await evalJs(
        c,
        `(function(){var b=[...document.querySelectorAll('button')]
          .find(function(x){return /空闲最多/.test(x.textContent);});
          if(b){b.click(); return 'sorted';} return 'no-btn';})()`
      );
      await sleep(2400);
      return { sortClick: sorted };
    },
  },
  {
    id: "09_mobile_pay",
    title: "手机支付页：金额服务端快照 + 模拟支付标识",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: 540, height: 1080, deviceScaleFactor: 1, mobile: true,
      });
      await goto(c, BASE + "/m/", 2200);
      // 复用已登录会话（token 存 localStorage，跨场景保留），避免触发 60s 限流
      await ensureLoggedIn(c);
      // 真实点第一张带「待缴费」的包裹卡 → 详情页
      const opened = await evalJs(
        c,
        `(function(){
          var cards=[...document.querySelectorAll('#pendingList .pkg-card')];
          var pay=cards.find(function(x){
            return /待缴费/.test(x.textContent);});
          var target = pay || cards[0];
          if(!target) return 'no-card';
          target.click(); return pay ? 'clicked-need-pay' : 'clicked-first';
        })()`
      );
      await sleep(2600);
      // 详情页里按钮文案已是「支付 ¥1.00 并开柜」
      const detailText = await evalJs(
        c,
        `(function(){var b=document.getElementById('btnOpen');
          return b ? b.textContent.trim() : 'no-btn';})()`
      );
      await sleep(1800);
      // 走真实支付页（openPay 由页面自身逻辑驱动）；若页面未自动弹，则直接调
      // 真实支付单接口，再由页面渲染——仍然是真实服务端数据。
      const payOpened = await evalJs(
        c,
        `(async()=>{
          if(typeof openPay!=='function') return 'no-openPay';
          var p=state && state.preview;
          if(!p || p.package_id==null) return 'no-preview';
          await openPay({
            bizType:'OVERTIME', bizId:p.package_id,
            desc:'超时保管费 · 包裹 #'+p.package_id,
            provider:'mock',
            onSuccess: function(){ show('pickup'); }
          });
          return 'opened';
        })()`,
        true
      );
      await sleep(3400);
      // 停留，让人看清「模拟支付」「¥1.00」「支付单号 P...」
      await sleep(2600);
      return { cardClick: opened, btnText: detailText, payScreen: payOpened };
    },
  },
  {
    id: "10_admin_payment",
    title: "管理端支付流水与备包装清单",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      await goto(c, BASE + "/admin/login", 1400);
      await evalJs(
        c,
        `(async()=>{const r=await fetch('/api/auth/login',{method:'POST',
          credentials:'include',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({username:'admin',password:'admin123'})});
          return r.status;})()`,
        true
      );
      await goto(c, BASE + "/admin/dashboard", 3200);
      // 真实点侧边栏「支付流水」
      const a = await evalJs(
        c,
        `(function(){var n=document.querySelector('.sidebar a[data-view=payments]');
          if(n){n.click(); return 'clicked';} return 'no-nav';})()`
      );
      await sleep(2800);
      await glide(c, [400, 400], [1300, 700], 16, 55);
      await sleep(1200);
      // 再切「备包装清单」
      const b = await evalJs(
        c,
        `(function(){var n=document.querySelector('.sidebar a[data-view=materials]');
          if(n){n.click(); return 'clicked';} return 'no-nav';})()`
      );
      await sleep(2800);
      return { payments: a, materials: b };
    },
  },
  {
    id: "11_admin_matrix",
    title: "管理端格口矩阵：按柜体实时状态着色",
    run: async (c, rec) => {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      await goto(c, BASE + "/admin/login", 1200);
      await evalJs(
        c,
        `(async()=>{const r=await fetch('/api/auth/login',{method:'POST',
          credentials:'include',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({username:'admin',password:'admin123'})});
          return r.status;})()`,
        true
      );
      await goto(c, BASE + "/admin/dashboard", 3000);
      const m = await evalJs(
        c,
        `(function(){var n=document.querySelector('.sidebar a[data-view=matrix]');
          if(n){n.click(); return 'clicked';} return 'no-nav';})()`
      );
      await sleep(3400);
      await glide(c, [400, 500], [1400, 780], 20, 55);
      await sleep(1600);
      return { matrix: m };
    },
  },
];

// ---------------------------------------------------------------------------
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "vidrec-"));
  const proc = spawn(BROWSER, [
    "--headless=new",
    `--remote-debugging-port=${PORT}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--hide-scrollbars",
    "--force-device-scale-factor=1",
    "--disable-lcd-text",
    `--user-data-dir=${profile}`,
    "about:blank",
  ]);
  proc.stderr.on("data", () => {});

  const manifest = { base: BASE, fps: FPS, out: OUT, scenes: [] };

  try {
    await waitDevtools();
    const pages = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)).filter(
      (x) => x.type === "page"
    );
    const c = await cdp(pages[0].webSocketDebuggerUrl);
    await c.send("Page.enable");
    await c.send("Runtime.enable");
    await c.send("Network.enable");

    const rec = makeRecorder(c);

    // 开录前先探数据：取件/超时两个场景要用"当下真实可用、且属于当前柜体"的取件码。
    // 没有可用数据就明确失败，绝不录出一段"取件失败"的视频当成正常流程。
    try {
      await c.send("Emulation.setDeviceMetricsOverride", {
        width: W, height: H, deviceScaleFactor: 1, mobile: false,
      });
      // 先打开柜机首页，读出当前选中的柜体（store 在 localStorage，页面会恢复）
      await c.send("Page.navigate", { url: BASE + "/" });
      await sleep(2600);
      const curCab = await evalJs(
        c,
        `(function(){
          var s=document.getElementById('cabinetSwitch');
          if(!s) return null;
          var v=s.value;
          var opt=[...s.options].find(function(o){return String(o.value)===String(v);});
          return opt ? opt.textContent.trim() : null;})()`
      );
      DEMO.cabinet = curCab;
      console.log(`[data] 当前柜体: ${curCab}`);

      const demo = await queryDemoPackages(c);
      if (!demo || !demo.ok) {
        throw new Error(`查询演示数据失败: ${JSON.stringify(demo)}`);
      }
      const sameCab = (x) => !DEMO.cabinet || !x.cabinet ||
        DEMO.cabinet.startsWith(x.cabinet) || x.cabinet.startsWith(DEMO.cabinet);
      DEMO.stored = demo.stored.find(sameCab) || demo.stored[0] || null;
      DEMO.expired = demo.expired.find(sameCab) || demo.expired[0] || null;
      console.log(
        `[data] 待取码=${DEMO.stored ? DEMO.stored.code + "@" + DEMO.stored.cabinet : "无"} ` +
        `超时码=${DEMO.expired ? DEMO.expired.code + "@" + DEMO.expired.cabinet : "无"}`
      );
      if (!DEMO.stored) {
        console.log("   !! 没有 STORED 待取件：04 取件场景会失败");
      }
      if (!DEMO.expired) {
        console.log("   !! 没有 EXPIRED 未缴件：05 超时场景会失败");
      }
      if (DEMO.stored && DEMO.cabinet && DEMO.stored.cabinet !== DEMO.cabinet) {
        console.log(`   !! 待取件在 ${DEMO.stored.cabinet}，与当前柜体 ${DEMO.cabinet} 不一致，` +
                    `取件会 409 —— 需要先切柜体或重置数据`);
      }
    } catch (e) {
      console.log("[data] 预检失败:", e.message);
    }

    const list = ONLY ? SCENES.filter((s) => ONLY.split(",").includes(s.id)) : SCENES;

    for (const scene of list) {
      process.stdout.write(`\n[scene] ${scene.id} ${scene.title}\n`);
      await rec.start(scene.id);
      const t0 = Date.now();
      let extra = {};
      try {
        extra = (await scene.run(c, rec)) || {};
      } catch (e) {
        console.log("   !! 场景异常:", e.message);
        extra = { error: e.message };
      }
      // 场景结束后的额外停留：让观众读完字幕再切下一段（必须在停录之前）
      if (HOLD > 0) {
        await sleep(HOLD);
      }
      const { frames } = await rec.stop();
      const concat = writeConcat(frames, scene.id);
      const durMs = frames.length ? frames[frames.length - 1].ms : 0;
      console.log(
        `   frames=${frames.length}  dur=${(durMs / 1000).toFixed(1)}s  (${((Date.now() - t0) / 1000).toFixed(1)}s wall)`
      );
      manifest.scenes.push({
        id: scene.id,
        title: scene.title,
        frames: frames.length,
        durationMs: durMs,
        concat,
        ...extra,
      });
    }

    fs.writeFileSync(
      path.join(OUT, "manifest.json"),
      JSON.stringify(manifest, null, 2),
      "utf-8"
    );
    console.log("\nmanifest:", path.join(OUT, "manifest.json"));
    c.close();
  } finally {
    try {
      proc.kill();
    } catch (e) {}
  }
})();
