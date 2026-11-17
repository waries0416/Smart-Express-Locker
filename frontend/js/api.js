// 前端 API 客户端 —— 与后端 Flask REST API 通信（同源 /api）
const API = {
  base: "/api",

  async request(method, path, body, extraHeaders = {}) {
    const opts = { method, headers: { ...extraHeaders } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(this.base + path, opts);
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = null;
    }
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || `请求失败 (${res.status})`;
      const err = new Error(msg);
      err.status = res.status; // 便于调用方区分 409 引用冲突
      err.data = data;
      throw err;
    }
    return data;
  },

  get(path) { return this.request("GET", path); },
  post(path, body) { return this.request("POST", path, body); },
  put(path, body) { return this.request("PUT", path, body); },
  del(path) { return this.request("DELETE", path); },

  // 实体 CRUD
  list(entity, params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.get(`/${entity}${qs ? "?" + qs : ""}`);
  },
  getOne(entity, id) { return this.get(`/${entity}/${id}`); },
  create(entity, payload) { return this.post(`/${entity}`, payload); },
  update(entity, id, payload) { return this.put(`/${entity}/${id}`, payload); },
  // force=true 时级联清理关联记录（删除前用 refs() 预检，一次确认即可完成）
  remove(entity, id, force) { return this.del(`/${entity}/${id}${force ? "?force=1" : ""}`); },
  // 删除前预检：该记录关联了多少条、是否需要级联清理
  refs(entity, id) { return this.get(`/${entity}/${id}/refs`); },
  // 柜体格口概况（实际数 / 空闲 / 占用 / 故障 / 可缩减下限）
  cabinetCellSummary(id) { return this.get(`/cabinets/${id}/cell-summary`); },

  // 后台登录认证：会话由服务端 HttpOnly Cookie 维护，前端不接触 token
  login(payload) { return this.post("/auth/login", payload); },
  verifyAuth() { return this.request("GET", "/auth/verify"); },
  logout() { return this.post("/auth/logout"); },

  // 触屏端登录（用户=手机号；快递员=工号+手机号）。token 存 sessionStorage "kiosk_token"
  kioskLogin(payload) { return this.post("/auth/kiosk-login", payload); },
  // 触屏端用户自助注册（姓名+手机号；注册成功即自动登录并签发 token）
  kioskRegister(payload) { return this.post("/auth/kiosk-register", payload); },
  kioskVerify() {
    return this.request("GET", "/auth/kiosk-verify", undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },

  // 手机端：取件二维码深链（柜机屏展示，手机系统相机扫）
  baseUrl() { return this.get("/m/base-url"); },
  qrSvg(data, scale) {
    return `${this.base}/m/qr.svg?data=${encodeURIComponent(data)}` +
      (scale ? `&scale=${scale}` : "");
  },

  // 扫码登录票据：柜机建票 → 屏幕展示 → 手机确认 → 柜机轮询换 token
  qrTicket(cabinetId) {
    return this.post("/qr/ticket", cabinetId ? { cabinet_id: cabinetId } : {});
  },
  qrPoll(ticket) { return this.get(`/qr/ticket/${ticket}/poll`); },
  qrCancel(ticket) { return this.post(`/qr/ticket/${ticket}/cancel`, {}); },

  // 业务流
  store(payload) { return this.post("/business/store", payload); },
  pickup(payload) { return this.post("/business/pickup", payload); },
  returnPkg(id) { return this.post(`/business/${id}/return`); },
  exception(id, payload) { return this.post(`/business/${id}/exception`, payload); },
  forceExpire(id) { return this.post(`/business/${id}/force-expire`); },

  // 寄件（用户下单）/ 揽收（快递员收取待寄件）
  sendOrder(payload) { return this.post("/business/send-order", payload); },
  collect(payload) { return this.post("/business/collect", payload); },
  // 两类记录查询
  receivePending(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.get(`/business/receive-pending${qs ? "?" + qs : ""}`);
  },
  sendPending(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.get(`/business/send-pending${qs ? "?" + qs : ""}`);
  },
  // 寄件单快速匹配（存件时按 订单号/收件人手机号 找寄件单）
  sendLookup(q) {
    return this.get(`/business/send-lookup?q=${encodeURIComponent(q)}`);
  },
  // 寄件全程追踪（登录态优先查本人；未登录时支持 订单号 / 手机号）
  sendTrack(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request("GET", `/business/send-track${qs ? "?" + qs : ""}`, undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },

  // 用户端：我的包裹记录查询（登录身份，服务端按 user_id 过滤，仅本人可见）
  myPackages() {
    return this.request("GET", "/business/my-packages", undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  // 用户撤回寄件（仅本人、仅待揽收状态）
  cancelSendOrder(id) {
    return this.request("POST", `/business/send-orders/${id}/cancel`, undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },

  // 触屏：批量取件 / 超时支付 / 开柜
  pickupCandidates(phone, cabinet) {
    const q = new URLSearchParams({ phone });
    if (cabinet) q.set("cabinet", cabinet);
    return this.get(`/business/pickup-candidates?${q}`);
  },
  // 登录用户的待取包裹（取件屏自动展示，仅本人，凭 token 过滤）
  myPickup(cabinet) {
    const q = new URLSearchParams();
    if (cabinet) q.set("cabinet", cabinet);
    return this.request("GET", `/business/my-pickup?${q}`, undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  payOvertime(ids) { return this.post("/business/pay-overtime", { package_ids: ids }); },
  unlock(id, cabinet) { return this.post("/business/unlock", { package_id: id, cabinet_id: cabinet }); },
  unlockBatch(ids, cabinet) { return this.post("/business/unlock-batch", { package_ids: ids, cabinet_id: cabinet }); },

  // 后台：格子矩阵 / 远程强制开锁
  cabinetCells(id) { return this.get(`/business/cabinets/${id}/cells`); },
  cabinetAvailability(id) { return this.get(`/business/cabinets/${id}/availability`); },
  forceUnlockCell(id) { return this.post(`/business/cells/${id}/force-unlock`); },

  // 统计
  overview() { return this.get("/stats/overview"); },
  cabinetThroughput() { return this.get("/stats/cabinet-throughput"); },
  companyRanking() { return this.get("/stats/company-ranking"); },
  cellSizeUsage() { return this.get("/stats/cell-size-usage"); },
  dailyTrend(days = 30) { return this.get(`/stats/daily-trend?days=${days}`); },
  exceptionDist() { return this.get("/stats/exception-distribution"); },
  cabinetOccupancy(id) { return this.get(`/stats/cabinet-occupancy/${id}`); },

  // 消息通知
  // 通知流水列表（type / status / channel / phone / package_id 过滤）
  notices(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return this.get(`/notify/${qs ? "?" + qs : ""}`);
  },
  notifyStats() { return this.get("/notify/stats"); },
  // 用户站内消息（凭登录身份拉取，消息绑定账号，精确送达）
  inboxToken(size = 20) {
    return this.request("GET", `/notify/inbox?size=${size}`, undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  // 站内信标记已读（按登录账号，全部置为已读）
  markInboxReadToken() {
    return this.request("POST", "/notify/inbox/read", {},
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  // 单条站内信标记已读（消息列表每条消息的「标为已读」按钮）
  markInboxReadOne(id) {
    return this.request("POST", `/notify/inbox/${id}/read`, {},
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  // 未读站内信计数（触屏轮询：红点角标 + 新通知到达增量提示）
  noticeUnreadCount() {
    return this.request("GET", "/notify/inbox/unread", undefined,
      { Authorization: "Bearer " + (sessionStorage.getItem("kiosk_token") || "") });
  },
  // 手动重投单条（死信也能复活）
  retryNotice(id) { return this.post(`/notify/${id}/retry`); },
  // 手动触发一次超时扫描 / 一次投递（演示用，不用等 worker 轮询）
  scanNotices() { return this.post("/notify/scan"); },
  dispatchNotices() { return this.post("/notify/dispatch"); },
  // 发一条测试通知，验证渠道连通
  testNotice(payload) { return this.post("/notify/test", payload); },
};

// 友好的错误提示（duration 可指定停留毫秒数，重要警告建议加长）
function toast(msg, type = "info", duration = 2600) {
  let box = document.getElementById("toast-box");
  if (!box) {
    box = document.createElement("div");
    box.id = "toast-box";
    box.style.cssText =
      "position:fixed;top:18px;left:50%;transform:translateX(-50%);z-index:9999;display:flex;flex-direction:column;gap:8px;align-items:center;";
    document.body.appendChild(box);
  }
  const el = document.createElement("div");
  const colors = {
    info: "#2563eb", success: "#16a34a", error: "#dc2626", warn: "#d97706",
  };
  el.style.cssText = `background:${colors[type] || colors.info};color:#fff;padding:10px 18px;border-radius:10px;
    box-shadow:0 8px 24px rgba(0,0,0,.18);font-size:14px;max-width:90vw;`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => {
    el.style.transition = "opacity .4s";
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 400);
  }, duration);
}

// 状态中文映射
const STATUS_CN = {
  STORED: "已存件", PICKED: "已取件", EXPIRED: "已超时",
  EXCEPTION: "异常", RETURNED: "已退回",
  SEND_WAIT_PICKUP: "待揽收", SEND_COLLECTED: "已揽收", SEND_CANCELLED: "已撤回",
  FREE: "空闲", OCCUPIED: "占用", FAULT: "故障",
  NORMAL: "正常", MAINTENANCE: "维护",
};
function statusCn(s) { return STATUS_CN[s] || s; }

// 包裹状态 → 徽章配色类（白名单；不在名单内返回空串走 .pi-badge 默认样式）
const BADGE_STATUS = ["STORED", "PICKED", "EXPIRED", "EXCEPTION", "RETURNED",
                      "SEND_WAIT_PICKUP", "SEND_COLLECTED", "SEND_CANCELLED"];
function badgeStatusCls(s) { return BADGE_STATUS.includes(s) ? s : ""; }

// 业务方向中文映射
const DIRECTION_CN = { RECEIVE: "收件", SEND: "寄件" };
function directionCn(s) { return DIRECTION_CN[s] || s; }

// 手机号脱敏：138****8888（界面展示用，避免整号暴露）
function maskPhone(p) {
  const s = String(p == null ? "" : p).trim();
  return /^\d{11}$/.test(s) ? s.replace(/^(\d{3})\d{4}(\d{4})$/, "$1****$2") : (s || "-");
}

// 统一时间展示格式：年.月.日 时:分（24 小时制，月/日/时不补零，分钟补零）
// 兼容多种输入：ISO(2026-08-31 / 2026-08-31 12:34:56 / T 分隔)、RFC(Flask 序列化 datetime)、空值/无效值
function fmtTime(t) {
  if (!t) return "-";
  const s = String(t).trim();
  const m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{2}))?/);
  if (m) {
    const [, y, mo, d, h, mi] = m;
    const date = `${y}.${+mo}.${+d}`;
    return h !== undefined ? `${date} ${+h}:${mi}` : date;
  }
  // 月-日（统计接口输出，如 '08-28'）→ 8.28
  const md = s.match(/^(\d{1,2})-(\d{1,2})$/);
  if (md) return `${+md[1]}.${+md[2]}`;
  // RFC 格式（如 "Mon, 31 Aug 2026 18:40:30 GMT"，后端按 UTC 输出）：
  // 用 UTC 组件还原，避免本地时区偏移造成 ±8h 错位
  const dt = new Date(s);
  if (isNaN(dt.getTime())) return "-";
  const p = (n) => String(n).padStart(2, "0");
  return `${dt.getUTCFullYear()}.${dt.getUTCMonth() + 1}.${dt.getUTCDate()} ${dt.getUTCHours()}:${p(dt.getUTCMinutes())}`;
}
