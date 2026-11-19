# 测试夹具：自建最小业务数据，让创新接口测试**不依赖演示数据是否已灌入**。
#
# 为什么需要它：
#   库里若没有 EXPIRED 包裹，支付与备包装测试只能整类 skip —— 那等于"测试通过"是
#   因为什么都没测。本模块在 setUp 里临时创建 柜体/格口/用户/快递员/包裹，
#   tearDown 里按外键顺序彻底清理，保证：
#     · 空库也能跑（不 skip）；
#     · 跑完不留垃圾（不污染演示数据）；
#     · 与演示数据完全隔离（只用 _TAG 前缀 + 专用手机号）。
import random

# 进程级测试互斥：导入即加锁，避免两个测试进程同时写库互踩（1213 死锁，见 _guard.py）
from tests import _guard  # noqa: F401
import db

# 专用标识，便于清理与人工辨认
TAG = "ZZTEST-INNO"
TEST_PHONE_USER = "13900007777"
TEST_PHONE_COURIER = "13900008888"
TEST_EMPLOYEE_NO = "ZZTEST001"

# 残留哨兵：凡是"上一次跑挂了"留下的夹具数据，都能靠这几条前缀被一次扫干净。
# 为什么必须有这一步（R8 实测）：
#   t_courier.uk_employee_no 是**全局唯一**，而本夹具把工号写死为 ZZTEST001。
#   只要有任何一次运行在 tearDown 前被打断（Ctrl-C、断言崩溃、进程被杀），
#   库里就会留下一行 ZZTEST001；此后**每一条**用例的 INSERT 都会撞
#   Duplicate entry 'ZZTEST001' for key 't_courier.uk_employee_no' ——
#   实测会让支付测试 33/41 直接 error，且人工看不出原因。
#   答辩现场"再跑一遍"恰恰最容易踩这个坑，所以清理做成幂等的、每次 setup 前先跑。


def purge_residue():
    """按外键依赖顺序删除历史残留夹具数据；幂等，空库 / 全干净时是 no-op。

    返回删除的行数统计（便于测试断言与排障）。任何单步失败都不抛出：
    清理是"尽力而为"的保险，不能反过来把测试搞红。
    """
    deleted = {}

    def _run(conn, sql, params):
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

    try:
        with db.transaction() as conn:
            # 1) 残留包裹集合：追踪号前缀 + 测试手机号 + 测试柜/用户/快递员名下的件
            conn.cursor().execute(
                """CREATE TEMPORARY TABLE IF NOT EXISTS tmp_zz_pkg (package_id BIGINT
                   PRIMARY KEY)""")
            conn.cursor().execute("DELETE FROM tmp_zz_pkg")
            conn.cursor().execute(
                """INSERT IGNORE INTO tmp_zz_pkg(package_id)
                   SELECT p.package_id FROM t_package p
                     LEFT JOIN t_user u  ON u.user_id = p.user_id
                     LEFT JOIN t_cabinet cb ON cb.cabinet_id = p.cabinet_id
                     LEFT JOIN t_courier c  ON c.courier_id = p.courier_id
                    WHERE p.tracking_no LIKE 'ZZTEST%%'
                       OR p.tracking_no LIKE 'ZZSEND%%'
                       OR u.phone IN (%s, %s)
                       OR cb.cabinet_code LIKE 'ZZT-%%'
                       OR cb.cabinet_code LIKE 'ZZT-TEST-%%'
                       OR c.employee_no LIKE 'ZZTEST%%'""",
                (TEST_PHONE_USER, TEST_PHONE_COURIER))

            # 2) 依赖 package 的子表（先清子、再清父）
            for table in ("t_pay_callback_log", "t_notice", "t_exception_log",
                          "t_pickup_record", "t_device_command", "t_pack_task"):
                sql = (f"DELETE FROM {table} WHERE package_id IN "
                       f"(SELECT package_id FROM tmp_zz_pkg)")
                if table == "t_pay_callback_log":
                    sql = ("DELETE FROM t_pay_callback_log WHERE pay_no IN ("
                           "SELECT pay_no FROM t_pay_order WHERE biz_id IN "
                           "(SELECT package_id FROM tmp_zz_pkg))")
                try:
                    deleted[table] = _run(conn, sql, ())
                except Exception:
                    pass

            # 3) 支付单 / 推荐 / 扫码票 → 包裹本体（from_send_id 自引用先置空）
            for label, sql in (
                ("t_pay_order", "DELETE FROM t_pay_order WHERE biz_id IN "
                                "(SELECT package_id FROM tmp_zz_pkg)"),
                ("t_pack_recommendation", "DELETE FROM t_pack_recommendation "
                                          "WHERE description LIKE %s"),
                ("t_package_self_ref", "UPDATE t_package SET from_send_id=NULL "
                                       "WHERE from_send_id IN "
                                       "(SELECT package_id FROM tmp_zz_pkg)"),
                ("t_package", "DELETE FROM t_package WHERE package_id IN "
                              "(SELECT package_id FROM tmp_zz_pkg)"),
            ):
                try:
                    params = (f"%{TAG}%",) if sql.count("%s") else ()
                    deleted[label] = _run(conn, sql, params)
                except Exception:
                    pass

            # 4) 柜体侧：格口 → 柜体（t_qr_ticket / t_device_command 已随包裹清理，
            #    仍按 cabinet_id 兜底一次）
            try:
                deleted["t_qr_ticket"] = _run(
                    conn,
                    "DELETE FROM t_qr_ticket WHERE cabinet_id IN ("
                    "SELECT cabinet_id FROM t_cabinet WHERE cabinet_code LIKE 'ZZT%%')",
                    ())
            except Exception:
                pass
            try:
                deleted["t_cell"] = _run(
                    conn,
                    "DELETE FROM t_cell WHERE cabinet_id IN ("
                    "SELECT cabinet_id FROM t_cabinet WHERE cabinet_code LIKE 'ZZT%%')",
                    ())
            except Exception:
                pass
            try:
                deleted["t_cabinet"] = _run(
                    conn,
                    "DELETE FROM t_cabinet WHERE cabinet_code LIKE 'ZZT%%'", ())
            except Exception:
                pass

            # 5) 快递员 → 快递公司
            for label, sql in (
                ("t_pack_task_courier", "DELETE FROM t_pack_task WHERE assignee_courier_id "
                                        "IN (SELECT courier_id FROM t_courier "
                                        "WHERE employee_no LIKE 'ZZTEST%%')"),
                ("t_courier", "DELETE FROM t_courier WHERE employee_no LIKE 'ZZTEST%%'"),
                ("t_express_company", "DELETE FROM t_express_company "
                                      "WHERE company_name LIKE %s OR company_code LIKE %s"),
            ):
                try:
                    params = ((f"%{TAG}%", "ZZT%") if sql.count("%s") == 2
                              else ())
                    deleted[label] = _run(conn, sql, params)
                except Exception:
                    pass

            # 6) 残留用户（只删夹具专用手机号；有包裹挂靠时上一步已清掉）
            try:
                deleted["t_user"] = _run(
                    conn,
                    "DELETE FROM t_user WHERE phone IN (%s, %s)",
                    (TEST_PHONE_USER, TEST_PHONE_COURIER))
            except Exception:
                pass
    except Exception:
        return deleted
    return {k: v for k, v in deleted.items() if v}


