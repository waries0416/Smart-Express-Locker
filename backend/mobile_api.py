# 手机端（H5）接口蓝图
#
# 定位：把"人在柜机前输码取件"还原成"人在路上用手机取件"。
# 链路：手机号+验证码登录 → 看待取列表 → 扫柜机二维码/输码预览
#       → 远程开柜（写指令队列）→ 柜机轮询执行并回执 → 取走包裹。
#
# 与触屏端的边界：
#   · 身份统一走 USER token（auth.issue_kiosk_token），服务端只认 token 里的 user_id，
#     不接受手机号参数，杜绝"改个号就能查别人包裹"；
#   · 开柜复用 business.do_unlock（同一套状态机与流水），手机端不另写一套取件逻辑；
#   · 手机端只"下指令"，柜门是否真的弹开以柜机回执（/api/device/commands/ack）为准。
import io
import json
import os
import random
import re
import socket
from datetime import datetime

import segno
from flask import Blueprint, Response, jsonify, request

import db
from auth import issue_kiosk_token, require_kiosk_role
from business import charge_overtime, do_unlock

mobile_bp = Blueprint("mobile", __name__, url_prefix="/api/m")
device_bp = Blueprint("device", __name__, url_prefix="/api/device")

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
CODE_RE = re.compile(r"^\d{6}$")

CODE_TTL_SECONDS = 300      # 验证码 5 分钟有效
CODE_RESEND_SECONDS = 60    # 同一手机号 60 秒内不可重复发送
OPEN_SECONDS = 30           # 柜门自动回弹倒计时（前端展示用）

# 演示环境把验证码回显在响应里，方便答辩演示；
# 接入真实短信后置 MOBILE_DEV_MODE=0，验证码只写日志/短信，不再回传。
DEV_MODE = os.getenv("MOBILE_DEV_MODE", "1") == "1"


# ---- 通用小工具 ----
def _mask_phone(phone):
    s = str(phone or "")
    return s.replace(s[3:7], "****") if len(s) == 11 else s


def _mask_name(name):
    s = str(name or "")
    return s[0] + "*" * (len(s) - 1) if len(s) > 1 else s


def _err(msg, status=400):
    return jsonify({"error": msg}), status


def _fee_of(r, need_pay):
    """超时保管费：与 business._charge_overtime 的默认值保持一致（未定价按 ¥1.00）。

    预览、开柜、缴费三处必须同源，否则会出现"预览 0 元、实扣 1 元"的体验断层。
    """
    fee = r.get("overtime_fee")
    if fee is not None:
        return round(float(fee), 2)
    return 1.00 if need_pay else None


def _pkg_row(r):
    """把待取/历史包裹行整理成手机端可直接渲染的结构。"""
    need_pay = 1 if (r["pkg_status"] == "EXPIRED" and not r["overtime_fee_paid"]) else 0
    return {
        "package_id": r["package_id"],
        "tracking_no": r["tracking_no"],
        "status": r["pkg_status"],
        "size_type": r["size_type"],
        "store_time": r["store_time"],
        "expire_time": r["expire_time"],
        "pickup_time": r.get("pickup_time"),
        "cabinet_code": r["cabinet_code"],
        "location": r.get("location"),
        "cell_code": r.get("cell_code"),
        "company_name": r.get("company_name"),
        "overtime_fee": _fee_of(r, need_pay),
        "need_pay": need_pay,
    }


