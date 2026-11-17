# 核心业务流程蓝图
# 存件分配格口 store、验证码取件 pickup、包裹退回 return、
# 异常登记 exception、强制超时 force-expire。
import random
import re
from datetime import datetime
from flask import Blueprint, request, jsonify

import db
import notify
from auth import require_kiosk_role

business_bp = Blueprint("business", __name__, url_prefix="/api/business")

SIZE_FIT = {
    "SMALL": ["SMALL"],
    "MEDIUM": ["MEDIUM"],
    "LARGE": ["LARGE"],
}

# 各规格格口的重量上限（kg）：用户寄件/快递员存件时校验，超限拒绝
SIZE_WEIGHT_LIMIT = {
    "SMALL": 5.0,
    "MEDIUM": 10.0,
    "LARGE": 20.0,
}
_SIZE_CN = {"SMALL": "小件", "MEDIUM": "中件", "LARGE": "大件"}


def _check_weight_limit(size_type, weight):
    """校验重量是否超过所选规格格口的限重；超限返回明确提示文案，合规返回 None。"""
    limit = SIZE_WEIGHT_LIMIT.get(size_type)
    if limit is None:
        return None
    try:
        w = float(weight) if weight is not None else 0.0
    except (TypeError, ValueError):
        return "重量格式不正确"
    if w > limit:
        return (f"{_SIZE_CN.get(size_type, size_type)}格口限重 {limit:g}kg，"
                f"您填写 {w:g}kg，已超限。请选择更大规格格口或调整重量")
    return None


def _gen_pickup_code():
    while True:
        code = "".join(random.choice("0123456789") for _ in range(6))
        if not db.query_one("SELECT 1 FROM t_package WHERE pickup_code=%s", (code,)):
            return code


def _gen_tracking_no(prefix):
    while True:
        no = prefix + "".join(random.choice("0123456789") for _ in range(12))
        if not db.query_one("SELECT 1 FROM t_package WHERE tracking_no=%s", (no,)):
            return no


def _detail(pid):
    return db.query_one("SELECT * FROM v_package_detail WHERE package_id=%s", (pid,))


@business_bp.route("/store", methods=["POST"])
def store():
    """快递员存件：分配格口、生成取件码、写入包裹与占用格口。

    支持 from_send_code（已揽收寄件的揽收码）：用户寄件下单时已确定格口大小，
    快递员把该寄件存柜（投递）时规格必须沿用寄件单的 size_type，不允许重选。
    """
    body = request.get_json(silent=True) or {}
    courier_id = body.get("courier_id")
    user_phone = (body.get("user_phone") or "").strip()
    user_name = (body.get("user_name") or "").strip()
    size_type = (body.get("size_type") or "").upper()
    from_send_code = (body.get("from_send_code") or "").strip()
    weight = body.get("weight", 0)
    cabinet_id = body.get("cabinet_id")
    note = body.get("note")

    if not courier_id:
        return jsonify({"error": "缺少快递员ID"}), 400

    # 关联寄件单：用户寄件时已确定的规格优先，快递员存柜必须沿用；
    # 收件人（手机号/姓名）未填时自动从寄件单带出，并建立投递↔寄件关联(from_send_id)供全程追踪。
    # 重量同样强制沿用用户寄件时录入的值，快递员不得手动填写，确保记录完全一致。
    from_send_id = None
    if from_send_code:
        send_pkg = db.query_one(
            "SELECT * FROM t_package WHERE pickup_code=%s", (from_send_code,))
        if not send_pkg or send_pkg["direction"] != "SEND" or send_pkg["status"] != "SEND_COLLECTED":
            return jsonify({"error": "揽收码无效或该寄件尚未揽收，无法关联存柜"}), 400
        size_type = send_pkg["size_type"]   # 强制沿用寄件规格
        weight = send_pkg["weight"] or 0    # 强制沿用寄件单重量（用户原始录入）
        from_send_id = send_pkg["package_id"]
        if not user_phone and send_pkg.get("recipient_phone"):
            user_phone = send_pkg["recipient_phone"]
        if not user_name and send_pkg.get("recipient_name"):
            user_name = send_pkg["recipient_name"]
        if not note:
            note = f"关联寄件单 {send_pkg['tracking_no']}（规格/重量沿用）"
    if size_type not in SIZE_FIT:
        return jsonify({"error": "包裹规格必须为 SMALL/MEDIUM/LARGE"}), 400
    if not user_phone:
        return jsonify({"error": "请填写收件人手机号"}), 400
    if not re.match(r"^1[3-9]\d{9}$", user_phone):
        return jsonify({"error": "收件人手机号格式不正确（须为 11 位有效手机号）"}), 400
    # 格口限重校验：超过所选规格格口的重量上限直接拒绝并明确提示
    limit_err = _check_weight_limit(size_type, weight)
    if limit_err:
        return jsonify({"error": limit_err}), 400

    # 校验快递员，顺便取出 company_code 用于生成运单号
    courier = db.query_one(
        "SELECT c.*, e.company_code FROM t_courier c "
        "JOIN t_express_company e ON e.company_id = c.company_id "
        "WHERE c.courier_id=%s", (courier_id,)
    )
    if not courier:
        return jsonify({"error": "快递员不存在"}), 404

    # 收件人按手机号查，查不到就自动建档；关联寄件单时姓名已由后端带出
    user = db.query_one("SELECT * FROM t_user WHERE phone=%s", (user_phone,))
    if not user:
        user_name = (user_name or "收件人").strip()[:30]
        try:
            uid = db.insert("INSERT INTO t_user(name, phone) VALUES(%s,%s)", (user_name, user_phone))
        except Exception as e:
            return jsonify({"error": f"收件人建档失败: {e}"}), 400
        user = db.query_one("SELECT * FROM t_user WHERE user_id=%s", (uid,))

    # 分配格口放在事务里，用 SELECT ... FOR UPDATE 加行级排他锁，
    # 防止两个并发存件请求争抢同一个空闲格口，锁在事务提交前一直生效。
    try:
        with db.transaction() as conn:
            cur = conn.cursor()
            fit = SIZE_FIT[size_type]
            placeholders = ",".join(["%s"] * len(fit))
            sql = (f"SELECT cell_id, cabinet_id, cell_code, size_type FROM t_cell "
                   f"WHERE status='FREE' AND size_type IN ({placeholders})")
            params = list(fit)
            if cabinet_id:
                sql += " AND cabinet_id=%s"
                params.append(cabinet_id)
            sql += " ORDER BY cell_id LIMIT 1 FOR UPDATE"
            cur.execute(sql, params)
            cell = cur.fetchone()
            if not cell:
                return jsonify({"error": "当前无可用格口（规格不匹配或柜体已满）"}), 409

            # 生成取件码与运单号
            pickup_code = _gen_pickup_code()
            tracking_no = body.get("tracking_no") or _gen_tracking_no(courier["company_code"])

            # 写入包裹，状态 STORED；若由寄件单转入则记录 from_send_id
            cur.execute(
                """INSERT INTO t_package(tracking_no, courier_id, user_id, cabinet_id, cell_id,
                                         size_type, weight, status, pickup_code, store_time,
                                         expire_time, note, from_send_id, overtime_fee, overtime_fee_paid)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,'STORED',%s, NOW(),
                         DATE_ADD(NOW(),INTERVAL 48 HOUR),%s,%s,NULL, 0)""",
                (tracking_no, courier_id, user["user_id"], cell["cabinet_id"], cell["cell_id"],
                 size_type, weight, pickup_code, note, from_send_id),
            )
            pid = cur.lastrowid
            # 占用格口，同一连接下前面的 FOR UPDATE 锁仍然有效
            cur.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell["cell_id"],))
    except Exception as e:
        return jsonify({"error": f"存件失败: {e}"}), 500

    detail = _detail(pid)
    # 通知旁路：存件事务已提交，这里才通知收件人；通知失败不影响存件结果
    notify.safe_enqueue("STORE_ARRIVAL", pid)
    return jsonify({
        "message": "存件成功，已分配格口",
        "pickup_code": pickup_code,
        "tracking_no": tracking_no,
        "cabinet_code": detail["cabinet_code"],
        "cell_code": detail["cell_code"],
        "package": detail,
    }), 201


