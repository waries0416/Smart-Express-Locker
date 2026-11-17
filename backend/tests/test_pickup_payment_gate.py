# 取件超时计费闸门 · 回归测试（PyUnit）
#
# 缺陷来源：D-01（测试发现）。验证码取件 /api/business/pickup 原先只判 PICKED /
# RETURNED / EXCEPTION 三态，漏了"EXPIRED 且未缴费"，导致用户输码即可绕过超时费；
# 且一旦置为 PICKED，包裹脱离 EXPIRED 态，缴费接口再也收不到这笔账。
#
# 覆盖点：
#   1) 超时未缴费 → 402 NEED_PAYMENT，且包裹状态仍是 EXPIRED（未被置 PICKED）；
#   2) 缴费后同一取件码可正常取件 → 200，状态置 PICKED，流水记为 SUCCESS；
#   3) 未超时的普通包裹不受闸门影响（防止误伤主流程）。
#
# 运行：cd backend && python -m unittest discover -s tests -v
# 依赖：MySQL（t_package / t_cell / t_user / t_pickup_record）。无库时整类跳过。
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db  # noqa: E402

TEST_PHONE = "13700009999"      # 本类专用测试号，跑完即删
TEST_NAME = "计费闸门测试"


def _db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库（smart_locker）")
class PickupPaymentGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)
        cls.cabinet = db.query_one(
            "SELECT cabinet_id FROM t_cabinet ORDER BY cabinet_id LIMIT 1")
        cls.courier = db.query_one(
            "SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
        if not cls.cabinet or not cls.courier:
            raise unittest.SkipTest("t_cabinet / t_courier 无数据，跳过计费闸门测试")

    def setUp(self):
        self.client = app_module.app.test_client()
        self.pids = []
        self.cids = []

    def tearDown(self):
        """还原：通知 → 异常 → 流水 → 指令 → 包裹 → 格口 → 测试用户"""
        for pid in self.pids:
            for table in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
                db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
            db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
        for cid in self.cids:
            db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cid,))
        db.execute("DELETE FROM t_user WHERE phone=%s", (TEST_PHONE,))

    # ---- 工具 ----
    def store_package(self):
        """存一件包裹，返回 (package_id, pickup_code, cell_id)"""
        resp = self.client.post("/api/business/store", json={
            "courier_id": self.courier["courier_id"],
            "user_phone": TEST_PHONE, "user_name": TEST_NAME,
            "size_type": "SMALL", "weight": 1.0,
            "cabinet_id": self.cabinet["cabinet_id"],
        })
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))
        data = resp.get_json()
        pid = data["package"]["package_id"]
        self.pids.append(pid)
        row = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
        self.cids.append(row["cell_id"])
        return pid, data["pickup_code"], row["cell_id"]

    def make_expired_unpaid(self, pid, fee=1.00):
        """把包裹改成"已超时未缴费"：store_time 前移 73h，保证 expire_time > store_time"""
        db.execute("UPDATE t_package SET status='EXPIRED', overtime_fee=%s, overtime_fee_paid=0, "
                   "store_time=DATE_SUB(NOW(), INTERVAL 73 HOUR), "
                   "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE package_id=%s", (fee, pid))

    # ---- 用例 ----
    def test_expired_unpaid_pickup_is_blocked(self):
        """超时未缴费：取件码取件必须被 402 拦下，且包裹仍停在 EXPIRED"""
        pid, code, _ = self.store_package()
        self.make_expired_unpaid(pid)

        resp = self.client.post("/api/business/pickup", json={"pickup_code": code})
        body = resp.get_json()
        self.assertEqual(resp.status_code, 402, resp.get_data(as_text=True))
        self.assertEqual(body["error"], "NEED_PAYMENT")
        self.assertEqual(body["package_id"], pid)
        self.assertEqual(body["overtime_fee"], 1.00)

        row = db.query_one("SELECT status, pickup_time FROM t_package WHERE package_id=%s", (pid,))
        self.assertEqual(row["status"], "EXPIRED", "被拦下的包裹不应置为 PICKED")
        self.assertIsNone(row["pickup_time"])

    def test_pickup_succeeds_after_payment(self):
        """缴费后同一取件码可正常取件，状态置 PICKED、流水记 SUCCESS"""
        pid, code, cell_id = self.store_package()
        self.make_expired_unpaid(pid)
        db.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell_id,))

        blocked = self.client.post("/api/business/pickup", json={"pickup_code": code})
        self.assertEqual(blocked.status_code, 402)

        pay = self.client.post("/api/business/pay-overtime", json={"package_ids": [pid]})
        self.assertEqual(pay.status_code, 200, pay.get_data(as_text=True))
        self.assertEqual(pay.get_json()["paid_count"], 1)

        resp = self.client.post("/api/business/pickup", json={"pickup_code": code})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(resp.get_json()["package"]["pkg_status"], "PICKED")

        rec = db.query_one("SELECT result FROM t_pickup_record WHERE package_id=%s "
                           "ORDER BY record_id DESC LIMIT 1", (pid,))
        self.assertEqual(rec["result"], "SUCCESS")
        cell = db.query_one("SELECT status FROM t_cell WHERE cell_id=%s", (cell_id,))
        self.assertEqual(cell["status"], "FREE", "取件后格口应释放")

    def test_normal_package_not_affected(self):
        """未超时的普通包裹不受闸门影响（防止误伤主流程）"""
        pid, code, _ = self.store_package()
        resp = self.client.post("/api/business/pickup", json={"pickup_code": code})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(resp.get_json()["package"]["pkg_status"], "PICKED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
