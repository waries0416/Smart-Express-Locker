/* ===========================================================================
 * api-core.js —— 三端共用的接口基础层（触屏端 / 管理端 / 手机端 H5）
 * ---------------------------------------------------------------------------
 * 为什么单独抽一层，而不是直接写进 api.js：
 *   手机端 app.js 已经用 `const STATUS_CN` / `function toast` / `function fmtTime`
 *   占了全局名字，api.js 里有同名 `const` 声明，两者同时加载会直接 SyntaxError。
 *   所以把「超时 / loading / 来源标识 / 错误文案」这些**与页面无关**的能力
 *   收进一个命名空间 ApiCore，三端各自按需加载，互不污染全局作用域。
 *
 * 约定（与后端 docs/api-innovations.md 一致）：
 *   · AI 接口的 source 只会是 "deepseek" | "rule"
 *   · 支付接口的 mock 是布尔值，provider_label 由后端下发中文文案，前端直接展示
 *   · 401/403 必须有明确中文提示，绝不静默失败
 * =========================================================================== */
const ApiCore = {
  base: "/api",

  // 默认超时 20s：AI 冷启动首包偶尔 >10s，太短会误判成失败
  defaultTimeout: 20000,

  // token 读取器可插拔：触屏/管理端读 sessionStorage，手机端读 localStorage
  tokenProvider: null,
  setTokenProvider(fn) { this.tokenProvider = fn; },

  /** 当前 token（没有则空串）。读取失败一律当匿名，不抛异常。 */
  token() {
    try {
      if (this.tokenProvider) return this.tokenProvider() || "";
      return sessionStorage.getItem("kiosk_token") || "";
    } catch (e) { return ""; }
  },

  /**
   * 鉴权头：唯一注入点，三端都走这里，页面不要各写一套。
   *
   * Lead 裁决 G-12（2026-11-18）：契约文档早期的 `X-Kiosk-Token` 与已运行的
   * `backend/auth.py::kiosk_identity()` 实读的 `Authorization: Bearer` 冲突，
   * 照契约写会全部 401。裁决以现有后端实现为准，统一 `Authorization: Bearer <token>`。
   * 管理端走 HttpOnly Cookie，不依赖本头；本头只服务 USER / COURIER 两套身份。
   */
  authHdr() {
    const tk = this.token();
    if (!tk) return {};
    return { Authorization: "Bearer " + tk };
  },

  /**
   * 统一请求入口。
   * @param {string} method HTTP 方法
   * @param {string} path   以 / 开头的接口路径（不含 /api 前缀）
   * @param {*}      body   JSON 请求体（undefined 表示无请求体）
   * @param {object} headers 额外请求头
   * @param {object} opts   { timeout, auth:boolean }
   *   timeout —— 毫秒；0 表示不限时
   *   auth    —— 默认 true，自动带登录 token；明确不需要身份的接口可传 false
   *
   * 抛出的 Error 带这些标记，调用方据此给不同的中文提示：
   *   timeout / network / unavailable(404,501) / authRequired(401) / forbidden(403) / status
   */
  async request(method, path, body, headers = {}, opts = {}) {
    const timeout = opts.timeout == null ? this.defaultTimeout : opts.timeout;
    const needAuth = opts.auth !== false;
    const h = { ...(needAuth ? this.authHdr() : {}), ...headers };

    const ctrl = new AbortController();
    const timer = timeout > 0 ? setTimeout(() => ctrl.abort(), timeout) : null;

    const fetchOpts = { method, headers: h, signal: ctrl.signal };
    if (body !== undefined) {
      fetchOpts.headers["Content-Type"] = "application/json";
      fetchOpts.body = JSON.stringify(body);
    }

    let res;
    try {
      res = await fetch(this.base + path, fetchOpts);
    } catch (e) {
      const aborted = e && e.name === "AbortError";
      const err = new Error(aborted
        ? `请求超时（超过 ${Math.round(timeout / 1000)} 秒），请稍后重试`
        : "网络连接失败，请检查网络后重试");
      err.timeout = aborted;
      err.network = !aborted;
      err.status = 0;
      throw err;
    } finally {
      if (timer) clearTimeout(timer);
    }

    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }

    if (!res.ok) {
      const raw = data && (data.error || data.message);
      const err = new Error(raw || `请求失败 (${res.status})`);
      err.status = res.status;
      err.data = data;
      // 新增能力后端还没上线时，页面应降级提示而不是报红。
      // 405 也要算：app.py 里有一条 `/api/<path>` 的 OPTIONS 兜底路由，
      // 未注册的接口用 POST 访问会命中它并返回 405（而不是 404）。
      err.unavailable = res.status === 404 || res.status === 405 || res.status === 501;
      if (res.status === 401) {
        err.authRequired = true;
        // 后端可能给出更具体的原因（如 token 已失效），优先用它
        if (!raw) err.message = "登录已过期，请重新登录";
      } else if (res.status === 403) {
        err.forbidden = true;
        if (!raw) err.message = "没有权限执行该操作";
      } else if (res.status === 429) {
        // AI 接口有频控，把 retry_after_s 翻译成人话
        err.rateLimited = true;
        const wait = data && data.retry_after_s;
        err.message = wait
          ? `提问太频繁了，请 ${wait} 秒后再试`
          : "请求太频繁，请稍后再试";
      }
      throw err;
    }
    return data;
  },

  get(path, opts) { return this.request("GET", path, undefined, {}, opts); },
  post(path, body, opts) { return this.request("POST", path, body, {}, opts); },
  put(path, body, opts) { return this.request("PUT", path, body, {}, opts); },
  del(path, opts) { return this.request("DELETE", path, undefined, {}, opts); },

  /**
   * 按钮 loading 态：请求期间禁用并改文案，结束（含异常）后恢复。
   * 同时挡住重复点击 —— 支付、下单这类操作必须有。
   */
  async withLoading(btn, loadingText, fn) {
    if (!btn) return fn();
    const oldHtml = btn.innerHTML;
    const wasDisabled = btn.disabled;
    btn.disabled = true;
    btn.dataset.loading = "1";
    if (loadingText) btn.textContent = loadingText;
    try {
      return await fn();
    } finally {
      btn.disabled = wasDisabled;
      delete btn.dataset.loading;
      btn.innerHTML = oldHtml;
    }
  },

  /** 按钮是否处于 loading（防重入兜底） */
  isLoading(btn) { return !!(btn && btn.dataset && btn.dataset.loading); },

  /**
   * 把任意异常翻译成一句用户能看懂的中文。
   * 401/403 有专门文案；超时/断网/未上线分别区分，避免一律"操作失败"。
   */
  errText(e) {
    if (!e) return "操作失败，请重试";
    if (e.authRequired) return "登录已过期，请重新登录";
    if (e.forbidden) return e.message || "没有权限执行该操作";
    if (e.rateLimited) return e.message || "请求太频繁，请稍后再试";
    if (e.timeout) return "服务响应较慢，请稍后重试";
    if (e.network) return "网络连接失败，请检查网络后重试";
    if (e.unavailable) return "该功能服务端暂未就绪，请稍后再试";
    return e.message || "操作失败，请重试";
  },
};

