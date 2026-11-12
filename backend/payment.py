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
import threading
import time
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
# 匿名持取件码缴费的授权（BUG1 方案A）
# ---------------------------------------------------------------------------
# 为什么需要：触屏端「凭取件码取件 → 超时缴费」是匿名流程，没有 USER token；
#   但用户必须能当场扫码付超时费。信任模型与 /business/pickup 完全一致：
#   6 位取件码本身就是取走包裹的凭证，能取走自然也能为它付费。
# 安全边界（从严，不放宽任何既有规则）：
#   · 只开放 OVERTIME；寄件费涉及寄件人账户，仍必须登录后支付；
#   · 取件码必须与 biz_id 指向同一件 RECEIVE 包裹，否则统一 403（避免枚举包裹）；
#   · 包裹必须 EXPIRED 且未缴费（没超时不出现匿名付费入口；已付再建单会重复扣钱）；
#   · 频控在 payment_api 侧按 IP 做（create / poll 各自独立桶）。
def verify_overtime_pickup_code(biz_type, biz_id, pickup_code):
    """校验"持码缴费"凭证，返回该包裹的 user_id（用于把支付单登记到正确用户名下）。"""
    if (biz_type or "").upper() != BIZ_OVERTIME:
        raise PaymentError("该支付需登录后发起", "FORBIDDEN", 403)
    pkg = db.query_one(
        "SELECT package_id, pickup_code, direction, status, overtime_fee_paid, user_id "
        "FROM t_package WHERE package_id=%s", (int(biz_id),))
    if (not pkg or pkg["direction"] != "RECEIVE"
            or pkg["pickup_code"] != (pickup_code or "")):
        raise PaymentError("取件码与包裹不匹配", "FORBIDDEN", 403)
    if pkg["status"] != "EXPIRED":
        raise PaymentError("该包裹当前无需支付超时费", "CONFLICT", 409)
    if pkg["overtime_fee_paid"]:
        raise PaymentError("该包裹超时费已支付，无需重复支付", "CONFLICT", 409)
    return pkg["user_id"]


