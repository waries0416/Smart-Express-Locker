# 创新点 4 · 支付服务层（金额快照 / 幂等 / 状态机）
#
# 分层：
#   payment.py      ← 本文件：业务规则与状态机，不碰 Flask；
#   payment_api.py  ← HTTP 层：鉴权、参数校验、错误码、回调原文处理；
#   integrations/alipay_client.py ← RSA2 签名/验签与下单参数。
#
# 三条不可退让的设计（每条都对应一个真实攻击面，docs/08 §4.4）：
#   1) **服务端金额快照**：金额只由 biz_type+biz_id 重新计算，请求里的 amount 一律忽略。
#      前端的任何金额都是"展示值"，不是"支付依据"。
#   2) **幂等**：同 biz_type+biz_id 只维护一行支付单（idempotency_key 唯一）。
#      重复提交复用原单，重复回调只记日志不重复入账。
#   3) **入账即生效，且只生效一次**：状态迁移用 `WHERE status='PENDING'` 做条件更新，
#      并发下只有一个请求能改成功；成功时同事务内回写业务单（超时费置已付）。
#
# 为什么支付成功要回写 t_package.overtime_fee_paid：
#   取件闸门（business.pickup / _do_unlock）判的是 `status='EXPIRED' AND overtime_fee_paid=0`。
#   若只在支付表里写 SUCCESS 而不回写包裹，用户付了钱仍然取不出件——
#   这正是 D-01 缺陷的反向版本，必须同事务保证一致。
import logging
import os
import random
from datetime import datetime, timedelta

import db
from integrations import alipay_client

log = logging.getLogger("payment")

PROVIDER_MOCK = "mock"
PROVIDER_ALIPAY = "alipay_sandbox"

PROVIDER_LABEL = {
    PROVIDER_MOCK: "模拟支付",
    PROVIDER_ALIPAY: "支付宝沙箱",
}

BIZ_OVERTIME = "OVERTIME"
BIZ_SEND = "SEND"
BIZ_TYPES = (BIZ_OVERTIME, BIZ_SEND)

STATUS_PENDING = "PENDING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_CLOSED = "CLOSED"
STATUSES = (STATUS_PENDING, STATUS_SUCCESS, STATUS_FAILED, STATUS_CLOSED)

DEFAULT_EXPIRE_MINUTES = 10
DEFAULT_OVERTIME_FEE = 1.00     # 与 business._charge_overtime / mobile_api._fee_of 一致
DEFAULT_SEND_FEE = 1.00         # 寄件费默认值（可用 SEND_FEE_YUAN 覆盖）


