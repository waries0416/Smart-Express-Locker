# 创新点 4 · 支付接口蓝图（/api/pay/*）
#
# 五个接口（docs/api-innovations.md §4.1–4.5）：
#   POST /api/pay/create                   USER（本人包裹）或 admin
#   GET  /api/pay/<pay_id>                 USER（本人）/ COURIER（相关）/ admin
#   POST /api/pay/<pay_id>/mock-succeed    admin 且 mock 模式
#   POST /api/pay/notify/alipay            **公开**（服务端到服务端，RSA2 验签 + 幂等键）
#   GET  /api/pay/records                  admin
#
# 鉴权总则（Lead G-12 裁决）：
#   · 前四个中的前三个（create / get / mock-succeed）与 records 统一走
#     `Authorization: Bearer <token>`（用户/快递员）或管理端 Cookie/Bearer；
#   · **例外**：/notify/alipay 是支付宝服务器直连本服务，不可能携带用户 token，
#     因此**不做 Bearer 校验**，改由 RSA2 验签 + (pay_no, trade_no) 幂等键把关。
#     这是设计上的例外，不是遗漏 —— 若强行加 Bearer，真实支付闭环会被 401 挡死。
import logging

from flask import Blueprint, Response, jsonify, request

import apiutil
import payment

payment_bp = Blueprint("payment", __name__, url_prefix="/api/pay")

log = logging.getLogger("payment_api")

MAX_PAGE_SIZE = 100

# 匿名持取件码缴费的频控（内存滑动窗口，与 AI_LIMITER 同源实现）：
#   · create：同一 IP 每分钟 10 次 —— 6 位取件码空间 1e6，10 次/分钟下爆破不现实；
#   · poll：同一 IP 每分钟 120 次 —— 触屏端 2s 轮询≈30 次/分钟，留 4 倍余量；
#   · 两个桶独立，避免正常轮询把建单额度吃掉。
PICKUP_CREATE_LIMITER = apiutil.SlidingWindowLimiter(limit=10, window_seconds=60)
PICKUP_POLL_LIMITER = apiutil.SlidingWindowLimiter(limit=120, window_seconds=60)


def _pay_error(err):
    """PaymentError → 契约 §0.3 的 {error, code} 响应。"""
    return apiutil.error(err.message, err.code, err.status)


def _json_body():
    """兼容 application/json 与表单/空体：支付接口一律只认 JSON。"""
    return request.get_json(silent=True) or {}


# ---------------------------------------------------------------------------
# 4.1 创建支付单
# ---------------------------------------------------------------------------
@payment_bp.route("/create", methods=["POST"])
def create_pay():
    """USER 只能为本人包裹建单；admin 可为任意。

    BUG1 方案A：触屏端「凭取件码取件 → 超时缴费」是匿名流程，不可能带 USER token。
    因此**完全没有登录态时**允许用 `pickup_code`（6 位取件码）作为凭证建单：
    码必须与 biz_id 指向同一件 EXPIRED 且未缴费的 OVERTIME 包裹（见
    payment.verify_overtime_pickup_code）。**有登录态时行为完全不变**（仍只允许
    本人 / 管理员，取件码不参与授权），避免持码者绕过归属校验操作他人支付单。
    """
    body = _json_body()
    biz_type = (body.get("biz_type") or "").strip().upper()
    biz_id = body.get("biz_id")
    provider = body.get("provider")
    pickup_code = (body.get("pickup_code") or "").strip()

    if not biz_type:
        return apiutil.bad_request("缺少 biz_type（OVERTIME / SEND）")
    if biz_id in (None, "", []):
        return apiutil.bad_request("缺少 biz_id")
    if not isinstance(provider, (str, type(None))):
        return apiutil.bad_request("provider 必须是字符串")
    try:
        biz_id = int(biz_id)
    except (TypeError, ValueError):
        return apiutil.bad_request("biz_id 必须是整数")

    # 鉴权：登录态优先（语义不变）；仅"匿名 + 带取件码"才走持码通道
    anonymous_uid = None
    ident, auth_err = apiutil.require_admin_or_kiosk("USER")
    if auth_err:
        if not pickup_code:
            return auth_err                      # 无任何凭证：保持原 401
        allowed, retry_after = PICKUP_CREATE_LIMITER.hit(
            apiutil.client_key("pickup_pay_create"))
        if not allowed:
            return apiutil.rate_limited(retry_after)
        try:
            anonymous_uid = payment.verify_overtime_pickup_code(
                biz_type, biz_id, pickup_code)
        except payment.PaymentError as e:
            return _pay_error(e)

    # 幂等键与归属校验：先取业务单再判断，避免越权者通过 404/403 差异探测包裹存在性
    try:
        _amount, biz_row = payment.amount_of(biz_type, biz_id)
    except payment.PaymentError as e:
        return _pay_error(e)

    user_id = None
    if anonymous_uid is not None:
        user_id = anonymous_uid                  # 持码缴费：登记到该件主人名下
    elif not apiutil.is_admin(ident):
        _role, uid = ident
        if biz_row.get("user_id") != uid:
            # 越权：不是本人的包裹（契约 §4.1 → 403 FORBIDDEN）
            return apiutil.forbidden("只能为本人名下的包裹创建支付单")
        user_id = uid

    try:
        # 请求里的 amount 完全不读取：服务端金额快照是唯一金额来源（docs/08 §4.4）
        payload = payment.create_order(biz_type, biz_id, provider, user_id=user_id,
                                       refresh=bool(body.get("refresh")))
        return jsonify(payload)
    except payment.PaymentError as e:
        return _pay_error(e)
    except Exception:  # noqa: BLE001
        log.exception("创建支付单失败")
        return apiutil.internal_error("创建支付单失败")


