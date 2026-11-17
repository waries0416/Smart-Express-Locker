# 后台管理看板 · 登录认证蓝图
#
# 定位：课程设计演示用的轻量门禁，不是生产级安全方案。
# 目标：让后台看板有个像样的登录入口，同时保持演示时"一键即可进入"。
#
# 账号集中在 ADMIN_ACCOUNTS，可配多个（默认 admin / admin123）；登录成功后下发
# token（用户名 + 签发时间 + 简易签名），前端存 sessionStorage；admin.html 启动时
# 调 /api/auth/verify 把关。密码比对用 hmac.compare_digest，避免时序侧信道。
import hashlib
import hmac
import os
import re
import time

from flask import Blueprint, jsonify, request

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# 演示账号（明文保存便于课程演示；正式环境应存哈希 + 加盐）
ADMIN_ACCOUNTS = {
    "admin": {"password": "admin123", "name": "系统管理员", "role": "超级管理员"},
    "operator": {"password": "operator123", "name": "运营值班", "role": "运营"},
}

# token 签名密钥（演示用途；生产应从环境变量读取）
_SECRET = os.getenv("AUTH_SECRET", "smart-locker-demo-secret")
_TOKEN_TTL = 12 * 3600  # 12 小时

# 管理端会话 Cookie：HttpOnly 使 JS 读不到 token，XSS 也偷不走；
# SameSite=Lax 防 CSRF；Secure 仅在 HTTPS 部署时打开（COOKIE_SECURE=1）。
ADMIN_COOKIE = "locker_admin"
_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"


def _sign(payload):
    """对 payload 生成简易 HMAC 签名，防止前端随手伪造 token"""
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def _issue_token(username):
    ts = str(int(time.time()))
    payload = f"{username}|{ts}"
    return f"{payload}|{_sign(payload)}"


def _parse_token(token):
    """校验并解析 token，返回 username；无效返回 None"""
    if not token or token.count("|") != 2:
        return None
    username, ts, sig = token.split("|")
    if not hmac.compare_digest(_sign(f"{username}|{ts}"), sig):
        return None
    if time.time() - int(ts) > _TOKEN_TTL:
        return None
    if username not in ADMIN_ACCOUNTS:
        return None
    return username


