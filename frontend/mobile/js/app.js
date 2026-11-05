/* 手机端 H5 逻辑
 * 页面：登录 → 取件（待取列表 / 扫码 / 手输码）→ 详情 → 开柜结果 → 寄件 → 我的
 * 身份：登录后拿 USER token 存 localStorage，所有请求带 Bearer，服务端按 token 过滤数据
 */
const API_BASE = "/api";
const TOKEN_KEY = "m_token";
const IDENTITY_KEY = "m_identity";

const SIZE_CN = { SMALL: "小件", MEDIUM: "中件", LARGE: "大件" };
const STATUS_CN = {
  STORED: "待取", EXPIRED: "已超时", PICKED: "已取走",
  RETURNED: "已退回", EXCEPTION: "异常",
  SEND_WAIT_PICKUP: "待揽收", SEND_COLLECTED: "已揽收", SEND_CANCELLED: "已撤回",
};

const $ = (id) => document.getElementById(id);
const state = {
  identity: null, pending: [], history: [], preview: null,
  openKey: null, timer: null,
  pendingTicket: null,    // 深链 ?ticket=xxxx（扫码登录柜机票据）
  ticket: null,           // 当前正在确认的票据
};

/* ---------------- 基础工具 ---------------- */
function token() { return localStorage.getItem(TOKEN_KEY) || ""; }

function saveAuth(tk, identity) {
  localStorage.setItem(TOKEN_KEY, tk);
  localStorage.setItem(IDENTITY_KEY, JSON.stringify(identity || null));
  state.identity = identity || null;
}

function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(IDENTITY_KEY);
  state.identity = null;
}