# ---- 寄件（用户下单）/ 揽收（快递员收取待寄件）/ 两类记录查询 ----
def _pending_row(r):
    need_pay = 1 if (r["pkg_status"] == "EXPIRED" and not r["overtime_fee_paid"]) else 0
    return {
        "package_id": r["package_id"],
        "tracking_no": r["tracking_no"],
        "status": r["pkg_status"],
        "direction": r.get("direction"),
        "size_type": r["size_type"],
        "weight": r.get("weight"),
        "pickup_code": r.get("pickup_code"),
        "store_time": r["store_time"],
        "expire_time": r["expire_time"],
        "pickup_time": r.get("pickup_time"),
        "cabinet_code": r["cabinet_code"],
        "location": r.get("location"),
        "cell_code": r["cell_code"],
        "courier_name": r.get("courier_name"),
        "company_name": r.get("company_name"),
        "user_name": r.get("user_name"),
        "user_phone": r.get("user_phone"),
        "overtime_fee": float(r["overtime_fee"]) if r["overtime_fee"] is not None else None,
        "need_pay": need_pay,
    }


# ---- 用户端：我的包裹记录查询（仅本人可见） / 寄件撤回 ----
@business_bp.route("/my-packages", methods=["GET"])
def my_packages():
    """登录用户的包裹记录查询：凭触屏 token 取身份，服务端按 user_id 过滤。

    返回该用户收件 + 寄件两个方向、全部状态的包裹（含已取/已撤回），
    状态一栏供前端渲染"包裹状态"时间线；不支持任何手机号/用户参数——
    身份只来自登录态，杜绝输入他人手机号的越权查询。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    rows = db.query(
        """SELECT * FROM v_package_detail WHERE user_id=%s
           ORDER BY store_time DESC LIMIT 200""", (uid,))
    packages = []
    for r in rows:
        if r.get("direction") == "RECEIVE":
            p = _pending_row(r)
        else:
            p = _send_order_row(
                db.query_one("SELECT * FROM t_package WHERE package_id=%s", (r["package_id"],)), r)
            p["delivery"] = _delivery_of(r["package_id"])   # 寄件单关联的投递件
        # 撤回可用性：仅本人寄件单、尚未被揽收时可以撤回
        p["can_cancel"] = bool(r.get("direction") == "SEND" and r["pkg_status"] == "SEND_WAIT_PICKUP")
        packages.append(p)
    return jsonify({"count": len(packages), "packages": packages})


@business_bp.route("/send-orders/<int:pid>/cancel", methods=["POST"])
def cancel_send_order(pid):
    """用户撤回寄件：仅本人、仅「待揽收」状态可撤回。

    撤回联动（同一事务提交）：
      1) t_package.status → SEND_CANCELLED（快递员待送列表按状态过滤，自动剔除）；
      2) 释放占用的格口（t_cell → FREE，格口可被新寄件/存件分配）；
      3) t_pickup_record 留痕（APP/USER/FAIL，原因"用户撤回寄件"）。
    快递员侧数据同步：未揽收寄件单 courier_id 为 NULL，快递员侧无归属记录需要改写；
    已揽收（SEND_COLLECTED）的件已脱离柜体由快递员经手，不允许用户单方面撤回。
    撤回成功后异步通知寄件人（SEND_CANCELLED 模板，幂等键隔离）。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pid,))
    if not pkg:
        return jsonify({"error": "寄件单不存在"}), 404
    if pkg["user_id"] != uid:
        return jsonify({"error": "只能撤回本人提交的寄件单"}), 403
    if pkg["direction"] != "SEND":
        return jsonify({"error": "仅寄件单支持撤回，收件件请走取件/退回流程"}), 409
    if pkg["status"] == "SEND_COLLECTED":
        return jsonify({"error": "该寄件已被快递员揽收，无法在线撤回，请联系快递公司处理"}), 409
    if pkg["status"] != "SEND_WAIT_PICKUP":
        return jsonify({"error": f"当前状态为 {pkg['status']}，无法撤回"}), 409

    try:
        with db.transaction() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE t_package SET status='SEND_CANCELLED' WHERE package_id=%s AND status='SEND_WAIT_PICKUP'",
                (pid,))
            if cur.rowcount != 1:          # 并发兜底：揽收与撤回同时发生时只允许一个成功
                raise ValueError("寄件单状态已变化（可能刚被揽收），请刷新后重试")
            cur.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (pkg["cell_id"],))
            cur.execute(
                """INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result,fail_reason)
                   VALUES(%s,'APP',NOW(),'USER','FAIL','用户撤回寄件，格口已释放')""", (pid,))
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": f"撤回失败: {e}"}), 500

    detail = _detail(pid)
    detail["status"] = detail["pkg_status"]      # 视图列名统一为 status 返回给前端
    # 通知旁路：撤回成功后告知寄件人（事务已提交，通知失败不影响撤回结果）
    notify.safe_enqueue("SEND_CANCELLED", pid)
    return jsonify({"message": "寄件已撤回，格口已释放", "package": detail})