class PaymentError(Exception):
    """业务错误：上层据此转成对应的 HTTP 状态码与稳定 code。

    code 对应契约 §0.3 的机读错误码；status 为 HTTP 状态码。
    """

    def __init__(self, message, code="VALIDATION_FAILED", status=400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
def _env_int(name, default):
    try:
        return int((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def _env_float(name, default):
    try:
        return float((os.getenv(name) or "").strip() or default)
    except ValueError:
        return default


def server_provider():
    """服务端配置的支付渠道：'mock' 或 'alipay_sandbox'。

    PAYMENT_PROVIDER=alipay 但凭据不全时**自动回落 mock**（契约 §4.0），
    绝不在缺凭据的情况下尝试真实扣款。
    """
    raw = (os.getenv("PAYMENT_PROVIDER") or PROVIDER_MOCK).strip().lower()
    if raw in ("alipay", "alipay_sandbox", "sandbox"):
        return PROVIDER_ALIPAY if alipay_client.available() else PROVIDER_MOCK
    return PROVIDER_MOCK


def server_provider_degraded():
    """配置了 alipay 但因缺凭据回落 mock 时，返回中文原因；否则 None。"""
    raw = (os.getenv("PAYMENT_PROVIDER") or PROVIDER_MOCK).strip().lower()
    if raw in ("alipay", "alipay_sandbox", "sandbox") and not alipay_client.available():
        return alipay_client.unavailable_reason() or "支付宝沙箱凭据不完整，已回落模拟支付"
    return None


def expire_minutes():
    v = _env_int("PAYMENT_EXPIRE_MINUTES", DEFAULT_EXPIRE_MINUTES)
    return v if v > 0 else DEFAULT_EXPIRE_MINUTES


def resolve_provider(requested):
    """请求里的 provider 不能越过服务端配置（契约 §4.1）。

    服务端是 mock 时，请求写 alipay_sandbox 也会被压回 mock：
    让"渠道降级"发生在服务端，而不是让前端自己判断。
    """
    srv = server_provider()
    req = (requested or "").strip().lower()
    if not req:
        return srv, server_provider_degraded()
    if req in ("mock",):
        return PROVIDER_MOCK, None
    if req in ("alipay", "alipay_sandbox", "sandbox"):
        if srv == PROVIDER_ALIPAY:
            return PROVIDER_ALIPAY, None
        return PROVIDER_MOCK, server_provider_degraded() or "服务端未启用支付宝沙箱，已回落模拟支付"
    raise PaymentError(f"provider 非法（只能是 mock / alipay_sandbox）：{requested}")


# ---------------------------------------------------------------------------
# 金额快照（**唯一的金额来源**）
# ---------------------------------------------------------------------------
def amount_of(biz_type, biz_id):
    """按 biz_type+biz_id 重新计算应付金额，返回 (amount, biz_row)。

    金额只来自数据库里的业务事实，绝不来自请求体。biz 不存在抛 404。
    """
    if biz_type == BIZ_OVERTIME:
        pkg = db.query_one(
            "SELECT package_id, user_id, status, direction, overtime_fee, overtime_fee_paid "
            "FROM t_package WHERE package_id=%s", (biz_id,))
        if not pkg:
            raise PaymentError("包裹不存在", "NOT_FOUND", 404)
        if pkg["direction"] == "SEND":
            raise PaymentError("寄件单请使用 biz_type=SEND 支付", "VALIDATION_FAILED", 400)
        fee = pkg["overtime_fee"]
        amount = round(float(fee), 2) if fee is not None else DEFAULT_OVERTIME_FEE
        if amount <= 0:
            amount = DEFAULT_OVERTIME_FEE
        return amount, pkg

    if biz_type == BIZ_SEND:
        pkg = db.query_one(
            "SELECT package_id, user_id, status, direction FROM t_package WHERE package_id=%s",
            (biz_id,))
        if not pkg:
            raise PaymentError("寄件单不存在", "NOT_FOUND", 404)
        if pkg["direction"] != "SEND":
            raise PaymentError("该包裹不是寄件单，请使用 biz_type=OVERTIME", "VALIDATION_FAILED", 400)
        fee = _env_float("SEND_FEE_YUAN", DEFAULT_SEND_FEE)
        return round(max(0.01, fee), 2), pkg

    raise PaymentError(f"biz_type 非法（只能是 OVERTIME / SEND）：{biz_type}")


def _idem_key(biz_type, biz_id):
    return f"{biz_type}:{int(biz_id)}"


# ---------------------------------------------------------------------------
# 时间与序列化
# ---------------------------------------------------------------------------
def fmt_dt(value):
    """数据库 datetime → 'YYYY-MM-DD HH:MM:SS'（契约 §0.1）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def iso_expire(value):
    """expire_at → ISO8601 带时区（契约 §4.1）。"""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return str(value)
    local = value.astimezone() if value.tzinfo else value.astimezone()
    return local.replace(microsecond=0).isoformat()


def _gen_pay_no():
    """商户订单号：P + YYYYMMDD + 3 位日序列。冲突时退化为随机后缀重试。"""
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"P{today}"
    row = db.query_one(
        "SELECT pay_no FROM t_pay_order WHERE pay_no LIKE %s ORDER BY pay_no DESC LIMIT 1",
        (prefix + "%",))
    seq = 1
    if row and row.get("pay_no"):
        try:
            seq = int(str(row["pay_no"])[len(prefix):]) + 1
        except ValueError:
            seq = 1
    for attempt in range(50):
        candidate = f"{prefix}{seq + attempt:03d}"
        if not db.query_one("SELECT 1 FROM t_pay_order WHERE pay_no=%s", (candidate,)):
            return candidate
    # 极端兜底：日序列耗尽，用随机 4 位避免唯一键冲突
    return f"{prefix}{random.randint(1000, 9999)}"


# ---------------------------------------------------------------------------
# 创建支付单
# ---------------------------------------------------------------------------
def create_order(biz_type, biz_id, provider=None, user_id=None):
    """创建（或复用）支付单，返回契约 §4.1 的响应 dict。

    幂等策略：
      · 同 biz 已有 PENDING 且未过期 → 复用原单（不新建）；
      · 同 biz 已有 SUCCESS            → 409 CONFLICT（不允许对已支付单再支付）；
      · 同 biz 已有 PENDING 但已过期   → 原单置 CLOSED，再用同一行重建；
      · 同 biz 已有 FAILED/CLOSED      → 用同一行重建。
    之所以"复用同一行"而不是每次插入新行：uk_pay_idem 是唯一键，
    复用行既能保住唯一键语义，又能在流水里保留最后一次支付尝试。
    """
    biz_type = (biz_type or "").strip().upper()
    if biz_type not in BIZ_TYPES:
        raise PaymentError(f"biz_type 非法（只能是 OVERTIME / SEND）：{biz_type}")
    try:
        biz_id = int(biz_id)
    except (TypeError, ValueError):
        raise PaymentError("biz_id 必须是整数") from None
    if biz_id <= 0:
        raise PaymentError("biz_id 必须是正整数")

    amount, biz_row = amount_of(biz_type, biz_id)

    prov, degraded_reason = resolve_provider(provider)
    label = PROVIDER_LABEL[prov]
    is_mock = 1 if prov == PROVIDER_MOCK else 0
    idem = _idem_key(biz_type, biz_id)
    now = datetime.now()
    expire_at = now + timedelta(minutes=expire_minutes())

    existing = db.query_one(
        "SELECT * FROM t_pay_order WHERE idempotency_key=%s", (idem,))

    if existing:
        st = existing["status"]
        if st == STATUS_SUCCESS:
            raise PaymentError("该业务单已支付成功，无需重复支付", "CONFLICT", 409)
        if st == STATUS_PENDING and existing["expire_at"] and existing["expire_at"] > now:
            # 复用原单：金额以本次重算的为准（业务事实可能已变，如超时费调整）
            db.execute(
                "UPDATE t_pay_order SET amount=%s, user_id=COALESCE(%s, user_id) "
                "WHERE pay_id=%s", (amount, user_id, existing["pay_id"]))
            row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s",
                               (existing["pay_id"],))
            return _order_payload(row, degraded_reason, reused=True)

        # 已过期 / FAILED / CLOSED：复用同一行重新开单（保住 uk_pay_idem）
        pay_no = _gen_pay_no()
        db.execute(
            """UPDATE t_pay_order
                  SET pay_no=%s, amount=%s, provider=%s, provider_label=%s, is_mock=%s,
                      status='PENDING', expire_at=%s, paid_at=NULL, fail_reason=NULL,
                      trade_no=NULL, user_id=COALESCE(%s, user_id), raw_payload=NULL
                WHERE pay_id=%s""",
            (pay_no, amount, prov, label, is_mock, expire_at, user_id,
             existing["pay_id"]))
        row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (existing["pay_id"],))
        return _order_payload(row, degraded_reason, reused=False)

    pay_no = _gen_pay_no()
    pay_id = db.insert(
        """INSERT INTO t_pay_order
               (pay_no, biz_type, biz_id, user_id, amount, provider, provider_label,
                is_mock, status, idempotency_key, expire_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',%s,%s)""",
        (pay_no, biz_type, biz_id, user_id or biz_row.get("user_id"), amount,
         prov, label, is_mock, idem, expire_at))
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (pay_id,))
    return _order_payload(row, degraded_reason, reused=False)


def _order_payload(row, degraded_reason=None, reused=False):
    """契约 §4.1 的响应体（create 与 get 共用同一套字段语义）。"""
    is_mock = bool(row["is_mock"])
    qr = None
    redirect = None
    if not is_mock and row["status"] == STATUS_PENDING:
        redirect = _build_alipay_redirect(row)
    return {
        "pay_id": row["pay_id"],
        "pay_no": row["pay_no"],
        "amount": round(float(row["amount"]), 2),
        "provider": row["provider"],
        "provider_label": row["provider_label"],
        "mock": is_mock,
        "status": row["status"],
        "expire_at": iso_expire(row["expire_at"]),
        "degraded": bool(degraded_reason),
        "degraded_reason": degraded_reason,
        "qr_code_url": qr,
        "redirect_url": redirect,
        "reused": bool(reused),
    }


def _build_alipay_redirect(row):
    """真实沙箱模式：拼带签名的跳转地址。失败返回 None（不影响建单成功）。"""
    try:
        params = alipay_client.build_page_pay_params(
            row["pay_no"], float(row["amount"]),
            subject=f"智能快递柜-{row['biz_type']}")
        return alipay_client.gateway_with_params(params)
    except Exception as e:  # noqa: BLE001
        log.warning("生成支付宝跳转地址失败：%s", type(e).__name__)
        return None


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------
def get_order(pay_id):
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (int(pay_id),))
    if not row:
        return None
    return {
        "pay_id": row["pay_id"],
        "pay_no": row["pay_no"],
        "status": row["status"],
        "amount": round(float(row["amount"]), 2),
        "provider": row["provider"],
        "provider_label": row["provider_label"],
        "mock": bool(row["is_mock"]),
        "paid_at": fmt_dt(row["paid_at"]),
        "created_at": fmt_dt(row["created_at"]),
        "fail_reason": row["fail_reason"],
        "biz_type": row["biz_type"],
        "biz_id": row["biz_id"],
        "expire_at": iso_expire(row["expire_at"]),
    }


def order_row(pay_id):
    return db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (int(pay_id),))