async function api(path, { method = "GET", body, headers = {} } = {}) {
  // 统一走 ApiCore：自动带 Bearer、20s 超时、401/403 中文提示、错误标记归一化。
  // token 由 /m/js/api-mobile.js 注入的读取器从 localStorage["m_token"] 取。
  return ApiCore.request(method, path, body, headers);
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtTime(v) {
  if (!v) return "--";
  const d = new Date(String(v));
  if (isNaN(d.getTime())) return String(v);
  const p = (n) => String(n).padStart(2, "0");
  // 后端按 RFC 1123（GMT）序列化 datetime，用 UTC 组件还原避免 ±8h 偏移
  return `${d.getUTCFullYear()}.${d.getUTCMonth() + 1}.${d.getUTCDate()} ` +
         `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

let toastTimer = null;
function toast(msg, type = "") {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast show " + type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast " + type; }, 2400);
}

/* ---------------- 屏幕切换 ---------------- */
const TAB_SCREENS = ["pickup", "send", "ai", "map", "me"];
const HDR_TITLE = {
  pickup: "手机取件", send: "寄件下单", me: "我的",
  ai: "智能助手", map: "附近的柜",
  pay: "支付",
  ticket: "扫码确认", courier: "快递员",
};
function show(name) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  const target = $("screen-" + name);
  if (target) target.classList.add("active");
  // 快递员没有取件/寄件/我的三个 Tab，底部导航整体隐藏
  const isCourier = ((state.identity || {}).role) === "COURIER";
  const isTab = TAB_SCREENS.includes(name) && !isCourier;
  $("tabbar").style.display = isTab ? "flex" : "none";
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name));
  if (HDR_TITLE[name]) $("hdrSub").textContent = HDR_TITLE[name];
  window.scrollTo(0, 0);
}

/* ---------------- 登录 ---------------- */
let sendTimer = null;
function startSendCountdown(sec) {
  const btn = $("btnSendCode");
  let left = sec;
  btn.disabled = true;
  btn.textContent = `${left}s`;
  clearInterval(sendTimer);
  sendTimer = setInterval(() => {
    left -= 1;
    if (left <= 0) {
      clearInterval(sendTimer);
      btn.disabled = false;
      btn.textContent = "获取验证码";
    } else {
      btn.textContent = `${left}s`;
    }
  }, 1000);
}

async function sendCode() {
  const phone = $("loginPhone").value.trim();
  if (!/^1[3-9]\d{9}$/.test(phone)) { toast("请输入正确的 11 位手机号", "err"); return; }
  try {
    const r = await api("/m/auth/send-code", { method: "POST", body: { phone } });
    if (r.dev_code) {
      $("loginHint").textContent = `演示验证码：${r.dev_code}（5 分钟内有效）`;
      $("loginCode").value = r.dev_code;
    } else {
      $("loginHint").textContent = "验证码已发送，请查看短信";
    }
    toast("验证码已发送", "ok");
    startSendCountdown(60);
  } catch (e) {
    toast(e.message, "err");
  }
}

async function doLogin() {
  const phone = $("loginPhone").value.trim();
  const code = $("loginCode").value.trim();
  $("loginErr").textContent = "";
  if (!/^1[3-9]\d{9}$/.test(phone)) { $("loginErr").textContent = "手机号格式不正确"; return; }
  if (!/^\d{6}$/.test(code)) { $("loginErr").textContent = "请输入 6 位验证码"; return; }

  const btn = $("btnLogin");
  btn.disabled = true;
  btn.textContent = "登录中…";
  try {
    const r = await api("/m/auth/login", { method: "POST", body: { phone, code } });
    saveAuth(r.token, r.identity);
    await enterApp();
    toast(r.message || "登录成功", "ok");
  } catch (e) {
    $("loginErr").textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "登录 / 注册";
  }
}

/* ---------------- 登录身份切换：用户 / 快递员 ---------------- */
function switchRole(role) {
  document.querySelectorAll(".rs-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.role === role));
  $("userLoginPane").hidden = role !== "USER";
  $("courierLoginPane").hidden = role !== "COURIER";
  $("loginFoot").textContent = role === "USER"
    ? "未注册的手机号将自动创建账号"
    : "快递员账号由后台统一建档，工号与手机号须属于同一人";
}

// 快递员登录：工号 + 手机号双因子（复用触屏端同一接口，token 结构一致）
async function courierLogin() {
  const employee_no = $("courierNo").value.trim().toUpperCase();
  const phone = $("courierPhone").value.trim();
  $("courierErr").textContent = "";
  if (!employee_no) { $("courierErr").textContent = "请填写工号"; return; }
  if (!/^1[3-9]\d{9}$/.test(phone)) { $("courierErr").textContent = "手机号格式不正确"; return; }

  const btn = $("btnCourierLogin");
  btn.disabled = true;
  btn.textContent = "登录中…";
  try {
    const r = await api("/auth/kiosk-login", {
      method: "POST", body: { role: "COURIER", employee_no, phone },
    });
    saveAuth(r.token, r.identity);
    await enterApp();
    toast(r.message || "登录成功", "ok");
  } catch (e) {
    $("courierErr").textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "快递员登录";
  }
}

/* ---------------- 扫码确认登录柜机（票据换 token） ---------------- */
function identityLabel() {
  const id = state.identity || {};
  if (!id.role) return "--";
  if (id.role === "COURIER") return `🚚 ${id.name}（${id.employee_no}）`;
  const phone = String(id.phone || "");
  const masked = phone.replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
  return `👤 ${id.name}（${masked}）`;
}

async function openTicket(tk) {
  state.ticket = tk;
  if (!token()) {           // 未登录：先登录，登录成功后 enterApp 会自动回到这张票据
    state.pendingTicket = tk;
    show("login");
    $("loginHint").textContent = "请先登录，登录后将自动确认柜机登录";
    return;
  }
  try {
    const r = await api("/qr/ticket/" + encodeURIComponent(tk));
    $("tkCabinet").textContent = `${r.cabinet_code} 柜`;
    $("tkLocation").textContent = r.location || "--";
    $("tkIdentity").textContent = identityLabel();
    $("tkExpire").textContent = `${r.expire_in} 秒内有效`;
    $("tkConfirmPane").hidden = false;
    $("tkDonePane").hidden = true;
    show("ticket");
  } catch (e) {
    state.ticket = null;
    toast(e.message, "err");
    show(((state.identity || {}).role === "COURIER") ? "courier" : "pickup");
  }
}

async function confirmTicket() {
  if (!state.ticket) return;
  const btn = $("btnTicketConfirm");
  btn.disabled = true;
  btn.textContent = "确认中…";
  try {
    const r = await api(`/qr/ticket/${encodeURIComponent(state.ticket)}/confirm`,
      { method: "POST", body: {} });
    $("tkDoneMsg").textContent = `${r.cabinet_code} 柜已登录：${(r.identity || {}).name || ""}`;
    $("tkConfirmPane").hidden = true;
    $("tkDonePane").hidden = false;
    toast("已确认，请回到柜机屏幕", "ok");
  } catch (e) {
    toast(e.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "确认登录";
  }
}

function cancelTicket() {
  state.ticket = null;
  toast("已取消");
  show(((state.identity || {}).role === "COURIER") ? "courier" : "pickup");
}

/* ---------------- 数据加载 ---------------- */
async function loadPackages() {
  const r = await api("/m/packages");
  renderPending(r.pending || []);
  state.history = r.history || [];
  renderHistory(state.history);
}

function renderPending(list) {
  state.pending = list;
  $("pendingCount").textContent = list.length;
  $("pendingEmpty").hidden = list.length > 0;
  $("pendingList").innerHTML = list.map((p) => `
    <div class="pkg-card ${p.need_pay ? "paid" : ""}" data-pid="${p.package_id}">
      <div class="pkg-top">
        <div>
          <div class="pkg-cabinet">${esc(p.cabinet_code)} 柜</div>
          <div class="pkg-loc">${esc(p.location || "")} · ${esc(p.company_name || "快递")}</div>
        </div>
        <span class="badge ${p.need_pay ? "warn" : ""}">${p.need_pay ? "待缴费" : "待取"}</span>
      </div>
      <div class="pkg-meta">
        <span>${SIZE_CN[p.size_type] || p.size_type}</span>
        <span>保管至 ${fmtTime(p.expire_time)}</span>
      </div>
      <div class="pkg-foot">
        <span class="fee-tag">${p.need_pay ? `超时费 ¥${Number(p.overtime_fee || 0).toFixed(2)}` : ""}</span>
        <span class="btn primary sm">开柜取件</span>
      </div>
    </div>`).join("");
}

function renderHistory(list) {
  $("historyEmpty").hidden = list.length > 0;
  $("historyList").innerHTML = list.map((p) => `
    <div class="pkg-card" style="border-left-color:#cbd5e1;cursor:default;">
      <div class="pkg-top">
        <div>
          <div class="pkg-cabinet">${esc(p.cabinet_code)} · ${esc(p.cell_code || "")}</div>
          <div class="pkg-loc">${esc(p.tracking_no)}</div>
        </div>
        <span class="badge gray">${STATUS_CN[p.status] || p.status}</span>
      </div>
      <div class="pkg-meta"><span>${SIZE_CN[p.size_type] || p.size_type}</span>
        <span>${fmtTime(p.pickup_time || p.store_time)}</span></div>
    </div>`).join("");
}

async function loadSendOptions() {
  // 寄件人姓名默认取账号姓名；用户可改，所以只在为空时预填，不覆盖已输入内容
  const nameInput = $("sendSenderName");
  if (nameInput && !nameInput.value) nameInput.value = (state.identity || {}).name || "";
  try {
    const [comps, cabs] = await Promise.all([
      api("/companies?size=100"),
      api("/cabinets?size=200"),
    ]);
    $("sendCompany").innerHTML = (comps.data || []).map((c) =>
      `<option value="${c.company_id}">${esc(c.company_name)}</option>`).join("");
    $("sendCabinet").innerHTML = (cabs.data || []).filter((c) => c.status === "NORMAL")
      .map((c) => `<option value="${c.cabinet_id}">${esc(c.cabinet_code)} · ${esc(c.location)}</option>`)
      .join("");
  } catch (e) { /* 选项加载失败不阻塞页面 */ }
}

async function loadMessages() {
  try {
    const r = await api("/notify/inbox?size=20");
    const list = r.data || [];
    $("msgEmpty").hidden = list.length > 0;
    $("msgList").innerHTML = list.map((m) => `
      <div class="pkg-card" style="border-left-color:${m.read ? "#cbd5e1" : "#2563eb"};cursor:default;">
        <div class="pkg-top">
          <div class="pkg-cabinet" style="font-size:14px;">${esc(m.title || "通知")}</div>
          <span class="badge ${m.read ? "gray" : ""}">${m.read ? "已读" : "未读"}</span>
        </div>
        <div class="pkg-loc" style="margin-top:6px;">${esc(m.content || "")}</div>
        <div class="pkg-meta"><span>${fmtTime(m.sent_at || m.created_at)}</span></div>
      </div>`).join("");
  } catch (e) { /* 未登录或接口异常时留空 */ }
}

function renderMe() {
  const id = state.identity || {};
  $("meName").textContent = id.name || "用户";
  $("mePhone").textContent = id.phone
    ? String(id.phone).replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2") : "--";
  $("meAvatar").textContent = (id.name || "用")[0];
}

/* ---------------- 取件详情 ---------------- */
function openDetailFromPackage(pid) {
  const p = state.pending.find((x) => x.package_id === Number(pid));
  if (!p) return;
  // 待取列表里带了格口号，但取件前不展示——与扫码预览保持一致
  const { cell_code, ...rest } = p;
  state.preview = { ...rest, _mode: "pkg" };
  state.openKey = null;
  renderDetail();
  show("detail");
}

async function queryByCode() {
  const code = $("manualCode").value.trim();
  if (!/^\d{6}$/.test(code)) { toast("请输入 6 位取件码", "err"); return; }
  try {
    const r = await api("/m/pickup/preview?code=" + encodeURIComponent(code));
    state.preview = { ...r, _mode: "code", code };
    state.openKey = null;
    renderDetail();
    show("detail");
  } catch (e) {
    toast(e.message, "err");
  }
}

function renderDetail() {
  const p = state.preview;
  $("dCabinet").textContent = `${p.cabinet_code} 柜`;
  $("dLocation").textContent = p.location || "";
  $("dStatus").textContent = STATUS_CN[p.status] || p.status;
  $("dStatus").className = "badge" + (p.need_pay ? " warn" : "");
  $("dTracking").textContent = p.tracking_no || "--";
  $("dSize").textContent = SIZE_CN[p.size_type] || p.size_type || "--";
  $("dStoreTime").textContent = fmtTime(p.store_time);
  $("dExpire").textContent = fmtTime(p.expire_time);
  $("dCell").textContent = p.cell_code || "开柜后显示";
  $("dFeeRow").hidden = !p.need_pay;
  $("dFee").textContent = "¥" + Number(p.overtime_fee || 0).toFixed(2);
  $("btnOpen").textContent = p.need_pay
    ? `支付 ¥${Number(p.overtime_fee || 0).toFixed(2)} 并开柜` : "确认开柜";
  $("dTip").textContent = p.need_pay
    ? "该包裹已超时，支付保管费后自动开柜" : "确认后柜门将自动弹开，请在 30 秒内取走包裹";
}

async function doOpen() {
  const p = state.preview;
  if (!p) return;
  const btn = $("btnOpen");
  btn.disabled = true;
  try {
    if (p.need_pay) {
      await api("/m/pay/overtime", { method: "POST", body: { package_id: p.package_id } });
      toast("保管费支付成功", "ok");
    }
    // 幂等键：同一次开柜重试复用，网络抖动不会导致柜门开两次
    if (!state.openKey) {
      state.openKey = (crypto.randomUUID && crypto.randomUUID()) ||
        `m-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
    const body = p._mode === "code" ? { code: p.code } : { package_id: p.package_id };
    const r = await api("/m/pickup/open", {
      method: "POST", body, headers: { "Idempotency-Key": state.openKey },
    });
    showResult(r);
  } catch (e) {
    if (e.status === 402) {
      toast("请先支付超时保管费", "err");
      state.preview.need_pay = 1;
      state.preview.overtime_fee = e.data && e.data.overtime_fee;
      renderDetail();
    } else {
      toast(e.message, "err");
    }
  } finally {
    btn.disabled = false;
  }
}

