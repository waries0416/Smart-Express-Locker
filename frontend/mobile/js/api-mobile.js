/* ===========================================================================
 * 手机端 H5 · 接口封装
 * ---------------------------------------------------------------------------
 * 为什么手机端不复用 /js/api.js：
 *   api.js 里有全局 `const STATUS_CN` / `function toast`，而 mobile/js/app.js
 *   也各自定义了一份同名标识（手机端的文案与触屏端并不相同）。两个文件同时
 *   加载会因 const 重复声明直接 SyntaxError，整页白屏。
 *   所以这里只依赖 /js/api-core.js 提供的 ApiCore 命名空间（超时、loading、
 *   鉴权头、错误归一化），自己声明手机端需要的接口方法，互不污染。
 *
 * token：手机端登录后把 token 存 localStorage["m_token"]，
 *       通过 ApiCore.setTokenProvider 注入，三端网络行为保持一致。
 * =========================================================================== */
const M_TOKEN_KEY = "m_token";

const MApi = {
  // ---- 认证 ----
  sendCode(phone) { return ApiCore.post("/m/auth/send-code", { phone }); },
  login(phone, code) { return ApiCore.post("/m/auth/login", { phone, code }); },
  courierLogin(payload) { return ApiCore.post("/auth/kiosk-login", payload); },
  verify() { return ApiCore.get("/auth/kiosk-verify"); },

  // ---- 取件 ----
  packages() { return ApiCore.get("/m/packages"); },
  pickupPreview(code) { return ApiCore.get(`/m/pickup/preview?code=${encodeURIComponent(code)}`); },
  pickupOpen(body, idemKey) {
    return ApiCore.request("POST", "/m/pickup/open", body,
      idemKey ? { "Idempotency-Key": idemKey } : {});
  },
  pickupReopen(packageId) { return ApiCore.post("/m/pickup/reopen", { package_id: packageId }); },
  payOvertime(packageId) { return ApiCore.post("/m/pay/overtime", { package_id: packageId }); },

  // ---- 寄件 ----
  sendOrder(payload) { return ApiCore.post("/business/send-order", payload); },
  companies() { return ApiCore.get("/companies?size=100"); },
  cabinets() { return ApiCore.get("/cabinets?size=200"); },

  // ---- 消息 ----
  inbox(size = 20) { return ApiCore.get(`/notify/inbox?size=${size}`); },

  // ---- 扫码登录票据 ----
  ticketInfo(tk) { return ApiCore.get("/qr/ticket/" + encodeURIComponent(tk)); },
  ticketConfirm(tk) {
    return ApiCore.post(`/qr/ticket/${encodeURIComponent(tk)}/confirm`, {});
  },

  // ============================================================
  // 创新能力接口
  // ============================================================

  // AI 包装推荐：source 只会是 "deepseek" | "rule"
  aiRecommend(description) {
    return ApiCore.post("/ai/pack-recommend", { description }, { timeout: 30000 });
  },
  aiHealth() { return ApiCore.get("/ai/health", { timeout: 8000 }); },
  // AI 问答
  aiChat(message, sessionId) {
    const body = { message };
    if (sessionId) body.session_id = sessionId;
    return ApiCore.post("/ai/chat", body, { timeout: 30000 });
  },

  // 附近柜体：尽量带上经纬度以获得距离排序
  nearbyCabinets(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return ApiCore.get(`/cabinets/nearby${qs ? "?" + qs : ""}`, { timeout: 12000 });
  },
  // 高德 JS API 配置（只下发公开客户端 key + 安全密钥）
  mapConfig() { return ApiCore.get("/map/config", { timeout: 8000 }); },
  // 地址解析：address 或 lat+lng 二选一；无 AMAP_WEB_KEY 时仍 200 且 degraded:true
  locationResolve(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return ApiCore.get(`/location/resolve?${qs}`, { timeout: 12000 });
  },

  // 备包装材料台账（契约 §2.1）：H5 用于展示"需携带材料"与库存提示
  packMaterials() { return ApiCore.get("/pack-materials", { timeout: 10000 }); },
  // 调整库存：只接受 stock / threshold（COURIER 或 admin 权限）
  updatePackMaterial(id, payload) {
    return ApiCore.put(`/pack-materials/${id}`, payload, { timeout: 10000 });
  },
  // 快递员备包装任务（契约 §2.2）：H5 快递员视图可查看/完成
  packagingTasks(params = {}) {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null)
    ).toString();
    return ApiCore.get(`/courier/packaging-tasks${qs ? "?" + qs : ""}`, { timeout: 12000 });
  },
  packagingTaskDone(taskId, note) {
    return ApiCore.post(`/courier/packaging-tasks/${taskId}/done`,
      note ? { note } : {}, { timeout: 12000 });
  },

  // 支付：创建只传 biz_type/biz_id/provider，金额与状态一律以查询结果为准
  payCreate(bizType, bizId, provider) {
    return ApiCore.post("/pay/create",
      { biz_type: bizType, biz_id: bizId, provider },
      { timeout: 15000 });
  },
  payStatus(payId) { return ApiCore.get(`/pay/${payId}`, { timeout: 10000 }); },
  payMockSucceed(payId) {
    return ApiCore.post(`/pay/${payId}/mock-succeed`, {}, { timeout: 10000 });
  },
};

/* 把手机端的 localStorage token 注入统一网络层 */
ApiCore.setTokenProvider(() => {
  try { return localStorage.getItem(M_TOKEN_KEY) || ""; } catch (e) { return ""; }
});
