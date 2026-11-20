# 寄件人 / 收件人地址 · 回归测试（BUG2）
#
# 缺陷来源（用户实测）：寄件表单原先只有寄件人/收件人的姓名与手机号，没有地址；
#   现实中"快递员上门揽收 / 收件人收货"都必须有地址，只留手机号不成立。
# 修复：t_package 加 sender_address / recipient_address（可空），
#   POST /api/business/send-order 接收并入库，_send_order_row 输出，
#   send-lookup 与 my-packages 都能读回。
#
# 覆盖点：
#   1) 带地址下单 → send-lookup 能原样读回寄件人/收件人地址；
#   2) 不传地址 → 仍 201，读回 NULL（向后兼容，老调用方零影响）；
#   3) 地址超 120 字符 → 400 明确报错（不静默截断，截断会把件送错地方）。
#
# 运行：cd backend && python -m unittest discover -s tests -p "test_*.py"
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
from tests import _fixtures  # noqa: E402

SENDER_ADDR = "北京市朝阳区建国路 88 号 3 单元 501"
RECIPIENT_ADDR = "上海市浦东新区世纪大道 100 号 A 座 12 层"


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class SendOrderAddressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        # 夹具柜体自带 SMALL / MEDIUM / LARGE 各一个空闲格口，够本用例下 3 单
        self.fx = _fixtures.Fixture().setup(with_package=False)

    def tearDown(self):
        self.fx.teardown()

    def _send(self, size_type="SMALL", **extra):
        body = {
            "user_phone": _fixtures.TEST_PHONE_USER,
            "user_name": "测试寄件人",
            "recipient_name": "测试收件人",
            "recipient_phone": "13900006666",
            "size_type": size_type,
            "company_id": self.fx.company_id,
            "cabinet_id": self.fx.cabinet_id,
            "weight": 1.0,
        }
        body.update(extra)
        resp = self.client.post("/api/business/send-order", json=body)
        if resp.status_code == 201:
            # 交给夹具统一清理（外键依赖顺序由 _fixtures 负责）
            self.fx.package_ids.append(resp.get_json()["package"]["package_id"])
        return resp

    def _lookup(self, order_code):
        resp = self.client.get(
            f"/api/business/send-lookup?q={order_code}")
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        packages = resp.get_json()["packages"]
        self.assertTrue(packages, "刚下的寄件单必须能被 send-lookup 查到")
        return packages[0]

    def test_addresses_roundtrip_and_backward_compatible(self):
        # 1) 带地址下单 → 读回原值（send-lookup 与 201 响应都要有）
        created = self._send(sender_address=SENDER_ADDR, recipient_address=RECIPIENT_ADDR)
        self.assertEqual(created.status_code, 201, created.get_data(as_text=True))
        created_body = created.get_json()
        self.assertEqual(created_body["sender_address"], SENDER_ADDR)
        self.assertEqual(created_body["recipient_address"], RECIPIENT_ADDR)

        row = self._lookup(created_body["order_code"])
        self.assertEqual(row["sender_address"], SENDER_ADDR)
        self.assertEqual(row["recipient_address"], RECIPIENT_ADDR)

        # 2) 不传地址：仍 201，读回 NULL（老调用方行为不变）
        plain = self._send(size_type="MEDIUM")
        self.assertEqual(plain.status_code, 201, plain.get_data(as_text=True))
        row_plain = self._lookup(plain.get_json()["order_code"])
        self.assertIsNone(row_plain["sender_address"])
        self.assertIsNone(row_plain["recipient_address"])

        # 3) 超长地址：明确 400，不静默截断
        too_long = self._send(size_type="LARGE", sender_address="地" * 121)
        self.assertEqual(too_long.status_code, 400, too_long.get_data(as_text=True))
        self.assertIn("过长", too_long.get_json()["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
