# 并发回归测试 · R9b：并发支付重复入账（缺陷 D）/ 并发取件重复取件（缺陷 E）
#
# 缺陷来源：quality/reports/09_loadtest.txt 第三/四节（quality-engineer 实测）。
#   修复前：
#     D · 5 件包裹并发支付 → 79 条 TIMEOUT-RESOLVED 流水，单件最多 20 条；
#     E · 同一取件码并发 10 次 → 7 次 200 + 7 条 SUCCESS 流水。
#   根因不是"不会写"，而是**同一套状态规则在多条代码路径上分叉**：
#     · _charge_overtime：无锁 SELECT → 判断 → 无条件 UPDATE + 无条件 INSERT；
#     · pickup / _do_unlock / force_unlock_cell：UPDATE 不带 WHERE status。
#   同一文件里 cancel_send() 早有 `cur.rowcount != 1` 兜底（揽收↔撤回），
#   说明写法团队掌握，只是这三/四条路径漏了同一套防护。
#
# 本文件的立场：用**真并发**（threading.Barrier + 每线程独立 test_client）把
# 不变量钉死，而不是靠时序概率去"赌"缺陷出现。修复后不变量恒成立；修复前必然破坏。
#   不变量（D）：每件包裹 TIMEOUT-RESOLVED 恰好 1 条；Σ paid_count == 包裹数；
#                 金额只收一次（绝对值覆盖写，不累加）。
#   不变量（E）：同码 10 并发 → 200 恰好 1 次、409 恰好 9 次、SUCCESS 流水恰好 1 条。
#
# 运行：cd backend && python -m unittest tests.test_concurrent_double_charge -v
# 依赖：MySQL（t_package / t_exception_log / t_pickup_record）。无库时整类跳过。
import os
import sys
import threading
import unittest

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import db  # noqa: E402
from tests import _fixtures  # noqa: E402

# 与 quality 的复测判据保持一致：同一取件码并发 10 次
CONCURRENCY = 10
THREAD_TIMEOUT = 30