# ============================================================================
# 1. 登录：手机号 + 短信验证码
# ============================================================================
@mobile_bp.route("/auth/send-code", methods=["POST"])
def send_code():
    """下发登录验证码。同一手机号 60 秒内只允许一次，避免短信轰炸。"""
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()
    if not PHONE_RE.match(phone):
        return _err("手机号格式不正确（须为 11 位有效手机号）")

    recent = db.query_one(
        "SELECT code_id FROM t_sms_code WHERE phone=%s "
        "AND created_at > DATE_SUB(NOW(), INTERVAL %s SECOND) "
        "ORDER BY code_id DESC LIMIT 1", (phone, CODE_RESEND_SECONDS))
    if recent:
        return _err(f"验证码已发送，请 {CODE_RESEND_SECONDS} 秒后再试", 429)

    code = f"{random.randint(0, 999999):06d}"
    db.insert(
        "INSERT INTO t_sms_code(phone, code, purpose, expire_at) "
        "VALUES(%s, %s, 'LOGIN', DATE_ADD(NOW(), INTERVAL %s SECOND))",
        (phone, code, CODE_TTL_SECONDS))

    payload = {"message": "验证码已发送", "expire_in": CODE_TTL_SECONDS}
    if DEV_MODE:
        payload["dev_code"] = code  # 演示用：真实环境关闭 MOBILE_DEV_MODE
    return jsonify(payload)


@mobile_bp.route("/auth/login", methods=["POST"])
def login():
    """校验验证码并签发 USER token；手机号未建档时自动建档（与存件自动建档一致）。"""
    body = request.get_json(silent=True) or {}
    phone = (body.get("phone") or "").strip()
    code = (body.get("code") or "").strip()

    if not PHONE_RE.match(phone):
        return _err("手机号格式不正确（须为 11 位有效手机号）")
    if not CODE_RE.match(code):
        return _err("验证码应为 6 位数字")

    row = db.query_one(
        "SELECT * FROM t_sms_code WHERE phone=%s AND code=%s AND used=0 AND expire_at>NOW() "
        "ORDER BY code_id DESC LIMIT 1", (phone, code))
    if not row:
        return _err("验证码错误或已过期", 401)
    db.execute("UPDATE t_sms_code SET used=1 WHERE code_id=%s", (row["code_id"],))

    user = db.query_one("SELECT * FROM t_user WHERE phone=%s", (phone,))
    if not user:
        uid = db.insert("INSERT INTO t_user(name, phone) VALUES(%s, %s)",
                        (f"用户{phone[-4:]}", phone))
        user = db.query_one("SELECT * FROM t_user WHERE user_id=%s", (uid,))

    return jsonify({
        "token": issue_kiosk_token("USER", user["user_id"]),
        "identity": {"role": "USER", "id": user["user_id"],
                     "name": user["name"], "phone": user["phone"]},
        "message": f"欢迎，{user['name']}",
    })


# ============================================================================
# 2. 我的包裹：待取 + 历史
# ============================================================================
@mobile_bp.route("/packages", methods=["GET"])
def my_packages():
    ident, err = require_kiosk_role("USER")
    if err:
        return _err(err[0], err[1])
    _, uid = ident

    base = """
        SELECT p.package_id, p.tracking_no, p.status AS pkg_status, p.size_type,
               p.store_time, p.expire_time, p.pickup_time,
               p.overtime_fee, p.overtime_fee_paid,
               cab.cabinet_code, cab.location, cell.cell_code,
               c.company_name
        FROM t_package p
        JOIN t_cabinet cab ON p.cabinet_id = cab.cabinet_id
        JOIN t_cell cell   ON p.cell_id = cell.cell_id
        LEFT JOIN t_courier cr ON p.courier_id = cr.courier_id
        LEFT JOIN t_express_company c ON cr.company_id = c.company_id
        WHERE p.user_id=%s AND p.direction='RECEIVE'
    """
    pending = db.query(base + " AND p.status IN ('STORED','EXPIRED') ORDER BY p.store_time",
                       (uid,))
    history = db.query(base + " AND p.status IN ('PICKED','RETURNED','EXCEPTION') "
                              "ORDER BY p.pickup_time DESC, p.package_id DESC LIMIT 20", (uid,))
    return jsonify({
        "pending": [_pkg_row(r) for r in pending],
        "history": [_pkg_row(r) for r in history],
    })