/* ------------------------------------------------------------------
 * 来源标识：让用户和评委一眼看出当前走的是 AI 还是本地规则
 * ------------------------------------------------------------------ */
const AI_SOURCE = {
  deepseek: { label: "AI 智能推荐", short: "AI 智能", cls: "src-ai", desc: "由大模型实时生成" },
  rule:     { label: "本地规则推荐", short: "本地规则", cls: "src-rule", desc: "大模型不可用，已降级为本地规则" },
};
/** 取来源元信息；未知来源返回中性兜底，不抛错 */
function aiSourceMeta(src) {
  return AI_SOURCE[String(src || "").toLowerCase()]
    || { label: "来源未知", short: "未知", cls: "src-unknown", desc: "接口未返回来源标识" };
}

/* ------------------------------------------------------------------
 * 支付状态：后端只给英文枚举，前端只在展示层翻译
 * 契约（docs/api-innovations.md §4）：PENDING | SUCCESS | FAILED | CLOSED
 * ------------------------------------------------------------------ */
const PAY_STATUS = {
  PENDING: { cn: "处理中", cls: "pending" },
  SUCCESS: { cn: "支付成功", cls: "success" },
  PAID:    { cn: "支付成功", cls: "success" },   // 兼容旧接口/别名
  FAILED:  { cn: "支付失败", cls: "failed" },
  CLOSED:  { cn: "已关闭", cls: "closed" },
  REFUNDED:{ cn: "已退款", cls: "closed" },
};
function payStatusMeta(s) {
  const k = String(s || "").toUpperCase();
  return PAY_STATUS[k] || { cn: s || "未知状态", cls: "pending" };
}
/** 只有 SUCCESS（及兼容别名 PAID）代表"已支付成功"，其余一律不算成功 */
function payIsSuccess(s) {
  const k = String(s || "").toUpperCase();
  return k === "SUCCESS" || k === "PAID";
}

/* 格口规格中文名（三端统一，避免各写一套） */
const SIZE_TYPE_CN = { SMALL: "小件", MEDIUM: "中件", LARGE: "大件" };
function sizeTypeCn(s) { return SIZE_TYPE_CN[String(s || "").toUpperCase()] || (s || "--"); }
