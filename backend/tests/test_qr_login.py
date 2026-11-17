# 扫码登录票据 · 回归测试（PyUnit）
#
# 覆盖点：
#   1) 建票：返回 32 位随机票据 + 深链，且同一柜体的旧 PENDING 票被自动作废；
#   2) 读票：票据本身就是凭据（免登录可读），过期/已取消/已消费返回 410；
#   3) 确认：必须带手机端 token，只认 token 里的身份，重复确认 409；
#   4) 轮询换 token：CONFIRMED 只能被消费一次，重放拿不到第二个 token；
#   5) 身份打通：用户与快递员都能扫码登录，返回的 identity 结构可直接渲染。
#
# 运行：cd backend && python -m unittest discover -s tests -v
# 依赖：MySQL（t_qr_ticket / t_cabinet / t_user / t_courier）。无库时整类跳过。
import os
import secrets
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db  # noqa: E402

TICKET_RE = r"^[0-9a-f]{32}$"


def _db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库（smart_locker）")
class QrLoginTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)
        cls.created = []            # 本类创建的票据，tearDown 清理
        cls.cabinet = db.query_one(
            "SELECT cabinet_id, cabinet_code FROM t_cabinet ORDER BY cabinet_id LIMIT 1")
        if not cls.cabinet:
            raise unittest.SkipTest("t_cabinet 无数据，跳过扫码登录测试")
        cls.user = db.query_one("SELECT user_id, name, phone FROM t_user ORDER BY user_id LIMIT 1")
        cls.courier = db.query_one(
            "SELECT courier_id, name, employee_no, phone FROM t_courier ORDER BY courier_id LIMIT 1")

    def setUp(self):
        self.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        for tid in cls.created:
            db.execute("DELETE FROM t_qr_ticket WHERE ticket_id=%s", (tid,))

    # ---- 工具 ----
    def new_ticket(self):
        resp = self.client.post("/api/qr/ticket", json={})
        self.assertEqual(resp.status_code, 201, resp.get_data(as_text=True))
        data = resp.get_json()
        type(self).created.append(data["ticket_id"])
        return data

    def login(self, role="USER"):
        if role == "COURIER":
            body = {"role": "COURIER", "employee_no": self.courier["employee_no"],
                    "phone": self.courier["phone"]}
        else:
            body = {"role": "USER", "phone": self.user["phone"]}
        resp = self.client.post("/api/auth/kiosk-login", json=body)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["token"]

    def auth(self, role="USER"):
        return {"Authorization": "Bearer " + self.login(role)}

    # ---- 1) 建票 ----
    def test_create_ticket(self):
        data = self.new_ticket()
        self.assertRegex(data["ticket"], TICKET_RE)
        self.assertEqual(data["cabinet_id"], self.cabinet["cabinet_id"])
        self.assertIn("/m?ticket=", data["deep_link"])
        self.assertIn(data["ticket"], data["deep_link"])
        self.assertEqual(data["expire_in"], 120)
        self.assertEqual(data["purpose"], "KIOSK_LOGIN")

    def test_new_ticket_cancels_previous_pending(self):
        first = self.new_ticket()
        self.new_ticket()
        resp = self.client.get(f"/api/qr/ticket/{first['ticket']}")
        self.assertEqual(resp.status_code, 410)   # 旧码被柜机刷新，手机扫到应提示重扫

    # ---- 2) 读票 ----
    def test_read_ticket_without_login(self):
        data = self.new_ticket()
        resp = self.client.get(f"/api/qr/ticket/{data['ticket']}")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "PENDING")
        self.assertEqual(body["cabinet_code"], self.cabinet["cabinet_code"])
        self.assertGreater(body["expire_in"], 0)

    def test_read_unknown_ticket(self):
        self.assertEqual(self.client.get("/api/qr/ticket/" + "0" * 32).status_code, 404)

    def test_expired_ticket_rejected(self):
        token = secrets.token_hex(16)
        tid = db.insert(
            "INSERT INTO t_qr_ticket(ticket, cabinet_id, expire_at, created_at) "
            "VALUES(%s, %s, DATE_SUB(NOW(), INTERVAL 10 SECOND), DATE_SUB(NOW(), INTERVAL 20 SECOND))",
            (token, self.cabinet["cabinet_id"]))
        type(self).created.append(tid)
        self.assertEqual(self.client.get(f"/api/qr/ticket/{token}").status_code, 410)
        poll = self.client.get(f"/api/qr/ticket/{token}/poll").get_json()
        self.assertEqual(poll["status"], "EXPIRED")
        self.assertIsNone(poll["token"])

    # ---- 3) 确认 ----
    def test_confirm_requires_token(self):
        data = self.new_ticket()
        self.assertEqual(self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm").status_code, 401)

    def test_confirm_binds_token_identity(self):
        data = self.new_ticket()
        resp = self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm", headers=self.auth())
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["status"], "CONFIRMED")
        self.assertEqual(body["identity"]["role"], "USER")
        self.assertEqual(body["identity"]["id"], self.user["user_id"])

    def test_double_confirm_rejected(self):
        data = self.new_ticket()
        headers = self.auth()
        self.assertEqual(self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm",
                                          headers=headers).status_code, 200)
        self.assertEqual(self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm",
                                          headers=headers).status_code, 409)

    def test_forged_token_rejected(self):
        data = self.new_ticket()
        headers = {"Authorization": "Bearer USER|1|9999999999|deadbeefdeadbeef"}
        self.assertEqual(self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm",
                                          headers=headers).status_code, 401)

    # ---- 4) 轮询换 token ----
    def test_poll_returns_token_once(self):
        data = self.new_ticket()
        pending = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()
        self.assertEqual(pending["status"], "PENDING")
        self.assertIsNone(pending["token"])

        self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm", headers=self.auth())
        got = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()
        self.assertEqual(got["status"], "CONSUMED")
        self.assertTrue(got["token"])
        self.assertEqual(got["identity"]["id"], self.user["user_id"])

        # 重放：第二次轮询不再给 token
        again = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()
        self.assertEqual(again["status"], "CONSUMED")
        self.assertIsNone(again["token"])

    def test_kiosk_token_from_poll_is_usable(self):
        """柜机换到的 token 必须是真 token：拿去调受保护接口应通过。"""
        data = self.new_ticket()
        self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm", headers=self.auth())
        tk = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()["token"]
        resp = self.client.get("/api/auth/kiosk-verify", headers={"Authorization": "Bearer " + tk})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["identity"]["role"], "USER")

    # ---- 5) 快递员也能扫码登录 ----
    def test_courier_qr_login(self):
        if not self.courier:
            self.skipTest("t_courier 无数据")
        data = self.new_ticket()
        resp = self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm",
                                headers=self.auth("COURIER"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["identity"]["role"], "COURIER")
        got = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()
        self.assertEqual(got["identity"]["employee_no"], self.courier["employee_no"])

    # ---- 取消 ----
    def test_cancel_ticket(self):
        data = self.new_ticket()
        resp = self.client.post(f"/api/qr/ticket/{data['ticket']}/cancel")
        self.assertTrue(resp.get_json()["cancelled"])
        poll = self.client.get(f"/api/qr/ticket/{data['ticket']}/poll").get_json()
        self.assertEqual(poll["status"], "CANCELLED")
        self.assertIsNone(poll["token"])
        # 已取消的码不能再被确认
        self.assertEqual(self.client.post(f"/api/qr/ticket/{data['ticket']}/confirm",
                                          headers=self.auth()).status_code, 410)


if __name__ == "__main__":
    unittest.main(verbosity=2)