# ============================================================================
# 3. 取件预览：扫码/输码后先看柜机与费用，不泄露格口号
# ============================================================================
@mobile_bp.route("/pickup/preview", methods=["GET"])
def pickup_preview():
    ident, err = require_kiosk_role("USER")
    if err:
        return _err(err[0], err[1])

    code = (request.args.get("code") or "").strip()
    if not CODE_RE.match(code):
        return _err("取件码应为 6 位数字")

    row = db.query_one("""
        SELECT p.package_id, p.tracking_no, p.status, p.size_type, p.store_time, p.expire_time,
               p.overtime_fee, p.overtime_fee_paid, p.recipient_name, p.recipient_phone,
               cab.cabinet_code, cab.location, cell.cell_code,
               u.name AS user_name, u.phone AS user_phone
        FROM t_package p
        JOIN t_cabinet cab ON p.cabinet_id = cab.cabinet_id
        JOIN t_cell cell   ON p.cell_id = cell.cell_id
        JOIN t_user u      ON p.user_id = u.user_id
        WHERE p.pickup_code=%s AND p.direction='RECEIVE'""", (code,))
    if not row:
        return _err("取件码无效，请核对柜机屏幕或短信", 404)
    if row["status"] not in ("STORED", "EXPIRED"):
        return _err(f"该包裹当前状态为「{row['status']}」，无法取件", 409)

    need_pay = row["status"] == "EXPIRED" and not row["overtime_fee_paid"]
    fee = _fee_of(row, need_pay) or 0.0
    return jsonify({
        "package_id": row["package_id"],
        "tracking_no": row["tracking_no"],
        "cabinet_code": row["cabinet_code"],
        "location": row["location"],
        "size_type": row["size_type"],
        "store_time": row["store_time"],
        "expire_time": row["expire_time"],
        "status": row["status"],
        "need_pay": 1 if need_pay else 0,
        "overtime_fee": round(fee, 2) if need_pay else 0.0,
        # 取件前不回传格口号：开柜成功后才告知，贴近真实柜机行为
        "cell_hint": "开柜成功后显示格口号",
        "recipient": {"name": _mask_name(row["recipient_name"] or row["user_name"]),
                      "phone": _mask_phone(row["recipient_phone"] or row["user_phone"])},
    })


# ============================================================================
# 4. 远程开柜：唯一会改变包裹状态与格口的入口
# ============================================================================
@mobile_bp.route("/pickup/open", methods=["POST"])
def pickup_open():
    """手机远程开柜。

    - 幂等：请求头 Idempotency-Key 唯一，重试直接复用首次响应，不会二次开柜；
    - 归属：按 package_id 开柜必须是本人包裹；按取件码开柜允许代取（码即凭证）；
    - 支付：超时未付费返回 402 + 金额，前端引导先缴费再开柜。
    """
    ident, err = require_kiosk_role("USER")
    if err:
        return _err(err[0], err[1])
    _, uid = ident

    body = request.get_json(silent=True) or {}
    idem_key = (request.headers.get("Idempotency-Key") or "").strip()[:64]

    # 幂等命中：直接返回首次结果
    if idem_key:
        dup = db.query_one("SELECT response_json FROM t_device_command WHERE idempotency_key=%s",
                           (idem_key,))
        if dup and dup["response_json"]:
            return jsonify(json.loads(dup["response_json"]))

    pid = body.get("package_id")
    code = (body.get("code") or "").strip()
    if pid:
        pkg = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (int(pid),))
        if not pkg:
            return _err("包裹不存在", 404)
        if pkg["user_id"] != uid:
            return _err("只能开启本人名下的包裹", 403)
    elif code:
        if not CODE_RE.match(code):
            return _err("取件码应为 6 位数字")
        pkg = db.query_one(
            "SELECT * FROM t_package WHERE pickup_code=%s AND direction='RECEIVE'", (code,))
        if not pkg:
            return _err("取件码无效", 404)
    else:
        return _err("请提供 package_id 或取件码")

    ok, payload, status = do_unlock(pkg["package_id"], method="APP", role="USER")
    if not ok:
        if payload.get("error") == "NEED_PAYMENT":
            fee = _fee_of(pkg, True)
            return jsonify({"error": "NEED_PAYMENT", "package_id": pkg["package_id"],
                            "overtime_fee": round(fee, 2),
                            "message": f"包裹已超时，请先支付保管费 ¥{fee:.2f}"}), 402
        return jsonify(payload), status

    detail = payload["package"]
    result = {
        "package_id": pkg["package_id"],
        "tracking_no": detail["tracking_no"],
        "cabinet_code": detail["cabinet_code"],
        "cell_code": detail["cell_code"],
        "location": detail["location"],
        "open_seconds": OPEN_SECONDS,
        "message": f"{detail['cell_code']} 号门已弹开，请在 {OPEN_SECONDS} 秒内取走包裹",
    }

    # 入队开柜指令：柜机轮询取走后置 SENT，执行完毕回调 ack
    try:
        cmd_id = db.insert(
            "INSERT INTO t_device_command(cabinet_id, cell_id, package_id, command_type, "
            "source, idempotency_key, payload) VALUES(%s,%s,%s,'OPEN_CELL','MOBILE',%s,%s)",
            (pkg["cabinet_id"], pkg["cell_id"], pkg["package_id"], idem_key or None,
             f"OPEN {detail['cell_code']} for {OPEN_SECONDS}s"))
    except Exception:
        # 并发下幂等键冲突：说明另一个请求已经开过柜，返回它的结果
        dup = db.query_one("SELECT response_json FROM t_device_command WHERE idempotency_key=%s",
                           (idem_key,))
        if dup and dup["response_json"]:
            return jsonify(json.loads(dup["response_json"]))
        return _err("开柜指令提交失败，请重试", 409)

    result["command_id"] = cmd_id
    db.execute("UPDATE t_device_command SET response_json=%s WHERE command_id=%s",
               (json.dumps(result, ensure_ascii=False, default=str), cmd_id))
    return jsonify(result)


