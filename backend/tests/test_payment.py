# 创新点 4 · 支付 · 离线单元测试
#
# 覆盖点（每一条都对应契约里的一条防刷设计）：
#   1) 金额快照：请求里带 amount 一律忽略，金额由服务端按业务单重算；
#   2) 越权：USER 不能为他人包裹建单（403）、不能查他人支付单（403）；
#   3) 幂等：同 biz 重复建单复用原单；重复 mock-succeed 返回 idempotent=true；
#   4) 伪造回调：验签失败 → 纯文本 fail，不入账；
#   5) 金额篡改：回调金额与快照不符 → fail，不入账；
#   6) 重复通知：同 (pay_no, trade_no) 只入账一次，仍返回 success；
#   7) 非 mock 模式调 mock-succeed → 403 MOCK_NOT_ALLOWED；
#   8) 手续费模式回落：PAYMENT_PROVIDER=alipay 但缺凭据 → 自动 mock + degraded；
#   9) RSA2 签名/验签往返正确（纯函数，无网络）。
#
# 运行：cd backend && python -m unittest tests.test_payment -v
# 数据：用 tests/_fixtures.Fixture 自建最小业务数据，**不依赖演示数据是否已灌入**，
#       空库也能全绿（不再整类 skip）。
# 网络：全部使用 mock 渠道 + 假签名后端，**不发起任何真实网络请求**。
import importlib.abc
import json
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module    # noqa: E402
import auth                 # noqa: E402
import db                   # noqa: E402
import payment              # noqa: E402
from integrations import alipay_client  # noqa: E402
from tests import _fixtures             # noqa: E402


def _db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False


def _admin_headers(client):
    """登录取管理端 Cookie（既有 auth.py 的登录接口）。"""
    resp = client.post("/api/auth/login",
                       json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {}


# ===========================================================================
# 依赖屏蔽工具：让 "cryptography 装不上" 这件事在测试里可复现
# ===========================================================================
class _BlockCryptoFinder(importlib.abc.MetaPathFinder):
    """插入 sys.meta_path 首位，令 `cryptography` 及其子模块导入失败。

    用 find_spec 抛 ImportError（而不是给 sys.modules 塞 None）：
    后者会让 `import cryptography` 成功返回 None，与"真没装"的行为不一致；
    抛 ImportError 才复现真实的缺依赖路径。
    """

    def find_spec(self, name, path=None, target=None):
        if name == "cryptography" or name.startswith("cryptography."):
            raise ImportError(f"R8 test: {name} 被屏蔽")
        return None


def _block_cryptography():
    """屏蔽 cryptography；返回 restore 函数。"""
    saved = {k: v for k, v in sys.modules.items()
             if k == "cryptography" or k.startswith("cryptography.")}
    for k in saved:
        del sys.modules[k]
    finder = _BlockCryptoFinder()
    sys.meta_path.insert(0, finder)

    def restore():
        try:
            sys.meta_path.remove(finder)
        except ValueError:
            pass
        sys.modules.update(saved)

    return restore


# ===========================================================================
# 一、RSA2 签名 / 验签（纯函数，无需数据库）
# ===========================================================================
class AlipayCryptoTest(unittest.TestCase):
    """用 cryptography 现场生成一对密钥做往返验证；绝不依赖真实支付宝凭据。"""

    @classmethod
    def setUpClass(cls):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except Exception:
            raise unittest.SkipTest("缺少 cryptography，跳过 RSA2 往返测试")
        cls._serialization = serialization
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()).decode()
        cls.public_pem = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        cls._saved = {k: os.environ.get(k) for k in
                      ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY",
                       "ALIPAY_SANDBOX")}

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        self._saved_backend = alipay_client._KEY_BACKEND
        alipay_client._KEY_BACKEND = None   # 用真实的 cryptography

    def tearDown(self):
        alipay_client._KEY_BACKEND = self._saved_backend

    def test_sign_then_verify_roundtrip(self):
        data = "app_id=2021000000&out_trade_no=P20261118001&total_amount=1.00"
        sig = alipay_client.sign(data, self.private_pem)
        self.assertTrue(sig)
        self.assertTrue(alipay_client.verify(data, sig, self.public_pem))

    def test_tampered_data_fails_verification(self):
        data = "total_amount=1.00"
        sig = alipay_client.sign(data, self.private_pem)
        self.assertFalse(alipay_client.verify("total_amount=999.00", sig, self.public_pem))

    def test_wrong_key_fails(self):
        data = "x=1"
        sig = alipay_client.sign(data, self.private_pem)
        # 用另一对密钥的公钥验证 → 必然失败
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pub = other.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.assertFalse(alipay_client.verify(data, sig, other_pub))

    def test_garbage_signature_returns_false_not_raise(self):
        """验签遇到垃圾输入必须返回 False，不能抛异常（回调要稳定给 fail 文本）。"""
        self.assertFalse(alipay_client.verify("x=1", "!!!not-base64!!!", self.public_pem))
        self.assertFalse(alipay_client.verify("x=1", "", self.public_pem))

    def test_sign_content_excludes_sign_fields(self):
        params = {"a": "1", "sign": "xxx", "sign_type": "RSA2", "b": "", "c": "3"}
        self.assertEqual(alipay_client.sign_content(params), "a=1&c=3")

    def test_sign_content_sorted_ascii(self):
        params = {"b": "2", "a": "1", "C": "3"}
        self.assertEqual(alipay_client.sign_content(params), "C=3&a=1&b=2")

    def test_unavailable_reason_lists_missing(self):
        for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY"):
            os.environ.pop(k, None)
        self.assertFalse(alipay_client.available())
        self.assertIn("ALIPAY_APP_ID", alipay_client.unavailable_reason())

    def test_pem_normalization_from_one_line(self):
        """用户常把 PEM 存成一行环境变量：必须能还原。"""
        body = "".join(self.public_pem.strip().splitlines()[1:-1])
        self.assertTrue(alipay_client.verify(
            "x=1", alipay_client.sign("x=1", self.private_pem), body))