# ---------------------------------------------------------------------------
# 4.2 查询支付单
# ---------------------------------------------------------------------------
@payment_bp.route("/records", methods=["GET"])
def pay_records():
    """管理端支付流水（注意：必须注册在 /<pay_id> 之前，否则会被当成 pay_id='records'）。"""
    err = apiutil.require_admin()
    if err:
        return err

    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        return apiutil.bad_request("page 必须是整数")
    try:
        size = int(request.args.get("size", 20))
    except ValueError:
        return apiutil.bad_request("size 必须是整数")
    if not (1 <= size <= MAX_PAGE_SIZE):
        return apiutil.bad_request(f"size 必须在 1~{MAX_PAGE_SIZE} 之间")

    try:
        return jsonify(payment.records(
            page=page, size=size,
            status=request.args.get("status"),
            provider=request.args.get("provider"),
            biz_type=request.args.get("biz_type"),
        ))
    except payment.PaymentError as e:
        return _pay_error(e)


@payment_bp.route("/<int:pay_id>", methods=["GET"])
def get_pay(pay_id):
    """USER 仅本人 / COURIER 仅相关 / admin 任意。"""
    ident, err = apiutil.require_admin_or_kiosk("USER", "COURIER")
    if err:
        return err

    row = payment.order_row(pay_id)
    if not row:
        return apiutil.not_found("支付单不存在")

    if not apiutil.is_admin(ident):
        role, rid = ident
        owner_uid, owner_cid = payment.biz_owner(row["biz_type"], row["biz_id"])
        if role == "USER":
            # 本人包裹 或 支付单本身就登记了本人
            if not (owner_uid == rid or row.get("user_id") == rid):
                return apiutil.forbidden("只能查询本人名下的支付单")
        elif role == "COURIER":
            # 快递员：只允许查看与自己经手的包裹相关的支付单
            if not (owner_cid == rid):
                return apiutil.forbidden("只能查询本人经手包裹的支付单")

    # 主动对账：ALIPAY_NOTIFY_URL 为空时异步通知到不了，轮询/查询时兜底查单入账
    payment.reconcile_alipay_pending(pay_id)
    return jsonify(payment.get_order(pay_id))


# ---------------------------------------------------------------------------
# 4.2b 匿名轮询（BUG1 方案A）：持取件码查自己那笔超时费单的状态
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:pay_id>/poll", methods=["POST"])
def poll_pay_by_pickup_code(pay_id):
    """匿名轮询支付状态：凭取件码即可，无需登录态。

    为什么不直接放宽 GET /api/pay/<id>：那个接口的语义是"本人 / 管理端查询"，
    放宽会破坏归属校验；触屏端匿名缴费只需要"这一笔单的状态"，用取件码做同源
    校验即可，而且本接口**只读**、不改变任何状态。

    频控：与 create 分开的 IP 桶（120 次/分钟），既不影响 2s 轮询，也能挡住
    用顺序 pay_id + 猜码的脚本。
    """
    body = _json_body()
    pickup_code = (body.get("pickup_code") or "").strip()
    allowed, retry_after = PICKUP_POLL_LIMITER.hit(
        apiutil.client_key("pickup_pay_poll"))
    if not allowed:
        return apiutil.rate_limited(retry_after)
    if not pickup_code:
        return apiutil.bad_request("缺少 pickup_code")

    row = payment.order_row(pay_id)
    if not row:
        return apiutil.not_found("支付单不存在")
    try:
        payment.assert_pickup_code_for_order(row, pickup_code)
    except payment.PaymentError as e:
        return _pay_error(e)
    # 主动对账：用户真机付款后若异步通知缺失，靠这里查到 TRADE_SUCCESS 完成入账
    payment.reconcile_alipay_pending(pay_id)
    return jsonify(payment.get_order(pay_id))


# ---------------------------------------------------------------------------
# 4.3 模拟支付成功（仅 mock）
# ---------------------------------------------------------------------------
@payment_bp.route("/<int:pay_id>/mock-succeed", methods=["POST"])
def mock_succeed(pay_id):
    """admin 专用；非 mock 模式返回 403 MOCK_NOT_ALLOWED。请求体中的金额/状态一律忽略。"""
    err = apiutil.require_admin()
    if err:
        return err
    try:
        return jsonify(payment.mock_succeed(pay_id))
    except payment.PaymentError as e:
        return _pay_error(e)
    except Exception:  # noqa: BLE001
        log.exception("模拟支付失败")
        return apiutil.internal_error("模拟支付失败")


# ---------------------------------------------------------------------------
# 4.4 支付宝异步通知（服务端到服务端 · 无用户 token）
# ---------------------------------------------------------------------------
@payment_bp.route("/notify/alipay", methods=["POST"])
def pay_notify_alipay():
    """支付宝服务器回调。

    **例外说明（不要"修正"成 Bearer）**：调用方是支付宝的服务器，没有也不可能有本系统
    的用户登录 token。本接口的安全边界是 RSA2 验签 + 金额核验 + (pay_no, trade_no)
    唯一幂等键；返回给支付宝的必须是纯文本 success / fail。
    """
    # 支付宝异步通知是 form-urlencoded；也兼容 JSON（便于本地复现与单测）
    params = request.form.to_dict() if request.form else _json_body()

    try:
        text, status = payment.handle_notify(params)
    except payment.PaymentError as e:
        body = apiutil.error(e.message, e.code, e.status)
        return body
    except Exception:  # noqa: BLE001 —— 回调异常也必须给支付宝 fail，不能 500
        log.exception("支付回调处理异常")
        text, status = "fail", 200

    return Response(text, status=status, mimetype="text/plain")