# ============================================================================
# 5. 重新开门：包裹已取走后柜门误关，5 分钟内可再弹一次
# ============================================================================
@mobile_bp.route("/pickup/reopen", methods=["POST"])
def pickup_reopen():
    """重新开门：仅限本人、刚取走（5 分钟内）的包裹，防止被当成"万能开锁"。"""
    ident, err = require_kiosk_role("USER")
    if err:
        return _err(err[0], err[1])
    _, uid = ident

    body = request.get_json(silent=True) or {}
    pid = body.get("package_id")
    if not pid:
        return _err("缺少 package_id")

    row = db.query_one("""
        SELECT p.package_id, p.cabinet_id, p.cell_id, p.status, p.pickup_time,
               cell.cell_code, cab.cabinet_code
        FROM t_package p
        JOIN t_cell cell   ON cell.cell_id = p.cell_id
        JOIN t_cabinet cab ON cab.cabinet_id = p.cabinet_id
        WHERE p.package_id=%s AND p.user_id=%s""", (int(pid), uid))
    if not row:
        return _err("包裹不存在或不属于本人", 404)
    if row["status"] != "PICKED":
        return _err("仅已取走的包裹可重新开门", 409)
    if not row["pickup_time"]:
        return _err("缺少取件时间，无法重新开门", 409)

    minutes = db.query_one(
        "SELECT TIMESTAMPDIFF(MINUTE, %s, NOW()) AS m", (row["pickup_time"],))["m"]
    if minutes is not None and int(minutes) > 5:
        return _err("已超过 5 分钟，如需帮助请联系现场工作人员", 409)

    cmd_id = db.insert(
        "INSERT INTO t_device_command(cabinet_id, cell_id, package_id, command_type, "
        "source, payload) VALUES(%s,%s,%s,'OPEN_CELL','MOBILE',%s)",
        (row["cabinet_id"], row["cell_id"], row["package_id"],
         f"REOPEN {row['cell_code']} for {OPEN_SECONDS}s"))
    return jsonify({"command_id": cmd_id, "cell_code": row["cell_code"],
                    "cabinet_code": row["cabinet_code"], "open_seconds": OPEN_SECONDS,
                    "message": f"{row['cell_code']} 号门已重新弹开"})