def biz_owner(biz_type, biz_id):
    """返回 (user_id, courier_id)——用于 GET /api/pay/{id} 的归属校验。"""
    if biz_type not in BIZ_TYPES:
        return None, None
    row = db.query_one(
        "SELECT user_id, courier_id FROM t_package WHERE package_id=%s", (int(biz_id),))
    if not row:
        return None, None
    return row["user_id"], row["courier_id"]


# ---------------------------------------------------------------------------
# 状态迁移（入账点：整个系统里唯一把支付单置 SUCCESS 的地方）
# ---------------------------------------------------------------------------
def mark_success(pay_id, *, trade_no=None, paid_via="mock", raw=None):
    """把 PENDING 单置为 SUCCESS，并**同事务**回写业务单。

    返回 (applied, row)：
      applied=True  首次入账；applied=False 说明已经是 SUCCESS（幂等调用）。
    条件更新 `WHERE status='PENDING'` 是并发安全的唯一手段：
    两个并发回调只有一个能 rowcount=1，另一个走幂等分支。
    """
    with db.transaction() as conn:
        cur = conn.cursor()
        cur.execute(
            """UPDATE t_pay_order
                  SET status='SUCCESS', paid_at=NOW(), trade_no=COALESCE(%s, trade_no),
                      fail_reason=NULL
                WHERE pay_id=%s AND status='PENDING'""",
            (trade_no, int(pay_id)))
        applied = cur.rowcount == 1

        row = None
        cur.execute("SELECT * FROM t_pay_order WHERE pay_id=%s", (int(pay_id),))
        row = cur.fetchone()
        if not row:
            raise PaymentError("支付单不存在", "NOT_FOUND", 404)

        if applied:
            if raw:
                cur.execute(
                    "UPDATE t_pay_order SET raw_payload=%s WHERE pay_id=%s",
                    (str(raw)[:2000], int(pay_id)))
            _apply_to_biz(cur, row)
        return applied, row