@business_bp.route("/send-order", methods=["POST"])
def send_order():
    """用户寄件下单：选择目标柜体/规格/寄送公司，分配空闲格口并生成揽收码。

    寄件单必须携带寄件人 + 收件人手机号（均做格式校验），快递员可凭揽收码/
    运单号/收件人手机号快速匹配该单直接完成存件（投递）。
    """
    body = request.get_json(silent=True) or {}
    user_phone = (body.get("user_phone") or "").strip()
    user_name = (body.get("user_name") or "").strip()
    recipient_phone = (body.get("recipient_phone") or "").strip()
    recipient_name = (body.get("recipient_name") or "").strip()[:30] or None
    size_type = (body.get("size_type") or "").upper()
    company_id = body.get("company_id")
    cabinet_id = body.get("cabinet_id")
    weight = body.get("weight") or 0
    note = body.get("note")

    if not re.match(r"^1[3-9]\d{9}$", user_phone):
        return jsonify({"error": "寄件人手机号格式不正确（须为 11 位有效手机号）"}), 400
    if not recipient_phone:
        return jsonify({"error": "请填写收件人手机号"}), 400
    if not re.match(r"^1[3-9]\d{9}$", recipient_phone):
        return jsonify({"error": "收件人手机号格式不正确（须为 11 位有效手机号）"}), 400
    if size_type not in SIZE_FIT:
        return jsonify({"error": "包裹规格必须为 SMALL/MEDIUM/LARGE"}), 400
    if not company_id:
        return jsonify({"error": "请选择寄送公司"}), 400
    company = db.query_one("SELECT * FROM t_express_company WHERE company_id=%s", (company_id,))
    if not company:
        return jsonify({"error": "寄送公司不存在"}), 404
    if not cabinet_id:
        return jsonify({"error": "请选择目标快递柜"}), 400
    # 格口限重校验：用户寄件录入的重量不能超过所选规格格口的重量上限
    limit_err = _check_weight_limit(size_type, weight)
    if limit_err:
        return jsonify({"error": limit_err}), 400

    user = db.query_one("SELECT * FROM t_user WHERE phone=%s", (user_phone,))
    if not user:
        try:
            uid = db.insert("INSERT INTO t_user(name, phone) VALUES(%s,%s)",
                            ((user_name or "寄件人")[:30], user_phone))
            user = db.query_one("SELECT * FROM t_user WHERE user_id=%s", (uid,))
        except Exception as e:
            return jsonify({"error": f"寄件人建档失败: {e}"}), 400

    try:
        with db.transaction() as conn:
            cur = conn.cursor()
            fit = SIZE_FIT[size_type]
            placeholders = ",".join(["%s"] * len(fit))
            sql = (f"SELECT cell_id, cabinet_id, cell_code, size_type FROM t_cell "
                   f"WHERE status='FREE' AND size_type IN ({placeholders}) AND cabinet_id=%s "
                   f"ORDER BY cell_id LIMIT 1 FOR UPDATE")
            cur.execute(sql, list(fit) + [cabinet_id])
            cell = cur.fetchone()
            if not cell:
                return jsonify({"error": "目标柜体当前无可用格口（规格不匹配或已满）"}), 409
            pickup_code = _gen_pickup_code()
            tracking_no = _gen_tracking_no(company["company_code"])
            cur.execute(
                """INSERT INTO t_package(direction, tracking_no, courier_id, user_id, company_id,
                                         cabinet_id, cell_id, size_type, weight, status, pickup_code,
                                         store_time, expire_time, recipient_name, recipient_phone,
                                         note, overtime_fee, overtime_fee_paid)
                   VALUES('SEND',%s,NULL,%s,%s,%s,%s,%s,%s,'SEND_WAIT_PICKUP',%s,NOW(),
                         DATE_ADD(NOW(),INTERVAL 48 HOUR),%s,%s,%s,NULL,0)""",
                (tracking_no, user["user_id"], company_id, cell["cabinet_id"], cell["cell_id"],
                 size_type, weight, pickup_code, recipient_name,
                 recipient_phone, note))
            pid = cur.lastrowid
            cur.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell["cell_id"],))
    except Exception as e:
        return jsonify({"error": f"寄件下单失败: {e}"}), 500

    detail = _detail(pid)
    notify.safe_enqueue("SEND_ORDER_CREATED", pid)
    return jsonify({
        "message": "寄件下单成功，请放入物品并关闭柜门",
        "order_code": pickup_code,
        "tracking_no": tracking_no,
        "cabinet_code": detail["cabinet_code"],
        "cell_code": detail["cell_code"],
        "company_name": detail["company_name"],
        "recipient_name": detail.get("recipient_name"),
        "recipient_phone": detail.get("recipient_phone"),
        "expire_time": detail["expire_time"],
        "package": detail,
    }), 201


@business_bp.route("/collect", methods=["POST"])
def collect():
    """快递员揽收：收取用户已下单待寄出的件（SEND_WAIT_PICKUP → SEND_COLLECTED）。"""
    body = request.get_json(silent=True) or {}
    pid = body.get("package_id")
    code = (body.get("order_code") or "").strip()
    courier_id = body.get("courier_id")
    if not pid and not code:
        return jsonify({"error": "请提供 package_id 或 揽收码"}), 400
    pkg = (db.query_one("SELECT * FROM t_package WHERE pickup_code=%s", (code,))
           if code else db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pid,)))
    if not pkg:
        return jsonify({"error": "包裹不存在"}), 404
    if pkg["direction"] != "SEND":
        return jsonify({"error": "该包裹为收件件，无需揽收"}), 409
    if pkg["status"] == "SEND_COLLECTED":
        return jsonify({"error": "该寄件件已被揽收"}), 409
    if pkg["status"] != "SEND_WAIT_PICKUP":
        return jsonify({"error": f"当前状态为 {pkg['status']}，无法揽收"}), 409
    if not courier_id:
        return jsonify({"error": "请指定揽收快递员"}), 400
    courier = db.query_one("SELECT * FROM t_courier WHERE courier_id=%s", (courier_id,))
    if not courier:
        return jsonify({"error": "快递员不存在"}), 404
    db.execute(
        "UPDATE t_package SET courier_id=%s, status='SEND_COLLECTED', pickup_time=NOW() "
        "WHERE package_id=%s", (courier_id, pkg["package_id"]))
    db.insert(
        "INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result)"
        " VALUES(%s,'APP',NOW(),'COURIER','SUCCESS')", (pkg["package_id"],))
    detail = _detail(pkg["package_id"])
    # 揽收完成通知寄件人（收件人信息在通知正文里带出）
    notify.safe_enqueue("SEND_COLLECTED", pkg["package_id"])
    return jsonify({"message": "揽收成功，包裹已交快递员", "package": detail})