class Fixture:
    """一次性创建一套最小可用数据；exit 时严格按依赖顺序清理。"""

    def __init__(self):
        self.cabinet_id = None
        self.cell_ids = []
        self.user_id = None
        self.courier_id = None
        self.company_id = None
        self.package_ids = []
        self.task_ids = []

    # ---- 创建 ----
    def setup(self, *, with_package=True, expired=True, fee="1.00"):
        # 先自愈：清掉上一次中断留下的同名夹具，避免 uk_employee_no 撞车（见 purge_residue）
        purge_residue()
        self._make_company_courier()
        self._make_cabinet_cells()
        self._make_user()
        if with_package:
            self.make_expired_package(expired=expired, fee=fee)
        return self

    def _make_company_courier(self):
        code = f"ZZT{random.randint(100, 999)}"
        self.company_id = db.insert(
            "INSERT INTO t_express_company(company_code, company_name, hotline) "
            "VALUES(%s,%s,'400-000-0000')", (code, f"{TAG} 测试快递"))
        self.courier_id = db.insert(
            "INSERT INTO t_courier(company_id, employee_no, name, phone) "
            "VALUES(%s,%s,%s,%s)",
            (self.company_id, TEST_EMPLOYEE_NO, "测试快递员", TEST_PHONE_COURIER))

    def _make_cabinet_cells(self):
        self.cabinet_id = db.insert(
            "INSERT INTO t_cabinet(cabinet_code, location, cabinet_type, total_cells, "
            "status, latitude, longitude) VALUES(%s,%s,%s,3,'NORMAL',%s,%s)",
            (f"ZZT-TEST-{random.randint(1000, 9999)}", f"{TAG} 测试柜",
             "社区柜", 39.908722, 116.397499))
        for code, size in (("A01", "SMALL"), ("B01", "MEDIUM"), ("C01", "LARGE")):
            cid = db.insert(
                "INSERT INTO t_cell(cabinet_id, cell_code, size_type, status) "
                "VALUES(%s,%s,%s,'FREE')", (self.cabinet_id, code, size))
            self.cell_ids.append(cid)

    def _make_user(self):
        existing = db.query_one("SELECT user_id FROM t_user WHERE phone=%s",
                                (TEST_PHONE_USER,))
        if existing:
            self.user_id = existing["user_id"]
            return
        self.user_id = db.insert(
            "INSERT INTO t_user(name, phone) VALUES(%s,%s)",
            (f"{TAG} 测试用户", TEST_PHONE_USER))

    def make_expired_package(self, *, expired=True, fee="1.00"):
        """造一件包裹；expired=True 时置为"超时未缴费"（支付/取件闸门场景）。"""
        cell_id = self.cell_ids[0]
        tracking = f"ZZTEST{random.randint(10 ** 11, 10 ** 12 - 1)}"
        code = f"{random.randint(0, 999999):06d}"
        while db.query_one("SELECT 1 FROM t_package WHERE pickup_code=%s", (code,)):
            code = f"{random.randint(0, 999999):06d}"
        status = "EXPIRED" if expired else "STORED"
        fee_val = float(fee) if expired else None
        pid = db.insert(
            """INSERT INTO t_package(direction, tracking_no, courier_id, user_id,
                                     cabinet_id, cell_id, size_type, weight, status,
                                     pickup_code, store_time, expire_time,
                                     overtime_fee, overtime_fee_paid)
               VALUES('RECEIVE',%s,%s,%s,%s,%s,'SMALL',1.00,%s,%s,
                      DATE_SUB(NOW(), INTERVAL 73 HOUR),
                      DATE_SUB(NOW(), INTERVAL 1 HOUR),%s,0)""",
            (tracking, self.courier_id, self.user_id, self.cabinet_id, cell_id,
             status, code, fee_val))
        db.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell_id,))
        self.package_ids.append(pid)
        return pid

    def make_send_package(self):
        """造一张寄件单（biz_type=SEND 场景）。"""
        cell_id = self.cell_ids[1]
        tracking = f"ZZSEND{random.randint(10 ** 10, 10 ** 11 - 1)}"
        code = f"{random.randint(0, 999999):06d}"
        while db.query_one("SELECT 1 FROM t_package WHERE pickup_code=%s", (code,)):
            code = f"{random.randint(0, 999999):06d}"
        pid = db.insert(
            """INSERT INTO t_package(direction, tracking_no, courier_id, user_id,
                                     company_id, cabinet_id, cell_id, size_type, weight,
                                     status, pickup_code, store_time, expire_time,
                                     recipient_name, recipient_phone)
               VALUES('SEND',%s,NULL,%s,%s,%s,%s,'MEDIUM',2.00,'SEND_WAIT_PICKUP',%s,
                      NOW(), DATE_ADD(NOW(), INTERVAL 48 HOUR),'收件人',%s)""",
            (tracking, self.user_id, self.company_id, self.cabinet_id, cell_id,
             code, "13900006666"))
        db.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell_id,))
        self.package_ids.append(pid)
        return pid

    # ---- 清理（严格按外键依赖顺序） ----
    def teardown(self):
        for pid in self.package_ids:
            for table in ("t_pay_callback_log", "t_notice", "t_exception_log",
                          "t_pickup_record", "t_device_command"):
                try:
                    if table == "t_pay_callback_log":
                        db.execute(
                            "DELETE FROM t_pay_callback_log WHERE pay_no IN "
                            "(SELECT pay_no FROM t_pay_order WHERE biz_id=%s)", (pid,))
                    else:
                        db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
                except Exception:
                    pass
            try:
                db.execute("DELETE FROM t_pay_order WHERE biz_id=%s", (pid,))
            except Exception:
                pass
            try:
                db.execute("DELETE FROM t_pack_task WHERE package_id=%s", (pid,))
            except Exception:
                pass
            try:
                db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
            except Exception:
                pass
        # 清理本次创建的推荐（任务已级联删除明细）
        try:
            db.execute(
                "DELETE FROM t_pack_recommendation WHERE description LIKE %s",
                (f"%{TAG}%",))
        except Exception:
            pass
        for cid in self.cell_ids:
            try:
                db.execute("DELETE FROM t_cell WHERE cell_id=%s", (cid,))
            except Exception:
                pass
        if self.cabinet_id:
            try:
                db.execute("DELETE FROM t_cabinet WHERE cabinet_id=%s", (self.cabinet_id,))
            except Exception:
                pass
        if self.user_id:
            try:
                db.execute("DELETE FROM t_user WHERE user_id=%s AND phone=%s",
                           (self.user_id, TEST_PHONE_USER))
            except Exception:
                pass
        if self.courier_id:
            try:
                db.execute("DELETE FROM t_courier WHERE courier_id=%s", (self.courier_id,))
            except Exception:
                pass
        if self.company_id:
            try:
                db.execute("DELETE FROM t_express_company WHERE company_id=%s",
                           (self.company_id,))
            except Exception:
                pass
        # 还原库存（材料台账测试可能改过）
        return self


def db_ready():
    try:
        db.query_one("SELECT 1")
        return True
    except Exception:
        return False