def _apply_to_biz(cur, row):
    """支付成功后回写业务单（必须与状态迁移在同一事务内）。"""
    if row["biz_type"] == BIZ_OVERTIME:
        # 超时费：标记已付，取件闸门据此放行
        cur.execute(
            "UPDATE t_package SET overtime_fee_paid=1, overtime_fee=%s "
            "WHERE package_id=%s",
            (round(float(row["amount"]), 2), int(row["biz_id"])))
        cur.execute(
            "INSERT INTO t_exception_log(package_id,exception_type,occur_time,handle_time,"
            "handler,handle_result,remark) VALUES(%s,'TIMEOUT',NOW(),NOW(),'用户','RESOLVED',%s)",
            (int(row["biz_id"]),
             f"在线支付超时保管费 ¥{float(row['amount']):.2f}（{row['pay_no']}）"))
    elif row["biz_type"] == BIZ_SEND:
        # 寄件费：只留痕，不改包裹状态（寄件流程的生命周期由 business.py 控制）
        cur.execute(
            "INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,"
            "result,fail_reason) VALUES(%s,'APP',NOW(),'USER','SUCCESS',%s)",
            (int(row["biz_id"]),
             f"寄件费已支付 ¥{float(row['amount']):.2f}（{row['pay_no']}）"))