@business_bp.route("/receive-pending", methods=["GET"])
def receive_pending():
    """待取件记录：收件方向、尚未取出的件（STORED/EXPIRED），可按手机号/用户/柜体过滤。"""
    phone = (request.args.get("phone") or "").strip()
    cabinet_id = request.args.get("cabinet")
    cabinet_id = int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None
    uid = request.args.get("user_id")
    wheres, params = ["p.direction='RECEIVE'", "p.status IN ('STORED','EXPIRED')"], []
    if phone:
        if not re.match(r"^1[3-9]\d{9}$", phone):
            return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400
        wheres.append("u.phone=%s"); params.append(phone)
    if uid:
        wheres.append("p.user_id=%s"); params.append(uid)
    if cabinet_id:
        wheres.append("p.cabinet_id=%s"); params.append(cabinet_id)
    rows = db.query(
        """SELECT p.package_id, p.direction, p.tracking_no, p.status AS pkg_status, p.size_type, p.weight,
                  p.store_time, p.expire_time, p.overtime_fee, p.overtime_fee_paid,
                  cab.cabinet_code, cab.location, cell.cell_code,
                  cr.name AS courier_name, c.company_name, u.name AS user_name, u.phone AS user_phone
           FROM t_package p
           JOIN t_user u       ON p.user_id = u.user_id
           JOIN t_cabinet cab  ON p.cabinet_id = cab.cabinet_id
           JOIN t_cell cell    ON p.cell_id = cell.cell_id
           LEFT JOIN t_courier cr ON p.courier_id = cr.courier_id
           LEFT JOIN t_express_company c ON cr.company_id = c.company_id
           WHERE """ + " AND ".join(wheres) + " ORDER BY p.store_time",
        params)
    packages = [_pending_row(r) for r in rows]
    return jsonify({"count": len(packages), "packages": packages})


@business_bp.route("/send-pending", methods=["GET"])
def send_pending():
    """待送记录：寄件方向、用户已下单但快递员尚未揽收的件（SEND_WAIT_PICKUP），可按柜体/手机号过滤。"""
    phone = (request.args.get("phone") or "").strip()
    cabinet_id = request.args.get("cabinet")
    cabinet_id = int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None
    wheres, params = ["p.direction='SEND'", "p.status='SEND_WAIT_PICKUP'"], []
    if phone:
        if not re.match(r"^1[3-9]\d{9}$", phone):
            return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400
        wheres.append("u.phone=%s"); params.append(phone)
    if cabinet_id:
        wheres.append("p.cabinet_id=%s"); params.append(cabinet_id)
    rows = db.query(
        """SELECT p.package_id, p.direction, p.tracking_no, p.status AS pkg_status, p.size_type, p.weight,
                  p.store_time, p.expire_time, p.overtime_fee, p.overtime_fee_paid, p.pickup_code,
                  cab.cabinet_code, cab.location, cell.cell_code,
                  c2.company_name, u.name AS user_name, u.phone AS user_phone
           FROM t_package p
           JOIN t_user u       ON p.user_id = u.user_id
           JOIN t_cabinet cab  ON p.cabinet_id = cab.cabinet_id
           JOIN t_cell cell    ON p.cell_id = cell.cell_id
           LEFT JOIN t_express_company c2 ON p.company_id = c2.company_id
           WHERE """ + " AND ".join(wheres) + " ORDER BY p.store_time",
        params)
    packages = [_pending_row(r) for r in rows]
    return jsonify({"count": len(packages), "packages": packages})


# ---- 寄件单快速匹配 / 全程追踪 ----
def _send_order_row(p, detail=None):
    """寄件单精简行（含收件人/寄件人信息），供匹配、追踪与合并列表使用。

    direction 固定为 SEND（本函数只处理寄件单）；投递件信息由调用方
    （合并列表 my-packages）按 from_send_id 单独关联后填充 delivery 字段。
    """
    d = detail or _detail(p["package_id"])
    return {
        "package_id": p["package_id"],
        "tracking_no": p["tracking_no"],
        "order_code": p["pickup_code"],
        "direction": "SEND",
        "status": p["status"],
        "size_type": p["size_type"],
        "weight": p.get("weight"),
        "store_time": p["store_time"],
        "pickup_time": p["pickup_time"],
        "company_name": d.get("company_name"),
        "sender_name": d.get("user_name"),
        "sender_phone": d.get("user_phone"),
        "recipient_name": p.get("recipient_name"),
        "recipient_phone": p.get("recipient_phone"),
        "delivery": None,   # 由调用方填充（见 my-packages）
    }


def _delivery_of(send_id):
    """寄件单对应的投递件（RECEIVE 方向、from_send_id 关联），用于合并列表展示
    「下单 → 揽收 → 投递存柜 → 取件」全链路。"""
    d = db.query_one(
        """SELECT pkg.tracking_no, pkg.status, pkg.store_time, pkg.pickup_time,
                  cab.cabinet_code, cell.cell_code
           FROM t_package pkg
           JOIN t_cabinet cab ON cab.cabinet_id = pkg.cabinet_id
           JOIN t_cell cell   ON cell.cell_id   = pkg.cell_id
           WHERE pkg.from_send_id=%s AND pkg.direction='RECEIVE'
           ORDER BY pkg.package_id DESC LIMIT 1""", (send_id,))
    return d if d else None


