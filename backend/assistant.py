# AI 助手服务层（包装推荐 / 智能问答）
#
# 分层意图：
#   assistant.py       ← 本文件：编排「模型 → 校验/兜底 → 落库」的业务流程，不碰 Flask；
#   assistant_api.py   ← HTTP 层：参数校验、频控、错误码、JSON 响应；
#   packaging_rules.py ← 规则引擎与二次校验（纯函数）；
#   integrations/deepseek_client.py ← 只负责把请求发出去。
#
# 这样拆的三个理由：
#   1) 单测可以直接调本层，不必构造 Flask 请求上下文；
#   2) "有模型"和"无模型"两条路径共用同一个校验器，结构天生一致；
#   3) 降级逻辑集中在一处，不会出现某个接口忘了 try/except 而 500。
import logging
import time
import uuid

import db
import packaging_rules
from integrations import deepseek_client
from integrations.errors import IntegrationError

log = logging.getLogger("assistant")

# 会话 id 前缀，便于前端与日志区分
_SESSION_PREFIX = "s_"

# 模型系统提示：明确"只输出 JSON、遵守取值域、遵守固定文案"
_PACK_SYSTEM = """你是快递柜系统的包装顾问。根据用户对物品的中文描述，只输出一个 JSON 对象，不要输出任何解释文字。
JSON 结构（字段全部必填）：
{
  "forbidden": [{"name": "物品名", "reason": "为什么禁寄"}],
  "sensitive": [{"name": "物品名", "reason": "为什么需要注意"}],
  "packaging": [{"step": 1, "title": "短标题", "detail": "具体做法"}],
  "size_type": "SMALL | MEDIUM | LARGE",
  "size_reason": "选择该格口规格的理由",
  "materials": ["气泡膜", "5 号纸箱"],
  "notice": "结果仅供参考，以快递员/承运商审核为准"
}
硬性约束：
1. size_type 只能是 SMALL、MEDIUM、LARGE 三者之一，禁止发明新档位；
2. packaging 给出 3 到 6 步，step 从 1 连续递增；
3. 锂电池、充电宝、打火机、酒精、香水、管制刀具、压缩气罐、活体动物等必须进 forbidden；
4. 玻璃、陶瓷、屏幕、液体、文件证件等易损/敏感物必须进 sensitive；
5. notice 必须原样使用上面给出的固定文案；
6. 只做建议，不要声称已确认订单或已通过审核。"""

_CHAT_SYSTEM = """你是智能快递柜的在线客服助手，用简体中文回答用户的寄件/取件/柜机使用问题。
要求：
1. 回答控制在 200 字以内，直接给可执行的步骤，不要客套话；
2. 涉及金额时说明"超时保管费每件 ¥1.00"；
3. 涉及能否寄递的判断，必须补一句"以快递员/承运商审核为准"；
4. 不确定的信息不要编造，引导用户联系现场工作人员或快递公司客服；
5. 不要索取或复述用户的手机号、姓名、地址等个人信息。"""


class _Timer:
    """毫秒计时器：elapsed_ms 要把重试时间也算进去，便于观测真实耗时。"""

    def __init__(self):
        self.t0 = time.monotonic()

    def ms(self):
        return int((time.monotonic() - self.t0) * 1000)


def _unavailable_reason():
    """AI 不可用的中文原因（区分"总开关关闭"与"未配 Key"）。

    为什么要区分：答辩时被问"为什么走本地规则"，一句准确的 degraded_reason
    比"未配置"更有说服力；运维也能据此判断是配置缺失还是主动关闭。
    """
    cfg = deepseek_client.load_config()
    if not cfg["enabled"]:
        return "AI 功能已被 AI_ENABLED=0 关闭"
    if not cfg["api_key"]:
        return "未配置 DEEPSEEK_API_KEY"
    return None


def health():
    """GET /api/ai/health 的数据源。**只回布尔，不回 Key**。"""
    return {
        "provider": "deepseek",
        "configured": deepseek_client.configured(),
        "mode": deepseek_client.mode(),
    }


# ---------------------------------------------------------------------------
# 包装推荐
# ---------------------------------------------------------------------------
def pack_recommend(description, *, persist=True):
    """返回 (payload, recommendation_id)。

    payload 字段与契约 §1.2 完全一致；recommendation_id 为落库主键（落库失败则 None，
    但**不影响接口成功**——AI 推荐是旁路能力，不能因库存不可用而整体失败）。
    """
    desc = str(description or "").strip()
    timer = _Timer()
    source, degraded, reason = "rule", True, None

    result = None
    if deepseek_client.configured():
        try:
            raw = deepseek_client.complete_json(
                [
                    {"role": "system", "content": _PACK_SYSTEM},
                    {"role": "user", "content": desc},
                ],
                temperature=0.2,
            )
            result = packaging_rules.validate_model_output(raw, desc)
            source, degraded = "deepseek", False
        except IntegrationError as e:
            # 走到这里就是"上游不可用"，一律降级为本地规则，绝不 500
            reason = e.reason
            log.info("pack-recommend 降级：%s", reason)
            result = None
    else:
        reason = _unavailable_reason()

    if result is None:
        result = packaging_rules.recommend_by_rules(desc)

    payload = {
        "source": source,
        "elapsed_ms": timer.ms(),
        "degraded": degraded,
        "degraded_reason": reason,
        "forbidden": result["forbidden"],
        "sensitive": result["sensitive"],
        "packaging": result["packaging"],
        "size_type": result["size_type"],
        "size_reason": result["size_reason"],
        "materials": result["materials"],
        "notice": result["notice"],
    }

    rec_id = None
    if persist:
        rec_id = _save_recommendation(payload, desc)
    payload["recommendation_id"] = rec_id
    return payload, rec_id