def mark_failed(pay_id, reason):
    db.execute(
        "UPDATE t_pay_order SET status='FAILED', fail_reason=%s "
        "WHERE pay_id=%s AND status='PENDING'", (str(reason)[:200], int(pay_id)))


def close_expired():
    """把已过期仍 PENDING 的单置 CLOSED（惰性调用，不依赖定时任务）。"""
    return db.execute(
        "UPDATE t_pay_order SET status='CLOSED', fail_reason='支付超时未完成，已关闭' "
        "WHERE status='PENDING' AND expire_at < NOW()")


# ---------------------------------------------------------------------------
# 模拟支付
# ---------------------------------------------------------------------------
def mock_succeed(pay_id):
    """仅 mock 模式可用的"直接置成功"（演示用）。

    非 mock 一律拒绝：这条防线的作用是防止演示环境误当真实支付，
    也防止真实模式被一个 HTTP 调用凭空入账。
    """
    if server_provider() != PROVIDER_MOCK:
        raise PaymentError("当前为真实支付模式，禁止使用模拟支付接口",
                           "MOCK_NOT_ALLOWED", 403)
    row = order_row(pay_id)
    if not row:
        raise PaymentError("支付单不存在", "NOT_FOUND", 404)
    if row["provider"] != PROVIDER_MOCK or not row["is_mock"]:
        raise PaymentError("当前为真实支付模式，禁止使用模拟支付接口",
                           "MOCK_NOT_ALLOWED", 403)
    if row["status"] in (STATUS_FAILED, STATUS_CLOSED):
        raise PaymentError(f"支付单状态为 {row['status']}，无法置为成功", "CONFLICT", 409)

    applied, row = mark_success(pay_id, paid_via=PROVIDER_MOCK)
    return {
        "pay_id": row["pay_id"],
        "status": row["status"],
        "amount": round(float(row["amount"]), 2),
        "mock": bool(row["is_mock"]),
        "provider_label": row["provider_label"],
        "paid_at": fmt_dt(row["paid_at"]),
        "idempotent": not applied,
    }


# ---------------------------------------------------------------------------
# 异步通知（支付宝 → 本服务，**服务端到服务端**）
# ---------------------------------------------------------------------------
CB_APPLIED = "APPLIED"
CB_DUPLICATE = "DUPLICATE"
CB_VERIFY_FAIL = "VERIFY_FAIL"
CB_AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
CB_IGNORED = "IGNORED"


