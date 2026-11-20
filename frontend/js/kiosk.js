// 快递柜触屏端逻辑
//
// 职责边界（与现实中的柜机一致）：
//   柜机只做两件事 —— ①扫码/输码取件 ②快递员存件揽收；
//   寄件下单、我的包裹、消息通知等"需要慢慢翻"的操作全部交给手机端 /m。
//
// 扫码登录的时序（票据见 backend/qr_login.py）：
//   柜机建票 → 屏幕画二维码 → 手机扫码确认 → 柜机轮询拿到 token → 进入取件页
let selectedSize = "SMALL";
let currentCabinet = null;     // 当前触屏终端绑定的柜体（URL 参数指定，未指定则默认第一个）
let doorTimer = null;          // 开柜倒计时
let doorCells = [];            // 当前已开柜的格口号列表（用于「重新开门」）
let payTargets = [];           // 待支付超时费的 package_id 列表
let payOnPaid = null;          // 支付完成后的回调
let myPickupCandidates = [];   // 登录用户取件屏自动加载的待取包裹（供「立即取件」定位）
let cabinetMap = {};           // cabinet_id -> cabinet_code（投递记录行内展示用）
let allCabinets = [];          // 全部柜体（左上角切换下拉 + 初始化用）
let sendLockedSize = null;     // 关联寄件单后锁定的规格（存柜必须沿用用户寄件时的格口大小）

// ---------------- 扫码登录票据状态 ----------------
let qrTicket = null;           // 当前屏幕上的票据
let qrPollTimer = null;        // 轮询句柄（1.5s）
let qrCountdownTimer = null;   // 倒计时句柄（1s）
let qrLeft = 0;                // 剩余秒数
let qrBusy = false;            // 轮询防重入（网络慢时不叠加请求）
const QR_POLL_MS = 1500;
const IDLE_LOGOUT_MS = 120000; // 登录后 2 分钟无操作自动退出（保护上一位用户的隐私）

const SIZE_CN = { SMALL: "小件", MEDIUM: "中件", LARGE: "大件" };
function sizeCn(s) { return SIZE_CN[s] || s; }

// ---------------- 触屏端登录会话 ----------------
let kioskUser = null;      // {role:'USER', id, name, phone}
let kioskCourier = null;   // {role:'COURIER', id, name, phone, employee_no, company_name}
let idleTimer = null;

function maskNamePhone(idt) {
  if (!idt) return "未登录";
  return idt.role === "USER"
    ? `${idt.name}（${maskPhone(idt.phone)}）`
    : `${idt.name}（${idt.employee_no} · ${maskPhone(idt.phone)}）`;
}

function applyIdentity(idt) {
  kioskUser = idt && idt.role === "USER" ? idt : null;
  kioskCourier = idt && idt.role === "COURIER" ? idt : null;

  const cEl = document.getElementById("courierIdentity");
  if (cEl) cEl.textContent = kioskCourier ? "🚚 " + maskNamePhone(kioskCourier) : "🚚 未登录";

  // 取件屏顶部身份条
  const bar = document.getElementById("pickupUserBar");
  const pidEl = document.getElementById("pickupIdentity");
  if (bar) bar.hidden = !kioskUser;
  if (pidEl) pidEl.textContent = kioskUser ? "👤 " + maskNamePhone(kioskUser) : "👤 已登录";

  // 存件 / 揽收 / 投递记录屏的"当前快递员"展示（来自登录身份，不可代选他人）
  const show = kioskCourier
    ? `${kioskCourier.name}（${kioskCourier.employee_no}）· ${kioskCourier.company_name || ""}`
    : "未登录";
  ["storeCourierShow", "collectCourierShow", "recordsCourierShow"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = show;
  });

  renderHomeAuth();
  resetIdleTimer();
}

function saveSession(token, identity) {
  sessionStorage.setItem("kiosk_token", token);
  sessionStorage.setItem("kiosk_identity", JSON.stringify(identity));
  applyIdentity(identity);
}

async function restoreSession() {
  const token = sessionStorage.getItem("kiosk_token");
  if (!token) { applyIdentity(null); return; }
  try {
    const r = await API.kioskVerify();
    applyIdentity(r.identity);
  } catch (e) {
    sessionStorage.removeItem("kiosk_token");
    sessionStorage.removeItem("kiosk_identity");
    applyIdentity(null);
  }
}

function logoutKiosk(silent) {
  sessionStorage.removeItem("kiosk_token");
  sessionStorage.removeItem("kiosk_identity");
  myPickupCandidates = [];
  applyIdentity(null);          // → renderHomeAuth 会自动重新建票、恢复扫码态
  if (!silent) toast("已退出登录", "info");
  go("home");
}

// 登录后 2 分钟无操作自动登出：柜机是公共设备，不能让下一位用户看到上一位的包裹
function resetIdleTimer() {
  clearTimeout(idleTimer);
  if (!kioskUser && !kioskCourier) return;
  idleTimer = setTimeout(() => {
    toast("长时间无操作，已自动退出登录", "info");
    logoutKiosk(true);
  }, IDLE_LOGOUT_MS);
}
document.addEventListener("pointerdown", resetIdleTimer, true);
document.addEventListener("keydown", resetIdleTimer, true);

// ---------------- 首页：扫码登录 ----------------
// 未登录 → 展示二维码并轮询；已登录 → 收起二维码，显示"继续 / 退出"
function renderHomeAuth() {
  const qrBox = document.getElementById("homeQrBox");
  const authBox = document.getElementById("homeAuthBox");
  if (!qrBox || !authBox) return;

  const idt = kioskUser || kioskCourier;
  if (!idt) {
    stopQrTimers();
    qrBox.hidden = false;
    authBox.hidden = true;
    ensureQrTicket();
    return;
  }
  stopQrTimers();
  qrBox.hidden = true;
  authBox.hidden = false;
  document.getElementById("homeUserAvatar").textContent = idt.role === "USER" ? "👤" : "🚚";
  document.getElementById("homeUserState").textContent = maskNamePhone(idt);
  document.getElementById("homeUserRole").textContent = idt.role === "USER"
    ? "已登录 · 可查看名下待取包裹"
    : `已登录 · ${idt.company_name || "快递员"} · 可存件与揽收`;
  const btn = document.getElementById("homeContinueBtn");
  btn.textContent = idt.role === "USER" ? "继续取件" : "进入快递员工作台";
}