function showResult(r) {
  state.preview = { ...(state.preview || {}), package_id: r.package_id, cell_code: r.cell_code };
  $("rCell").textContent = r.cell_code;
  $("rCabinet").textContent = `${r.cabinet_code} · ${r.location || ""}`;
  $("rTip").textContent = r.message || "请取走包裹并关好柜门";
  show("result");
  startCountdown(r.open_seconds || 30);
}

function startCountdown(sec) {
  clearInterval(state.timer);
  let left = sec;
  const total = sec;
  const tick = () => {
    $("rCountdown").textContent = left > 0 ? `${left}s` : "已结束";
    $("rBar").style.width = Math.max(0, (left / total) * 100) + "%";
    if (left <= 0) clearInterval(state.timer);
    left -= 1;
  };
  tick();
  state.timer = setInterval(tick, 1000);
}

async function reopen() {
  if (!state.preview || !state.preview.package_id) return;
  try {
    const r = await api("/m/pickup/reopen", {
      method: "POST", body: { package_id: state.preview.package_id },
    });
    toast(r.message || "柜门已重新弹开", "ok");
    startCountdown(r.open_seconds || 30);
  } catch (e) {
    toast(e.message, "err");
  }
}

/* ---------------- 寄件 ---------------- */
async function submitSend() {
  const err = $("sendErr");
  err.textContent = "";
  const id = state.identity || {};
  const body = {
    user_phone: id.phone,
    // 寄件人姓名允许在表单里改（默认是账号姓名），空则回落到账号姓名
    user_name: ($("sendSenderName").value.trim() || id.name || ""),
    // 寄件人地址：选填。后端未支持时会被忽略，不会阻断下单
    sender_address: $("sendSenderAddress").value.trim() || null,
    recipient_name: $("sendRecipientName").value.trim(),
    recipient_phone: $("sendRecipientPhone").value.trim(),
    // 收件人地址：选填
    recipient_address: $("sendRecipientAddress").value.trim() || null,
    size_type: $("sendSize").value,
    weight: Number($("sendWeight").value) || 0,
    company_id: Number($("sendCompany").value),
    cabinet_id: Number($("sendCabinet").value),
    note: $("sendNote").value.trim() || null,
  };
  // 只有手机号是硬校验；地址一律选填，不参与拦截
  if (!/^1[3-9]\d{9}$/.test(body.recipient_phone)) {
    err.textContent = "收件人手机号格式不正确";
    return;
  }
  const btn = $("btnSend");
  btn.disabled = true;
  btn.textContent = "提交中…";
  try {
    const r = await api("/business/send-order", { method: "POST", body });
    $("sendResult").hidden = false;
    $("srCode").textContent = r.order_code;
    $("srCell").textContent = `${r.cabinet_code} · ${r.cell_code}`;
    $("srTracking").textContent = r.tracking_no;
    toast("下单成功，请放入物品并关好柜门", "ok");
    await loadPackages();
  } catch (e) {
    err.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "下单并开柜";
  }
}