def _save_recommendation(payload, description):
    """把推荐结果落到 t_pack_recommendation / t_pack_recommend_item。

    落库失败只记日志并返回 None：AI 推荐属于旁路增强，库暂时不可用时应降级为
    "能看不能用"（recommendation_id 为 null），而不是让整个接口 500。
    """
    try:
        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO t_pack_recommendation
                       (description, source, degraded, degraded_reason, size_type,
                        size_reason, elapsed_ms, notice)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (description[:500], payload["source"], 1 if payload["degraded"] else 0,
                 (payload["degraded_reason"] or None), payload["size_type"],
                 (payload["size_reason"] or None)[:255], payload["elapsed_ms"],
                 payload["notice"][:200]),
            )
            rec_id = cur.lastrowid

            rows = []
            for it in payload["forbidden"]:
                rows.append((rec_id, "FORBIDDEN", 0, it["name"][:100], it["reason"][:500], None, None))
            for it in payload["sensitive"]:
                rows.append((rec_id, "SENSITIVE", 0, it["name"][:100], it["reason"][:500], None, None))
            for it in payload["packaging"]:
                rows.append((rec_id, "STEP", int(it["step"]), it["title"][:100],
                             it["detail"][:500], None, None))
            for name in payload["materials"]:
                rows.append((rec_id, "MATERIAL", 0, str(name)[:100], None, 1, None))
            if rows:
                cur.executemany(
                    """INSERT INTO t_pack_recommend_item
                           (recommendation_id, kind, seq, name, detail, qty, unit)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    rows,
                )
        return rec_id
    except Exception as e:  # noqa: BLE001 —— 落库失败不得影响接口成功
        log.warning("推荐结果落库失败（接口仍返回成功）：%s", type(e).__name__)
        return None


def load_recommendation(rec_id):
    """读回一条推荐（供备包装任务生成材料快照使用）。不存在返回 None。"""
    if not rec_id:
        return None
    head = db.query_one(
        "SELECT * FROM t_pack_recommendation WHERE recommendation_id=%s", (int(rec_id),))
    if not head:
        return None
    items = db.query(
        "SELECT kind, seq, name, detail, qty, unit FROM t_pack_recommend_item "
        "WHERE recommendation_id=%s ORDER BY item_id", (int(rec_id),))
    out = {"forbidden": [], "sensitive": [], "packaging": [], "materials": []}
    for it in items:
        kind = it["kind"]
        if kind == "FORBIDDEN":
            out["forbidden"].append({"name": it["name"], "reason": it["detail"] or ""})
        elif kind == "SENSITIVE":
            out["sensitive"].append({"name": it["name"], "reason": it["detail"] or ""})
        elif kind == "STEP":
            out["packaging"].append(
                {"step": int(it["seq"] or 0), "title": it["name"] or "",
                 "detail": it["detail"] or ""})
        elif kind == "MATERIAL":
            out["materials"].append(it["name"])
    out["size_type"] = head["size_type"]
    out["size_reason"] = head["size_reason"]
    return out


# ---------------------------------------------------------------------------
# 智能问答
# ---------------------------------------------------------------------------
def chat(message, session_id=None):
    """返回契约 §1.3 的响应 dict。无状态：session_id 仅回显/生成，不存服务端会话。"""
    msg = str(message or "").strip()
    sid = _normalize_session(session_id)
    timer = _Timer()
    source, degraded, reason = "rule", True, None

    if deepseek_client.configured():
        try:
            reply = deepseek_client.complete(
                [
                    {"role": "system", "content": _CHAT_SYSTEM},
                    {"role": "user", "content": msg},
                ],
                temperature=0.3,
            )
            return {
                "source": "deepseek",
                "reply": reply,
                "session_id": sid,
                "elapsed_ms": timer.ms(),
                "degraded": False,
                "degraded_reason": None,
            }
        except IntegrationError as e:
            reason = e.reason
            log.info("ai/chat 降级：%s", reason)
    else:
        reason = _unavailable_reason()

    return {
        "source": source,
        "reply": packaging_rules.answer_by_rules(msg),
        "session_id": sid,
        "elapsed_ms": timer.ms(),
        "degraded": degraded,
        "degraded_reason": reason,
    }


def _normalize_session(session_id):
    """session_id 归一：合法则原样用，非法/缺失则生成一个新的。"""
    s = str(session_id or "").strip()
    if s and len(s) <= 64:
        return s
    return _SESSION_PREFIX + uuid.uuid4().hex[:8]