@business_bp.route("/send-lookup", methods=["GET"])
def send_lookup():
    """存件快速匹配：按订单号（揽收码/运单号）或收件人手机号查找寄件单。

    快递员在存件界面输入任意一种标识，即可带出寄件单的收件人、规格等信息直接完成存件。
    匹配范围：寄件方向（SEND）全部状态，未揽收/已揽收均返回，由前端按需筛选。
    """
    q = (request.args.get("q") or "").strip()
    order_code = (request.args.get("order_code") or "").strip()
    tracking_no = (request.args.get("tracking_no") or "").strip()
    recipient_phone = (request.args.get("recipient_phone") or "").strip()
    if not (q or order_code or tracking_no or recipient_phone):
        return jsonify({"error": "请提供订单号或收件人手机号"}), 400

    wheres, params = ["p.direction='SEND'"], []
    key = q or order_code or tracking_no or recipient_phone
    # 输入自动识别：11 位手机号 → 按收件人手机号匹配；否则按揽收码/运单号匹配
    if recipient_phone:
        if not re.match(r"^1[3-9]\d{9}$", recipient_phone):
            return jsonify({"error": "收件人手机号格式不正确（须为 11 位有效手机号）"}), 400
        wheres.append("p.recipient_phone=%s"); params.append(recipient_phone)
    elif re.match(r"^1[3-9]\d{9}$", key):
        wheres.append("p.recipient_phone=%s"); params.append(key)
    else:
        wheres.append("(p.pickup_code=%s OR p.tracking_no=%s)")
        params += [key, key]
    rows = db.query(
        "SELECT p.* FROM t_package p WHERE " + " AND ".join(wheres) + " ORDER BY p.store_time DESC LIMIT 20",
        params)
    if not rows:
        return jsonify({"count": 0, "packages": []})
    return jsonify({"count": len(rows), "packages": [_send_order_row(p) for p in rows]})


@business_bp.route("/send-track", methods=["GET"])
def send_track():
    """寄件全程追踪：按订单号（揽收码/运单号）或手机号（寄件人/收件人）查询寄件单全链路。

    返回每条寄件单的：下单 → 揽收 → 投递存柜 → 取件 各环节时间/柜体/操作状态，
    投递包裹通过 from_send_id 关联寄件单，实现「寄 → 揽 → 投 → 取」闭环追踪。
    触屏登录态（USER token）优先：按登录 user_id 只查本人的寄件单，
    忽略请求携带的手机号参数，保证"我的寄件"只能看到本人记录。
    """
    from auth import kiosk_identity      # 局部引入：寄件追踪对登录态是"可选增强"
    ident = kiosk_identity()
    uid = ident[1] if ident and ident[0] == "USER" else None
    q = (request.args.get("q") or "").strip()
    phone = (request.args.get("phone") or "").strip()
    if uid:
        rows = db.query(
            """SELECT p.* FROM t_package p
               WHERE p.direction='SEND' AND p.user_id=%s
               ORDER BY p.store_time DESC LIMIT 20""", (uid,))
    elif q or phone:
        if phone:
            if not re.match(r"^1[3-9]\d{9}$", phone):
                return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400
            rows = db.query(
                """SELECT p.* FROM t_package p
                   JOIN t_user u ON p.user_id=u.user_id
                   WHERE p.direction='SEND' AND (u.phone=%s OR p.recipient_phone=%s)
                   ORDER BY p.store_time DESC LIMIT 20""", (phone, phone))
        else:
            rows = db.query(
                "SELECT * FROM t_package WHERE direction='SEND' AND (pickup_code=%s OR tracking_no=%s)",
                (q, q))
    else:
        return jsonify({"error": "请提供订单号或手机号"}), 400
    if not rows:
        return jsonify({"count": 0, "orders": []})

    result = []
    for p in rows:
        d = _detail(p["package_id"])
        # 该寄件单对应的投递包裹（from_send_id 关联）
        delivery = db.query_one(
            """SELECT pkg.*, cab.cabinet_code, cell.cell_code
               FROM t_package pkg
               JOIN t_cabinet cab ON cab.cabinet_id = pkg.cabinet_id
               JOIN t_cell cell   ON cell.cell_id   = pkg.cell_id
               WHERE pkg.from_send_id=%s AND pkg.direction='RECEIVE'
               ORDER BY pkg.package_id DESC LIMIT 1""", (p["package_id"],))
        result.append({
            "package_id": p["package_id"],
            "tracking_no": p["tracking_no"],
            "order_code": p["pickup_code"],
            "size_type": p["size_type"],
            "weight": p.get("weight"),
            "status": p["status"],
            "company_name": d.get("company_name"),
            "sender_name": d.get("user_name"),
            "sender_phone": d.get("user_phone"),
            "recipient_name": p.get("recipient_name"),
            "recipient_phone": p.get("recipient_phone"),
            "order_time": p["store_time"],
            "pickup_time": p["pickup_time"],                       # 揽收时间
            "courier_name": d.get("courier_name"),
            "delivery": {
                "tracking_no": delivery["tracking_no"] if delivery else None,
                "status": delivery["status"] if delivery else None,
                "store_time": delivery["store_time"] if delivery else None,
                "pickup_time": delivery["pickup_time"] if delivery else None,
                "cabinet_code": delivery["cabinet_code"] if delivery else None,
                "cell_code": delivery["cell_code"] if delivery else None,
            } if delivery else None,
        })
    return jsonify({"count": len(result), "orders": result})


@business_bp.route("/pickup", methods=["POST"])
def pickup():
    """用户验证码取件：校验取件码、置为已取、记录取件流水（触发器自动释放格口）。

    超时未缴费（EXPIRED 且 overtime_fee_paid=0）返回 402 NEED_PAYMENT，
    调用方需先调 /business/pay-overtime 再重试本接口。
    """
    body = request.get_json(silent=True) or {}
    code = (body.get("pickup_code") or "").strip()
    cabinet_id = body.get("cabinet_id")

    pkg = db.query_one("SELECT * FROM t_package WHERE pickup_code=%s", (code,))
    if not pkg:
        return jsonify({"error": "取件码无效，请核对后重试"}), 404
    if pkg["direction"] == "SEND":
        return jsonify({"error": "该包裹为寄件件（待揽收），请由快递员在柜体端揽收，不能凭取件码取出"}), 409
    if cabinet_id and pkg["cabinet_id"] != int(cabinet_id):
        return jsonify({"error": "该取件码不属于当前柜体，请到对应柜体取件"}), 404

    status = pkg["status"]
    if status == "PICKED":
        db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result,fail_reason)"
                  " VALUES(%s,'CODE',NOW(),'USER','FAIL','包裹已取走')", (pkg["package_id"],))
        return jsonify({"error": "该包裹已取走"}), 409
    if status == "RETURNED":
        db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result,fail_reason)"
                  " VALUES(%s,'CODE',NOW(),'USER','FAIL','包裹已退回')", (pkg["package_id"],))
        return jsonify({"error": "该包裹已退回快递员"}), 409
    if status == "EXCEPTION":
        db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result,fail_reason)"
                  " VALUES(%s,'CODE',NOW(),'USER','FAIL','包裹存在异常')", (pkg["package_id"],))
        return jsonify({"error": "包裹存在异常，请联系管理员处理"}), 409
    # 超时未缴费：与 _do_unlock 保持一致，支付阻断必须发生在置 PICKED 之前，
    # 否则先取件再缴费的调用顺序会让包裹脱离 EXPIRED 态，缴费接口再也收不到这笔账。
    if status == "EXPIRED" and not pkg["overtime_fee_paid"]:
        fee = float(pkg["overtime_fee"]) if pkg["overtime_fee"] is not None else 1.00
        return jsonify({"error": "NEED_PAYMENT", "package_id": pkg["package_id"],
                        "overtime_fee": round(fee, 2),
                        "message": f"包裹已超时，请先支付超时保管费 ¥{fee:.2f}"}), 402

    # 成功取件
    db.execute("UPDATE t_package SET status='PICKED', pickup_time=NOW() WHERE package_id=%s",
               (pkg["package_id"],))
    db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result)"
              " VALUES(%s,'CODE',NOW(),'USER','SUCCESS')", (pkg["package_id"],))
    detail = _detail(pkg["package_id"])
    return jsonify({"message": "取件成功，请取走物品", "package": detail})