/* ---------------- 扫码 ----------------
 * 手机端**不做**应用内扫码，原因有两个：
 *   ① 柜机二维码的用途已经是"登录柜机"（票据 /m?ticket=xxx），扫码后柜机自己开柜，
 *      手机端再做一个"扫码取件"按钮纯属重复；
 *   ② 浏览器 getUserMedia 只在 HTTPS / localhost 下可用，局域网 HTTP 地址会直接被禁用，
 *      而手机系统相机（或微信扫一扫）是操作系统能力，不受此限制 —— 用它扫深链更好用。
 * 所以这里只保留一条路径：系统相机扫 → 打开 /m?ticket=xxx → 确认登录。
 */

/* ---------------- 启动与事件绑定 ---------------- */
function renderCourier() {
  const id = state.identity || {};
  $("cGreet").textContent = `你好，${id.name || "快递员"}`;
  $("cAvatar").textContent = "🚚";
  $("cName").textContent = `${id.name || "--"}（${id.employee_no || "--"}）`;
  const phone = String(id.phone || "");
  $("cMeta").textContent = `${id.company_name || "快递员"} · ` +
    phone.replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2");
}

async function enterApp() {
  const isCourier = ((state.identity || {}).role) === "COURIER";

  if (isCourier) {
    renderCourier();
    show("courier");
  } else {
    await loadPackages();
    await loadSendOptions();
    renderMe();
    loadMessages();
    $("greet").textContent = `你好，${(state.identity || {}).name || "用户"}`;
    show("pickup");
  }

  // 扫柜机二维码进来（/m?ticket=...）：登录后立刻进入确认页，柜机侧正在轮询
  if (state.pendingTicket) {
    const tk = state.pendingTicket;
    state.pendingTicket = null;
    try { history.replaceState(null, "", "/m"); } catch (e) { /* 忽略 */ }
    await openTicket(tk);
  }
}