def _log_callback(params, *, pay_id=None, pay_no=None, trade_no=None,
                  verify_ok=False, amount_ok=False, applied=False,
                  result=CB_IGNORED, reason=None):
    """写 t_pay_callback_log。uk_cb_idem 唯一，重复通知不会重复入账。"""
    idem = f"{pay_no or '-'}:{trade_no or '-'}"
    try:
        db.insert(
            """INSERT INTO t_pay_callback_log
                   (pay_id, pay_no, trade_no, idem_key, provider, trade_status,
                    verify_ok, amount_ok, applied, result, reason, raw_payload)
               VALUES (%s,%s,%s,%s,'alipay_sandbox',%s,%s,%s,%s,%s,%s,%s)""",
            (pay_id, pay_no, trade_no, idem,
             (params or {}).get("trade_status"), 1 if verify_ok else 0,
             1 if amount_ok else 0, 1 if applied else 0, result,
             (reason or "")[:200] or None,
             _safe_raw(params)))
        return True
    except Exception as e:  # noqa: BLE001 —— 唯一键冲突即重复通知
        if "Duplicate" in str(e) or "duplicate" in str(e):
            return False
        log.warning("回调日志写入失败：%s", type(e).__name__)
        return False


def _safe_raw(params):
    """回调原文：**剔除 sign 之外的红线字段**，避免把凭据类信息写进日志表。"""
    if not isinstance(params, dict):
        return None
    keep = {k: v for k, v in params.items()
            if k in ("notify_time", "notify_type", "notify_id", "trade_status",
                     "out_trade_no", "trade_no", "total_amount", "app_id",
                     "charset", "version", "sign_type")}
    return str(keep)[:2000]


def handle_notify(params):
    """处理支付宝异步通知，返回 (纯文本, HTTP 状态)。支付宝要求 'success'/'fail' 纯文本。

    处理顺序（每一步失败都不入账）：
      1) 验签（RSA2）——失败 → fail
      2) 订单存在性（out_trade_no）——不存在 → fail
      3) 金额核验（total_amount 必须等于服务端快照）——不等 → fail
      4) 状态判断（TRADE_SUCCESS/TRADE_FINISHED 才入账，其余仅记日志）
      5) 幂等：同 (pay_no, trade_no) 已有日志 → 只记日志不重复入账，仍返回 success
    """
    params = params or {}
    pay_no = (params.get("out_trade_no") or "").strip()
    trade_no = (params.get("trade_no") or "").strip()
    trade_status = (params.get("trade_status") or "").strip()

    if server_provider() != PROVIDER_ALIPAY:
        # mock 模式：不暴露任何真实凭据，也不接受任何回调入账
        raise PaymentError("当前为模拟支付模式，不接收支付宝回调",
                           "MOCK_NOT_ALLOWED", 403)

    verify_ok = alipay_client.verify_callback(params)
    if not verify_ok:
        # 验签失败也要尽力记下 pay_id：这条日志是事后追查"谁在伪造回调"
        # 的唯一直索，缺了 pay_id 就只能按 pay_no 猜，等于线索断了一半。
        # 注意：**只读不写**，绝不为伪造回调改变任何业务状态。
        failed_pay_id = None
        if pay_no:
            try:
                hit = db.query_one(
                    "SELECT pay_id FROM t_pay_order WHERE pay_no=%s", (pay_no,))
                failed_pay_id = hit["pay_id"] if hit else None
            except Exception:  # noqa: BLE001
                failed_pay_id = None
        _log_callback(params, pay_id=failed_pay_id, pay_no=pay_no, trade_no=trade_no,
                      verify_ok=False, result=CB_VERIFY_FAIL,
                      reason="RSA2 验签失败")
        return "fail", 200

    if not pay_no:
        _log_callback(params, trade_no=trade_no, verify_ok=True,
                      result=CB_IGNORED, reason="缺少 out_trade_no")
        return "fail", 200

    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_no=%s", (pay_no,))
    if not row:
        _log_callback(params, pay_no=pay_no, trade_no=trade_no, verify_ok=True,
                      result=CB_IGNORED, reason="商户订单号不存在")
        return "fail", 200

    amount_ok = _amount_matches(params.get("total_amount"), row["amount"])
    if not amount_ok:
        _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                      verify_ok=True, amount_ok=False, result=CB_AMOUNT_MISMATCH,
                      reason="金额与订单快照不符")
        return "fail", 200

    if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED"):
        _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                      verify_ok=True, amount_ok=True, result=CB_IGNORED,
                      reason=f"交易状态 {trade_status or '空'} 不入账")
        return "success", 200

    if row["status"] == STATUS_SUCCESS:
        # 重复通知：只记日志，不重复入账，仍返回 success（支付宝要求）
        _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                      verify_ok=True, amount_ok=True, applied=False,
                      result=CB_DUPLICATE, reason="订单已成功，重复通知")
        return "success", 200

    if row["status"] in (STATUS_FAILED, STATUS_CLOSED):
        _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                      verify_ok=True, amount_ok=True, applied=False,
                      result=CB_IGNORED, reason=f"订单状态 {row['status']}，不入账")
        return "fail", 200

    try:
        applied, _row = mark_success(row["pay_id"], trade_no=trade_no,
                                     paid_via=PROVIDER_ALIPAY, raw=params)
    except Exception as e:  # noqa: BLE001
        log.warning("回调入账失败：%s", type(e).__name__)
        _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                      verify_ok=True, amount_ok=True, applied=False,
                      result=CB_IGNORED, reason="入账异常")
        return "fail", 200

    _log_callback(params, pay_id=row["pay_id"], pay_no=pay_no, trade_no=trade_no,
                  verify_ok=True, amount_ok=True, applied=applied,
                  result=CB_APPLIED if applied else CB_DUPLICATE,
                  reason=None if applied else "并发重复通知")
    return "success", 200