@business_bp.route("/<int:pkg_id>/return", methods=["POST"])
def return_package(pkg_id):
    """包裹退回快递员：释放格口并登记退回异常。"""
    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pkg_id,))
    if not pkg:
        return jsonify({"error": "包裹不存在"}), 404
    if pkg["direction"] == "SEND":
        return jsonify({"error": "寄件件不可走收件退回流程，如须取消请联系管理员"}), 409
    if pkg["status"] in ("PICKED", "RETURNED"):
        return jsonify({"error": f"包裹当前状态为 {pkg['status']}，无法退回"}), 409
    db.execute("UPDATE t_package SET status='RETURNED' WHERE package_id=%s", (pkg_id,))
    db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (pkg["cell_id"],))
    db.insert("INSERT INTO t_exception_log(package_id,exception_type,occur_time,handle_time,handler,handle_result,remark)"
              " VALUES(%s,'RETURNED',NOW(),NOW(),'系统', 'AUTO_RETURNED','用户未取，自动退回快递员')", (pkg_id,))
    return jsonify({"message": "包裹已退回快递员", "package": _detail(pkg_id)})


@business_bp.route("/<int:pkg_id>/exception", methods=["POST"])
def mark_exception(pkg_id):
    """登记异常（破损/错格/超重等），必要时将包裹置为异常态。"""
    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pkg_id,))
    if not pkg:
        return jsonify({"error": "包裹不存在"}), 404
    body = request.get_json(silent=True) or {}
    etype = (body.get("exception_type") or "").upper()
    if etype not in ("TIMEOUT", "OVERWEIGHT", "DAMAGED", "WRONG_CELL", "MISSED", "RETURNED"):
        return jsonify({"error": "异常类型不合法"}), 400
    handler = (body.get("handler") or "管理员")[:30]
    remark = body.get("remark")
    db.insert("INSERT INTO t_exception_log(package_id,exception_type,occur_time,handler,handle_result,remark)"
              " VALUES(%s,%s,NOW(),%s,'PENDING',%s)", (pkg_id, etype, handler, remark))
    if etype in ("DAMAGED", "WRONG_CELL", "OVERWEIGHT"):
        db.execute("UPDATE t_package SET status='EXCEPTION' WHERE package_id=%s", (pkg_id,))
    notify.safe_enqueue("EXCEPTION_ALERT", pkg_id, extra={"exception_type": etype})
    return jsonify({"message": "异常已登记", "package": _detail(pkg_id)})


@business_bp.route("/<int:pkg_id>/force-expire", methods=["POST"])
def force_expire(pkg_id):
    """强制置为超时（触发器会自动登记 TIMEOUT 异常流转）。"""
    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pkg_id,))
    if not pkg:
        return jsonify({"error": "包裹不存在"}), 404
    if pkg["status"] != "STORED":
        return jsonify({"error": f"仅 STORED 状态可超时，当前为 {pkg['status']}"}), 409
    # expire_time 取 原到期时刻 与 当前时刻 的较小者：
    #   · 免费期内的件被强制超时（演示：刚存入即超时）→ 钳到 NOW()，模拟"此刻到期"，
    #     同时用 GREATEST(store_time+1s) 保底，避免与 store_time 同秒触发
    #     chk_pkg_time(expire_time > store_time)；
    #   · 真实已过免费期的件被强制超时 → 保留原 expire_time（不抹掉真实到期时间），
    #     与自动超时流转(auto_expire_overdue)的语义保持一致。
    db.execute("UPDATE t_package SET status='EXPIRED',"
               " expire_time=LEAST(expire_time, GREATEST(NOW(), store_time + INTERVAL 1 SECOND))"
               " WHERE package_id=%s", (pkg_id,))
    # 触发器会自动登记 TIMEOUT 异常流转。通知统一走与"自然到期"一致的 EXPIRE_URGE
    # （面向收件人、含缴费金额），不再发面向内部处置的 EXCEPTION_ALERT——
    # 否则同一收件人同一天会收到"异常告警"与"超时催收"两条语义打架的消息。
    # biz_key 带当日日期后缀：worker 对 EXPIRED 的催收扫描同日幂等命中同一键，不会重复发。
    notify.safe_enqueue("EXPIRE_URGE", pkg_id,
                        biz_suffix=datetime.now().strftime("%Y-%m-%d"))
    return jsonify({"message": "已标记为超时", "package": _detail(pkg_id)})


