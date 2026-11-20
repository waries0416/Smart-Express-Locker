// 前端 API 客户端 —— 与后端 Flask REST API 通信（同源 /api）
// 网络层（超时 / 鉴权头 / loading / 错误归一化）在 api-core.js 的 ApiCore 里，
// 本文件只负责"有哪些接口、路径怎么拼"，三端共用同一套网络行为。
const API = {
  base: "/api",

  // 默认超时：新增的 AI / 地图 / 支付接口在弱网下可能较慢，
  // 统一 20s 兜底，避免按钮永久卡在 loading（AI 冷启动首包偶尔 >10s）。
  defaultTimeout: 20000,
  // token 来源可插拔：触屏/管理端用 sessionStorage，手机端由 app.js 注入 localStorage 读取器
  tokenProvider: null,
  setTokenProvider(fn) {
    this.tokenProvider = fn;
    ApiCore.setTokenProvider(fn);
  },

  // 统一鉴权头（委托 ApiCore，保证三端行为一致）
  authHdr() { return ApiCore.authHdr(); },

  /** 统一请求入口（委托 ApiCore.request，异常标记见 api-core.js） */
  request(method, path, body, extraHeaders = {}, opts = {}) {
    return ApiCore.request(method, path, body, extraHeaders, opts);
  },

  get(path, opts) { return this.request("GET", path, undefined, {}, opts); },
  post(path, body, opts) { return this.request("POST", path, body, {}, opts); },
  put(path, body, opts) { return this.request("PUT", path, body, {}, opts); },
  del(path, opts) { return this.request("DELETE", path, undefined, {}, opts); },

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
  // 鉴权头由 ApiCore.authHdr() 统一注入（见文件末尾 setTokenProvider），这里不再手写
  kioskVerify() { return this.get("/auth/kiosk-verify"); },

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
    return this.get(`/business/send-track${qs ? "?" + qs : ""}`);
  },

  // 用户端：我的包裹记录查询（登录身份，服务端按 user_id 过滤，仅本人可见）
  myPackages() { return this.get("/business/my-packages"); },
  // 用户撤回寄件（仅本人、仅待揽收状态）
  cancelSendOrder(id) {
    return this.post(`/business/send-orders/${id}/cancel`, undefined);
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
    return this.get(`/business/my-pickup?${q}`);
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
  inboxToken(size = 20) { return this.get(`/notify/inbox?size=${size}`); },
  // 站内信标记已读（按登录账号，全部置为已读）
  markInboxReadToken() { return this.post("/notify/inbox/read", {}); },
  // 单条站内信标记已读（消息列表每条消息的「标为已读」按钮）
  markInboxReadOne(id) { return this.post(`/notify/inbox/${id}/read`, {}); },
  // 未读站内信计数（触屏轮询：红点角标 + 新通知到达增量提示）
  noticeUnreadCount() { return this.get("/notify/inbox/unread"); },
  // 手动重投单条（死信也能复活）
  retryNotice(id) { return this.post(`/notify/${id}/retry`); },
  // 手动触发一次超时扫描 / 一次投递（演示用，不用等 worker 轮询）
  scanNotices() { return this.post("/notify/scan"); },
  dispatchNotices() { return this.post("/notify/dispatch"); },
  // 发一条测试通知，验证渠道连通
  testNotice(payload) { return this.post("/notify/test", payload); },

  // ============================================================
  // 创新能力接口（AI 包装推荐 / AI 问答 / 地图找柜 / 支付 / 备包装）
  // ------------------------------------------------------------
  // 契约来源：Lead 确认版（docs/api-innovations.md 为准）。
  // 约定：AI 类接口的 source 只会是 "deepseek" | "rule"；
  //       支付类接口的 mock 为布尔、provider_label 由后端给中文文案，前端直接展示。
  // ============================================================

  // ---- AI 包装推荐（手机端"描述你的物品"） ----
  // 返回：{source, degraded, elapsed_ms, forbidden[], sensitive[],
  //        packaging[], size_type, size_reason, materials[], notice}
  aiPackRecommend(description) {
    return this.post("/ai/pack-recommend", { description }, { timeout: 30000 });
  },
  // AI 能力健康度：{provider, configured, mode:"deepseek"|"rule"}
  aiHealth() { return this.get("/ai/health", { timeout: 8000 }); },
  // AI 问答：{source, reply, session_id, elapsed_ms}
  aiChat(message, sessionId) {
    const body = { message };
    if (sessionId) body.session_id = sessionId;
    return this.post("/ai/chat", body, { timeout: 30000 });
  },

  // ---- 地图找柜 ----
  // 在既有 /cabinets/nearby 基础上增补 latitude/longitude/distance_m
  nearbyCabinets(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return this.get(`/cabinets/nearby${qs ? "?" + qs : ""}`);
  },
  // 高德 JS API 配置：{provider, js_key, security_js_code, configured}
  // 仅下发公开客户端 key，私有 Key 永远在后端。
  mapConfig() { return this.get("/map/config", { timeout: 8000 }); },

  // ---- 支付 ----
  // 创建支付单：body 只传 biz_type / biz_id / provider，金额与状态一律以查询为准
  payCreate(payload) { return this.post("/pay/create", payload, { timeout: 20000 }); },
  // 查询支付单：前端轮询此接口拿最终状态，不本地判定成功。
  // 需要登录态（USER 本人 / COURIER / admin）；匿名请用 payPollAnonymous。
  payStatus(payId) { return this.get(`/pay/${payId}`, { timeout: 10000 }); },
  /**
   * 匿名状态轮询（无 token 时使用，例如触屏端直接输取件码缴费）。
   * 契约：POST /api/pay/{pay_id}/poll  body={"pickup_code":"641497"}
   * 返回字段与 GET /api/pay/{id} 相同（不含 qr_code_url —— 二维码只在 create 返回）。
   * auth:false 是刻意的：匿名通道靠 pickup_code 交叉校验，不依赖 Bearer token。
   */
  payPollAnonymous(payId, pickupCode) {
    return this.post(`/pay/${payId}/poll`, { pickup_code: pickupCode },
      { timeout: 10000, auth: false });
  },
  // 仅 mock 模式可用：把支付单直接置为成功（演示用）
  payMockSucceed(payId) { return this.post(`/pay/${payId}/mock-succeed`, {}, { timeout: 10000 }); },
  // 管理端支付流水
  payRecords(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return this.get(`/pay/records${qs ? "?" + qs : ""}`);
  },

  // ---- 备包装清单（材料台账，契约 §2.1） ----
  // 权限：COURIER 或 admin；返回 {data:[{material_id,name,spec,stock,threshold,unit}]}
  packMaterials() { return this.get("/pack-materials", { timeout: 10000 }); },
  // 只接受 stock / threshold 两个字段，其余字段后端忽略（契约 §2.1）
  updatePackMaterial(id, payload) {
    return this.put(`/pack-materials/${id}`, payload, { timeout: 10000 });
  },

  // ---- 快递员备包装任务（契约 §2.2） ----
  // 权限：COURIER（只看本人）或 admin；params 支持 status(PENDING|DONE|CANCELED)/page/size
  packagingTasks(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return this.get(`/courier/packaging-tasks${qs ? "?" + qs : ""}`, { timeout: 12000 });
  },
  // 完成备包装任务：note 可选、<=200 字；非本人 403、已完成/已取消 409
  packagingTaskDone(taskId, note) {
    const body = note ? { note } : {};
    return this.post(`/courier/packaging-tasks/${taskId}/done`, body, { timeout: 12000 });
  },

  // ---- 地址解析（契约 §3.3） ----
  // 二选一：address（1–200 字） 或 lat+lng（逆地理编码）
  // 无 AMAP_WEB_KEY / 无网络时后端仍返回 200 + degraded:true + provider:"local"
  locationResolve(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return this.get(`/location/resolve?${qs}`, { timeout: 12000 });
  },
};

/* ------------------------------------------------------------------
 * 三端共用能力的便捷别名：真实实现都在 api-core.js 的 ApiCore 里。
 * 这里只做转发，保持触屏端/管理端既有调用写法（withLoading(...) 等）不变。
 * ------------------------------------------------------------------ */
function withLoading(btn, loadingText, fn) {
  return ApiCore.withLoading(btn, loadingText, fn);
}
function apiErrText(e) { return ApiCore.errText(e); }

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