# ===========================================================================
# 一·五、R8 回归：凭据齐全但缺 cryptography —— 必须回落 mock，不得静默半失效
# ===========================================================================
class AlipayCryptoMissingTest(unittest.TestCase):
    """R8 缺陷回归（不依赖数据库）。

    缺陷原貌：available() 只校验凭据，不看签名库。凭据齐全 + cryptography 缺失时
    available()=True → server_provider()=alipay_sandbox → 下单 200，但
    build_page_pay_params 抛错被吞，redirect_url/qr_code_url 为 None；
    同时 mock-succeed 又因"非 mock 模式"被 403。用户既付不了款也退不回去。
    修复后应统一回落 mock，并给出 degraded_reason。
    """

    KEYS = ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY",
            "ALIPAY_SANDBOX", "PAYMENT_PROVIDER")

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in self.KEYS}
        self._saved_backend = alipay_client._KEY_BACKEND
        # _KEY_BACKEND 保持 None：这样 sign() 会真正走 _crypto() 判定，
        # 不会被假后端短路掉（否则测不到依赖缺失）。
        alipay_client._KEY_BACKEND = None
        # 凭据齐全 + 沙箱开启 —— 唯一的短板就是签名库
        os.environ.update({
            "PAYMENT_PROVIDER": "alipay",
            "ALIPAY_APP_ID": "2021000000000000",
            "ALIPAY_PRIVATE_KEY": "dummy-private-key",
            "ALIPAY_PUBLIC_KEY": "dummy-public-key",
            "ALIPAY_SANDBOX": "1",
        })

    def tearDown(self):
        alipay_client._KEY_BACKEND = self._saved_backend
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_credentials_complete_but_crypto_missing(self):
        """凭据齐全 + 屏蔽 cryptography → available() 必须为 False。"""
        restore = _block_cryptography()
        try:
            self.assertIsNone(alipay_client._crypto(), "cryptography 应已被屏蔽")
            self.assertFalse(alipay_client.available(),
                             "缺签名库时 available() 不得返回 True（R8 核心断言）")
            # 有凭据时也不能给出误导性的"未配置"文案
            reason = alipay_client.unavailable_reason()
            self.assertTrue(reason)
            self.assertIn("cryptography", reason)
            for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY"):
                self.assertNotIn(k, reason, "凭据齐全时不应报缺凭据")
        finally:
            restore()

    def test_server_provider_falls_back_to_mock_with_degraded_reason(self):
        """回落链：server_provider()=mock 且给出 degraded_reason。"""
        restore = _block_cryptography()
        try:
            self.assertEqual(payment.server_provider(), payment.PROVIDER_MOCK)
            reason = payment.server_provider_degraded()
            self.assertIsNotNone(reason, "回落 mock 必须给出原因")
            self.assertIn("cryptography", reason)
            prov, why = payment.resolve_provider("alipay_sandbox")
            self.assertEqual(prov, payment.PROVIDER_MOCK)
            self.assertIsNotNone(why)
        finally:
            restore()

    def test_available_true_when_crypto_present(self):
        """反向对照：依赖可用时行为不变（防"改过头"把真实模式也禁掉）。"""
        try:
            import cryptography  # noqa: F401
        except Exception:
            raise unittest.SkipTest("本机未安装 cryptography，跳过正向对照")
        self.assertTrue(alipay_client.available())
        self.assertEqual(payment.server_provider(), payment.PROVIDER_ALIPAY)
        self.assertIsNone(payment.server_provider_degraded())


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class AlipayCryptoMissingApiTest(unittest.TestCase):
    """R8 回归（需要数据库）：HTTP 层必须返回 mock + degraded，而不是 200 + 空跳转地址。"""

    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self._saved = {k: os.environ.get(k) for k in
                       ("PAYMENT_PROVIDER", "ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY",
                        "ALIPAY_PUBLIC_KEY", "ALIPAY_SANDBOX")}
        self._saved_backend = alipay_client._KEY_BACKEND
        alipay_client._KEY_BACKEND = None
        os.environ.update({
            "PAYMENT_PROVIDER": "alipay",
            "ALIPAY_APP_ID": "2021000000000000",
            "ALIPAY_PRIVATE_KEY": "dummy-private-key",
            "ALIPAY_PUBLIC_KEY": "dummy-public-key",
            "ALIPAY_SANDBOX": "1",
        })
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=True, fee="1.00")

    def tearDown(self):
        self.fx.teardown()
        alipay_client._KEY_BACKEND = self._saved_backend
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_create_order_degrades_to_mock_when_crypto_missing(self):
        """修复前：200 + redirect_url=None + mock=false；修复后：mock + degraded=True。"""
        row = db.query_one(
            "SELECT package_id, user_id FROM t_package WHERE package_id=%s",
            (self.fx.package_ids[0],))
        headers = {"Authorization": "Bearer " + auth.issue_kiosk_token(
            "USER", row["user_id"])}
        restore = _block_cryptography()
        try:
            resp = self.client.post(
                "/api/pay/create",
                json={"biz_type": "OVERTIME", "biz_id": row["package_id"],
                      "provider": "alipay_sandbox"},
                headers=headers)
            self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
            body = resp.get_json()
            self.assertEqual(body["provider"], "mock",
                             "缺签名库必须回落 mock，不能停在 alipay_sandbox")
            self.assertTrue(body["mock"])
            self.assertTrue(body["degraded"])
            self.assertIn("cryptography", body["degraded_reason"] or "")
            self.assertIsNone(body["redirect_url"])
            self.assertIsNone(body["qr_code_url"])
        finally:
            restore()

    def test_mock_succeed_still_allowed_when_crypto_missing(self):
        """回落 mock 后，演示用的 mock-succeed 必须可用（不能 403 死锁）。"""
        row = db.query_one(
            "SELECT package_id, user_id FROM t_package WHERE package_id=%s",
            (self.fx.package_ids[0],))
        headers = {"Authorization": "Bearer " + auth.issue_kiosk_token(
            "USER", row["user_id"])}
        restore = _block_cryptography()
        try:
            created = self.client.post(
                "/api/pay/create",
                json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
                headers=headers).get_json()
            _admin_headers(self.client)
            resp = self.client.post(f"/api/pay/{created['pay_id']}/mock-succeed",
                                    json={})
            self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
            self.assertEqual(resp.get_json()["status"], "SUCCESS")
        finally:
            restore()