async function init() {
  bindEvents();
  // 扫码深链：?ticket=<32位hex>（手机系统相机扫柜机二维码后直接带参数打开）
  const urlTicket = (new URLSearchParams(location.search).get("ticket") || "").trim();
  if (/^[0-9a-fA-F]{32}$/.test(urlTicket)) state.pendingTicket = urlTicket.toLowerCase();

  if (!token()) {
    show("login");
    if (state.pendingTicket) {
      $("loginHint").textContent = "请先登录，登录后将自动确认柜机登录";
    }
    return;
  }
  try {
    if (!state.identity) {
      const v = await api("/auth/kiosk-verify");
      state.identity = v.identity;
      localStorage.setItem(IDENTITY_KEY, JSON.stringify(v.identity));
    }
    await enterApp();
  } catch (e) {
    clearAuth();
    show("login");
  }
}

function bindEvents() {
  $("btnSendCode").addEventListener("click", sendCode);
  $("btnLogin").addEventListener("click", doLogin);
  $("loginCode").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
  $("btnCourierLogin").addEventListener("click", courierLogin);
  $("courierPhone").addEventListener("keydown", (e) => { if (e.key === "Enter") courierLogin(); });
  document.querySelectorAll(".rs-btn").forEach((b) =>
    b.addEventListener("click", () => switchRole(b.dataset.role)));

  $("btnQueryCode").addEventListener("click", queryByCode);
  $("manualCode").addEventListener("keydown", (e) => { if (e.key === "Enter") queryByCode(); });

  $("btnTicketConfirm").addEventListener("click", confirmTicket);
  $("btnTicketCancel").addEventListener("click", cancelTicket);
  $("btnTicketDone").addEventListener("click", () => {
    show(((state.identity || {}).role === "COURIER") ? "courier" : "pickup");
  });

  $("pendingList").addEventListener("click", (e) => {
    const card = e.target.closest(".pkg-card");
    if (card) openDetailFromPackage(card.dataset.pid);
  });

  $("btnBackDetail").addEventListener("click", () => show("pickup"));
  $("btnOpen").addEventListener("click", doOpen);
  $("btnReopen").addEventListener("click", reopen);
  $("btnDone").addEventListener("click", async () => {
    clearInterval(state.timer);
    show("pickup");
    try { await loadPackages(); } catch (e) { /* 刷新失败不影响返回 */ }
  });

  $("btnSend").addEventListener("click", submitSend);
  const doLogout = () => {
    clearAuth();
    state.pending = [];
    state.history = [];
    state.ticket = null;
    show("login");
    toast("已退出登录");
  };
  $("btnLogout").addEventListener("click", doLogout);
  $("btnCourierLogout").addEventListener("click", doLogout);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", async () => {
      if (!token()) { show("login"); return; }
      const name = tab.dataset.tab;
      show(name);
      if (name === "pickup") { try { await loadPackages(); } catch (e) { /* ignore */ } }
      if (name === "me") { renderMe(); loadMessages(); }
      // 助手 / 找柜两个页面的数据加载（定义在 innovations.js）
      if (typeof onInnovationTabEnter === "function") onInnovationTabEnter(name);
    });
  });
}

document.addEventListener("DOMContentLoaded", init);