function setScanState(cls, text) {
  const el = document.getElementById("scanLoginState");
  if (!el) return;
  el.className = "qr-state " + (cls || "");
  el.textContent = text;
}

function setQrMask(show, text) {
  const mask = document.getElementById("homeQrMask");
  if (!mask) return;
  mask.style.display = show ? "flex" : "none";
  document.getElementById("homeQrMaskText").textContent = text || "";
}

function renderQrCountdown() {
  const el = document.getElementById("homeQrCountdown");
  if (el) el.textContent = qrLeft > 0 ? `剩余 ${qrLeft}s` : "已过期";
}

function stopQrTimers() {
  if (qrPollTimer) { clearInterval(qrPollTimer); qrPollTimer = null; }
  if (qrCountdownTimer) { clearInterval(qrCountdownTimer); qrCountdownTimer = null; }
}

// 建票：拿到 128bit 票据 + 深链，把深链渲染成二维码
async function newQrTicket() {
  stopQrTimers();
  qrTicket = null;
  setQrMask(true, "正在生成二维码…");
  setScanState("loading", "正在生成二维码…");
  document.getElementById("homeQrCountdown").textContent = "--";
  try {
    const r = await API.qrTicket(currentCabinet ? currentCabinet.cabinet_id : undefined);
    qrTicket = r.ticket;
    qrLeft = r.expire_in;
    document.getElementById("homeQrImg").src = API.qrSvg(r.deep_link, 6);
    setQrMask(false);
    renderQrCountdown();
    setScanState("wait", "请用手机相机扫一扫");
    qrCountdownTimer = setInterval(() => {
      qrLeft -= 1;
      renderQrCountdown();
      if (qrLeft <= 0) expireQr("二维码已过期，请点击刷新");
    }, 1000);
    qrPollTimer = setInterval(pollQrTicket, QR_POLL_MS);
  } catch (e) {
    setQrMask(true, "二维码生成失败");
    setScanState("error", "二维码生成失败：" + e.message);
  }
}

function ensureQrTicket() {
  if (qrTicket) return;           // 已有有效票据就不重复建票（避免刷新页面时浪费）
  newQrTicket();
}

async function refreshQrTicket() {
  const old = qrTicket;
  if (old) { try { await API.qrCancel(old); } catch (e) { /* 作废旧票失败不阻塞刷新 */ } }
  newQrTicket();
}

function expireQr(text) {
  stopQrTimers();
  setScanState("expired", text);
  setQrMask(true, "已过期");
  qrTicket = null;
}

// 轮询：PENDING 继续等；CONFIRMED 提示"正在登录"；CONSUMED 带 token 即完成交接
async function pollQrTicket() {
  if (!qrTicket || qrBusy) return;
  if (document.visibilityState === "hidden") return;
  qrBusy = true;
  try {
    const r = await API.qrPoll(qrTicket);
    if (r.token && r.identity) {
      stopQrTimers();
      qrTicket = null;
      saveSession(r.token, r.identity);
      toast(r.message || "登录成功", "success");
      go(r.identity.role === "USER" ? "pickup" : "courier-home");
      return;
    }
    if (r.status === "CONFIRMED") {
      setScanState("confirm", "手机已确认，正在登录…");
    } else if (["EXPIRED", "CANCELLED", "CONSUMED"].includes(r.status)) {
      expireQr(r.message || "二维码已失效，请点击刷新");
    }
  } catch (e) {
    // 网络抖动/柜机短暂离线：忽略本轮，下一轮再试（票据过期由倒计时兜底）
  } finally {
    qrBusy = false;
  }
}

function continueAfterLogin() {
  go(kioskUser ? "pickup" : "courier-home");
}