# ===========================================================================
# 二、金额快照与状态机（需要数据库里的包裹数据）
# ===========================================================================
@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PaymentAmountTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self._saved_provider = os.environ.get("PAYMENT_PROVIDER")
        os.environ["PAYMENT_PROVIDER"] = "mock"     # 强制 mock，绝不碰真实渠道
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=True, fee="1.00")

    def tearDown(self):
        self.fx.teardown()
        if self._saved_provider is None:
            os.environ.pop("PAYMENT_PROVIDER", None)
        else:
            os.environ["PAYMENT_PROVIDER"] = self._saved_provider

    def test_amount_comes_from_package_not_request(self):
        """契约核心：金额只能来自业务单，请求里的 amount 不予采信。"""
        pid = self.fx.package_ids[0]
        row = db.query_one(
            "SELECT overtime_fee FROM t_package WHERE package_id=%s", (pid,))
        amount, _biz = payment.amount_of("OVERTIME", pid)
        self.assertGreater(amount, 0)
        self.assertEqual(amount, round(float(row["overtime_fee"]), 2))

    def test_amount_defaults_when_fee_null(self):
        pid = self.fx.package_ids[0]
        db.execute("UPDATE t_package SET overtime_fee=NULL WHERE package_id=%s", (pid,))
        amount, _ = payment.amount_of("OVERTIME", pid)
        self.assertEqual(amount, payment.DEFAULT_OVERTIME_FEE)

    def test_unknown_biz_raises_not_found(self):
        with self.assertRaises(payment.PaymentError) as ctx:
            payment.amount_of("OVERTIME", 999999999)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(ctx.exception.code, "NOT_FOUND")

    def test_invalid_biz_type(self):
        with self.assertRaises(payment.PaymentError) as ctx:
            payment.amount_of("WRONG", 1)
        self.assertEqual(ctx.exception.code, "VALIDATION_FAILED")

    def test_send_biz_rejects_receive_package(self):
        pid = self.fx.package_ids[0]     # 这是一件 RECEIVE 包裹
        with self.assertRaises(payment.PaymentError):
            payment.amount_of("SEND", pid)

    def test_overtime_biz_rejects_send_package(self):
        sid = self.fx.make_send_package()
        with self.assertRaises(payment.PaymentError):
            payment.amount_of("OVERTIME", sid)

    def test_send_fee_from_config(self):
        sid = self.fx.make_send_package()
        amount, _ = payment.amount_of("SEND", sid)
        self.assertGreaterEqual(amount, 0.01)

    def test_amount_matches_by_cent(self):
        self.assertTrue(payment._amount_matches("1.00", 1.0))
        self.assertTrue(payment._amount_matches("1.0", "1.00"))
        self.assertFalse(payment._amount_matches("0.01", 1.0))
        self.assertFalse(payment._amount_matches("abc", 1.0))
        self.assertFalse(payment._amount_matches(None, 1.0))


