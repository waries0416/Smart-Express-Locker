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
# 数据来源（R9b 收尾修复，2026-11-18）：
#   原实现用"演示库第 1 个柜体 + 第 1 个快递员"（SELECT ... ORDER BY cabinet_id
#   LIMIT 1）。一旦 CAB-001 的 SMALL 格口被占满，存件直接 409「当前无可用格口」，
#   本类三个用例全红 —— 不是闸门逻辑坏了，而是测试依赖了"恰好有空位"这个脆弱前提。
#   实测 2026-11-18 深夜演示库里 CAB-001/002/003 的 SMALL 格口均为 12/12 OCCUPIED
#   （其中 54 个是"OCCUPIED 但无活动包裹"的历史残留，来自压测/e2e 的清理只删包裹
#   没复位格口），于是"重置演示数据后再跑"必然失败。
#   现改为用 tests/_fixtures 自建柜体/格口/快递员：每个用例独占一个全新柜体，
#   只需 1 个 SMALL 空闲格口即可覆盖本类场景，与演示数据完全隔离；
#   连续跑多少遍都不会互相污染，也不再受历史残留影响。
#
# 运行：cd backend && python -m unittest discover -s tests -p "test_*.py"
# 依赖：MySQL（t_package / t_cell / t_user / t_pickup_record）。无库时整类跳过。
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db  # noqa: E402
from tests import _fixtures  # noqa: E402

TEST_PHONE = "13700009999"      # 本类专用测试号，跑完即删
TEST_NAME = "计费闸门测试"


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库（smart_locker）")
class PickupPaymentGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        # 自建最小数据：柜体 + 3 个格口（SMALL/MEDIUM/LARGE）+ 快递公司/快递员。
        # with_package=False：本类的包裹由 store 接口实时创建（被测链路本身）。
        self.fx = _fixtures.Fixture().setup(with_package=False)
        self.cabinet_id = self.fx.cabinet_id
        self.courier_id = self.fx.courier_id
        self.pids = []
        self.cids = []

    def tearDown(self):
        """还原：通知 → 异常 → 流水 → 指令 → 包裹 → （夹具）格口/柜体/快递员/用户"""
        for pid in self.pids:
            for table in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
                db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
            db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
        # 包裹删完后才能删格口/柜体（外键依赖），交给夹具按序清理
        self.fx.teardown()
        db.execute("DELETE FROM t_user WHERE phone=%s", (TEST_PHONE,))

    # ---- 工具 ----
    def store_package(self):
        """存一件包裹，返回 (package_id, pickup_code, cell_id)"""
        resp = self.client.post("/api/business/store", json={
            "courier_id": self.courier_id,
            "user_phone": TEST_PHONE, "user_name": TEST_NAME,
            "size_type": "SMALL", "weight": 1.0,
            "cabinet_id": self.cabinet_id,
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
