# 触屏端匿名「持取件码缴费」· 回归测试（BUG1 方案A）
#
# 背景（用户实测第二轮）：触屏端「凭取件码取件 → 超时缴费」是**匿名**流程，
#   拿不到 USER token；而 /api/pay/create 原先要求登录态且只允许本人包裹，
#   于是弹层里既没有二维码、也无法建单。方案A 用一个明确的信任模型补上这一环：
#   **6 位取件码本身就是取走包裹的凭证**（与 /business/pickup 一致），
#   持码即可为「同一件、EXPIRED、未缴费」的 OVERTIME 包裹建单；
#   有登录态时行为完全不变，取件码不参与授权，避免持码者操作他人支付单。
#
# 覆盖点：
#   1) 匿名 + 正确取件码 → 200，alipay 模式返回非空 qr_code_url；
#   2) 码不符 → 403；无码匿名 → 401；有 token（非本人）+ 正确码 → 仍 403（语义不变）；
#      未超时/已缴费的件 → 409；
#   3) 新增匿名轮询 POST /api/pay/{id}/poll：持码可查状态、码错 403、缺码 400、单不存在 404；
#   4) 匿名建单按 IP 限流：第 11 次返回 429（防 6 位码爆破）。
#
# 运行：cd backend && python -m unittest discover -s tests -p "test_*.py"
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import payment_api  # noqa: E402
from integrations import alipay_client  # noqa: E402
from tests import _fixtures  # noqa: E402

FAKE_QR = "https://qr.alipay.com/kiosk-pickup-pay-token"


def _wrong_code(code):
    """构造一个必然错误的 6 位码（避免与真实码撞车）。"""
    return "111111" if code != "111111" else "222222"


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class KioskPickupPayTest(unittest.TestCase):
    KEYS = ("PAYMENT_PROVIDER", "ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY",
            "ALIPAY_PUBLIC_KEY", "ALIPAY_SANDBOX")

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved_env = {k: os.environ.get(k) for k in self.KEYS}
        self._saved_backend = alipay_client._KEY_BACKEND
        alipay_client._KEY_BACKEND = lambda op, *args: "FAKE_SIGN"
        os.environ.update({
            "PAYMENT_PROVIDER": "alipay",
            "ALIPAY_APP_ID": "2021000000000000",
            "ALIPAY_PRIVATE_KEY": "dummy-private-key",
            "ALIPAY_PUBLIC_KEY": "dummy-public-key",
            "ALIPAY_SANDBOX": "1",
        })
        payment_api.PICKUP_CREATE_LIMITER.reset()
        payment_api.PICKUP_POLL_LIMITER.reset()
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=True, fee="1.00")
        self.pid = self.fx.package_ids[0]
        row = db.query_one(
            "SELECT pickup_code, user_id FROM t_package WHERE package_id=%s",
            (self.pid,))
        self.code = row["pickup_code"]
        self.uid = row["user_id"]

    def tearDown(self):
        self.fx.teardown()
        alipay_client._KEY_BACKEND = self._saved_backend
        payment_api.PICKUP_CREATE_LIMITER.reset()
        payment_api.PICKUP_POLL_LIMITER.reset()
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---- 工具 ----
    def _create(self, **extra):
        body = {"biz_type": "OVERTIME", "biz_id": self.pid}
        body.update(extra)
        return self.client.post("/api/pay/create", json=body)

    def _token(self, uid):
        return {"Authorization": "Bearer " + auth.issue_kiosk_token("USER", uid)}

    def _poll(self, pay_id, **extra):
        body = {}
        body.update(extra)
        return self.client.post(f"/api/pay/{pay_id}/poll", json=body)

    # ---- 用例 ----
    def test_anonymous_create_with_pickup_code_returns_qr(self):
        """匿名 + 正确取件码 → 200，且 alipay 模式必须给出可编码的二维码内容。"""
        payload = {"alipay_trade_precreate_response":
                   {"code": "10000", "qr_code": FAKE_QR}}
        with mock.patch.object(alipay_client, "_post_form", return_value=payload):
            resp = self._create(pickup_code=self.code)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["provider"], "alipay_sandbox")
        self.assertFalse(body["mock"])
        self.assertEqual(body["qr_code_url"], FAKE_QR)
        self.assertTrue(body["redirect_url"], "真实模式仍应给出可跳转地址")
        # 支付单必须登记到该件主人名下（不是匿名空用户）
        row = db.query_one("SELECT user_id FROM t_pay_order WHERE pay_id=%s",
                           (body["pay_id"],))
        self.assertEqual(row["user_id"], self.uid)

    def test_pickup_code_authorization_is_strict(self):
        """码不符 403 / 无码匿名 401 / 非本人 token + 正确码 仍 403（有 token 语义不变）。"""
        self.assertEqual(self._create(pickup_code=_wrong_code(self.code)).status_code, 403)
        self.assertEqual(self._create().status_code, 401)

        resp = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": self.pid,
                  "pickup_code": self.code},
            headers=self._token(self.uid + 100000))
        self.assertEqual(resp.status_code, 403,
                         "有登录态时必须走原归属校验，取件码不能绕过")

        # 未超时 / 已缴费的件：匿名持码也不能建单（409）
        db.execute("UPDATE t_package SET status='STORED' WHERE package_id=%s", (self.pid,))
        self.assertEqual(self._create(pickup_code=self.code).status_code, 409)
        db.execute("UPDATE t_package SET status='EXPIRED', overtime_fee_paid=1 "
                   "WHERE package_id=%s", (self.pid,))
        self.assertEqual(self._create(pickup_code=self.code).status_code, 409)

    def test_poll_with_pickup_code_without_login(self):
        """匿名轮询：持码可查状态；码错 403、缺码 400、支付单不存在 404；有 token 时仍可查。"""
        os.environ["PAYMENT_PROVIDER"] = "mock"      # 本用例不需要真实二维码
        created = self._create(pickup_code=self.code)
        self.assertEqual(created.status_code, 200, created.get_data(as_text=True))
        created_body = created.get_json()
        self.assertTrue(created_body["mock"])
        pay_id = created_body["pay_id"]

        resp = self._poll(pay_id, pickup_code=self.code)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(resp.get_json()["pay_id"], pay_id)
        self.assertEqual(resp.get_json()["status"], "PENDING")

        self.assertEqual(self._poll(pay_id, pickup_code=_wrong_code(self.code)).status_code, 403)
        self.assertEqual(self._poll(pay_id).status_code, 400)
        self.assertEqual(self._poll(999999999, pickup_code=self.code).status_code, 404)

        # 有 token 的原有查询通道不受影响
        owner = self.client.get(f"/api/pay/{pay_id}", headers=self._token(self.uid))
        self.assertEqual(owner.status_code, 200, owner.get_data(as_text=True))

    def test_anonymous_create_is_rate_limited(self):
        """同一 IP 连续猜码：第 11 次建单必须 429（6 位码防爆破）。"""
        wrong = _wrong_code(self.code)
        codes = [self._create(pickup_code=wrong).status_code for _ in range(10)]
        self.assertEqual(codes, [403] * 10, codes)
        self.assertEqual(self._create(pickup_code=wrong).status_code, 429)


if __name__ == "__main__":
    unittest.main(verbosity=2)