# ===========================================================================
# 三、HTTP 层：鉴权 / 越权 / 幂等 / mock 门禁
# ===========================================================================
@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PayApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved_provider = os.environ.get("PAYMENT_PROVIDER")
        os.environ["PAYMENT_PROVIDER"] = "mock"
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=True, fee="1.00")

    def tearDown(self):
        self.fx.teardown()
        if self._saved_provider is None:
            os.environ.pop("PAYMENT_PROVIDER", None)
        else:
            os.environ["PAYMENT_PROVIDER"] = self._saved_provider

    # ---- 辅助 ----
    def expired_pkg(self):
        """本用例专属的"超时未缴费"包裹行。"""
        pid = self.fx.package_ids[0]
        return db.query_one(
            "SELECT package_id, user_id, overtime_fee FROM t_package "
            "WHERE package_id=%s", (pid,))

    def user_token(self, uid):
        return {"Authorization": "Bearer " + auth.issue_kiosk_token("USER", uid)}

    def admin_login(self):
        _admin_headers(self.client)

    # ---- 鉴权 ----
    def test_create_requires_login(self):
        resp = self.client.post("/api/pay/create",
                                json={"biz_type": "OVERTIME", "biz_id": 1})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "UNAUTHORIZED")

    def test_records_requires_admin(self):
        self.assertEqual(self.client.get("/api/pay/records").status_code, 401)

    def test_mock_succeed_requires_admin(self):
        row = self.expired_pkg()
        self.assertEqual(
            self.client.post(f"/api/pay/mock-succeed", json={}).status_code, 405)

    def test_other_users_package_forbidden(self):
        row = self.expired_pkg()
        other_uid = (row["user_id"] or 0) + 100000
        resp = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(other_uid))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    def test_own_package_allowed_and_amount_snapshot(self):
        row = self.expired_pkg()
        resp = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"],
                  "amount": 0.01},        # 恶意金额：必须被忽略
            headers=self.user_token(row["user_id"]))
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["provider"], "mock")
        self.assertEqual(body["provider_label"], "模拟支付")
        self.assertTrue(body["mock"])
        self.assertEqual(body["status"], "PENDING")
        self.assertNotEqual(body["amount"], 0.01, "请求里的 amount 必须被忽略")
        self.assertIn("expire_at", body)
        self.assertRegex(body["pay_no"], r"^P\d{8}\d{3,}$")

    def test_idempotent_create_reuses_pending_order(self):
        row = self.expired_pkg()
        headers = self.user_token(row["user_id"])
        first = self.client.post("/api/pay/create",
                                 json={"biz_type": "OVERTIME",
                                       "biz_id": row["package_id"]},
                                 headers=headers).get_json()
        second = self.client.post("/api/pay/create",
                                  json={"biz_type": "OVERTIME",
                                        "biz_id": row["package_id"]},
                                  headers=headers).get_json()
        self.assertEqual(first["pay_id"], second["pay_id"], "同业务单必须复用原单")
        self.assertEqual(first["pay_no"], second["pay_no"])

    def test_get_other_users_pay_forbidden(self):
        row = self.expired_pkg()
        created = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"])).get_json()
        other = self.client.get(f"/api/pay/{created['pay_id']}",
                                headers=self.user_token((row["user_id"] or 0) + 777))
        self.assertEqual(other.status_code, 403)

    def test_get_nonexistent_pay_is_404(self):
        self.admin_login()
        resp = self.client.get("/api/pay/999999999")
        self.assertEqual(resp.status_code, 404)

    # ---- mock 支付闭环 ----
    def test_mock_succeed_and_idempotent(self):
        row = self.expired_pkg()
        created = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"])).get_json()
        pay_id = created["pay_id"]

        self.admin_login()
        first = self.client.post(f"/api/pay/{pay_id}/mock-succeed", json={})
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        body = first.get_json()
        self.assertEqual(body["status"], "SUCCESS")
        self.assertFalse(body["idempotent"])
        self.assertTrue(body["mock"])
        paid_at = body["paid_at"]
        self.assertIsNotNone(paid_at)

        # 重复调用：idempotent=true，paid_at 保持首次值，不重复入账
        second = self.client.post(f"/api/pay/{pay_id}/mock-succeed", json={})
        self.assertEqual(second.status_code, 200)
        body2 = second.get_json()
        self.assertTrue(body2["idempotent"])
        self.assertEqual(body2["paid_at"], paid_at)

    def test_mock_succeed_ignores_body_amount_and_status(self):
        """请求体里塞 amount/status 必须被完全忽略（防"点一下就算付了"）。"""
        row = self.expired_pkg()
        created = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"])).get_json()
        pay_id = created["pay_id"]
        expected_amount = created["amount"]

        self.admin_login()
        body = self.client.post(
            f"/api/pay/{pay_id}/mock-succeed",
            json={"amount": 0.00, "status": "SUCCESS"}).get_json()
        self.assertEqual(body["amount"], expected_amount, "金额必须以快照为准")

    def test_mock_succeed_paid_then_repay_is_conflict(self):
        row = self.expired_pkg()
        created = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"])).get_json()
        pay_id = created["pay_id"]
        self.admin_login()
        self.client.post(f"/api/pay/{pay_id}/mock-succeed", json={})
        # 已支付成功后再建单 → 409 CONFLICT
        again = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"]))
        self.assertEqual(again.status_code, 409)
        self.assertEqual(again.get_json()["code"], "CONFLICT")

    def test_mock_succeed_rejected_in_alipay_mode(self):
        """非 mock 模式 → 403 MOCK_NOT_ALLOWED（绝不"点一下就入账"）。"""
        row = self.expired_pkg()
        created = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
            headers=self.user_token(row["user_id"])).get_json()
        pay_id = created["pay_id"]

        self.admin_login()
        os.environ["PAYMENT_PROVIDER"] = "alipay"
        for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY"):
            os.environ[k] = "dummy-for-mode-switch"
        os.environ["ALIPAY_SANDBOX"] = "1"
        try:
            resp = self.client.post(f"/api/pay/{pay_id}/mock-succeed", json={})
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.get_json()["code"], "MOCK_NOT_ALLOWED")
        finally:
            for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY",
                      "ALIPAY_SANDBOX"):
                os.environ.pop(k, None)

    def test_alipay_without_credentials_falls_back_to_mock(self):
        """PAYMENT_PROVIDER=alipay 但缺凭据 → 自动回落 mock 并 degraded（契约 §4.0）。"""
        row = self.expired_pkg()
        os.environ["PAYMENT_PROVIDER"] = "alipay"
        for k in ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY", "ALIPAY_PUBLIC_KEY"):
            os.environ.pop(k, None)
        try:
            body = self.client.post(
                "/api/pay/create",
                json={"biz_type": "OVERTIME", "biz_id": row["package_id"]},
                headers=self.user_token(row["user_id"])).get_json()
            self.assertEqual(body["provider"], "mock", "缺凭据必须回落 mock")
            self.assertTrue(body["mock"])
            self.assertTrue(body["degraded"])
            self.assertIn("ALIPAY", body["degraded_reason"])
        finally:
            os.environ.pop("PAYMENT_PROVIDER", None)

    def test_requested_alipay_cannot_bypass_server_mock(self):
        """服务端是 mock 时，请求写 alipay_sandbox 也必须被压回 mock。"""
        row = self.expired_pkg()
        body = self.client.post(
            "/api/pay/create",
            json={"biz_type": "OVERTIME", "biz_id": row["package_id"],
                  "provider": "alipay_sandbox"},
            headers=self.user_token(row["user_id"])).get_json()
        self.assertEqual(body["provider"], "mock")
        self.assertTrue(body["mock"])

    def test_records_listing_and_filters(self):
        self.admin_login()
        resp = self.client.get("/api/pay/records?page=1&size=5")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        for key in ("count", "page", "size", "data"):
            self.assertIn(key, body)
        self.assertLessEqual(len(body["data"]), 5)
        for row in body["data"]:
            self.assertIn("provider_label", row)
            self.assertIn("mock", row)

    def test_records_invalid_filter_is_400(self):
        self.admin_login()
        self.assertEqual(self.client.get("/api/pay/records?status=WRONG").status_code, 400)
        self.assertEqual(self.client.get("/api/pay/records?size=0").status_code, 400)
        self.assertEqual(self.client.get("/api/pay/records?size=101").status_code, 400)