def admin_token():
    """取管理端 token：优先 HttpOnly Cookie，其次 Authorization 头（兼容脚本/旧客户端）。

    Cookie 是页面访问的主通道——服务端渲染页面前就能校验，未登录直接 302，
    不必依赖前端 JS 兜底跳转（关掉 JS 也挡得住）。
    """
    token = (request.cookies.get(ADMIN_COOKIE) or "").strip()
    if token:
        return token
    return (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()


def admin_session_valid():
    """当前请求是否携带有效的管理员会话（供页面门禁使用）。"""
    return _parse_token(admin_token()) is not None


def set_admin_cookie(resp, token):
    resp.set_cookie(
        ADMIN_COOKIE, token,
        max_age=_TOKEN_TTL,
        httponly=True,          # JS 不可读，避免 token 泄露
        samesite="Lax",         # 跨站请求不带 Cookie，缓解 CSRF
        secure=_COOKIE_SECURE,  # HTTPS 部署时置 COOKIE_SECURE=1
        path="/",
    )
    return resp


@auth_bp.route("/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    account = ADMIN_ACCOUNTS.get(username)
    if not account:
        return jsonify({"error": "账号不存在"}), 401
    if not hmac.compare_digest(password, account["password"]):
        return jsonify({"error": "密码错误"}), 401

    resp = jsonify({
        "user": {
            "username": username,
            "name": account["name"],
            "role": account["role"],
        },
        "message": f"欢迎回来，{account['name']}",
    })
    # 登录态走 HttpOnly Cookie，响应体不再回传 token（前端也就无从泄露）
    return set_admin_cookie(resp, _issue_token(username))


@auth_bp.route("/verify", methods=["GET"])
def verify():
    """校验管理员会话是否有效（页面启动时调用；Cookie 或 Bearer 均可）"""
    username = _parse_token(admin_token())
    if not username:
        return jsonify({"error": "未登录或登录已过期"}), 401
    acc = ADMIN_ACCOUNTS[username]
    return jsonify({
        "valid": True,
        "user": {"username": username, "name": acc["name"], "role": acc["role"]},
    })


@auth_bp.route("/logout", methods=["POST"])
def logout():
    # token 本身无状态，清除 Cookie 即完成登出
    resp = jsonify({"message": "已退出登录"})
    resp.delete_cookie(ADMIN_COOKIE, path="/")
    return resp


@auth_bp.route("/accounts", methods=["GET"])
def accounts():
    """管理员账号清单（仅登录后可查，且**不回传密码**）。

    原实现对所有匿名请求返回明文密码，等于把后台入口和钥匙一起挂在首页——
    与「普通用户不接触管理端」的目标冲突，故收紧为登录态可见、仅暴露必要字段。
    """
    if not admin_session_valid():
        return jsonify({"error": "未登录或登录已过期"}), 401
    return jsonify({
        "accounts": [
            {"username": u, "name": a["name"], "role": a["role"]}
            for u, a in ADMIN_ACCOUNTS.items()
        ]
    })


# ============================================================================
# 触屏端登录（用户 / 快递员）
# ----------------------------------------------------------------------------
# 演示环境的轻量身份方案：触屏端不设密码，凭"本人标识"换取 HMAC 签名 token，
# 与后台 admin token 同一套签发/校验逻辑（payload|ts|sig，12 小时有效）。
#   用户   —— 手机号即账号（须已建档：存件/寄件自动建档或 mock 数据锚定号）；
#   快递员 —— 工号 + 手机号双因子匹配（两者须同属一名快递员）。
# 后续"我的包裹 / 站内消息 / 寄件撤回"等接口一律凭 token 取身份，
# 服务端按 recipient_id 过滤，杜绝"输任意手机号查别人数据"的越权查询。
# ============================================================================
import db  # noqa: E402  （放此处在模块导入时可用，避免与上方纯工具函数混淆）

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")
_KIOSK_TTL = 12 * 3600


def _kiosk_sign(payload):
    return hmac.new(_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]


def issue_kiosk_token(role, rid):
    """签发触屏端 / 手机端用户态 token（payload = role|rid|ts|sig）。

    手机端蓝图复用同一套签名逻辑，故此处公开导出。
    """
    ts = str(int(time.time()))
    payload = f"{role}|{rid}|{ts}"
    return f"{payload}|{_kiosk_sign(payload)}"


def kiosk_identity():
    """从请求头解析触屏端 token，返回 (role, rid) 或 None。

    role ∈ {'USER','COURIER'}；后台 admin token（username|ts|sig）不在此列。
    """
    token = (request.headers.get("Authorization") or "").replace("Bearer ", "").strip()
    if not token or token.count("|") != 3:
        return None
    role, rid, ts, sig = token.split("|")
    if role not in ("USER", "COURIER"):
        return None
    if not hmac.compare_digest(_kiosk_sign(f"{role}|{rid}|{ts}"), sig):
        return None
    try:
        if time.time() - int(ts) > _KIOSK_TTL:
            return None
        return role, int(rid)
    except ValueError:
        return None


def build_identity(role, rid):
    """按 (role, rid) 组装前端可直接渲染的身份卡片；账号已删则返回 None。

    抽成公共函数的理由：触屏端恢复会话（kiosk-verify）、手机端扫码确认（qr-login）、
    票据轮询换 token 三处需要**完全一致**的身份结构，否则前端要写三套渲染分支。
    """
    if role == "USER":
        user = db.query_one("SELECT * FROM t_user WHERE user_id=%s", (rid,))
        if not user:
            return None
        return {"role": "USER", "id": user["user_id"],
                "name": user["name"], "phone": user["phone"]}
    if role == "COURIER":
        courier = db.query_one(
            "SELECT c.*, e.company_name FROM t_courier c "
            "JOIN t_express_company e ON e.company_id=c.company_id WHERE c.courier_id=%s", (rid,))
        if not courier:
            return None
        return {"role": "COURIER", "id": courier["courier_id"], "name": courier["name"],
                "phone": courier["phone"], "employee_no": courier["employee_no"],
                "company_name": courier["company_name"]}
    return None


def require_kiosk_role(*roles):
    """触屏端接口的通用门卫：返回 (role, rid) 或 Flask 响应(401)。"""
    ident = kiosk_identity()
    if not ident:
        return None, ("请先在触屏端登录", 401)
    if roles and ident[0] not in roles:
        return None, ("当前登录身份无权执行该操作", 403)
    return ident, None


@auth_bp.route("/kiosk-login", methods=["POST"])
def kiosk_login():
    """触屏端登录：用户凭手机号，快递员凭 工号+手机号。成功签发 12h token。"""
    body = request.get_json(silent=True) or {}
    role = (body.get("role") or "").strip().upper()
    phone = (body.get("phone") or "").strip()

    if not PHONE_RE.match(phone):
        return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400

    if role == "USER":
        user = db.query_one("SELECT * FROM t_user WHERE phone=%s", (phone,))
        if not user:
            return jsonify({"error": "该手机号尚未注册，请先注册后登录（演示：15800000001）"}), 404
        token = issue_kiosk_token("USER", user["user_id"])
        return jsonify({
            "token": token,
            "identity": {"role": "USER", "id": user["user_id"], "name": user["name"],
                         "phone": user["phone"]},
            "message": f"欢迎，{user['name']}",
        })

    if role == "COURIER":
        employee_no = (body.get("employee_no") or "").strip().upper()
        if not employee_no:
            return jsonify({"error": "请填写快递员工号"}), 400
        # 工号 + 手机号双因子：两者必须同属一名快递员，防止只凭一个标识冒充
        courier = db.query_one(
            "SELECT c.*, e.company_name FROM t_courier c "
            "JOIN t_express_company e ON e.company_id=c.company_id "
            "WHERE c.employee_no=%s AND c.phone=%s", (employee_no, phone))
        if not courier:
            return jsonify({"error": "工号与手机号不匹配，请核对后重试"}), 404
        token = issue_kiosk_token("COURIER", courier["courier_id"])
        return jsonify({
            "token": token,
            "identity": {"role": "COURIER", "id": courier["courier_id"], "name": courier["name"],
                         "phone": courier["phone"], "employee_no": courier["employee_no"],
                         "company_name": courier["company_name"]},
            "message": f"欢迎，{courier['name']}（{courier['employee_no']}）",
        })

    return jsonify({"error": "role 必须为 USER 或 COURIER"}), 400


@auth_bp.route("/kiosk-register", methods=["POST"])
def kiosk_register():
    """触屏端用户自助注册：姓名 + 手机号（手机号即账号，唯一）。

    与业务"自动建档"共用 t_user 唯一键/CHECK 约束；注册成功即签发 token
    自动登录，免二次登录。快递员由后台统一建档，不在自助注册范围。
    """
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    phone = (body.get("phone") or "").strip()

    if not name:
        return jsonify({"error": "请填写姓名"}), 400
    if len(name) > 30:  # 对齐 t_user.name VARCHAR(30)
        return jsonify({"error": "姓名不能超过 30 个字符"}), 400
    if not PHONE_RE.match(phone):
        return jsonify({"error": "手机号格式不正确（须为 11 位有效手机号）"}), 400

    existing = db.query_one("SELECT user_id FROM t_user WHERE phone=%s", (phone,))
    if existing:
        return jsonify({"error": "该手机号已注册，请直接登录"}), 409

    try:
        uid = db.insert("INSERT INTO t_user(name, phone) VALUES(%s, %s)", (name, phone))
    except Exception:
        # 兜底：并发注册下唯一键 uk_user_phone 冲突
        return jsonify({"error": "该手机号已注册，请直接登录"}), 409

    token = issue_kiosk_token("USER", uid)
    return jsonify({
        "token": token,
        "identity": {"role": "USER", "id": uid, "name": name, "phone": phone},
        "message": f"注册成功，欢迎，{name}",
    }), 201


@auth_bp.route("/kiosk-verify", methods=["GET"])
def kiosk_verify():
    """校验触屏端 token 是否有效（kiosk.html 启动时恢复会话用）"""
    ident = kiosk_identity()
    if not ident:
        return jsonify({"error": "未登录或登录已过期"}), 401
    identity = build_identity(*ident)
    if not identity:
        return jsonify({"error": "账号已不存在"}), 401
    return jsonify({"valid": True, "identity": identity})
