"""扫码登录 · 柜机 ↔ 手机 的一次性票据换 token。

解决的问题：触屏端登录要输手机号，慢且暴露号码；改成"柜机出码、手机扫码确认"，
手机端已经是登录态（H5 里点过验证码登录），扫一下就完成身份交接，柜机零输入。
"""
#
# 解决的问题：触屏端登录要输手机号，慢且暴露号码；改成"柜机出码、手机扫码确认"，
# 手机端已经是登录态（H5 里点过验证码登录），扫一下就完成身份交接，柜机零输入。
#
# 时序（票据是唯一的凭据，128bit 随机，2 分钟过期）：
#   ① 柜机 POST /api/qr/ticket            → 建票，屏幕画二维码（内容为深链 /m?ticket=xxx）
#   ② 手机 扫码打开 /m?ticket=xxx          → GET /api/qr/ticket/xxx 读票据信息
#   ③ 手机 点"确认登录"                    → POST .../confirm（带手机端 token，写 CONFIRMED）
#   ④ 柜机 每 1.5s 轮询                    → GET .../poll 拿 CONFIRMED 即原子消费 → 返回 token
#
# 为什么 token 不直接给手机：手机本来就有自己的 token，柜机需要的是**柜机侧会话**。
# 让柜机从票据里换，等于把"人在现场"这一事实变成了可验证的凭据。
#
# 重放防护：CONFIRMED 只能被消费一次（UPDATE ... WHERE status='CONFIRMED' + rowcount==1），
# 第二次轮询只会拿到 CONSUMED 且**不带 token**，所以二维码被截图也无法二次登录。
import secrets
from datetime import datetime

from flask import Blueprint, jsonify, request

from auth import build_identity, issue_kiosk_token, require_kiosk_role
from mobile_api import public_base

import db

qr_bp = Blueprint("qr", __name__, url_prefix="/api/qr")

TICKET_TTL_SECONDS = 120   # 票据有效期：屏幕上的倒计时
POLL_MAX = 240             # 轮询次数上限（1.5s × 240 = 6 分钟），防死循环打库


def _err(msg, status=400):
    return jsonify({"error": msg}), status


def _ticket_row(ticket):
    return db.query_one("""
        SELECT q.*, cab.cabinet_code, cab.location
        FROM t_qr_ticket q
        JOIN t_cabinet cab ON cab.cabinet_id = q.cabinet_id
        WHERE q.ticket=%s""", (ticket,))


def _remain(row):
    """剩余秒数（负数归零），前端用来画倒计时。"""
    left = db.query_one("SELECT TIMESTAMPDIFF(SECOND, NOW(), %s) AS s", (row["expire_at"],))["s"]
    return max(0, int(left or 0))


def _expire_if_needed(row):
    """PENDING 且已过期的票就地置 EXPIRED，返回最新状态字符串。

    惰性清理而非定时任务：票据是短命数据，没人查就没有清理价值，
    等下一次轮询/查询时顺手改状态，省一个后台线程。
    """
    if row["status"] == "PENDING" and _remain(row) <= 0:
        db.execute("UPDATE t_qr_ticket SET status='EXPIRED' "
                   "WHERE ticket_id=%s AND status='PENDING'", (row["ticket_id"],))
        return "EXPIRED"
    return row["status"]


# ============================================================================
# 1. 建票（柜机调用）
# ============================================================================
@qr_bp.route("/ticket", methods=["POST"])
def create_ticket():
    """柜机申请一张二维码票据。

    cabinet_id 可省略——演示环境只有一台柜机，缺省取第一台启用中的柜体。
    """
    body = request.get_json(silent=True) or {}
    purpose = (body.get("purpose") or "KIOSK_LOGIN").strip().upper()
    if purpose not in ("KIOSK_LOGIN", "PICKUP"):
        return _err("purpose 只能为 KIOSK_LOGIN 或 PICKUP")

    cabinet_id = body.get("cabinet_id")
    if cabinet_id:
        cab = db.query_one("SELECT cabinet_id, cabinet_code, location FROM t_cabinet "
                           "WHERE cabinet_id=%s", (int(cabinet_id),))
    else:
        cab = db.query_one("SELECT cabinet_id, cabinet_code, location FROM t_cabinet "
                           "ORDER BY cabinet_id LIMIT 1")
    if not cab:
        return _err("柜机不存在，请先初始化柜体数据", 404)

    # 同一柜体上还没被扫的旧票作废，保证屏幕上永远只有一张有效二维码
    db.execute("UPDATE t_qr_ticket SET status='CANCELLED' "
               "WHERE cabinet_id=%s AND status='PENDING'", (cab["cabinet_id"],))

    ticket = secrets.token_hex(16)  # 32 位十六进制 = 128bit，不可枚举
    tid = db.insert(
        "INSERT INTO t_qr_ticket(ticket, purpose, cabinet_id, expire_at) "
        "VALUES(%s, %s, %s, DATE_ADD(NOW(), INTERVAL %s SECOND))",
        (ticket, purpose, cab["cabinet_id"], TICKET_TTL_SECONDS))

    base, source = public_base()
    deep_link = f"{base}/m?ticket={ticket}"
    return jsonify({
        "ticket_id": tid,
        "ticket": ticket,
        "purpose": purpose,
        "cabinet_id": cab["cabinet_id"],
        "cabinet_code": cab["cabinet_code"],
        "location": cab["location"],
        "deep_link": deep_link,
        "base_url": base,
        "base_source": source,
        "expire_in": TICKET_TTL_SECONDS,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }), 201