def assert_pickup_code_for_order(order_row, pickup_code):
    """匿名轮询授权：取件码必须与支付单对应的包裹一致（只读，不改任何状态）。"""
    if (order_row.get("biz_type") or "").upper() != BIZ_OVERTIME:
        raise PaymentError("该支付单不支持取件码查询", "FORBIDDEN", 403)
    pkg = db.query_one(
        "SELECT package_id, pickup_code, direction FROM t_package WHERE package_id=%s",
        (int(order_row["biz_id"]),))
    if (not pkg or pkg["direction"] != "RECEIVE"
            or pkg["pickup_code"] != (pickup_code or "")):
        raise PaymentError("取件码与支付单不匹配", "FORBIDDEN", 403)
    return pkg


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
def create_order(biz_type, biz_id, provider=None, user_id=None, refresh=False):
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
            # 复用原单：金额以本次重算的为准（业务事实可能已变，如超时费调整）。
            # 真实支付宝模式下还必须**刷新二维码**（见 _refresh_alipay_pending），
            # 否则返回的是几小时前那张旧码，用户扫了会提示"已过期/已失效"。
            if prov == PROVIDER_ALIPAY and not is_mock:
                return _refresh_alipay_pending(
                    existing, amount=amount, user_id=user_id, prov=prov, label=label,
                    is_mock=is_mock, expire_at=expire_at,
                    degraded_reason=degraded_reason, refresh=refresh)
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
                      trade_no=NULL, qr_code=NULL, user_id=COALESCE(%s, user_id),
                      raw_payload=NULL
                WHERE pay_id=%s""",
            (pay_no, amount, prov, label, is_mock, expire_at, user_id,
             existing["pay_id"]))
        row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (existing["pay_id"],))
        _ensure_alipay_qr(row)
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
    _ensure_alipay_qr(row)
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (pay_id,))
    return _order_payload(row, degraded_reason, reused=False)


def _alipay_trade_paid(node):
    """交易是否已支付（支付宝 trade_status 口径）。"""
    return (node.get("trade_status") or "").upper() in ("TRADE_SUCCESS", "TRADE_FINISHED")


def _query_alipay_trade(pay_no):
    try:
        return alipay_client.query_trade(pay_no) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("查询支付宝交易失败：%s", type(e).__name__)
        return {}


# 主动对账节流：pay_id -> 上次查询单调时钟。轮询 2s 一次，这里最多 3s 查一次，
# 避免前端轮询把网关打爆（示范量级，不需要更复杂的分布式节流）。
_QUERY_THROTTLE = {}
_QUERY_MIN_INTERVAL = 3.0
_QUERY_LOCK = threading.Lock()


def reconcile_alipay_pending(pay_id):
    """主动查支付宝交易并对账（无异步通知时的唯一兜底）。

    为什么必须有：ALIPAY_NOTIFY_URL 为空时（本机 127.0.0.1 支付宝也回调不到），
    用户真机付款后异步通知永远不会到达；若只依赖回调，支付单会一直 PENDING、
    柜机永远不开门。这里在查询/轮询路径上主动 `alipay.trade.query` 一次，
    查到 TRADE_SUCCESS/TRADE_FINISHED 且金额与快照一致就入账（mark_success 内部
    用条件更新保证只入账一次）。

    返回最新的订单行（未发生对账时原样返回）。
    """
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (int(pay_id),))
    if not row or row["status"] != STATUS_PENDING or row["is_mock"]:
        return row
    if row["biz_type"] not in BIZ_TYPES or not row["pay_no"]:
        return row

    now = time.monotonic()
    with _QUERY_LOCK:
        last = _QUERY_THROTTLE.get(row["pay_id"], 0.0)
        if now - last < _QUERY_MIN_INTERVAL:
            return row
        _QUERY_THROTTLE[row["pay_id"]] = now

    node = _query_alipay_trade(row["pay_no"])
    if not _alipay_trade_paid(node):
        return row
    paid_amount = node.get("total_amount")
    try:
        if paid_amount is not None and abs(
                float(paid_amount) - float(row["amount"])) > 0.005:
            log.warning("支付宝查单金额与支付单快照不一致，拒绝自动入账")
            return row
        mark_success(row["pay_id"], trade_no=node.get("trade_no"), paid_via="alipay")
    except Exception:  # noqa: BLE001
        log.exception("支付宝查单入账失败")
        return row
    return db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (int(pay_id),))


def _close_alipay_trade(pay_no):
    """best-effort 关闭支付宝交易（只对"已存在"的交易有效）。返回是否成功关闭。"""
    try:
        node = alipay_client.close_trade(pay_no)
    except Exception as e:  # noqa: BLE001
        log.warning("关闭支付宝交易失败：%s", type(e).__name__)
        return False
    if (node.get("code") or "") == "10000":
        return True
    sub = (node.get("sub_code") or "").lower()
    # 交易不存在（还没被扫过）也视为"无需关闭"；ACQ.TRADE_NOT_EXIST 是下划线写法
    return ("not_exist" in sub) or ("not-exist" in sub or "notexist" in sub) \
        or ("交易不存在" in (node.get("sub_msg") or ""))


def _ensure_alipay_qr(row):
    """确保真实模式支付单有一张**缓存的**二维码；返回 qr_code 或 None。

    只在"还没有缓存码"时调用 precreate，并立刻写回 t_pay_order.qr_code。
    绝不在每次响应里重复 precreate —— 支付宝对同一 out_trade_no 再次预下单会换新码
    并把旧码顶掉，那正是"用户扫了提示已失效"的直接原因。
    """
    if bool(row["is_mock"]) or row["status"] != STATUS_PENDING:
        return None
    if row.get("qr_code"):
        return row["qr_code"]
    qr = _build_alipay_qr(row)
    if qr:
        db.execute("UPDATE t_pay_order SET qr_code=%s WHERE pay_id=%s",
                   (qr, row["pay_id"]))
    return qr


def _refresh_alipay_pending(existing, *, amount, user_id, prov, label, is_mock,
                            expire_at, degraded_reason, refresh=False):
    """复用 PENDING 支付单：默认返回**同一张有效码**，只在必要时换交易出新码。

    支付宝实测（2026-11-20 探针，本项目真实沙箱）：
      · 同一 out_trade_no 连续 precreate 返回**不同码串**，且旧码随之作废；
      · 交易在被扫之前并不存在（query → ACQ.TRADE_NOT_EXIST）；
      · 被扫过（WAIT_BUYER_PAY）后重复扫同一码会提示"二维码已失效"。
    因此：
      ① 默认复用缓存 qr_code，**绝不重复预下单**（否则把用户手里的码顶掉）；
      ② 已支付 → 入账并 409；
      ③ 码已被扫过（交易 WAIT_BUYER_PAY）→ 关闭旧交易并换 out_trade_no 重新出码
         （旧码已无意义，关掉换号是安全的）；
      ④ 前端显式 refresh=true → 换新交易出新码（"刷新二维码"按钮用）。
    """
    pay_id = existing["pay_id"]
    old_pay_no = existing["pay_no"]
    cached = existing.get("qr_code")
    old_was_alipay = (not existing["is_mock"]) and existing["provider"] == PROVIDER_ALIPAY

    node = {}
    if old_was_alipay and old_pay_no:
        node = _query_alipay_trade(old_pay_no)
        if _alipay_trade_paid(node):
            try:
                mark_success(pay_id, trade_no=node.get("trade_no"), paid_via="alipay")
            except Exception:  # noqa: BLE001
                log.exception("复用支付单时发现已支付，但入账失败")
            raise PaymentError("该业务单已支付成功，无需重复支付", "CONFLICT", 409)

    need_new = bool(refresh) or not cached or not old_was_alipay
    if not need_new and (node.get("trade_status") or "").upper() == "WAIT_BUYER_PAY":
        # 码已被扫过：交易存在但未支付，再扫同一码会失效 → 关掉旧交易换新码
        _close_alipay_trade(old_pay_no)
        need_new = True

    if not need_new:
        db.execute(
            "UPDATE t_pay_order SET amount=%s, user_id=COALESCE(%s, user_id) "
            "WHERE pay_id=%s", (amount, user_id, pay_id))
        row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (pay_id,))
        return _order_payload(row, degraded_reason, reused=True)

    pay_no = _gen_pay_no()
    db.execute(
        """UPDATE t_pay_order
              SET pay_no=%s, amount=%s, provider=%s, provider_label=%s, is_mock=%s,
                  status='PENDING', expire_at=%s, paid_at=NULL, fail_reason=NULL,
                  trade_no=NULL, qr_code=NULL, user_id=COALESCE(%s, user_id),
                  raw_payload=NULL
            WHERE pay_id=%s""",
        (pay_no, amount, prov, label, is_mock, expire_at, user_id, pay_id))
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (pay_id,))
    _ensure_alipay_qr(row)
    row = db.query_one("SELECT * FROM t_pay_order WHERE pay_id=%s", (pay_id,))
    return _order_payload(row, degraded_reason, reused=True)


def _order_payload(row, degraded_reason=None, reused=False):
    """契约 §4.1 的响应体（create 与 get 共用同一套字段语义）。"""
    is_mock = bool(row["is_mock"])
    qr = None
    redirect = None
    if not is_mock and row["status"] == STATUS_PENDING:
        redirect = _build_alipay_redirect(row)
        # 二维码来自支付单上的缓存（首次 precreate 后写入）；普通复用**不重复预下单**，
        # 否则支付宝会把用户手里那张码顶掉 —— 就是"扫码提示已失效"的根因。
        qr = row.get("qr_code") or redirect
    return {
        "pay_id": row["pay_id"],
        "pay_no": row["pay_no"],
        "amount": round(float(row["amount"]), 2),
        "provider": row["provider"],
        "provider_label": row["provider_label"],
        "mock": is_mock,
        "status": row["status"],
        "expire_at": iso_expire(row["expire_at"]),
        # 系统订单有效期是否已过（PENDING 且 expire_at 已到）。前端据此提示
        # "支付单已过期，请重新获取二维码"，而不是继续展示一张已失效的码。
        "expired": bool(row["status"] == STATUS_PENDING and row["expire_at"]
                        and row["expire_at"] <= datetime.now()),
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
            subject=f"智能快递柜-{row['biz_type']}",
            # 交易有效期与"系统订单有效期"对齐：每次 create 都会重建交易并重新计时，
            # 避免出现"系统订单还有效、支付宝交易却已超时"的错位。
            timeout_express=f"{expire_minutes()}m")
        return alipay_client.gateway_with_params(params)
    except Exception as e:  # noqa: BLE001
        log.warning("生成支付宝跳转地址失败：%s", type(e).__name__)
        return None


def _build_alipay_qr(row):
    """真实沙箱模式：调 precreate 换真二维码内容（qr_code）。失败返回 None。

    注意：每次 create（含复用）都会调到这里，但只有 out_trade_no 变了才会拿到**新码**
    （支付宝对同一 out_trade_no 只返回同一张旧码）。复用时的换号逻辑见
    _refresh_alipay_pending —— 那是"扫码提示已过期"的根因修复。
    """
    try:
        return alipay_client.precreate(
            row["pay_no"], float(row["amount"]),
            subject=f"智能快递柜-{row['biz_type']}",
            timeout_express=f"{expire_minutes()}m")
    except Exception as e:  # noqa: BLE001
        log.warning("支付宝预下单(二维码)失败：%s", type(e).__name__)
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
        "expired": bool(row["status"] == STATUS_PENDING and row["expire_at"]
                        and row["expire_at"] <= datetime.now()),
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
