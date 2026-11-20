/* ===========================================================================
 * 触屏端 · 创新能力逻辑（AI 问答 + 支付状态结果展示）
 * ---------------------------------------------------------------------------
 * 依赖：api-core.js（ApiCore / aiSourceMeta / payStatusMeta）、api.js（API）
 * 与 kiosk.js 共享全局：toast / go / esc 等（kiosk.js 先于本文件加载）
 *
 * 设计取舍：
 *   · 触屏端是"公共设备"，AI 问答不预填、不记忆个人物品信息，
 *     只做通用寄件知识问答，且明确标注来源（AI / 本地规则）。
 *   · 支付结果展示复用同一套状态语义：处理中 / 成功 / 失败，
 *     触屏大字展示，避免用户站在柜机前看不懂。
 * =========================================================================== */

/* ===========================================================================
 * 一、AI 问答（帮助屏入口）
 * =========================================================================== */
const kaiState = {
  sessionId: null,
  busy: false,
};

/** 向日志追加一条消息；role = "user" | "bot" */
function kaiAppend(role, text, source) {
  const log = document.getElementById("kaiLog");
  if (!log) return;
  const wrap = document.createElement("div");
  wrap.className = "kai-msg " + (role === "user" ? "user" : "bot");

  const bubble = document.createElement("div");
  bubble.className = "kai-bubble";
  bubble.textContent = text;      // 用 textContent 防注入（模型输出不可信）
  wrap.appendChild(bubble);

  // 机器人回复标注来源：让评委一眼看出走的是 AI 还是本地规则
  if (role !== "user" && source) {
    const m = aiSourceMeta(source);
    const tag = document.createElement("span");
    tag.className = "kai-src " + m.cls;
    tag.textContent = m.short;
    wrap.appendChild(tag);
  }
  log.appendChild(wrap);
  log.scrollTop = log.scrollHeight;
}

/** 发送问题 */
async function kaiAsk(preset) {
  const input = document.getElementById("kaiInput");
  const hint = document.getElementById("kaiHint");
  const msg = (preset != null ? preset : (input.value || "")).trim();
  if (!msg || kaiState.busy) return;

  kaiAppend("user", msg);
  if (preset == null && input) input.value = "";
  kaiState.busy = true;

  const btn = document.getElementById("kaiSend");
  if (btn) btn.disabled = true;
  if (hint) hint.textContent = "思考中…";

  try {
    const r = await ApiCore.post("/ai/chat",
      { message: msg, ...(kaiState.sessionId ? { session_id: kaiState.sessionId } : {}) },
      { timeout: 30000, auth: false });
    if (r && r.session_id) kaiState.sessionId = r.session_id;
    kaiAppend("bot", (r && r.reply) || "暂时没有答案，请咨询现场工作人员。", r && r.source);
    if (hint) {
      const m = aiSourceMeta(r && r.source);
      hint.textContent = `本条回复来源：${m.label} · 仅供参考，以快递员/承运商审核为准`;
    }
  } catch (e) {
    // 接口不可用时给明确中文提示 + 兜底引导，不白屏也不静默
    const txt = e && e.unavailable
      ? "智能问答暂未开通，请咨询现场工作人员或拨打客服电话"
      : ApiCore.errText(e);
    kaiAppend("bot", "抱歉，" + txt);
    if (hint) hint.textContent = "";
  } finally {
    kaiState.busy = false;
    if (btn) btn.disabled = false;
  }
}

/** 快捷提问 */
function kaiQuick(text) {
  kaiAsk(text);
}

/* ===========================================================================
 * 二、支付结果展示（复用同一套状态语义）
 * =========================================================================== */

/**
 * 渲染支付弹层里的"提供方 + mock 标识"。
 * provider_label 由后端下发中文文案，前端不硬编码第二套。
 */
function kaiRenderPayProvider(p) {
  const tag = document.getElementById("payProviderTag");
  const note = document.getElementById("payProviderNote");
  if (!tag || !note) return;

  // 后端没给就用中性占位，绝不默认成"模拟支付"——真实沙箱模式下那样会误导用户
  const label = (p && (p.provider_label || p.provider)) || "--";
  tag.textContent = label;

  const isMock = !!(p && p.mock);
  tag.className = "pay-provider-tag" + (isMock ? " mock" : " real");
  note.textContent = !p
    ? "正在获取支付渠道…"
    : isMock
      ? "演示环境，不会真实扣款"
      : "支付结果以服务端返回为准";
}

/**
 * 轮询支付单直到出结果（成功/失败/关闭），超时则提示。
 * 触屏端没有"前端判定成功"这回事，一律以服务端状态为准。
 */
async function kaiPollPay(payId, progressEl, opts = {}) {
  const maxTries = opts.maxTries || 60;
  const interval = opts.interval || 1500;
  for (let i = 0; i < maxTries; i += 1) {
    try {
      const p = await ApiCore.get(`/pay/${payId}`, { timeout: 8000, auth: false });
      if (p) kaiRenderPayProvider(p);
      const meta = payStatusMeta(p && p.status);
      if (progressEl) {
        progressEl.textContent =
          meta.cls === "success" ? "✅ " + meta.cn
          : meta.cls === "failed" || meta.cls === "closed" ? "❌ " + meta.cn
          : "⏳ " + meta.cn + "…";
        progressEl.className = "pay-progress " +
          (meta.cls === "success" ? "ok" : (meta.cls === "failed" || meta.cls === "closed") ? "err" : "");
      }
      if (payIsSuccess(p && p.status)) return { ok: true, pay: p };
      if (meta.cls === "failed" || meta.cls === "closed") return { ok: false, pay: p };
    } catch (e) {
      // 单次失败继续重试；连续失败到上限才放弃
      if (i >= maxTries - 1) return { ok: false, error: e };
    }
    await new Promise((r) => setTimeout(r, interval));
  }
  return { ok: false, timeout: true };
}