def _amount_matches(notified, snapshot):
    """金额核验：按"分"比较，避免浮点误差误判。"""
    try:
        a = int(round(float(notified) * 100))
        b = int(round(float(snapshot) * 100))
    except (TypeError, ValueError):
        return False
    return a == b


# ---------------------------------------------------------------------------
# 流水（管理端）
# ---------------------------------------------------------------------------
def records(page=1, size=20, status=None, provider=None, biz_type=None):
    """GET /api/pay/records 的数据源：分页 + 版本无关的筛选。"""
    wheres, params = [], []
    if status:
        if status.upper() not in STATUSES:
            raise PaymentError(f"status 非法：{status}")
        wheres.append("status=%s")
        params.append(status.upper())
    if provider:
        if provider.lower() not in (PROVIDER_MOCK, PROVIDER_ALIPAY):
            raise PaymentError(f"provider 非法：{provider}")
        wheres.append("provider=%s")
        params.append(provider.lower())
    if biz_type:
        if biz_type.upper() not in BIZ_TYPES:
            raise PaymentError(f"biz_type 非法：{biz_type}")
        wheres.append("biz_type=%s")
        params.append(biz_type.upper())
    where_sql = (" WHERE " + " AND ".join(wheres)) if wheres else ""

    total = db.query_one(f"SELECT COUNT(*) AS c FROM t_pay_order{where_sql}", params)["c"]
    rows = db.query(
        f"SELECT * FROM t_pay_order{where_sql} ORDER BY pay_id DESC LIMIT %s OFFSET %s",
        params + [size, (page - 1) * size])
    return {
        "count": int(total),
        "page": page,
        "size": size,
        "data": [{
            "pay_id": r["pay_id"],
            "pay_no": r["pay_no"],
            "biz_type": r["biz_type"],
            "biz_id": r["biz_id"],
            "amount": round(float(r["amount"]), 2),
            "status": r["status"],
            "provider": r["provider"],
            "provider_label": r["provider_label"],
            "mock": bool(r["is_mock"]),
            "created_at": fmt_dt(r["created_at"]),
            "paid_at": fmt_dt(r["paid_at"]),
        } for r in rows],
    }