# ---- 触屏端：批量取件 / 超时支付 / 开柜 ----
@business_bp.route("/pickup-candidates", methods=["GET"])
def pickup_candidates():
    """按手机号查询该用户待取包裹（已存件/已超时），用于触屏批量取件。"""
    phone = (request.args.get("phone") or "").strip()
    cabinet_id = request.args.get("cabinet")
    cabinet_id = int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None
    if not re.match(r"^1[3-9]\d{9}$", phone):
        return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400
    rows = db.query(
        """SELECT p.package_id, p.tracking_no, p.status AS pkg_status, p.size_type,
                  p.store_time, p.expire_time, p.overtime_fee, p.overtime_fee_paid,
                  cab.cabinet_code, cab.location, cell.cell_code,
                  cr.name AS courier_name, c.company_name
           FROM t_package p
           JOIN t_user u       ON p.user_id = u.user_id
           JOIN t_cabinet cab  ON p.cabinet_id = cab.cabinet_id
           JOIN t_cell cell    ON p.cell_id = cell.cell_id
           JOIN t_courier cr   ON p.courier_id = cr.courier_id
           JOIN t_express_company c ON cr.company_id = c.company_id
           WHERE u.phone=%s AND p.status IN ('STORED','EXPIRED')
             AND (%s IS NULL OR p.cabinet_id=%s)
           ORDER BY p.store_time""",
        (phone, cabinet_id, cabinet_id),
    )
    packages = []
    for r in rows:
        need_pay = 1 if (r["pkg_status"] == "EXPIRED" and not r["overtime_fee_paid"]) else 0
        packages.append({
            "package_id": r["package_id"],
            "tracking_no": r["tracking_no"],
            "status": r["pkg_status"],
            "size_type": r["size_type"],
            "store_time": r["store_time"],
            "expire_time": r["expire_time"],
            "cabinet_code": r["cabinet_code"],
            "cell_code": r["cell_code"],
            "courier_name": r["courier_name"],
            "company_name": r["company_name"],
            "overtime_fee": float(r["overtime_fee"]) if r["overtime_fee"] is not None else None,
            "need_pay": need_pay,
        })
    return jsonify({"phone": phone, "count": len(packages), "packages": packages})