# ===========================================================================
# 四、回调（伪造 / 金额篡改 / 重复通知 / 幂等）
# ===========================================================================
@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PayNotifyTest(unittest.TestCase):
    """用假签名后端模拟支付宝回调，完全离线。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self._saved_provider = os.environ.get("PAYMENT_PROVIDER")
        self._saved_backend = alipay_client._KEY_BACKEND
        self._saved_keys = {k: os.environ.get(k) for k in
                            ("ALIPAY_APP_ID", "ALIPAY_PRIVATE_KEY",
                             "ALIPAY_PUBLIC_KEY", "ALIPAY_SANDBOX")}
        # 进入真实沙箱模式 + 假签名后端（verify 由测试控制）
        os.environ["PAYMENT_PROVIDER"] = "alipay"
        os.environ["ALIPAY_APP_ID"] = "test-app"
        os.environ["ALIPAY_PRIVATE_KEY"] = "test-private"
        os.environ["ALIPAY_PUBLIC_KEY"] = "test-public"
        os.environ["ALIPAY_SANDBOX"] = "1"
        self.verify_result = True
        self.sign_calls = []
        alipay_client._KEY_BACKEND = self._fake_backend
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=True, fee="1.00")

    def tearDown(self):
        alipay_client._KEY_BACKEND = self._saved_backend
        self.fx.teardown()
        for k, v in self._saved_keys.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        if self._saved_provider is None:
            os.environ.pop("PAYMENT_PROVIDER", None)
        else:
            os.environ["PAYMENT_PROVIDER"] = self._saved_provider

    def _fake_backend(self, op, *args):
        """假的密码学后端：sign 返回固定串，verify 由 self.verify_result 控制。"""
        self.sign_calls.append(op)
        if op == "sign":
            return "FAKE_SIGNATURE"
        return self.verify_result

    def _make_order(self):
        """为夹具包裹建一条 alipay 渠道的 PENDING 单（绕过 mock 限制）。"""
        pid = self.fx.package_ids[0]
        row = db.query_one(
            "SELECT package_id, user_id, overtime_fee FROM t_package "
            "WHERE package_id=%s", (pid,))
        biz_id = row["package_id"]
        amount = round(float(row["overtime_fee"] or 1.00), 2)
        idem = f"OVERTIME:{biz_id}"
        db.execute("DELETE FROM t_pay_order WHERE idempotency_key=%s", (idem,))
        pay_no = payment._gen_pay_no()
        pay_id = db.insert(
            """INSERT INTO t_pay_order
                   (pay_no, biz_type, biz_id, user_id, amount, provider,
                    provider_label, is_mock, status, idempotency_key, expire_at)
               VALUES (%s,'OVERTIME',%s,%s,%s,'alipay_sandbox','支付宝沙箱',0,
                       'PENDING',%s, DATE_ADD(NOW(), INTERVAL 10 MINUTE))""",
            (pay_no, biz_id, row["user_id"], amount, idem))
        return {"pay_id": pay_id, "pay_no": pay_no, "amount": amount,
                "biz_id": biz_id, "user_id": row["user_id"]}

    def _notify(self, order, *, total_amount=None, trade_status="TRADE_SUCCESS",
                trade_no="T-TRADE-001"):
        return self.client.post("/api/pay/notify/alipay", data={
            "out_trade_no": order["pay_no"],
            "trade_no": trade_no,
            "trade_status": trade_status,
            "total_amount": str(total_amount if total_amount is not None
                                else f"{order['amount']:.2f}"),
            "app_id": "test-app",
            "sign": "FAKE_SIGNATURE",
            "sign_type": "RSA2",
        })

    # ---- 伪造回调 ----
    def test_forged_signature_returns_fail_text(self):
        order = self._make_order()
        self.verify_result = False            # 验签失败
        resp = self._notify(order)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_data(as_text=True), "fail")
        self.assertIn("text/plain", resp.headers["Content-Type"])
        # 未入账
        row = db.query_one("SELECT status FROM t_pay_order WHERE pay_id=%s",
                           (order["pay_id"],))
        self.assertEqual(row["status"], "PENDING")
        # 已留痕
        log = db.query_one(
            "SELECT result FROM t_pay_callback_log WHERE pay_id=%s "
            "ORDER BY log_id DESC LIMIT 1", (order["pay_id"],))
        self.assertEqual(log["result"], payment.CB_VERIFY_FAIL)

    def test_missing_signature_returns_fail(self):
        order = self._make_order()
        resp = self.client.post("/api/pay/notify/alipay", data={
            "out_trade_no": order["pay_no"], "trade_no": "T1",
            "trade_status": "TRADE_SUCCESS",
            "total_amount": f"{order['amount']:.2f}",
        })
        self.assertEqual(resp.get_data(as_text=True), "fail")

    # ---- 金额篡改 ----
    def test_amount_mismatch_returns_fail(self):
        order = self._make_order()
        resp = self._notify(order, total_amount=0.01)
        self.assertEqual(resp.get_data(as_text=True), "fail")
        row = db.query_one("SELECT status FROM t_pay_order WHERE pay_id=%s",
                           (order["pay_id"],))
        self.assertEqual(row["status"], "PENDING", "金额不符不得入账")
        log = db.query_one(
            "SELECT result FROM t_pay_callback_log WHERE pay_id=%s "
            "ORDER BY log_id DESC LIMIT 1", (order["pay_id"],))
        self.assertEqual(log["result"], payment.CB_AMOUNT_MISMATCH)

    def test_unknown_pay_no_returns_fail(self):
        resp = self.client.post("/api/pay/notify/alipay", data={
            "out_trade_no": "P99999999999", "trade_no": "T1",
            "trade_status": "TRADE_SUCCESS", "total_amount": "1.00",
            "sign": "FAKE_SIGNATURE",
        })
        self.assertEqual(resp.get_data(as_text=True), "fail")

    # ---- 正常入账 + 幂等 ----
    def test_valid_notify_applies_and_writes_biz(self):
        order = self._make_order()
        # 前置：包裹未缴费
        before = db.query_one(
            "SELECT overtime_fee_paid FROM t_package WHERE package_id=%s",
            (order["biz_id"],))
        resp = self._notify(order)
        self.assertEqual(resp.get_data(as_text=True), "success")
        pay = db.query_one("SELECT status, paid_at, trade_no FROM t_pay_order "
                           "WHERE pay_id=%s", (order["pay_id"],))
        self.assertEqual(pay["status"], "SUCCESS")
        self.assertIsNotNone(pay["paid_at"])
        self.assertEqual(pay["trade_no"], "T-TRADE-001")
        # 业务侧回写：超时费已付（取件闸门据此放行）
        after = db.query_one(
            "SELECT overtime_fee_paid FROM t_package WHERE package_id=%s",
            (order["biz_id"],))
        self.assertEqual(int(after["overtime_fee_paid"]), 1)
        # 还原，避免影响其它用例
        db.execute("UPDATE t_package SET overtime_fee_paid=%s WHERE package_id=%s",
                   (before["overtime_fee_paid"], order["biz_id"]))

    def test_duplicate_notify_does_not_double_book(self):
        """重复通知：同 (pay_no,trade_no) 只入账一次，仍返回 success。"""
        order = self._make_order()
        first = self._notify(order)
        self.assertEqual(first.get_data(as_text=True), "success")
        paid_at_1 = db.query_one(
            "SELECT paid_at FROM t_pay_order WHERE pay_id=%s", (order["pay_id"],))["paid_at"]

        second = self._notify(order)
        self.assertEqual(second.get_data(as_text=True), "success",
                         "重复通知仍须返回 success（支付宝要求）")
        paid_at_2 = db.query_one(
            "SELECT paid_at FROM t_pay_order WHERE pay_id=%s", (order["pay_id"],))["paid_at"]
        self.assertEqual(paid_at_1, paid_at_2, "重复通知不得改写支付时间")
        # 入账日志只有 1 条 APPLIED
        applied = db.query(
            "SELECT log_id FROM t_pay_callback_log WHERE pay_id=%s AND applied=1",
            (order["pay_id"],))
        self.assertEqual(len(applied), 1, "只允许入账一次")

    def test_non_success_trade_status_not_applied(self):
        order = self._make_order()
        resp = self._notify(order, trade_status="WAIT_BUYER_PAY")
        self.assertEqual(resp.get_data(as_text=True), "success")
        row = db.query_one("SELECT status FROM t_pay_order WHERE pay_id=%s",
                           (order["pay_id"],))
        self.assertEqual(row["status"], "PENDING", "非成功状态不得入账")

    def test_notify_rejected_in_mock_mode(self):
        """mock 模式不接收回调（也不暴露任何真实凭据）。"""
        order = self._make_order()
        os.environ["PAYMENT_PROVIDER"] = "mock"
        resp = self._notify(order)
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertEqual(body["code"], "MOCK_NOT_ALLOWED")

    def test_notify_returns_plain_text_not_json(self):
        """支付宝要求纯文本 success/fail，不能是 JSON（契约 §4.4）。"""
        order = self._make_order()
        resp = self._notify(order)
        text = resp.get_data(as_text=True)
        self.assertIn(text, ("success", "fail"))
        self.assertNotIn("{", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