// ---------------- 快递员登录：工号 + 手机号双因子 ----------------
async function courierLogin() {
  const employee_no = document.getElementById("courierLoginNo").value.trim();
  const phone = document.getElementById("courierLoginPhone").value.trim();
  if (!employee_no) return toast("请输入工号", "warn");
  if (!/^1[3-9]\d{9}$/.test(phone)) return toast("请输入有效的 11 位手机号", "warn");
  const btn = document.getElementById("courierLoginBtn");
  btn.disabled = true; btn.textContent = "登录中…";
  try {
    const r = await API.kioskLogin({ role: "COURIER", employee_no, phone });
    saveSession(r.token, r.identity);
    toast(r.message, "success");
    go("courier-home");
  } catch (e) {
    toast("登录失败：" + e.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "登录";
  }
}

// ---------------- 屏幕切换 ----------------
function go(screen) {
  if (screen === "courier-home" && !kioskCourier) {
    toast("请先登录快递员账号（或在首页扫码登录）", "warn");
    screen = "courier-login";
  }
  if (["store", "collect", "records"].includes(screen) && !kioskCourier) {
    toast("请先登录快递员账号", "warn");
    screen = "courier-login";
  }
  const target = document.getElementById("screen-" + screen);
  if (!target) return;
  document.querySelectorAll(".kiosk-screen").forEach((s) => s.classList.remove("active"));
  target.classList.add("active");

  if (screen === "home") renderHomeAuth();
  if (screen === "pickup") {
    loadMyPickup();
    setTimeout(() => document.getElementById("pickupInput").focus(), 50);
  }
  if (screen === "courier-login") setTimeout(() => document.getElementById("courierLoginNo").focus(), 50);
  if (screen === "store") loadAvailability();
  if (screen === "collect") loadCollect();
  if (screen === "records") loadRecords();
  // AI 问答屏：自动聚焦输入框，省掉一次点击
  if (screen === "ai-help") setTimeout(() => {
    const el = document.getElementById("kaiInput");
    if (el) el.focus();
  }, 60);
}

// 各规格格口重量上限(kg) —— 与后端 business.py 的 SIZE_WEIGHT_LIMIT 保持一致
const SIZE_WEIGHT_LIMIT = { SMALL: 5, MEDIUM: 10, LARGE: 20 };
function weightLimitOf(size) { return SIZE_WEIGHT_LIMIT[size] ?? null; }
function weightLimitErr(size, weight) {
  const limit = weightLimitOf(size);
  if (limit == null) return null;
  const w = Number(weight) || 0;
  if (w > limit) return `${sizeCn(size)}格口限重 ${limit}kg，您填写 ${w}kg，已超限。请选择更大规格格口或调整重量`;
  return null;
}

// 时钟
function tickClock() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  document.getElementById("clock").textContent =
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
setInterval(tickClock, 1000); tickClock();

// 确定当前终端绑定的柜体：优先取 URL 参数（?cabinet=2），否则默认第一个柜体
function resolveCabinet(cabinets) {
  const want = Number(new URLSearchParams(location.search).get("cabinet"));
  const hit = (want && cabinets.data.find((c) => c.cabinet_id === want)) || cabinets.data[0];
  return hit || null;
}

// 初始化：先定柜体（二维码要绑定柜体），再恢复会话，最后按登录态决定"扫码"还是"已登录"
async function initKiosk() {
  try {
    const cabinets = await API.list("cabinets", { size: 200 });
    allCabinets = cabinets.data || [];
    currentCabinet = resolveCabinet(cabinets);
    cabinetMap = {};
    allCabinets.forEach((c) => { cabinetMap[c.cabinet_id] = c.cabinet_code; });

    const sw = document.getElementById("cabinetSwitch");
    if (sw) {
      sw.innerHTML = allCabinets.map((c) =>
        `<option value="${c.cabinet_id}">${c.cabinet_code} · ${c.location}</option>`).join("");
    }
    const cabSel = document.getElementById("recordsCabinet");
    if (cabSel) {
      cabSel.innerHTML = '<option value="">全部柜体</option>' +
        allCabinets.map((c) => `<option value="${c.cabinet_id}">${c.cabinet_code}</option>`).join("");
    }
    renderCabinetUI();
  } catch (e) {
    toast("初始化失败：" + e.message, "error");
  }
  await restoreSession();   // 未登录 → renderHomeAuth 会建票并开始轮询
}

// 把当前柜体渲染到各屏展示位
function renderCabinetUI() {
  const label = currentCabinet
    ? `${currentCabinet.cabinet_code} · ${currentCabinet.location}`
    : "未配置柜体";
  const store = document.getElementById("storeCabinetShow");
  if (store) store.value = label;
  const sw = document.getElementById("cabinetSwitch");
  if (sw && currentCabinet) sw.value = String(currentCabinet.cabinet_id);
}

// 左上角切换柜体：更新当前柜体，未登录时重新建票（二维码绑定柜体）
function switchCabinet(id) {
  const c = allCabinets.find((x) => x.cabinet_id === Number(id));
  if (!c) return;
  currentCabinet = c;
  renderCabinetUI();
  const active = document.querySelector(".kiosk-screen.active");
  const sid = active ? active.id : "";
  if (sid === "screen-store") loadAvailability();
  if (sid === "screen-collect") loadCollect();
  if (sid === "screen-records") loadRecords();
  if (sid === "screen-pickup") loadMyPickup();
  if (sid === "screen-home" && !kioskUser && !kioskCourier) refreshQrTicket();
  toast(`已切换到 ${c.cabinet_code}（${c.location}）`, "info");
}

// 规格选择（为 0 的规格会被禁用，此处仅允许选中可用规格）
function selectSize(size) {
  const btn = document.querySelector(`#storeSize button[data-size="${size}"]`);
  if (!btn || btn.disabled) return;
  document.querySelectorAll("#storeSize button").forEach((b) => b.classList.remove("active"));
  btn.classList.add("active");
  selectedSize = size;
}
document.getElementById("storeSize").addEventListener("click", (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  selectSize(btn.dataset.size);
});

// 加载当前柜体剩余格口数（总数 + 各规格），并为 0 的规格禁用按钮
async function loadAvailability() {
  if (!currentCabinet) return;
  try {
    const r = await API.cabinetAvailability(currentCabinet.cabinet_id);
    const bs = r.by_size;
    const map = { SMALL: bs.SMALL || 0, MEDIUM: bs.MEDIUM || 0, LARGE: bs.LARGE || 0 };
    document.getElementById("capStats").textContent = sendLockedSize
      ? `规格已锁定（${sizeCn(sendLockedSize)}），剩余 ${map[sendLockedSize] || 0} 个`
      : `共 ${r.total_free} 个 · 小 ${map.SMALL} / 中 ${map.MEDIUM} / 大 ${map.LARGE}`;
    document.querySelectorAll("#storeSize button").forEach((b) => {
      const n = map[b.dataset.size];
      const num = b.querySelector(".cap-num");
      if (num) num.textContent = `剩余 ${n}`;
      b.disabled = sendLockedSize ? b.dataset.size !== sendLockedSize : n <= 0;
    });
    const cur = document.querySelector(`#storeSize button[data-size="${selectedSize}"]`);
    if (cur && cur.disabled && !sendLockedSize) {
      const first = document.querySelector("#storeSize button:not(:disabled)");
      if (first) selectSize(first.dataset.size);
    }
  } catch (e) {
    document.getElementById("capStats").textContent = "剩余格口加载失败";
  }
}

let sendLookupMatches = [];   // 存件快速匹配出的寄件单列表（多条时供选择）

// 关联寄件单：支持 揽收码(6位) / 运单号 / 收件人手机号(11位) 快速匹配
async function assocSend() {
  const q = document.getElementById("storeSendCode").value.trim();
  const hint = document.getElementById("storeSendAssoc");
  if (!q) { clearSendAssoc(); return; }
  const isCode = /^\d{6}$/.test(q);
  const isPhone = /^1[3-9]\d{9}$/.test(q);
  const isTracking = /^[A-Za-z0-9]{8,20}$/.test(q);
  if (!isCode && !isPhone && !isTracking) {
    return toast("请输入 6 位揽收码、运单号或 11 位收件人手机号", "warn");
  }
  try {
    const r = await API.sendLookup(q);
    if (!r.count) {
      hint.innerHTML = `<span style="color:#fca5a5;">未匹配到寄件单（${q}），请确认已先在「揽收」中收取该件</span>`;
      clearSendAssoc(false);
      return;
    }
    sendLookupMatches = r.packages;
    if (r.count === 1) { applySendMatch(0); return; }
    hint.innerHTML =
      `<div style="color:#fde68a;margin-bottom:6px;">匹配到 ${r.count} 条寄件单，请选择：</div>` +
      r.packages.map((p, i) => `
        <div class="lookup-item">
          <span>${p.tracking_no} · ${sizeCn(p.size_type)} · ${statusCn(p.status)} · 收件人 ${p.recipient_name || "—"}(${p.recipient_phone || "—"})</span>
          <button class="btn sm" onclick="applySendMatch(${i})">选用</button>
        </div>`).join("");
  } catch (e) {
    toast("匹配失败：" + e.message, "error");
  }
}

// 选中一条寄件单：带出收件人 + 锁定规格 + 沿用寄件录入的重量（禁止手动改）
async function applySendMatch(idx) {
  const p = sendLookupMatches[idx];
  if (!p) return;
  sendLockedSize = p.size_type;
  selectSize(p.size_type);
  document.querySelectorAll("#storeSize button").forEach((b) => {
    b.disabled = b.dataset.size !== p.size_type;
  });
  if (p.recipient_phone) document.getElementById("storePhone").value = p.recipient_phone;
  if (p.recipient_name) document.getElementById("storeName").value = p.recipient_name;
  const wEl = document.getElementById("storeWeight");
  if (p.weight != null) {
    wEl.value = p.weight;
    wEl.disabled = true;
    wEl.placeholder = "重量沿用寄件单";
  }
  document.getElementById("storeSendAssoc").innerHTML =
    `✅ 已关联寄件 ${p.tracking_no}：收件人 ${p.recipient_name || "—"}(${p.recipient_phone || "—"})，` +
    `规格 ${sizeCn(p.size_type)}、重量 ${p.weight != null ? p.weight + "kg" : "—"} 已沿用寄件单（不可修改）`;
  let free = "--";
  try {
    const cap = await API.cabinetAvailability(currentCabinet.cabinet_id);
    free = cap.by_size[p.size_type] || 0;
  } catch (e) { /* 忽略 */ }
  document.getElementById("capStats").textContent =
    `规格已锁定（${sizeCn(p.size_type)}），剩余 ${free} 个`;
}

function clearSendAssoc(reset = true) {
  sendLockedSize = null;
  document.getElementById("storeSendAssoc").innerHTML = "";
  const wEl = document.getElementById("storeWeight");
  if (wEl) { wEl.disabled = false; wEl.value = ""; wEl.placeholder = "如 2.5"; }
  if (reset) loadAvailability();
}

document.getElementById("storeSendCode").addEventListener("input", (e) => {
  if (!e.target.value.trim()) clearSendAssoc();
});

// 存件
async function submitStore() {
  if (!kioskCourier) { toast("请先登录快递员账号", "warn"); return go("courier-login"); }
  const btn = document.getElementById("storeBtn");
  const payload = {
    courier_id: kioskCourier.id,        // 来自登录身份，不再由下拉代选
    user_phone: document.getElementById("storePhone").value.trim(),
    user_name: document.getElementById("storeName").value.trim(),
    size_type: selectedSize,
    weight: parseFloat(document.getElementById("storeWeight").value) || 0,
    cabinet_id: currentCabinet ? currentCabinet.cabinet_id : undefined,
    from_send_code: sendLockedSize ? document.getElementById("storeSendCode").value.trim() : undefined,
  };
  if (!sendLockedSize && payload.weight > 0) {
    const wErr = weightLimitErr(payload.size_type, payload.weight);
    if (wErr) return toast(wErr, "warn");
  }
  btn.disabled = true; btn.textContent = "存件中…";
  try {
    const r = await API.store(payload);
    // 存件只给取件码，不再弹二维码：
    // 收件人往往几小时后才来，此刻的二维码早已过期；取件二维码放在首页常驻才有效。
    showModal("✅", "存件成功", `
      <p>格口已分配，取件码已通过短信与站内消息发送给收件人。</p>
      <div class="big-code">${r.pickup_code}</div>
      <p>柜体 ${r.cabinet_code} · 格口 ${r.cell_code}<br/>运单号 ${r.tracking_no}</p>
      <p class="muted">通知已发送至 ${maskPhone(payload.user_phone)}</p>
      <p class="muted">收件人可用手机扫柜机首页二维码取件，或在首页输入取件码</p>
      ${sendLockedSize ? `<p class="muted">规格沿用寄件单：${sizeCn(sendLockedSize)}</p>` : ""}
    `);
    document.getElementById("storeSendCode").value = "";
    clearSendAssoc();
    loadAvailability();
    document.getElementById("storePhone").value = "";
    document.getElementById("storeName").value = "";
    document.getElementById("storeWeight").value = "";
  } catch (e) {
    toast("存件失败：" + e.message, "error");
  } finally {
    btn.disabled = false; btn.textContent = "确认存件";
  }
}

// ---------------- 快递员揽收（收取用户待寄出的件） ----------------
async function loadCollect() {
  if (!currentCabinet) return;
  try {
    const r = await API.sendPending({ cabinet: currentCabinet.cabinet_id });
    document.getElementById("collectCount").textContent = `（共 ${r.count} 件）`;
    if (!r.count) {
      document.getElementById("collectList").innerHTML =
        `<div class="pkg-item"><div>本柜当前没有待揽收的寄件。</div></div>`;
      return;
    }
    document.getElementById("collectList").innerHTML = r.packages.map((p) => `
      <div class="pkg-item">
        <div>
          <div class="pi-cell">${p.cell_code} · ${sizeCn(p.size_type)}</div>
          <div class="pi-sub">${p.company_name || "—"} · 寄件人 ${p.user_name || "—"}(${p.user_phone || "—"}) · 重量 ${p.weight != null ? p.weight + "kg" : "—"}</div>
          <div class="pi-sub">揽收码 <b style="color:#2563eb;">${p.pickup_code}</b>（存件关联时使用）</div>
        </div>
        <button class="btn green" style="padding:6px 12px;font-size:13px;"
          onclick="collectOne(${p.package_id}, '${p.cell_code}')">揽收</button>
      </div>`).join("");
  } catch (e) {
    document.getElementById("collectCount").textContent = "加载失败";
  }
}

async function collectOne(pid, cellCode) {
  if (!kioskCourier) { toast("请先登录快递员账号", "warn"); return go("courier-login"); }
  try {
    const r = await API.collect({ package_id: pid, courier_id: kioskCourier.id });
    openDoor([r.package]);
    toast(`已揽收 ${cellCode}，包裹交快递员`, "success");
    loadCollect();
  } catch (e) {
    toast("揽收失败：" + e.message, "error");
  }
}

// ---------------- 快递员：投递记录查询（登录身份 + 多条件筛选） ----------------
async function loadRecords() {
  if (!kioskCourier) { toast("请先登录快递员账号", "warn"); return go("courier-login"); }
  const box = document.getElementById("recordsList");
  try {
    const params = { courier_id: kioskCourier.id, size: 50 };
    const phone = document.getElementById("recordsPhone").value.trim();
    const cab = document.getElementById("recordsCabinet").value;
    const days = document.getElementById("recordsDays").value;
    const status = document.getElementById("recordsStatus").value;
    if (phone) params.recipient_phone = phone;
    if (cab) params.cabinet_id = Number(cab);
    if (status) params.status = status;
    if (days) {
      const d = new Date();
      d.setDate(d.getDate() - Number(days));
      d.setHours(0, 0, 0, 0);
      const p = (n) => String(n).padStart(2, "0");
      params.store_time_from = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} 00:00:00`;
    }
    const r = await API.list("packages", params);
    const condDesc = [cab ? `柜 ${cabinetMap[cab] || cab}` : "", days ? `近 ${days} 天` : "",
                      phone ? `收件人含 ${phone}` : "", status ? statusCn(status) : ""]
      .filter(Boolean).join(" · ");
    document.getElementById("recordsCount").textContent =
      `（共 ${r.total} 条${condDesc ? "，筛选：" + condDesc : "，全部"}，最多显示 50）`;
    if (!r.data.length) {
      box.innerHTML = `<div class="pkg-item"><div>该条件暂无匹配包裹。</div></div>`;
      return;
    }
    box.innerHTML = r.data.map((p) => `
      <div class="pkg-item">
        <div>
          <div class="pi-cell">${p.tracking_no}</div>
          <div class="pi-sub">${directionCn(p.direction)} · ${p.size_type} · 柜 ${cabinetMap[p.cabinet_id] || p.cabinet_id} · 取件码 ${p.pickup_code}</div>
        </div>
        <div style="text-align:right;">
          <span class="pi-badge ${badgeStatusCls(p.status)}">${statusCn(p.status)}</span>
          <div class="pi-sub">${p.pickup_time ? "完成 " + fmtTime(p.pickup_time).slice(5) : "存入 " + fmtTime(p.store_time).slice(5)}</div>
        </div>
      </div>`).join("");
  } catch (e) {
    box.innerHTML = `<div class="pkg-item"><div>加载失败：${e.message}</div></div>`;
  }
}

// ---------------- 取件（首页取件码 / 取件屏共用） ----------------
// 首页：只收 6 位取件码（手机号批量取件已迁到手机端「我的包裹」）
function submitHomeCode() {
  const raw = document.getElementById("homeCodeInput").value.trim();
  if (!/^\d{6}$/.test(raw)) return toast("请输入 6 位数字取件码", "warn");
  document.getElementById("homeCodeInput").value = "";
  doCodePickup(raw);
}

// 取件屏：同样只收 6 位取件码（扫码登录的用户走"立即取件"按钮）
function submitPickup() {
  const raw = document.getElementById("pickupInput").value.trim();
  if (!/^\d{6}$/.test(raw)) return toast("请输入 6 位数字取件码", "warn");
  document.getElementById("pickupInput").value = "";
  doCodePickup(raw);
}

async function doCodePickup(code) {
  const cid = currentCabinet ? currentCabinet.cabinet_id : undefined;
  try {
    const r = await API.pickup({ pickup_code: code, cabinet_id: cid });
    openDoor([r.package]);
    refreshMyPickupIfVisible();
  } catch (e) {
    // 超时未缴费：服务端 402 阻断，先扫码支付，付完用同一取件码重试。
    // 把取件码一并传给 startPay —— 匿名用户（未登录、只输码）靠它走匿名缴费通道。
    if (e.status === 402 && e.data && e.data.package_id) {
      const fee = Number(e.data.overtime_fee || 1).toFixed(2);
      startPay([e.data.package_id], `¥${fee}`, async () => {
        try {
          const r2 = await API.pickup({ pickup_code: code, cabinet_id: cid });
          openDoor([r2.package]);
          refreshMyPickupIfVisible();
        } catch (e2) {
          showModal("❌", "取件失败", `<p>${e2.message}</p><p>请稍后重试或联系管理员。</p>`);
        }
      }, code);
      return;
    }
    showModal("❌", "取件失败", `<p>${e.message}</p><p>请核对取件码或联系管理员。</p>`);
  }
}

// 单个包裹取件（含超时支付阻断）
async function singlePickup(pkg) {
  if (pkg.need_pay) {
    // 「立即取件」来自已登录用户的待取列表，本就有 token；但包裹行若带取件码也一并传下去，
    // 这样即便会话中途过期，匿名缴费通道仍能兜住（服务端会做交叉校验）。
    startPay([pkg.package_id], `¥${pkg.overtime_fee || 1}.00`, async () => {
      const r = await API.unlock(pkg.package_id, currentCabinet ? currentCabinet.cabinet_id : undefined);
      openDoor([r.package]);
      refreshMyPickupIfVisible();
    }, pkg.pickup_code || undefined);
    return;
  }
  try {
    const r = await API.unlock(pkg.package_id, currentCabinet ? currentCabinet.cabinet_id : undefined);
    openDoor([r.package]);
    refreshMyPickupIfVisible();
  } catch (e) {
    showModal("❌", "取件失败", `<p>${e.message}</p>`);
  }
}

function refreshMyPickupIfVisible() {
  const box = document.getElementById("myPickupBox");
  if (box && !box.hidden) loadMyPickup();
}

// ---------------- 登录用户：名下待取包裹 ----------------
async function loadMyPickup() {
  const box = document.getElementById("myPickupBox");
  const list = document.getElementById("myPickupList");
  if (!box || !list) return;
  if (!kioskUser) { box.hidden = true; return; }
  box.hidden = false;
  list.innerHTML = `<div class="pkg-item"><div>加载中…</div></div>`;
  try {
    const r = await API.myPickup(currentCabinet ? currentCabinet.cabinet_id : undefined);
    myPickupCandidates = r.packages || [];
    document.getElementById("myPickupCount").textContent = `（${r.count} 件）`;
    if (!r.count) {
      list.innerHTML = `<div class="pkg-item"><div>当前柜体下暂无待取包裹。</div></div>`;
      return;
    }
    list.innerHTML = myPickupCandidates.map((p) => `
      <div class="pkg-item ${p.need_pay ? "need-pay" : ""}">
        <div>
          <div class="pi-cell">${p.cabinet_code} · ${p.cell_code} · ${sizeCn(p.size_type)}</div>
          <div class="pi-sub">${p.company_name || "—"} · 存入 ${fmtTime(p.store_time).slice(5)}</div>
        </div>
        <div style="text-align:right;">
          ${p.need_pay
            ? `<span class="pi-badge">超时待付 ¥${p.overtime_fee || 1}</span>`
            : `<span class="pi-badge ok">待取</span>`}
          <div style="margin-top:6px;">
            <button class="btn sm green" onclick="pickupById(${p.package_id})">立即取件</button>
          </div>
        </div>
      </div>`).join("");
  } catch (e) {
    list.innerHTML = `<div class="pkg-item"><div>加载失败：${e.message}</div></div>`;
  }
}

// 「立即取件」：按 id 定位候选包裹，复用单件取件（含超时支付阻断）
function pickupById(pid) {
  const pkg = myPickupCandidates.find((p) => p.package_id === pid);
  if (!pkg) return;
  singlePickup(pkg);
}

// ---------------- 超时扫码支付 ----------------
/* 支付状态机（BUG1 修复要点）：
 *   ① 打开弹层就调 POST /api/pay/create（biz_type=OVERTIME），拿到 pay_id / 金额 /
 *      provider_label / mock / qr_code_url / redirect_url —— 二维码**只来自 create**，
 *      GET /api/pay/{id} 不返回 qr_code_url（契约 §4.1 vs §4.2）。
 *   ② alipay 模式且响应带 qr_code_url → 用本地 QRCodeMini 画到 canvas（不联网、不用 CDN）。
 *      画不出来或没有 qr_code_url → 显示「跳转收银台」按钮（redirect_url）兜底。
 *   ③ 轮询 GET /api/pay/{id}，只有 status=SUCCESS 才放行取件；
 *      FAILED/CLOSED 停下并提示；超时则提示可重试。
 *   ④ mock 模式保持原快速路径（可直接点「我已支付」走 mock-succeed/admin 通道）。
 */
let payState = null;      // { payId, pollTimer, ticks, closed, channel }
const PAY_POLL_MS = 2000;      // 轮询间隔：2 秒
const PAY_MAX_TICKS = 90;      // 最多轮询 90 次 ≈ 3 分钟（与支付单 10 分钟有效期相比更保守）

function _payEl(id) { return document.getElementById(id); }

/** 渲染二维码：成功返回 true，失败/无内容返回 false（调用方走跳转兜底） */
function renderPayQr(qrText) {
  const canvas = _payEl("payQrCanvas");
  const icon = _payEl("payQrIcon");
  const box = _payEl("payQrBox");
  if (!canvas || !icon) return false;
  if (!qrText) {
    canvas.hidden = true; icon.hidden = false;
    if (box) box.classList.remove("has-qr");
    return false;
  }
  try {
    const ok = (typeof QRCodeMini !== "undefined") &&
      QRCodeMini.toCanvas(canvas, qrText, { size: 240, margin: 3, ecc: "M" });
    if (ok) {
      canvas.hidden = false; icon.hidden = true;
      // 画布出现后取消外层固定尺寸，避免压住下方标题
      if (box) box.classList.add("has-qr");
      return true;
    }
  } catch (e) { /* 落到兜底分支 */ }
  canvas.hidden = true;
  icon.hidden = false;
  if (box) box.classList.remove("has-qr");
  return false;
}

/** 展示后端下发的渠道信息（provider_label / mock 均以服务端为准） */
function renderPayChannel(p) {
  if (typeof kaiRenderPayProvider === "function") kaiRenderPayProvider(p);
}

/** 停止轮询（切屏/关闭弹层时必须调用，避免后台空转） */
function stopPayPoll() {
  if (payState && payState.pollTimer) {
    clearInterval(payState.pollTimer);
    payState.pollTimer = null;
  }
}

/** 关闭弹层：停轮询 + 复位状态 */
function closePay() {
  stopPayPoll();
  if (payState) payState.closed = true;
  const m = _payEl("payModal");
  if (m) m.classList.remove("show");
}

/**
 * 发起超时费支付。
 * @param {number[]} ids     待支付包裹 id（多个时按第一个建单，服务端金额以 biz_id 为准）
 * @param {string}   amountText 兜底展示金额（服务端返回后会被覆盖）
 * @param {Function} onPaid     支付成功后的回调（放行取件）
 * @param {string}   [pickupCode] 取件码。匿名（未登录）缴费时必传：
 *                                服务端用它与该包裹做交叉校验，避免凭 package_id 越权缴费。
 */
async function startPay(ids, amountText, onPaid, pickupCode) {
  payTargets = ids;
  payOnPaid = onPaid;
  // reqSeq：每发起一次建单就自增。异步响应回来时若序号已过期，直接丢弃，
  // 杜绝旧响应晚到把新二维码覆盖掉（后端起根因修复后，旧码不会再顶掉新码，
  // 但前端仍必须保证"只渲染最后一次响应"，否则用户看到的可能是上一单的图）。
  payState = { payId: null, pollTimer: null, ticks: 0, closed: false,
               pickupCode: pickupCode || "", anonymous: false,
               reqSeq: 0, appliedSeq: 0, creating: false, expired: false };

  const amountEl = _payEl("payAmount");
  const descEl = _payEl("payDesc");
  const progEl = _payEl("payProgress");
  const jumpEl = _payEl("payJump");
  const confirmBtn = _payEl("payConfirm");
  const refreshBtn = _payEl("payRefresh");

  amountEl.textContent = amountText;
  descEl.textContent = "正在创建支付单…";
  progEl.textContent = "等待支付…";
  progEl.className = "pay-progress";
  confirmBtn.disabled = false;
  jumpEl.hidden = true;
  if (refreshBtn) refreshBtn.hidden = true;
  renderPayQr(null);              // 先清掉上一单的二维码
  _payEl("payModal").classList.add("show");

  const bizId = Array.isArray(ids) ? ids[0] : ids;

  /* 建单有两条通道（契约 §4.1 匿名持码缴费）：
   *   ① 有 token —— 原路径不变，服务端按本人包裹鉴权，pickup_code 不参与授权；
   *   ② 无 token 但有取件码 —— 走匿名通道：body 带 pickup_code 与服务端交叉校验。
   *      这是「用户不扫码、直接输取件码缴费」的主场景，必须有二维码。
   *   ③ 两者都没有 —— 无法证明对这单的处置权，提示先扫码登录。 */
  const hasToken = !!(ApiCore.token && ApiCore.token());
  if (!hasToken && !pickupCode) {
    descEl.textContent = "请先用手机扫描柜机屏幕二维码登录，或改用取件码缴费";
    progEl.className = "pay-progress err";
    progEl.textContent = "缺少身份凭证，无法发起在线支付";
    _payEl("payConfirm").disabled = true;
    return;
  }
  payState.anonymous = !hasToken;
  payState.bizId = bizId;

  // 建单只此一处：首次打开与「刷新二维码」都走它，靠 reqSeq 保证只采纳最后一次
  await createPayOrder(false);
}

/**
 * 发起建单并渲染二维码。
 * @param {boolean} refresh true = 显式换新码（服务端换新 pay_no + 新二维码）
 *
 * 防竞态三条：
 *   1. creating 门闩 —— 同一时刻只允许一个建单在飞，重复点击直接忽略；
 *   2. reqSeq 序号 —— 响应回来时比对序号，过期响应一律丢弃不渲染；
 *   3. 只渲染最后一次 —— 保证画到 canvas 上的永远是当前有效那单的码。
 */
async function createPayOrder(refresh) {
  if (payState.creating) return;          // ① 门闩：并发调用直接丢弃
  payState.creating = true;
  const seq = ++payState.reqSeq;          // ② 本次请求的序号

  const descEl = _payEl("payDesc");
  const progEl = _payEl("payProgress");
  const jumpEl = _payEl("payJump");
  const refreshBtn = _payEl("payRefresh");

  if (refresh) {
    descEl.textContent = "正在刷新二维码…";
    progEl.className = "pay-progress";
    progEl.textContent = "获取新二维码…";
    if (refreshBtn) refreshBtn.disabled = true;
  }

  try {
    const reqBody = { biz_type: "OVERTIME", biz_id: payState.bizId };
    if (payState.anonymous) reqBody.pickup_code = payState.pickupCode;
    if (refresh) reqBody.refresh = true;   // 显式要求换新码

    const p = await API.payCreate(reqBody);

    // ③ 过期响应丢弃：用户在等新码期间又触发了别的请求，这次结果不再有效
    if (seq !== payState.reqSeq || !payState || payState.closed) return;

    payState.payId = p.pay_id;
    payState.channel = p;
    payState.appliedSeq = seq;
    payState.expired = !!p.expired;

    if (p.amount != null) _payEl("payAmount").textContent = "¥" + Number(p.amount).toFixed(2);
    renderPayChannel(p);

    const isMock = !!p.mock;
    const qrText = p.qr_code_url || "";
    const redirect = p.redirect_url || "";

    if (isMock) {
      descEl.textContent = "演示环境使用模拟支付，不会产生真实扣款";
    } else if (qrText) {
      const drawn = renderPayQr(qrText);
      descEl.textContent = drawn
        ? "请用支付宝扫描上方二维码完成支付，支付成功后会自动开柜"
        : "请点击下方按钮跳转收银台完成支付";
    } else if (redirect) {
      descEl.textContent = "请点击下方按钮跳转收银台完成支付";
    } else {
      descEl.textContent = "等待支付结果…";
    }

    // 跳转兜底：有 redirect_url 就展示（扫码不便 / 二维码画不出来时用）
    if (redirect) {
      jumpEl.href = redirect;
      jumpEl.hidden = false;
    }

    // 刷新按钮：真实扫码模式下常显，用户扫码提示"已失效"时可自己换新码
    if (refreshBtn) {
      refreshBtn.hidden = isMock;
      refreshBtn.disabled = false;
    }

    progEl.className = "pay-progress";
    progEl.textContent = "等待支付…";

    // 每张新码都从零开始计轮询次数，避免刷新几次后提前超时
    payState.ticks = 0;
    if (!payState.pollTimer) {
      payState.pollTimer = setInterval(() => pollPayOnce(), PAY_POLL_MS);
    }
  } catch (e) {
    if (seq !== payState.reqSeq) return;
    progEl.className = "pay-progress err";
    progEl.textContent = (refresh ? "刷新二维码失败：" : "创建支付单失败：") + ApiCore.errText(e);
    descEl.textContent = "请稍后重试，或联系现场工作人员";
    if (refreshBtn) refreshBtn.disabled = false;
  } finally {
    payState.creating = false;
  }
}

/** 「刷新二维码」按钮：显式告诉服务端换一张新码 */
function refreshPayQr() {
  if (!payState) return;
  createPayOrder(true);
}

/** 轮询一次支付状态；只有 SUCCESS 才放行 */
async function pollPayOnce() {
  if (!payState || !payState.payId || payState.closed) return;
  const progEl = _payEl("payProgress");
  try {
    // 状态查询分两条通道（契约 §4.2）：
    //   登录态 —— GET  /api/pay/{id}（带 Bearer，服务端按本人/相关方鉴权）
    //   匿名态 —— POST /api/pay/{id}/poll {pickup_code}（靠取件码交叉校验）
    // 用 auth:false 去打 GET 会 401，状态永远停在 PENDING；这两条必须严格区分。
    const p = payState.anonymous
      ? await API.payPollAnonymous(payState.payId, payState.pickupCode)
      : await ApiCore.get(`/pay/${payState.payId}`, { timeout: 8000 });
    renderPayChannel(p);
    const meta = payStatusMeta(p && p.status);

    if (meta.cls === "success") {
      stopPayPoll();
      progEl.className = "pay-progress ok";
      progEl.textContent = "✅ 支付成功，正在开柜…";
      const cb = payOnPaid;
      payOnPaid = null;
      payTargets = [];
      setTimeout(() => { closePay(); if (cb) cb(); }, 700);
      return;
    }
    if (meta.cls === "failed" || meta.cls === "closed") {
      stopPayPoll();
      progEl.className = "pay-progress err";
      progEl.textContent = "❌ " + meta.cn + (p && p.fail_reason ? "：" + p.fail_reason : "");
      // 失败/关闭后原单不可再付，只能换新码重来
      const rb = _payEl("payRefresh");
      if (rb && !(payState.channel && payState.channel.mock)) {
        rb.hidden = false; rb.disabled = false;
      }
      return;
    }

    // 已过期：二维码不能再扫，必须换新码。提示 + 亮出刷新按钮，由用户点一下换码
    // （不自动刷新，避免用户正把手机对准屏幕时画面突然换图）。
    if (p && p.expired) {
      stopPayPoll();
      payState.expired = true;
      progEl.className = "pay-progress err";
      progEl.textContent = "⏰ 二维码已过期，请点「刷新二维码」获取新码";
      const descEl = _payEl("payDesc");
      if (descEl) descEl.textContent = "二维码已过期，刷新后可继续扫码支付";
      const refreshBtn = _payEl("payRefresh");
      if (refreshBtn) { refreshBtn.hidden = false; refreshBtn.disabled = false; }
      return;
    }

    // PENDING
    payState.ticks += 1;
    if (payState.ticks >= PAY_MAX_TICKS) {
      stopPayPoll();
      progEl.className = "pay-progress err";
      progEl.textContent = "⏰ 等待超时，请重新支付或联系工作人员";
      return;
    }
    progEl.className = "pay-progress";
    progEl.textContent = "⏳ " + meta.cn + "…";
  } catch (e) {
    // 单次查询失败不终止，交给下一轮；连续失败交给超时上限兜底
    payState.ticks += 1;
    if (payState.ticks >= PAY_MAX_TICKS) {
      stopPayPoll();
      if (progEl) {
        progEl.className = "pay-progress err";
        progEl.textContent = "查询支付状态失败：" + ApiCore.errText(e);
      }
    }
  }
}

/**
 * 「我已支付」：mock 模式下走原来的快速通道（管理端模拟置成功），
 * 真实沙箱模式则立即查一次状态（不做任何前端判定成功）。
 */
async function confirmPay() {
  const btn = _payEl("payConfirm");
  const progEl = _payEl("payProgress");
  if (!payState || !payState.payId) return;

  if (payState.isMock === undefined) {
    // 首次点击时判断渠道；mock 才有权限直接置成功
    payState.isMock = !!(payState.channel && payState.channel.mock);
  }
  btn.disabled = true;
  progEl.className = "pay-progress";
  progEl.textContent = "正在确认支付结果…";
  try {
    await pollPayOnce();
  } finally {
    if (payState && !payState.closed) btn.disabled = false;
  }
}
function closePay() { document.getElementById("payModal").classList.remove("show"); }

// ---------------- 开柜引导 ----------------
function openDoor(packages) {
  doorCells = packages.map((p) => `${p.cabinet_code} ${p.cell_code}`);
  const first = packages[0];
  document.getElementById("doorCell").textContent = first.cell_code;
  const extra = packages.length > 1 ? `<p>本次共开启 ${packages.length} 个格口</p>` : "";
  document.getElementById("doorInfo").innerHTML =
    `柜体 ${first.cabinet_code} · 运单号 ${first.tracking_no}<br/>` + extra;
  document.getElementById("doorModal").classList.add("show");
  startCountdown();
}
function startCountdown() {
  let left = 30;
  const el = document.getElementById("doorCountdown");
  el.textContent = left;
  clearInterval(doorTimer);
  doorTimer = setInterval(() => {
    left -= 1;
    el.textContent = Math.max(0, left);
    if (left <= 0) {
      clearInterval(doorTimer);
      toast("柜门已自动关闭", "info");
    }
  }, 1000);
}
function reopenDoor() {
  startCountdown();
  toast("已为您重新开门：" + doorCells.join("、"), "success");
}
function closeDoor() {
  clearInterval(doorTimer);
  document.getElementById("doorModal").classList.remove("show");
}

// ---------------- 弹层控制 ----------------
function showModal(icon, title, bodyHtml) {
  document.getElementById("kmIcon").textContent = icon;
  document.getElementById("kmTitle").textContent = title;
  document.getElementById("kmBody").innerHTML = bodyHtml;
  document.getElementById("kioskModal").classList.add("show");
}
function closeModal() { document.getElementById("kioskModal").classList.remove("show"); }

// 首页取件码输入框回车即提交（柜机外接键盘场景）
document.getElementById("homeCodeInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitHomeCode();
});
document.getElementById("pickupInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitPickup();
});

initKiosk();
