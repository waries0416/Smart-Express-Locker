# 智能快递柜管理系统 · 后端服务入口 (Flask + PyMySQL)
# 前后端分离：本服务仅提供 REST API，前端为独立静态站点。
# 启动： python backend/app.py   (默认 http://127.0.0.1:5000)
import os
import sys
from decimal import Decimal

from flask import Flask, jsonify, send_from_directory, request, redirect, abort
from flask.json.provider import DefaultJSONProvider

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
import entities  # noqa: E402
import business  # noqa: E402
import stats  # noqa: E402
import auth  # noqa: E402
import notify  # noqa: E402
import mobile_api  # noqa: E402
import qr_login  # noqa: E402

app = Flask(__name__, static_folder=None)


class _JSONProvider(DefaultJSONProvider):
    """支持 Decimal 序列化（数据库 DECIMAL 列默认无法被 Flask 原生 JSON 编码）。"""
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


app.json = _JSONProvider(app)

# 跨域支持（前端可独立部署或本地 file:// 打开）
@app.after_request
def after_request(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
    return resp


# 页面禁止强缓存：门户页已下线，若浏览器继续用缓存里的旧 index.html / 旧 kiosk.html，
# 用户仍能"返回"到已删除的门户。HTML 一律 no-store；静态资源走 no-cache 强制回源校验
# （Flask 自带 ETag/Last-Modified，未变更时仍是 304，不影响本地加载速度）。
@app.after_request
def no_stale_frontend(resp):
    if request.path.startswith("/api"):
        return resp
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    else:
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.route("/api/<path:_path>", methods=["OPTIONS"])
def cors_preflight(_path):
    return ("", 204)


app.register_blueprint(entities.entities_bp)
app.register_blueprint(business.business_bp)
app.register_blueprint(stats.stats_bp)
app.register_blueprint(auth.auth_bp)
app.register_blueprint(notify.notify_bp)
app.register_blueprint(mobile_api.mobile_bp)
app.register_blueprint(mobile_api.device_bp)
app.register_blueprint(qr_login.qr_bp)

# 启动通知轮询线程（daemon，随进程退出）。测试脚本导入本模块时不想真的跑后台线程，
# 可用 NOTIFY_WORKER=0 关掉，改为手动调用 notify.dispatch_pending() 控制时序。
if os.getenv("NOTIFY_WORKER", "1") == "1":
    notify.start_worker()


@app.route("/api/health", methods=["GET"])
def health():
    try:
        db.query_one("SELECT 1")
        return jsonify({"status": "ok", "db": "connected"})
    except Exception as e:
        return jsonify({"status": "error", "db": str(e)}), 500


# ============================================================================
# 页面路由：触屏端(/) 与 管理端(/admin) 完全分离
# ----------------------------------------------------------------------------
# · 普通用户访问站点只会到达触屏端，页面内不存在任何后台入口；
# · 管理端挂在独立前缀下（ADMIN_PATH，默认 admin），由服务端 Cookie 会话把门：
#   未登录访问 /admin/dashboard 直接 302 到登录页，不依赖前端 JS 兜底；
# · 静态资源仅放行白名单目录，未知路径一律 404，不能按文件名摸到后台页面。
# ============================================================================
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
ADMIN_PATH = (os.getenv("ADMIN_PATH", "admin") or "admin").strip("/")
ASSET_DIRS = ("css", "js", "lib", "img")
ADMIN_LOGIN_URL = f"/{ADMIN_PATH}/login"


def _page(name):
    return send_from_directory(FRONTEND_DIR, name)


@app.before_request
def _guard_admin_pages():
    """管理端页面门禁（仅拦页面；/api 仍由各接口自己的 token 校验负责）。"""
    path = request.path
    prefix = f"/{ADMIN_PATH}"
    if request.method != "GET" or not (path == prefix or path.startswith(prefix + "/")):
        return None
    if path in (prefix, prefix + "/", ADMIN_LOGIN_URL):  # 登录页放行，否则死循环
        return None
    if not auth.admin_session_valid():
        return redirect(ADMIN_LOGIN_URL, code=302)
    return None


@app.route("/", methods=["GET"])
def home():
    """默认首页 = 快递柜触屏端（普通用户入口）。"""
    return _page("kiosk.html")


@app.route("/kiosk", methods=["GET"])
def kiosk_page():
    """触屏端别名，支持 /kiosk?cabinet=2 绑定具体柜体。"""
    return _page("kiosk.html")


@app.route(f"/{ADMIN_PATH}", methods=["GET"])
@app.route(f"/{ADMIN_PATH}/", methods=["GET"])
@app.route(f"/{ADMIN_PATH}/login", methods=["GET"])
def admin_login_page():
    return _page("login.html")


@app.route(f"/{ADMIN_PATH}/dashboard", methods=["GET"])
def admin_dashboard_page():
    return _page("admin.html")


# 手机端 H5：独立入口 /m，与触屏端共享同一套 API 与数据
@app.route("/m", methods=["GET"])
@app.route("/m/", methods=["GET"])
def mobile_page():
    return _page("mobile/index.html")


@app.route("/m/<path:filename>", methods=["GET"])
def mobile_asset(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "mobile"), filename)


@app.route("/<folder>/<path:filename>", methods=["GET"])
def static_asset(folder, filename):
    if folder not in ASSET_DIRS:  # 白名单：admin/api 等目录不会被当静态资源放出去
        abort(404)
    return send_from_directory(os.path.join(FRONTEND_DIR, folder), filename)


# 旧地址只做跳转，不再直接输出页面（书签与旧文档里的链接仍可用）
@app.route("/index.html", methods=["GET"])
@app.route("/kiosk.html", methods=["GET"])
def legacy_kiosk():
    return redirect("/", code=302)


@app.route("/login.html", methods=["GET"])
@app.route("/admin.html", methods=["GET"])
def legacy_admin():
    return redirect(ADMIN_LOGIN_URL, code=302)


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api"):
        return jsonify({"error": "接口不存在"}), 404
    # 不再回退首页：未知路径就是 404，避免后台入口被扫描发现
    return (
        "<!doctype html><meta charset='utf-8'><title>404</title>"
        "<div style='font-family:system-ui;text-align:center;padding:80px 20px'>"
        "<h1 style='font-size:48px;margin:0'>404</h1>"
        "<p style='color:#64748b'>页面不存在</p>"
        "<p><a href='/' style='color:#2563eb'>返回快递柜</a></p></div>",
        404,
        {"Content-Type": "text/html; charset=utf-8"},
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