# ============================================================================
# 2. 读票（手机扫码后确认页用；票据本身就是凭据，故不要求登录）
# ============================================================================
@qr_bp.route("/ticket/<ticket>", methods=["GET"])
def read_ticket(ticket):
    row = _ticket_row(ticket)
    if not row:
        return _err("二维码无效，请在柜机上重新刷新", 404)
    status = _expire_if_needed(row)
    if status == "EXPIRED":
        return _err("二维码已过期，请在柜机上点击刷新", 410)
    if status == "CANCELLED":
        return _err("二维码已被柜机刷新，请重新扫码", 410)
    if status == "CONSUMED":
        return _err("该二维码已被使用，请在柜机上重新刷新", 410)

    return jsonify({
        "ticket": row["ticket"],
        "purpose": row["purpose"],
        "status": status,
        "cabinet_code": row["cabinet_code"],
        "location": row["location"],
        "expire_in": _remain(row),
        "confirmed_role": row["confirm_role"],
    })


# ============================================================================
# 3. 手机确认（手机端 token 换取票据的 CONFIRMED 标记）
# ============================================================================
@qr_bp.route("/ticket/<ticket>/confirm", methods=["POST"])
def confirm_ticket(ticket):
    """手机端确认登录：把当前登录身份绑定到这张票据上。

    只认 token 里的身份，不接受 body 里传 role/id——否则任何人都能替别人确认。
    """
    ident, err = require_kiosk_role("USER", "COURIER")
    if err:
        return _err(err[0], err[1])
    role, rid = ident

    identity = build_identity(role, rid)
    if not identity:
        return _err("账号已不存在，请重新登录", 401)

    row = _ticket_row(ticket)
    if not row:
        return _err("二维码无效，请在柜机上重新刷新", 404)
    status = _expire_if_needed(row)
    if status == "EXPIRED":
        return _err("二维码已过期，请在柜机上点击刷新", 410)
    if status == "CANCELLED":
        return _err("二维码已被柜机取消，请重新扫码", 410)
    if status != "PENDING":
        return _err("该二维码已被确认或使用，请重新扫码", 409)

    # 原子抢占：并发下两张手机同时确认，只有一张能改成功
    n = db.execute(
        "UPDATE t_qr_ticket SET status='CONFIRMED', confirm_role=%s, confirm_id=%s, "
        "confirmed_at=NOW() WHERE ticket_id=%s AND status='PENDING'",
        (role, rid, row["ticket_id"]))
    if n != 1:
        return _err("该二维码已被确认或使用，请重新扫码", 409)

    return jsonify({
        "ticket": ticket,
        "status": "CONFIRMED",
        "identity": identity,
        "cabinet_code": row["cabinet_code"],
        "message": f"已确认，{row['cabinet_code']} 柜机正在登录",
    })


# ============================================================================
# 4. 轮询换 token（柜机调用）
# ============================================================================
@qr_bp.route("/ticket/<ticket>/poll", methods=["GET"])
def poll_ticket(ticket):
    """柜机轮询：CONFIRMED 即原子消费并返回柜机侧 token。

    返回体里 status 是唯一需要前端分支的字段：
      PENDING   继续轮询；CONFIRMED/CONSUMED 才有 token（CONSUMED 时为空，即重放）；
      EXPIRED / CANCELLED 停止轮询并提示刷新。
    """
    row = _ticket_row(ticket)
    if not row:
        return _err("二维码无效，请在柜机上重新刷新", 404)
    if row["poll_count"] >= POLL_MAX:
        return jsonify({"status": "EXPIRED", "token": None,
                        "message": "轮询次数超限，请刷新二维码"}), 429

    db.execute("UPDATE t_qr_ticket SET poll_count=poll_count+1 WHERE ticket_id=%s",
               (row["ticket_id"],))

    status = _expire_if_needed(row)
    if status != "CONFIRMED":
        payload = {"status": status, "token": None, "expire_in": _remain(row)}
        if status == "EXPIRED":
            payload["message"] = "二维码已过期，请刷新"
        elif status == "CANCELLED":
            payload["message"] = "二维码已取消，请刷新"
        elif status == "CONSUMED":
            payload["message"] = "二维码已被使用，请刷新"
        return jsonify(payload)

    # 原子消费：并发轮询只有一个能拿到 token，另一个落到 CONSUMED 分支（无 token）
    n = db.execute("UPDATE t_qr_ticket SET status='CONSUMED', consumed_at=NOW() "
                   "WHERE ticket_id=%s AND status='CONFIRMED'", (row["ticket_id"],))
    if n != 1:
        return jsonify({"status": "CONSUMED", "token": None,
                        "message": "二维码已被使用，请刷新"})

    role, rid = row["confirm_role"], row["confirm_id"]
    identity = build_identity(role, rid)
    if not identity:
        return _err("该账号已不存在，请重新扫码", 401)

    return jsonify({
        "status": "CONSUMED",
        "token": issue_kiosk_token(role, rid),
        "identity": identity,
        "cabinet_code": row["cabinet_code"],
        "message": f"欢迎，{identity['name']}",
    })


# ============================================================================
# 5. 取消/刷新（柜机主动作废旧码）
# ============================================================================
@qr_bp.route("/ticket/<ticket>/cancel", methods=["POST"])
def cancel_ticket(ticket):
    row = _ticket_row(ticket)
    if not row:
        return jsonify({"cancelled": False})  # 已不存在视为已取消，幂等
    n = db.execute("UPDATE t_qr_ticket SET status='CANCELLED' "
                   "WHERE ticket_id=%s AND status='PENDING'", (row["ticket_id"],))
    return jsonify({"cancelled": n == 1, "status": "CANCELLED" if n == 1 else row["status"]})