# ============================================================================
# 6. 超时保管费：只允许支付本人包裹
# ============================================================================
@mobile_bp.route("/pay/overtime", methods=["POST"])
def pay_overtime():
    ident, err = require_kiosk_role("USER")
    if err:
        return _err(err[0], err[1])
    _, uid = ident

    body = request.get_json(silent=True) or {}
    ids = body.get("package_ids") or ([body["package_id"]] if body.get("package_id") else [])
    if not ids:
        return _err("缺少 package_id")
    ids = [int(x) for x in ids]

    ph = ",".join(["%s"] * len(ids))
    owned = db.query(f"SELECT package_id FROM t_package WHERE package_id IN ({ph}) AND user_id=%s",
                     tuple(ids) + (uid,))
    if {r["package_id"] for r in owned} != set(ids):
        return _err("存在不属于本人的包裹，已拒绝", 403)

    payable, total = charge_overtime(ids)
    return jsonify({
        "paid_count": len(payable),
        "total_fee": total,
        "packages": [r["package_id"] for r in payable],
        "message": f"支付成功，合计 ¥{total:.2f}" if total else "无需支付保管费",
    })


# ============================================================================
# 7. 附近柜机：按位置/编号搜索，带各规格空闲格口数
# ============================================================================
@mobile_bp.route("/cabinets/nearby", methods=["GET"])
def cabinets_nearby():
    q = (request.args.get("q") or "").strip()
    like = f"%{q}%" if q else None
    rows = db.query("""
        SELECT cab.cabinet_id, cab.cabinet_code, cab.location, cab.cabinet_type, cab.status,
               COUNT(cell.cell_id) AS total,
               COALESCE(SUM(cell.status='FREE'), 0) AS free_cnt,
               COALESCE(SUM(cell.status='FREE' AND cell.size_type='SMALL'), 0)  AS free_small,
               COALESCE(SUM(cell.status='FREE' AND cell.size_type='MEDIUM'), 0) AS free_medium,
               COALESCE(SUM(cell.status='FREE' AND cell.size_type='LARGE'), 0)  AS free_large
        FROM t_cabinet cab
        LEFT JOIN t_cell cell ON cell.cabinet_id = cab.cabinet_id
        WHERE (%s IS NULL OR cab.location LIKE %s OR cab.cabinet_code LIKE %s)
        GROUP BY cab.cabinet_id, cab.cabinet_code, cab.location, cab.cabinet_type, cab.status
        ORDER BY cab.cabinet_id
    """, (like, like, like))
    return jsonify({"count": len(rows), "cabinets": [
        {**r, "total": int(r["total"]), "free_cnt": int(r["free_cnt"]),
         "free_small": int(r["free_small"]), "free_medium": int(r["free_medium"]),
         "free_large": int(r["free_large"])} for r in rows]})