def run_concurrently(fn, n=CONCURRENCY):
    """n 个线程在 Barrier 上就位后同时起跑。

    返回 (results, errors)：
      results[i] = fn(i) 的返回值（顺序与 i 对应，便于断言"恰好几次 200"）；
      errors     = 线程内抛出的异常列表（不允许被吞掉，否则"测试通过"可能是假的）。
    """
    barrier = threading.Barrier(n)
    results = [None] * n
    errors = []

    def worker(i):
        try:
            barrier.wait(timeout=THREAD_TIMEOUT)
            results[i] = fn(i)
        except Exception as exc:                     # 收集，交给主线程断言
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=THREAD_TIMEOUT)
    alive = sum(1 for t in threads if t.is_alive())
    if alive:
        raise AssertionError(f"有 {alive} 个并发线程未在 {THREAD_TIMEOUT}s 内结束（疑似死锁）")
    return results, errors


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class ConcurrentOvertimeChargeTest(unittest.TestCase):
    """缺陷 D：多线程同时支付同一批超时包裹，只允许每件入账一次。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        # with_package=False 后自己造：夹具数据与演示数据完全隔离，跑完按序清理
        self.fx = _fixtures.Fixture().setup(with_package=False)
        self.pids = [self.fx.make_expired_package(expired=True, fee="1.00")
                     for _ in range(3)]

    def tearDown(self):
        self.fx.teardown()

    # ---- 工具 ----
    def resolved_counts(self):
        """每件包裹的 TIMEOUT-RESOLVED 流水条数（只统计本用例的包裹）。"""
        ph = ",".join(["%s"] * len(self.pids))
        rows = db.query(
            f"SELECT package_id, COUNT(*) AS n FROM t_exception_log "
            f"WHERE exception_type='TIMEOUT' AND handle_result='RESOLVED' "
            f"AND package_id IN ({ph}) GROUP BY package_id", self.pids)
        return {r["package_id"]: int(r["n"]) for r in rows}

    def paid_flags(self):
        ph = ",".join(["%s"] * len(self.pids))
        rows = db.query(
            f"SELECT package_id, overtime_fee_paid, overtime_fee FROM t_package "
            f"WHERE package_id IN ({ph})", self.pids)
        return {r["package_id"]: (int(r["overtime_fee_paid"]),
                                  float(r["overtime_fee"])) for r in rows}

    # ---- 用例 ----
    def test_concurrent_pay_charges_each_package_exactly_once(self):
        """并发支付：每件恰好 1 条 RESOLVED 流水，Σ paid_count == 包裹数。"""
        def pay(_i):
            client = app_module.app.test_client()
            resp = client.post("/api/business/pay-overtime",
                               json={"package_ids": self.pids})
            body = resp.get_json() or {}
            return resp.status_code, int(body.get("paid_count") or 0)

        results, errors = run_concurrently(pay)
        self.assertEqual(errors, [], f"并发支付线程内异常：{errors}")
        self.assertTrue(all(sc == 200 for sc, _ in results), results)

        # 不变量 ①：每件包裹 TIMEOUT-RESOLVED 恰好 1 条（修复前实测单件最多 20 条）
        counts = self.resolved_counts()
        self.assertEqual(counts, {pid: 1 for pid in self.pids},
                         f"重复入账：{counts}（每件必须恰好 1 条）")

        # 不变量 ②：各次调用自报 paid_count 合计 == 包裹数
        # 竞争失败的调用必须是幂等空转（paid_count=0），而不是把同一件再报一次
        total_paid = sum(n for _, n in results)
        self.assertEqual(total_paid, len(self.pids),
                         f"Σ paid_count={total_paid} 应为 {len(self.pids)}；明细={results}")

        # 不变量 ③：金额只收一次，且仍是各件原价（绝对值覆盖写，不累加）
        flags = self.paid_flags()
        for pid in self.pids:
            self.assertEqual(flags[pid][0], 1, f"包裹 {pid} 未置为已缴：{flags[pid]}")
            self.assertEqual(flags[pid][1], 1.00, f"包裹 {pid} 金额被改写：{flags[pid]}")

    def test_repeated_pay_is_idempotent(self):
        """同一包裹支付两次（串行）：第二次必须 paid_count=0，流水仍只有 1 条。

        这条是确定性版本（不依赖线程交错），保证并发修复没有把
        "重复调用 → 幂等空转" 的单线程语义改坏。
        """
        client = app_module.app.test_client()
        first = client.post("/api/business/pay-overtime",
                            json={"package_ids": self.pids})
        second = client.post("/api/business/pay-overtime",
                             json={"package_ids": self.pids})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["paid_count"], len(self.pids))
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["paid_count"], 0,
                         f"重复支付必须幂等空转：{second.get_json()}")
        self.assertEqual(self.resolved_counts(),
                         {pid: 1 for pid in self.pids})


class _PickupBase(unittest.TestCase):
    """取件类用例的公共夹具：一件 STORED（免缴费）包裹 + 取件码/格口。"""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(TESTING=True)

    def setUp(self):
        self.fx = _fixtures.Fixture().setup(with_package=False)
        # expired=False → STORED，未超时，可直接取件（不受 402 闸门影响）
        self.pid = self.fx.make_expired_package(expired=False)
        row = db.query_one("SELECT pickup_code, cell_id FROM t_package WHERE package_id=%s",
                           (self.pid,))
        self.code = row["pickup_code"]
        self.cell_id = row["cell_id"]

    def tearDown(self):
        self.fx.teardown()

    def status_code_counts(self, results):
        counts = {}
        for sc in results:
            counts[sc] = counts.get(sc, 0) + 1
        return counts

    def success_records(self):
        return int(db.query_one(
            "SELECT COUNT(*) AS n FROM t_pickup_record "
            "WHERE package_id=%s AND result='SUCCESS'", (self.pid,))["n"])

    def assert_picked_once(self):
        row = db.query_one("SELECT status, pickup_time FROM t_package WHERE package_id=%s",
                           (self.pid,))
        self.assertEqual(row["status"], "PICKED")
        self.assertIsNotNone(row["pickup_time"])
        cell = db.query_one("SELECT status FROM t_cell WHERE cell_id=%s", (self.cell_id,))
        self.assertEqual(cell["status"], "FREE", "取件后格口应释放")


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class ConcurrentPickupTest(_PickupBase):
    """缺陷 E 路径①：验证码取件 /api/business/pickup。"""

    def test_concurrent_pickup_code_only_succeeds_once(self):
        """同码并发 10 次：200 恰好 1 次、409 恰好 9 次、SUCCESS 流水恰好 1 条。"""
        def pickup(_i):
            client = app_module.app.test_client()
            return client.post("/api/business/pickup",
                               json={"pickup_code": self.code}).status_code

        results, errors = run_concurrently(pickup)
        self.assertEqual(errors, [], f"并发取件线程内异常：{errors}")
        self.assertEqual(results.count(200), 1,
                         f"200 必须恰好 1 次：{self.status_code_counts(results)}")
        self.assertEqual(results.count(409), CONCURRENCY - 1,
                         f"其余必须全是 409：{self.status_code_counts(results)}")
        self.assertEqual(self.success_records(), 1, "SUCCESS 流水必须恰好 1 条")
        self.assert_picked_once()

    def test_second_pickup_after_success_still_409(self):
        """对照：串行重复取件仍然是 409（修复没有改变单线程语义）。"""
        client = app_module.app.test_client()
        first = client.post("/api/business/pickup", json={"pickup_code": self.code})
        second = client.post("/api/business/pickup", json={"pickup_code": self.code})
        self.assertEqual(first.status_code, 200, first.get_data(as_text=True))
        self.assertEqual(second.status_code, 409, second.get_data(as_text=True))
        self.assertEqual(second.get_json()["error"], "该包裹已取走")
        self.assertEqual(self.success_records(), 1)


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class ConcurrentUnlockTest(_PickupBase):
    """缺陷 E 路径②：无码/开柜取件 /api/business/unlock（_do_unlock）。"""

    def test_concurrent_unlock_only_succeeds_once(self):
        def unlock(_i):
            client = app_module.app.test_client()
            return client.post("/api/business/unlock",
                               json={"package_id": self.pid}).status_code

        results, errors = run_concurrently(unlock)
        self.assertEqual(errors, [], f"并发开柜线程内异常：{errors}")
        self.assertEqual(results.count(200), 1,
                         f"200 必须恰好 1 次：{self.status_code_counts(results)}")
        self.assertEqual(results.count(409), CONCURRENCY - 1,
                         f"其余必须全是 409：{self.status_code_counts(results)}")
        self.assertEqual(self.success_records(), 1, "SUCCESS 流水必须恰好 1 条")
        self.assert_picked_once()


@unittest.skipUnless(_fixtures.db_ready(), "需要 MySQL 数据库")
class ConcurrentForceUnlockTest(_PickupBase):
    """缺陷 E 路径③：管理员远程强制开柜 /api/business/cells/<id>/force-unlock。

    这条路径的状态集合是 ('STORED','EXPIRED','EXCEPTION')（管理员可处置异常件），
    因此不可照搬取件路径的两态集合；断言也相应只看"同一件包裹不被成功取走两次"：
      · SUCCESS 流水恰好 1 条（修复前并发点两次会写出 2 条）；
      · 不出现 5xx；
      · 竞争失败方要么 409（CAS 未命中），要么读到时已是空置格口走"解除故障"
        分支返回 200（该分支幂等、不写包裹流水，属既有语义，不改）。
    """

    def test_concurrent_force_unlock_picks_package_once(self):
        def force(_i):
            client = app_module.app.test_client()
            resp = client.post(f"/api/business/cells/{self.cell_id}/force-unlock")
            return resp.status_code

        results, errors = run_concurrently(force)
        self.assertEqual(errors, [], f"并发强制开柜线程内异常：{errors}")
        self.assertTrue(all(sc < 500 for sc in results),
                        f"不应出现 5xx：{self.status_code_counts(results)}")
        self.assertEqual(self.success_records(), 1,
                         f"同一件包裹只允许一条 ADMIN SUCCESS 流水：{self.success_records()}")
        self.assert_picked_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
