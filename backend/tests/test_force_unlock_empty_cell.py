# 管理端「远程强制开锁 / 解除故障」· 空格口分支 · 确定性回归测试
#
# 为什么单独补这一条（R9b 收尾，2026-11-19，quality 覆盖率抖动 57.34% / 57.40%）：
#   force_unlock_cell() 的 else 分支（格口空闲/故障 → 复位 FREE，返回
#   {"cell_id":…, "cleared": true}）原本只在并发测试恰好命中"格口已空"的时序时
#   才会被执行，于是覆盖率在两档之间抖动（差 2 行）。
#   但这条分支本身是**合法的正常业务路径**，不是防御性死代码：管理端格口详情抽屉里，
#   空格口/故障格口上的按钮就是「解除故障 / 置为空闲」，调用的正是本接口
#   （frontend/js/admin.js 的 drawerForceUnlock → POST /business/cells/<id>/force-unlock），
#   所以它不应该靠时序运气才被验证。
#
# 覆盖点：
#   1) 故障格口远程开锁 → 200 + detail.cleared == True + 格口复位为 FREE；
#   2) 幂等：同一格口再开一次仍 200 / cleared=True，格口保持 FREE，且不产生取件流水；
#   3) 把两条分支**响应结构不同**这件事钉死（detail 是 {cell_id, cleared} 而不是包裹详情），
#      防止以后有人"统一结构"时静默改坏管理端的提示文案。
#
# 运行：cd backend && python -m unittest discover -s tests -p "test_*.py"
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db  # noqa: E402
from tests import _fixtures  # noqa: E402


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class ForceUnlockEmptyCellTest(unittest.TestCase):
    """空格口（FREE/FAULT）走 force-unlock：200 + cleared=True + 复位 FREE。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        # 自建柜体 + 3 个 FREE 格口（with_package=False：本用例不需要任何包裹）
        self.fx = _fixtures.Fixture().setup(with_package=False)
        self.cabinet_id = self.fx.cabinet_id
        self.cell_id = self.fx.cell_ids[0]        # SMALL 格口

    def tearDown(self):
        self.fx.teardown()

    def _force_unlock(self):
        return self.client.post(f"/api/business/cells/{self.cell_id}/force-unlock")

    def test_force_unlock_empty_cell_clears_fault_idempotently(self):
        # 先置为故障：这是管理端「解除故障 / 置为空闲」按钮的真实场景
        db.execute("UPDATE t_cell SET status='FAULT' WHERE cell_id=%s", (self.cell_id,))

        resp = self._force_unlock()
        body = resp.get_json()
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(body["message"], "远程开锁成功")
        self.assertEqual(
            body["detail"], {"cell_id": self.cell_id, "cleared": True},
            "空格口分支必须回 cleared=True（前端据此显示「故障/空闲格口已重置」）；"
            "这里刻意不返回包裹详情，两条分支结构不同是有意设计")
        self.assertEqual(
            db.query_one("SELECT status FROM t_cell WHERE cell_id=%s",
                         (self.cell_id,))["status"],
            "FREE", "空格口远程开锁应把格口复位为 FREE")

        # 幂等：再开一次仍成功，格口保持 FREE（管理端连点两次不应报错）
        again = self._force_unlock()
        self.assertEqual(again.status_code, 200, again.get_data(as_text=True))
        self.assertEqual(again.get_json()["detail"]["cleared"], True)
        self.assertEqual(
            db.query_one("SELECT status FROM t_cell WHERE cell_id=%s",
                         (self.cell_id,))["status"],
            "FREE")

        # 该分支不触碰包裹，因此不应产生任何取件流水
        n = db.query_one(
            "SELECT COUNT(*) AS n FROM t_pickup_record r "
            "JOIN t_package p ON p.package_id = r.package_id "
            "WHERE p.cabinet_id = %s", (self.cabinet_id,))["n"]
        self.assertEqual(int(n), 0, "空格口开锁不应写取件流水")


if __name__ == "__main__":
    unittest.main(verbosity=2)
