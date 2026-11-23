# 创新点 2 · 包装准备协同 · 离线单元测试
#
# 覆盖点：
#   1) /api/pack-materials 鉴权（401/403）与结构；
#   2) PUT 校验：负数/非整数/超上限 → 400 VALIDATION_FAILED；不存在 → 404；
#   3) 只接受 stock/threshold，其余字段忽略；
#   4) 快递员只能看本人任务（越权 403）；admin 可看全部；
#   5) done：非本人 403、已完成/已取消 409、成功后状态与时间正确；
#   6) 材料快照：台账改名后历史任务的材料名不变（解耦验证）；
#   7) 推荐 → 任务生成：带 pack_recommendation_id 的寄件/存件自动建任务；
#      不带该字段时行为与改造前完全一致（向后兼容）。
#
# 运行：cd backend && python -m unittest tests.test_packaging -v
# 数据：用 tests/_fixtures.Fixture 自建，空库也能全绿。
import os
import sys
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module           # noqa: E402
import assistant                   # noqa: E402
import auth                        # noqa: E402
import db                          # noqa: E402
import packaging_tasks             # noqa: E402
from tests import _fixtures        # noqa: E402


def _db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PackMaterialsApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self.fx = _fixtures.Fixture().setup(with_package=False)
        # 记录一条材料原值，用于还原（测试会改库存）
        self.material = db.query_one(
            "SELECT material_id, stock, threshold FROM t_pack_material "
            "ORDER BY material_id LIMIT 1")

    def tearDown(self):
        if self.material:
            db.execute("UPDATE t_pack_material SET stock=%s, threshold=%s "
                       "WHERE material_id=%s",
                       (self.material["stock"], self.material["threshold"],
                        self.material["material_id"]))
        self.fx.teardown()

    # ---- 鉴权 ----
    def test_list_requires_login(self):
        resp = self.client.get("/api/pack-materials")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "UNAUTHORIZED")

    def test_list_rejects_user_role(self):
        """USER 身份无权查材料台账 → 403 ROLE_REQUIRED（带 required_role）。"""
        headers = {"Authorization": "Bearer "
                   + auth.issue_kiosk_token("USER", self.fx.user_id)}
        resp = self.client.get("/api/pack-materials", headers=headers)
        self.assertEqual(resp.status_code, 403)
        body = resp.get_json()
        self.assertEqual(body["code"], "ROLE_REQUIRED")
        self.assertEqual(body["required_role"], "COURIER")

    def test_list_allows_courier(self):
        headers = {"Authorization": "Bearer "
                   + auth.issue_kiosk_token("COURIER", self.fx.courier_id)}
        resp = self.client.get("/api/pack-materials", headers=headers)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("data", body)
        self.assertIsInstance(body["data"], list)
        if body["data"]:
            for key in ("material_id", "name", "spec", "stock", "threshold", "unit"):
                self.assertIn(key, body["data"][0])

    def test_list_allows_admin(self):
        self.client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
        self.assertEqual(self.client.get("/api/pack-materials").status_code, 200)

    # ---- 更新校验 ----
    def _courier_headers(self):
        return {"Authorization": "Bearer "
                + auth.issue_kiosk_token("COURIER", self.fx.courier_id)}

    def test_update_stock_ok(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        resp = self.client.put(f"/api/pack-materials/{mid}", json={"stock": 33},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["stock"], 33)
        self.assertEqual(body["material_id"], mid)

    def test_update_rejects_negative_stock(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        resp = self.client.put(f"/api/pack-materials/{mid}", json={"stock": -1},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "VALIDATION_FAILED")

    def test_update_rejects_over_limit(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        resp = self.client.put(f"/api/pack-materials/{mid}", json={"stock": 100001},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "VALIDATION_FAILED")

    def test_update_accepts_boundary_values(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        for v in (0, 100000):
            resp = self.client.put(f"/api/pack-materials/{mid}", json={"stock": v},
                                   headers=self._courier_headers())
            self.assertEqual(resp.status_code, 200, f"stock={v} 应被接受")

    def test_update_rejects_non_integer(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        for bad in (1.5, "abc", "", True, None):
            resp = self.client.put(f"/api/pack-materials/{mid}", json={"stock": bad},
                                   headers=self._courier_headers())
            self.assertEqual(resp.status_code, 400, f"stock={bad!r} 应被拒绝")

    def test_update_ignores_other_fields(self):
        """契约：只接受 stock/threshold，其余字段忽略（不能借机改 name/unit）。"""
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        before = db.query_one("SELECT name, unit FROM t_pack_material "
                              "WHERE material_id=%s", (mid,))
        resp = self.client.put(
            f"/api/pack-materials/{mid}",
            json={"stock": 7, "name": "被篡改的名字", "unit": "吨"},
            headers=self._courier_headers())
        self.assertEqual(resp.status_code, 200)
        after = db.query_one("SELECT name, unit FROM t_pack_material "
                             "WHERE material_id=%s", (mid,))
        self.assertEqual(before["name"], after["name"])
        self.assertEqual(before["unit"], after["unit"])

    def test_update_threshold_ok(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        resp = self.client.put(f"/api/pack-materials/{mid}", json={"threshold": 9},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["threshold"], 9)

    def test_update_requires_at_least_one_field(self):
        if not self.material:
            self.skipTest("材料台账为空")
        mid = self.material["material_id"]
        resp = self.client.put(f"/api/pack-materials/{mid}", json={},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "VALIDATION_FAILED")

    def test_update_nonexistent_is_404(self):
        resp = self.client.put("/api/pack-materials/999999999", json={"stock": 5},
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.get_json()["code"], "NOT_FOUND")


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PackagingTaskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self.fx = _fixtures.Fixture().setup(with_package=True, expired=False)
        # 造一条推荐 + 任务
        self.rec_id = self._make_recommendation()
        self.task_id = packaging_tasks.create_task_from_recommendation(
            self.fx.package_ids[0], self.rec_id, courier_id=self.fx.courier_id)
        # 派一个"另一个快递员"用于越权测试
        self.other_courier_id = db.insert(
            "INSERT INTO t_courier(company_id, employee_no, name, phone) "
            "VALUES(%s,%s,%s,%s)",
            (self.fx.company_id, _fixtures.TEST_EMPLOYEE_NO + "B",
             "他人快递员", "13900009999"))

    def tearDown(self):
        if getattr(self, "task_id", None):
            db.execute("DELETE FROM t_pack_task WHERE task_id=%s", (self.task_id,))
        db.execute(
            "DELETE FROM t_pack_recommendation WHERE description LIKE %s",
            (f"%{_fixtures.TAG}%",))
        try:
            db.execute("DELETE FROM t_courier WHERE courier_id=%s",
                       (self.other_courier_id,))
        except Exception:
            pass
        self.fx.teardown()

    def _make_recommendation(self):
        payload, rec_id = assistant.pack_recommend(
            f"{_fixtures.TAG} 一个玻璃杯和两本书", persist=True)
        return rec_id

    def _courier_headers(self, cid=None):
        return {"Authorization": "Bearer "
                + auth.issue_kiosk_token("COURIER", cid or self.fx.courier_id)}

    # ---- 任务生成 ----
    def test_task_created_with_material_snapshot(self):
        self.assertIsNotNone(self.task_id, "带推荐时必须生成备包装任务")
        items = db.query(
            "SELECT name, qty, unit FROM t_pack_task_item WHERE task_id=%s",
            (self.task_id,))
        self.assertTrue(items, "任务必须有材料明细")
        for it in items:
            self.assertTrue(it["name"])
            self.assertGreaterEqual(int(it["qty"]), 1)
            self.assertTrue(it["unit"])

    def test_task_without_recommendation_returns_none(self):
        """不带推荐时不得建任务（向后兼容：老调用方行为不变）。"""
        self.assertIsNone(packaging_tasks.create_task_from_recommendation(
            self.fx.package_ids[0], None))
        self.assertIsNone(packaging_tasks.create_task_from_recommendation(
            self.fx.package_ids[0], 999999999))

    def test_material_snapshot_survives_ledger_rename(self):
        """台账改名不影响历史任务（快照解耦，docs/08 §2.2）。"""
        items = db.query(
            "SELECT task_item_id, name FROM t_pack_task_item WHERE task_id=%s "
            "ORDER BY task_item_id", (self.task_id,))
        if not items:
            self.skipTest("任务无材料明细")
        original = items[0]["name"]
        mat = db.query_one("SELECT material_id, name FROM t_pack_material "
                           "WHERE name=%s", (original,))
        if not mat:
            self.skipTest("材料不在台账中，跳过改名验证")
        try:
            db.execute("UPDATE t_pack_material SET name=%s WHERE material_id=%s",
                       (original + "-改名", mat["material_id"]))
            after = db.query_one(
                "SELECT name FROM t_pack_task_item WHERE task_item_id=%s",
                (items[0]["task_item_id"],))
            self.assertEqual(after["name"], original,
                             "历史任务的材料名必须是快照值，不随台账改名而变化")
        finally:
            db.execute("UPDATE t_pack_material SET name=%s WHERE material_id=%s",
                       (original, mat["material_id"]))

    # ---- 列表与越权 ----
    def test_list_returns_own_tasks_only(self):
        body = self.client.get("/api/courier/packaging-tasks",
                               headers=self._courier_headers()).get_json()
        self.assertIn("count", body)
        self.assertIn("data", body)
        self.assertIn("page", body)
        self.assertIn("size", body)
        for task in body["data"]:
            row = db.query_one(
                "SELECT assignee_courier_id FROM t_pack_task WHERE task_id=%s",
                (task["task_id"],))
            self.assertEqual(row["assignee_courier_id"], self.fx.courier_id,
                             "快递员只能看到指派给本人的任务")

    def test_other_courier_cannot_see_task(self):
        body = self.client.get(
            "/api/courier/packaging-tasks",
            headers=self._courier_headers(self.other_courier_id)).get_json()
        ids = [t["task_id"] for t in body["data"]]
        self.assertNotIn(self.task_id, ids)

    def test_list_requires_courier_role(self):
        headers = {"Authorization": "Bearer "
                   + auth.issue_kiosk_token("USER", self.fx.user_id)}
        resp = self.client.get("/api/courier/packaging-tasks", headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "ROLE_REQUIRED")

    def test_list_requires_login(self):
        self.assertEqual(self.client.get("/api/courier/packaging-tasks").status_code, 401)

    def test_status_filter_validated(self):
        resp = self.client.get("/api/courier/packaging-tasks?status=WRONG",
                               headers=self._courier_headers())
        self.assertEqual(resp.status_code, 400)

    def test_status_filter_works(self):
        body = self.client.get("/api/courier/packaging-tasks?status=PENDING",
                               headers=self._courier_headers()).get_json()
        for task in body["data"]:
            self.assertEqual(task["status"], "PENDING")

    def test_pagination_params(self):
        body = self.client.get("/api/courier/packaging-tasks?page=1&size=1",
                               headers=self._courier_headers()).get_json()
        self.assertEqual(body["page"], 1)
        self.assertEqual(body["size"], 1)
        self.assertLessEqual(len(body["data"]), 1)

    # ---- 完成任务 ----
    def test_done_by_owner(self):
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done",
            json={"note": "已备好气泡膜"}, headers=self._courier_headers())
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        body = resp.get_json()
        self.assertEqual(body["task_id"], self.task_id)
        self.assertEqual(body["status"], "DONE")
        self.assertTrue(body["done_at"])
        row = db.query_one("SELECT status, note FROM t_pack_task WHERE task_id=%s",
                           (self.task_id,))
        self.assertEqual(row["status"], "DONE")
        self.assertEqual(row["note"], "已备好气泡膜")

    def test_done_by_other_courier_forbidden(self):
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done", json={},
            headers=self._courier_headers(self.other_courier_id))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json()["code"], "FORBIDDEN")

    def test_done_twice_conflict(self):
        self.client.post(f"/api/courier/packaging-tasks/{self.task_id}/done",
                         json={}, headers=self._courier_headers())
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done", json={},
            headers=self._courier_headers())
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["code"], "CONFLICT")

    def test_done_canceled_conflict(self):
        db.execute("UPDATE t_pack_task SET status='CANCELED' WHERE task_id=%s",
                   (self.task_id,))
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done", json={},
            headers=self._courier_headers())
        self.assertEqual(resp.status_code, 409)

    def test_done_nonexistent_is_404(self):
        resp = self.client.post("/api/courier/packaging-tasks/999999999/done",
                                json={}, headers=self._courier_headers())
        self.assertEqual(resp.status_code, 404)

    def test_done_note_too_long_is_400(self):
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done",
            json={"note": "备" * 201}, headers=self._courier_headers())
        self.assertEqual(resp.status_code, 400)

    def test_done_by_admin_allowed(self):
        self.client.post("/api/auth/login",
                         json={"username": "admin", "password": "admin123"})
        resp = self.client.post(
            f"/api/courier/packaging-tasks/{self.task_id}/done", json={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["status"], "DONE")


@unittest.skipUnless(_db_ready(), "需要 MySQL 数据库")
class PackRecommendationWiringTest(unittest.TestCase):
    """/api/ai/pack-recommend 的 recommendation_id 与寄件单的衔接（契约 §2.3）。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.client = app_module.app.test_client()
        self.fx = _fixtures.Fixture().setup(with_package=False)

    def tearDown(self):
        db.execute("DELETE FROM t_pack_recommendation WHERE description LIKE %s",
                   (f"%{_fixtures.TAG}%",))
        self.fx.teardown()

    def test_recommend_returns_recommendation_id(self):
        body = self.client.post(
            "/api/ai/pack-recommend",
            json={"description": f"{_fixtures.TAG} 一个玻璃杯"}).get_json()
        self.assertIn("recommendation_id", body)
        self.assertIsNotNone(body["recommendation_id"])
        row = db.query_one(
            "SELECT recommendation_id FROM t_pack_recommendation "
            "WHERE recommendation_id=%s", (body["recommendation_id"],))
        self.assertIsNotNone(row, "推荐结果必须落库，供备包装任务引用")

    def test_store_order_accepts_recommendation_and_creates_task(self):
        rec = self.client.post(
            "/api/ai/pack-recommend",
            json={"description": f"{_fixtures.TAG} 两本书"}).get_json()
        rec_id = rec["recommendation_id"]
        resp = self.client.post("/api/business/store", json={
            "courier_id": self.fx.courier_id,
            "user_phone": _fixtures.TEST_PHONE_USER,
            "user_name": "测试用户",
            "size_type": rec["size_type"] if rec["size_type"] in
                         ("SMALL", "MEDIUM", "LARGE") else "SMALL",
            "weight": 1.0,
            "cabinet_id": self.fx.cabinet_id,
            "pack_recommendation_id": rec_id,
        })
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))
        body = resp.get_json()
        pid = body["package"]["package_id"]
        self.fx.package_ids.append(pid)
        self.assertIn("pack_task_id", body, "带推荐时应返回备包装任务 id")
        self.assertIsNotNone(body["pack_task_id"])
        # 落库的包裹必须记录推荐引用
        row = db.query_one(
            "SELECT pack_recommendation_id FROM t_package WHERE package_id=%s", (pid,))
        self.assertEqual(row["pack_recommendation_id"], rec_id)
        task = db.query_one(
            "SELECT task_id, assignee_courier_id FROM t_pack_task WHERE task_id=%s",
            (body["pack_task_id"],))
        self.assertIsNotNone(task)
        self.assertEqual(task["assignee_courier_id"], self.fx.courier_id)

    def test_store_without_recommendation_unchanged(self):
        """向后兼容：不带该字段时响应体里不出现 pack_task_id，也不建任务。"""
        before = db.query_one("SELECT COUNT(*) c FROM t_pack_task")["c"]
        resp = self.client.post("/api/business/store", json={
            "courier_id": self.fx.courier_id,
            "user_phone": _fixtures.TEST_PHONE_USER,
            "user_name": "测试用户",
            "size_type": "SMALL",
            "weight": 1.0,
            "cabinet_id": self.fx.cabinet_id,
        })
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))
        body = resp.get_json()
        self.fx.package_ids.append(body["package"]["package_id"])
        self.assertNotIn("pack_task_id", body)
        after = db.query_one("SELECT COUNT(*) c FROM t_pack_task")["c"]
        self.assertEqual(before, after, "不带推荐时不应产生任务")

    def test_store_with_invalid_recommendation_is_ignored(self):
        """非法推荐 id 不能让存件失败（可选字段容错）。"""
        resp = self.client.post("/api/business/store", json={
            "courier_id": self.fx.courier_id,
            "user_phone": _fixtures.TEST_PHONE_USER,
            "user_name": "测试用户",
            "size_type": "SMALL",
            "weight": 1.0,
            "cabinet_id": self.fx.cabinet_id,
            "pack_recommendation_id": "not-an-int",
        })
        self.assertIn(resp.status_code, (200, 201), resp.get_data(as_text=True))
        self.fx.package_ids.append(resp.get_json()["package"]["package_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
