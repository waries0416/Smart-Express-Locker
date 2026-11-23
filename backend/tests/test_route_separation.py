# 触屏端 / 管理端路由分离 · 回归测试（PyUnit）
#
# 覆盖点：
#   1) 默认首页是触屏端，且页面内不含任何后台入口；
#   2) 管理端挂在 /admin 下，未登录访问看板被服务端 302 拦到登录页；
#   3) 登录后 Cookie 会话生效，登出后立即失效；
#   4) 伪造 / 越权 Cookie 一律拒绝；
#   5) 旧地址只跳转、静态资源白名单、未知路径 404。
#
# 运行：cd backend && python -m unittest discover -s tests -v
# 说明：页面路由不依赖数据库，故本文件无需 MySQL 即可执行。
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")  # 测试期间不启动后台通知线程
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests import _guard  # noqa: E402,F401  进程级测试互斥（见 tests/_guard.py）
import app as app_module  # noqa: E402


class RouteSeparationTest(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    # ---- 1) 默认入口 ----
    def test_root_serves_kiosk(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("快递柜", html)
        for leak in ("admin", "后台", "login.html", "index.html"):
            self.assertNotIn(leak, html, f"触屏端首页不应出现后台痕迹: {leak}")

    def test_kiosk_alias(self):
        self.assertEqual(self.client.get("/kiosk").status_code, 200)

    def test_html_is_not_cached(self):
        """页面必须 no-store：否则浏览器会拿缓存里的旧门户页继续"返回首页"。"""
        resp = self.client.get("/")
        self.assertIn("no-store", resp.headers.get("Cache-Control", ""))
        self.assertEqual(self.client.get("/admin/login").headers.get("Cache-Control"),
                         "no-store, no-cache, must-revalidate, max-age=0")

    # ---- 2) 管理端门禁 ----
    def test_admin_login_page_is_public(self):
        for path in ("/admin", "/admin/", "/admin/login"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_dashboard_redirects_when_anonymous(self):
        resp = self.client.get("/admin/dashboard")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers["Location"].endswith("/admin/login"))

    def test_forged_and_wrong_role_cookie_rejected(self):
        cases = [
            "locker_admin=admin|9999999999|deadbeefdeadbeef",       # 签名伪造
            "locker_admin=USER|1|9999999999|deadbeefdeadbeef",      # 越权角色
            "locker_admin=",                                        # 空值
        ]
        for cookie in cases:
            resp = self.client.get("/admin/dashboard", headers={"Cookie": cookie})
            self.assertEqual(resp.status_code, 302, cookie)

    # ---- 3) 登录 / 登出闭环 ----
    def test_login_sets_cookie_and_grants_access(self):
        resp = self.client.post("/api/auth/login",
                                json={"username": "admin", "password": "admin123"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("locker_admin", resp.headers.get("Set-Cookie", ""))
        # 响应体不再回传 token，避免前端可读
        self.assertNotIn("token", resp.get_json())
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)

    def test_logout_revokes_access(self):
        self.client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
        self.client.post("/api/auth/logout")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 302)

    def test_wrong_password_rejected(self):
        resp = self.client.post("/api/auth/login",
                                json={"username": "admin", "password": "wrong"})
        self.assertEqual(resp.status_code, 401)

    # ---- 4) 账号清单不泄露 ----
    def test_accounts_requires_login_and_hides_password(self):
        self.assertEqual(self.client.get("/api/auth/accounts").status_code, 401)
        self.client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
        resp = self.client.get("/api/auth/accounts")
        self.assertEqual(resp.status_code, 200)
        for acc in resp.get_json()["accounts"]:
            self.assertNotIn("password", acc)

    # ---- 5) 实体接口写操作必须带管理员会话 ----
    def test_entity_mutation_requires_admin(self):
        """页面门禁挡不住直接调接口，写操作必须自己校验会话。"""
        resp = self.client.post("/api/companies",
                                json={"company_code": "ZZ9", "company_name": "越权测试"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(self.client.delete("/api/packages/1").status_code, 401)
        self.assertEqual(self.client.put("/api/cabinets/1", json={"status": "OFFLINE"}).status_code, 401)

    def test_entity_read_stays_open(self):
        """手机端下单要选公司与柜体、触屏端投递记录要查包裹，GET 必须保持可用。"""
        self.assertEqual(self.client.get("/api/companies?size=5").status_code, 200)
        self.assertEqual(self.client.get("/api/cabinets?size=5").status_code, 200)

    def test_entity_mutation_allowed_with_admin(self):
        self.client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
        resp = self.client.post("/api/companies",
                                json={"company_code": "ZZTEST", "company_name": "门禁回归测试"})
        self.assertEqual(resp.status_code, 201)
        new_id = resp.get_json()["id"]
        self.assertEqual(self.client.delete(f"/api/companies/{new_id}").status_code, 200)

    # ---- 6) 旧地址与兜底 ----
    def test_legacy_urls_redirect(self):
        self.assertTrue(self.client.get("/index.html").headers["Location"].endswith("/"))
        self.assertTrue(self.client.get("/kiosk.html").headers["Location"].endswith("/"))
        for old in ("/admin.html", "/login.html"):
            self.assertTrue(self.client.get(old).headers["Location"].endswith("/admin/login"))

    def test_static_whitelist_and_unknown_path(self):
        self.assertEqual(self.client.get("/css/style.css").status_code, 200)
        self.assertEqual(self.client.get("/js/api.js").status_code, 200)
        # 后台页面不能按文件名直接取到
        self.assertEqual(self.client.get("/admin.html").status_code, 302)
        self.assertEqual(self.client.get("/foo/bar").status_code, 404)

    def test_api_404_returns_json(self):
        resp = self.client.get("/api/not-exist")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("error", resp.get_json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