# ============================================================================
# 8. 取件二维码：柜机屏展示，手机用系统相机扫 → 直接打开 H5 取件页
# ----------------------------------------------------------------------------
# 为什么用"深链二维码"而不是浏览器内摄像头扫码：
#   浏览器 getUserMedia 只在 HTTPS / localhost 下可用，局域网 HTTP 地址会被
#   直接禁用；而手机系统相机扫二维码是操作系统能力，不受该限制。
#   于是把「取件码」编码成 http://<局域网IP>:<端口>/m?code=XXXXXX，
#   扫码即跳转，H5 读 URL 参数自动进入取件确认，全链路 HTTP 可用。
# ============================================================================
def _lan_ip():
    """探测本机在局域网中的出口 IP（不实际发包，仅让内核选路由）。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


# 内网穿透（cloudflared / ngrok 等）启动后把公网地址写进这个文件，
# 二维码就自动指向公网地址——手机用流量、换 Wi-Fi、跨网段都能扫开。
# 放在文件而不是环境变量里，是因为隧道地址每次重启都会变，
# 由启动脚本回写即可，不必重启 Flask。
PUBLIC_BASE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "public_base_url.txt")


def public_base():
    """返回 (base_url, source)，供柜机拼手机端深链 / 二维码内容。

    优先级：PUBLIC_BASE_URL 环境变量 > logs/public_base_url.txt（隧道地址）> 局域网 IP。
    局域网 IP 兜底是为了解决"柜机用 127.0.0.1 打开、二维码里的地址手机打不开"。
    """
    env = (os.getenv("PUBLIC_BASE_URL") or "").strip()
    if env:
        return env.rstrip("/"), "env"

    try:
        with open(PUBLIC_BASE_FILE, encoding="utf-8") as f:
            tunnel = f.readline().strip()
        if tunnel.startswith("http"):
            return tunnel.rstrip("/"), "tunnel"
    except OSError:
        pass

    port = int(os.getenv("PORT", "5000"))
    host = request.host or ""
    if ":" in host:
        tail = host.rsplit(":", 1)[1]
        if tail.isdigit():
            port = int(tail)
    return f"http://{_lan_ip()}:{port}", "auto"


@mobile_bp.route("/base-url", methods=["GET"])
def base_url():
    """当前手机端可访问的站点根地址（柜机二维码用它拼深链）。"""
    base, source = public_base()
    payload = {"base_url": base, "source": source}
    if source == "auto":
        payload["lan_ip"] = _lan_ip()
    return jsonify(payload)


@mobile_bp.route("/qr.svg", methods=["GET"])
def qr_svg():
    """按需生成二维码 SVG（服务端渲染，前端零依赖，离线可用）。"""
    data = (request.args.get("data") or "").strip()
    if not data:
        return _err("缺少二维码内容")
    if len(data) > 300:
        return _err("二维码内容过长")
    scale = max(3, min(12, request.args.get("scale", default=6, type=int) or 6))
    qr = segno.make(data, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, border=2, dark="#0f172a", light="#ffffff")
    resp = Response(buf.getvalue(), mimetype="image/svg+xml")
    resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


# ============================================================================
# 9. 柜机端：指令轮询与回执（模拟真实柜机的长轮询）
# ============================================================================
@device_bp.route("/commands/poll", methods=["GET"])
def poll_commands():
    """柜机取走待执行指令；取走即置 SENT，避免重复执行。"""
    cabinet_id = request.args.get("cabinet_id", type=int)
    if not cabinet_id:
        return _err("缺少 cabinet_id")
    rows = db.query("""
        SELECT cmd.command_id, cmd.command_type, cmd.payload, cmd.created_at,
               cell.cell_code, cab.cabinet_code
        FROM t_device_command cmd
        JOIN t_cell cell    ON cell.cell_id = cmd.cell_id
        JOIN t_cabinet cab  ON cab.cabinet_id = cmd.cabinet_id
        WHERE cmd.cabinet_id=%s AND cmd.status='PENDING'
        ORDER BY cmd.command_id LIMIT 20
    """, (cabinet_id,))
    for r in rows:
        db.execute("UPDATE t_device_command SET status='SENT', sent_at=NOW() WHERE command_id=%s",
                   (r["command_id"],))
    return jsonify({"count": len(rows), "commands": rows})


@device_bp.route("/commands/<int:cid>/ack", methods=["POST"])
def ack_command(cid):
    """柜机回执：ACK 表示柜门已弹开，FAILED 记录失败原因。"""
    body = request.get_json(silent=True) or {}
    ok = bool(body.get("success", True))
    db.execute(
        "UPDATE t_device_command SET status=%s, ack_at=NOW(), error_msg=%s WHERE command_id=%s",
        ("ACK" if ok else "FAILED", None if ok else str(body.get("error") or "柜机执行失败"), cid))
    return jsonify({"command_id": cid, "status": "ACK" if ok else "FAILED",
                    "acked_at": datetime.now().isoformat(timespec="seconds")})