@business_bp.route("/my-pickup", methods=["GET"])
def my_pickup():
    """登录用户的待取包裹：凭 token 取身份，返回本人名下收件方向未取件（STORED/EXPIRED）。

    供触屏「取件」屏在用户登录后自动展示待取包裹并支持逐件立即取件；
    身份只来自登录态，不接收手机号参数，杜绝越权查询。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return jsonify({"error": err[0]}), err[1]
    _, uid = ident
    cabinet_id = request.args.get("cabinet")
    cabinet_id = int(cabinet_id) if cabinet_id and cabinet_id.isdigit() else None
    rows = db.query(
        """SELECT p.package_id, p.tracking_no, p.status AS pkg_status, p.size_type,
                  p.store_time, p.expire_time, p.overtime_fee, p.overtime_fee_paid,
                  cab.cabinet_code, cab.location, cell.cell_code,
                  cr.name AS courier_name, c.company_name
           FROM t_package p
           JOIN t_user u       ON p.user_id = u.user_id
           JOIN t_cabinet cab  ON p.cabinet_id = cab.cabinet_id
           JOIN t_cell cell    ON p.cell_id = cell.cell_id
           LEFT JOIN t_courier cr ON p.courier_id = cr.courier_id
           LEFT JOIN t_express_company c ON cr.company_id = c.company_id
           WHERE p.user_id=%s AND p.direction='RECEIVE' AND p.status IN ('STORED','EXPIRED')
             AND (%s IS NULL OR p.cabinet_id=%s)
           ORDER BY p.store_time""",
        (uid, cabinet_id, cabinet_id))
    packages = []
    for r in rows:
        need_pay = 1 if (r["pkg_status"] == "EXPIRED" and not r["overtime_fee_paid"]) else 0
        packages.append({
            "package_id": r["package_id"],
            "tracking_no": r["tracking_no"],
            "status": r["pkg_status"],
            "size_type": r["size_type"],
            "store_time": r["store_time"],
            "expire_time": r["expire_time"],
            "cabinet_code": r["cabinet_code"],
            "location": r.get("location"),
            "cell_code": r["cell_code"],
            "courier_name": r["courier_name"],
            "company_name": r["company_name"],
            "overtime_fee": float(r["overtime_fee"]) if r["overtime_fee"] is not None else None,
            "need_pay": need_pay,
        })
    return jsonify({"count": len(packages), "packages": packages})


def _charge_overtime(ids):
    """对超时且未支付的包裹计收保管费，返回 (已计费列表, 合计金额)。"""
    if not ids:
        return [], 0.0
    ph = ",".join(["%s"] * len(ids))
    rows = db.query(
        f"SELECT package_id, status, overtime_fee, overtime_fee_paid FROM t_package "
        f"WHERE package_id IN ({ph})", ids)
    payable = [r for r in rows if r["status"] == "EXPIRED" and not r["overtime_fee_paid"]]
    total = 0.0
    for r in payable:
        fee = float(r["overtime_fee"]) if r["overtime_fee"] is not None else 1.00
        db.execute(
            "UPDATE t_package SET overtime_fee_paid=1, overtime_fee=%s WHERE package_id=%s",
            (fee, r["package_id"]))
        db.insert(
            "INSERT INTO t_exception_log(package_id,exception_type,occur_time,handle_time,"
            "handler,handle_result,remark) VALUES(%s,'TIMEOUT',NOW(),NOW(),'用户','RESOLVED',%s)",
            (r["package_id"], f"扫码支付超时保管费 ¥{fee:.2f}"))
        total += fee
    return payable, round(total, 2)


@business_bp.route("/pay-overtime", methods=["POST"])
def pay_overtime():
    """模拟超时保管费支付（扫码支付 ¥1.00）。支持单个或批量。"""
    body = request.get_json(silent=True) or {}
    ids = body.get("package_ids") or ([body["package_id"]] if body.get("package_id") else [])
    if not ids:
        return jsonify({"error": "缺少 package_id"}), 400
    payable, total = _charge_overtime([int(x) for x in ids])
    return jsonify({
        "paid_count": len(payable),
        "total_fee": total,
        "packages": [r["package_id"] for r in payable],
    })


def _do_unlock(pid, method="CODE", role="USER", cabinet_id=None):
    """执行开柜取件：置 PICKED、记录流水、触发器释放格口。返回 (ok, payload, http_status)。"""
    pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pid,))
    if not pkg:
        return False, {"error": "包裹不存在"}, 404
    if pkg["direction"] == "SEND":
        return False, {"error": "该包裹为寄件件（待揽收），需由快递员揽收"}, 409
    if cabinet_id and pkg["cabinet_id"] != int(cabinet_id):
        return False, {"error": "该包裹不属于当前柜体，请到对应柜体取件"}, 404
    st = pkg["status"]
    if st == "PICKED":
        db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result,fail_reason)"
                  " VALUES(%s,%s,NOW(),%s,'FAIL','包裹已取走')", (pid, method, role))
        return False, {"error": "该包裹已取走"}, 409
    if st == "RETURNED":
        return False, {"error": "该包裹已退回快递员"}, 409
    if st == "EXCEPTION":
        return False, {"error": "包裹存在异常，请联系管理员处理"}, 409
    if st == "EXPIRED" and not pkg["overtime_fee_paid"]:
        return False, {"error": "NEED_PAYMENT", "package_id": pid}, 402
    db.execute("UPDATE t_package SET status='PICKED', pickup_time=NOW() WHERE package_id=%s", (pid,))
    db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result)"
              " VALUES(%s,%s,NOW(),%s,'SUCCESS')", (pid, method, role))
    notify.safe_enqueue("PICKUP_RECEIPT", pid)
    return True, {"package": _detail(pid)}, 200


@business_bp.route("/unlock", methods=["POST"])
def unlock():
    """单个开柜（验证码或无码开柜）。超时未支付将返回 NEED_PAYMENT(402)。"""
    body = request.get_json(silent=True) or {}
    pid = body.get("package_id")
    cabinet_id = body.get("cabinet_id")
    if not pid:
        return jsonify({"error": "缺少 package_id"}), 400
    ok, payload, status = _do_unlock(int(pid), cabinet_id=cabinet_id)
    return jsonify(payload), status


@business_bp.route("/unlock-batch", methods=["POST"])
def unlock_batch():
    """一键全部开柜：批量取件（超时包裹会先计费再开柜）。"""
    body = request.get_json(silent=True) or {}
    ids = body.get("package_ids") or []
    cabinet_id = body.get("cabinet_id")
    if not ids:
        return jsonify({"error": "缺少 package_ids"}), 400
    ids = [int(x) for x in ids]
    # 先对超时未支付包裹批量计费（支付阻断在开柜之前）
    _charge_overtime(ids)
    results = []
    ok_count = 0
    for pid in ids:
        ok, payload, _ = _do_unlock(pid, cabinet_id=cabinet_id)
        results.append({"package_id": pid, **payload, "unlocked": ok})
        if ok:
            ok_count += 1
    return jsonify({"requested": len(ids), "unlocked": ok_count, "results": results})


# ---- 后台：柜体格口矩阵 / 远程强制开锁 ----
@business_bp.route("/cabinets/<int:cabinet_id>/cells", methods=["GET"])
def cabinet_cells(cabinet_id):
    """返回柜体物理格口矩阵（含格口状态、占用包裹、存放时长、是否需支付超时费）。"""
    cab = db.query_one("SELECT * FROM t_cabinet WHERE cabinet_id=%s", (cabinet_id,))
    if not cab:
        return jsonify({"error": "柜体不存在"}), 404
    rows = db.query(
        """SELECT cell.cell_id, cell.cell_code, cell.size_type, cell.status AS cell_status,
                  p.package_id, p.status AS pkg_status, p.tracking_no, p.store_time,
                  p.expire_time, p.overtime_fee, p.overtime_fee_paid
           FROM t_cell cell
           LEFT JOIN t_package p ON p.cell_id = cell.cell_id
                AND p.status IN ('STORED','EXPIRED','EXCEPTION')
           WHERE cell.cabinet_id=%s
           ORDER BY cell.cell_code""",
        (cabinet_id,))
    cells = []
    for c in rows:
        stored_hours = None
        if c["store_time"]:
            stored_hours = round((datetime.now() - c["store_time"]).total_seconds() / 3600, 1)
        need_pay = 1 if (c["pkg_status"] == "EXPIRED" and not c["overtime_fee_paid"]) else 0
        cells.append({
            "cell_id": c["cell_id"],
            "cell_code": c["cell_code"],
            "size_type": c["size_type"],
            "cell_status": c["cell_status"],
            "pkg_status": c["pkg_status"],
            "package_id": c["package_id"],
            "tracking_no": c["tracking_no"],
            "store_time": c["store_time"],
            "expire_time": c["expire_time"],
            "stored_hours": stored_hours,
            "need_pay": need_pay,
        })
    return jsonify({"cabinet": cab, "cells": cells})


@business_bp.route("/cabinets/<int:cabinet_id>/availability", methods=["GET"])
def cabinet_availability(cabinet_id):
    """返回当前柜体剩余（空闲）格口统计：总数 + 按规格（小/中/大）分组。"""
    cab = db.query_one("SELECT * FROM t_cabinet WHERE cabinet_id=%s", (cabinet_id,))
    if not cab:
        return jsonify({"error": "柜体不存在"}), 404
    rows = db.query(
        "SELECT size_type, COUNT(*) AS cnt FROM t_cell "
        "WHERE cabinet_id=%s AND status='FREE' GROUP BY size_type", (cabinet_id,))
    by_size = {"SMALL": 0, "MEDIUM": 0, "LARGE": 0}
    for r in rows:
        by_size[r["size_type"]] = int(r["cnt"])
    return jsonify({
        "cabinet_id": cabinet_id,
        "cabinet_code": cab["cabinet_code"],
        "total_free": sum(by_size.values()),
        "by_size": by_size,
    })


@business_bp.route("/cells/<int:cell_id>/force-unlock", methods=["POST"])
def force_unlock_cell(cell_id):
    """管理员远程强制开锁：占用则标记已取并释放格口；故障/空闲格口则解除故障。"""
    cell = db.query_one("SELECT * FROM t_cell WHERE cell_id=%s", (cell_id,))
    if not cell:
        return jsonify({"error": "格口不存在"}), 404
    pkg = db.query_one(
        "SELECT * FROM t_package WHERE cell_id=%s AND status IN ('STORED','EXPIRED','EXCEPTION') "
        "ORDER BY package_id DESC LIMIT 1", (cell_id,))
    if pkg:
        db.execute("UPDATE t_package SET status='PICKED', pickup_time=NOW() WHERE package_id=%s",
                   (pkg["package_id"],))
        db.insert("INSERT INTO t_pickup_record(package_id,pickup_method,pickup_time,operator_role,result)"
                  " VALUES(%s,'ADMIN',NOW(),'ADMIN','SUCCESS')", (pkg["package_id"],))
        detail = _detail(pkg["package_id"])
    else:
        db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cell_id,))
        detail = {"cell_id": cell_id, "cleared": True}
    return jsonify({"message": "远程开锁成功", "detail": detail})


# ----------------------------------------------------------------------------
# 对外稳定接口：供手机端蓝图复用（避免跨模块直接调用下划线私有函数）
# ----------------------------------------------------------------------------
do_unlock = _do_unlock
charge_overtime = _charge_overtime
package_detail = _detail
