# 创新点 1 · AI 接口蓝图（/api/ai/*）
#
# 三个接口（docs/api-innovations.md §1）：
#   GET  /api/ai/health         公开  能力探测，只回布尔
#   POST /api/ai/pack-recommend 公开  包装推荐（频控）
#   POST /api/ai/chat           公开  智能问答（频控）
#
# 三条硬约束（每一条都对应一次真实事故的预防）：
#   1) 外部不可用一律 200 + degraded，绝不 500 —— 见 apiutil 与 assistant 的降级链；
#   2) 任何响应/日志都不得出现 DEEPSEEK_API_KEY —— health 只回布尔；
#   3) 频控超限返回 429 RATE_LIMITED + retry_after_s。
import logging

from flask import Blueprint, jsonify, request

import apiutil
import assistant

assistant_bp = Blueprint("assistant", __name__, url_prefix="/api/ai")

log = logging.getLogger("assistant_api")

MAX_DESCRIPTION = 500
MAX_MESSAGE = 500
MAX_SESSION = 64


@assistant_bp.route("/health", methods=["GET"])
def ai_health():
    """公开：前端据此决定是否展示"AI 推荐"角标。只回布尔，绝不回 Key。"""
    return jsonify(assistant.health())


@assistant_bp.route("/pack-recommend", methods=["POST"])
def pack_recommend():
    """公开（频控）：根据物品描述给出包装与格口建议。"""
    allowed, retry = apiutil.AI_LIMITER.hit(apiutil.client_key("ai-pack"))
    if not allowed:
        resp = apiutil.rate_limited(retry)
        return resp

    body = request.get_json(silent=True) or {}
    raw = body.get("description")
    if raw is None:
        return apiutil.bad_request("缺少 description（物品描述）")
    if not isinstance(raw, str):
        return apiutil.bad_request("description 必须是字符串")
    description = raw.strip()
    if not description:
        return apiutil.bad_request("description 不能为空")
    if len(description) > MAX_DESCRIPTION:
        return apiutil.bad_request(
            f"description 超长（最多 {MAX_DESCRIPTION} 字符，当前 {len(description)}）")

    try:
        payload, _rec_id = assistant.pack_recommend(description)
        return jsonify(payload)
    except Exception:  # noqa: BLE001 —— 兜底：绝不让业务输入触发 500
        log.exception("pack-recommend 未预期异常，已降级为本地规则")
        return jsonify(_ultimate_fallback(description))


def _ultimate_fallback(description):
    """最后一道防线：连规则引擎都异常时，仍返回契约形状的 200 响应。

    之所以要这一层：契约 §0.4 明确"外部依赖不可用一律降级成功返回 200"。
    宁可给一份保守的通用建议，也不让柜机屏幕弹出 500。
    """
    import packaging_rules
    base = packaging_rules.recommend_by_rules(description or "")
    return {
        "source": "rule",
        "elapsed_ms": 0,
        "degraded": True,
        "degraded_reason": "服务端处理异常，已降级为本地规则",
        "forbidden": base["forbidden"],
        "sensitive": base["sensitive"],
        "packaging": base["packaging"],
        "size_type": base["size_type"],
        "size_reason": base["size_reason"],
        "materials": base["materials"],
        "notice": base["notice"],
        "recommendation_id": None,
    }


@assistant_bp.route("/chat", methods=["POST"])
def ai_chat():
    """公开（频控）：无状态问答，session_id 仅用于前端串联对话。"""
    allowed, retry = apiutil.AI_LIMITER.hit(apiutil.client_key("ai-chat"))
    if not allowed:
        return apiutil.rate_limited(retry)

    body = request.get_json(silent=True) or {}
    raw = body.get("message")
    if raw is None:
        return apiutil.bad_request("缺少 message（提问内容）")
    if not isinstance(raw, str):
        return apiutil.bad_request("message 必须是字符串")
    message = raw.strip()
    if not message:
        return apiutil.bad_request("message 不能为空")
    if len(message) > MAX_MESSAGE:
        return apiutil.bad_request(
            f"message 超长（最多 {MAX_MESSAGE} 字符，当前 {len(message)}）")

    session_id = body.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        return apiutil.bad_request("session_id 必须是字符串")
    if isinstance(session_id, str) and len(session_id) > MAX_SESSION:
        return apiutil.bad_request(f"session_id 超长（最多 {MAX_SESSION} 字符）")

    try:
        return jsonify(assistant.chat(message, session_id))
    except Exception:  # noqa: BLE001
        log.exception("ai/chat 未预期异常，已降级为本地规则")
        import packaging_rules
        return jsonify({
            "source": "rule",
            "reply": packaging_rules.answer_by_rules(message),
            "session_id": (session_id or "s_fallback")[:MAX_SESSION],
            "elapsed_ms": 0,
            "degraded": True,
            "degraded_reason": "服务端处理异常，已降级为本地规则",
        })
