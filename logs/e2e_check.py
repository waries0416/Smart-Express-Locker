# 一次性端到端核验脚本（不进入版本库，仅用于采集测试报告证据）
# 走 Flask test_client，不启动 HTTP 服务；跑完把产生的包裹/流水/通知/格口全部还原。
import json
import os
import sys

os.environ.setdefault("NOTIFY_WORKER", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import app as app_module  # noqa: E402
import db  # noqa: E402

app_module.app.config.update(TESTING=True)
c = app_module.app.test_client()

TEST_PHONE = "13700001234"
results = []
created = {"package_ids": [], "cell_ids": []}


def check(no, name, ok, detail=""):
    results.append((no, name, "PASS" if ok else "FAIL", detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {no} {name} {detail}")


def purge_leftovers():
    """清掉上次中断遗留的测试数据（按测试手机号定位）"""
    rows = db.query("SELECT package_id FROM t_package WHERE user_id IN "
                    "(SELECT user_id FROM t_user WHERE phone=%s)", (TEST_PHONE,))
    for r in rows:
        for t in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
            db.execute(f"DELETE FROM {t} WHERE package_id=%s", (r["package_id"],))
        db.execute("DELETE FROM t_package WHERE package_id=%s", (r["package_id"],))
    db.execute("UPDATE t_cell SET status='FREE' WHERE status='OCCUPIED' AND cell_id NOT IN "
               "(SELECT cell_id FROM t_package WHERE status IN ('STORED','EXPIRED','EXCEPTION',"
               "'SEND_WAIT_PICKUP'))")
    db.execute("DELETE FROM t_user WHERE phone=%s", (TEST_PHONE,))
    if rows:
        print(f"[*] 清理遗留测试包裹 {len(rows)} 件")


def main():
    purge_leftovers()
    # ---------- TC-K-05 存件 ----------
    before = db.query_one("SELECT COUNT(*) n FROM t_package")["n"]
    r = c.post("/api/business/store", json={
        "courier_id": 1, "user_phone": TEST_PHONE, "user_name": "测试收件人",
        "size_type": "SMALL", "weight": 1.5, "cabinet_id": 1,
    })
    ok = r.status_code in (200, 201)
    d = r.get_json() if ok else {}
    pkg = (d.get("package") or {}) if ok else {}
    cell_id = None
    if ok:
        created["package_ids"].append(pkg["package_id"])
        cell_id = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s",
                               (pkg["package_id"],))["cell_id"]
        created["cell_ids"].append(cell_id)
    check("TC-K-05", "存件成功并返回取件码/格口", ok,
          f"status={r.status_code} code={d.get('pickup_code')} cell={d.get('cell_code')}")

    after = db.query_one("SELECT COUNT(*) n FROM t_package")["n"]
    check("TC-K-05b", "包裹总数 +1", after == before + 1, f"{before} -> {after}")

    pid, code = pkg.get("package_id"), d.get("pickup_code")
    row = db.query_one("SELECT * FROM t_package WHERE package_id=%s", (pid,)) if pid else None
    check("TC-K-05c", "状态 STORED 且免费期 48 小时",
          bool(row) and row["status"] == "STORED" and
          (row["expire_time"] - row["store_time"]).total_seconds() == 48 * 3600,
          f"status={row['status'] if row else '-'} "
          f"delta={(row['expire_time'] - row['store_time']) if row else '-'}")

    cell = db.query_one("SELECT status FROM t_cell WHERE cell_id=%s", (cell_id,)) if cell_id else None
    check("TC-K-05d", "格口置为 OCCUPIED", bool(cell) and cell["status"] == "OCCUPIED",
          f"cell_status={cell['status'] if cell else '-'}")

    n = db.query_one("SELECT COUNT(*) n FROM t_notice WHERE package_id=%s", (pid,))["n"] if pid else 0
    check("TC-K-05e", "已入队通知（不阻塞主流程）", n >= 1, f"notice_count={n}")

    # ---------- 取件码校验 ----------
    r = c.post("/api/business/pickup", json={"pickup_code": "000000"})
    check("TC-K-04a", "错误取件码被拒绝", r.status_code in (400, 404), f"status={r.status_code}")

    # ---------- TC-K-04 正常取件 ----------
    r = c.post("/api/business/pickup", json={"pickup_code": code, "cabinet_id": 1})
    ok = r.status_code == 200
    pk = r.get_json().get("package", {}) if ok else {}
    check("TC-K-04", "取件码取件成功并返回格口号", ok,
          f"status={r.status_code} cell={pk.get('cell_code')}")

    row = db.query_one("SELECT status, pickup_time FROM t_package WHERE package_id=%s", (pid,))
    check("TC-K-04b", "包裹状态置 PICKED 且有取件时间",
          row["status"] == "PICKED" and row["pickup_time"] is not None, f"status={row['status']}")

    rec = db.query_one("SELECT * FROM t_pickup_record WHERE package_id=%s ORDER BY record_id DESC LIMIT 1", (pid,))
    check("TC-K-04c", "生成取件流水（方式/角色/结果）",
          bool(rec) and rec["result"] == "SUCCESS", f"method={rec['pickup_method'] if rec else '-'}")

    cell = db.query_one("SELECT status FROM t_cell WHERE cell_id=%s", (cell_id,))
    check("TC-K-04d", "格口释放为 FREE", cell["status"] == "FREE", f"cell_status={cell['status']}")

    # ---------- 重复取件 ----------
    r = c.post("/api/business/pickup", json={"pickup_code": code})
    check("TC-K-04e", "重复取件被拒绝（状态冲突）", r.status_code in (400, 409), f"status={r.status_code}")

    # ---------- 超时计费 ----------
    # 注意：chk_pkg_time 要求 expire_time > store_time，把存件时间一并前移 73 小时
    db.execute("UPDATE t_package SET status='EXPIRED', overtime_fee=1.00, overtime_fee_paid=0, "
               "store_time=DATE_SUB(NOW(), INTERVAL 73 HOUR), "
               "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR), pickup_time=NULL WHERE package_id=%s", (pid,))
    db.execute("UPDATE t_cell SET status='OCCUPIED' WHERE cell_id=%s", (cell_id,))
    r = c.post("/api/business/pickup", json={"pickup_code": code})
    body = r.get_json() or {}
    check("TC-K-03a", "超时未缴费取件返回需缴费", r.status_code in (402, 409) or body.get("error") == "NEED_PAYMENT",
          f"status={r.status_code} error={body.get('error')}")

    r = c.post("/api/business/pay-overtime", json={"package_ids": [pid]})
    ok = r.status_code == 200
    paid = db.query_one("SELECT overtime_fee_paid FROM t_package WHERE package_id=%s", (pid,))["overtime_fee_paid"]
    check("TC-K-03b", "缴费后标记已缴费", ok and paid == 1, f"paid={paid} resp={r.get_json()}")

    r = c.post("/api/business/pickup", json={"pickup_code": code})
    check("TC-K-03c", "缴费后可正常取件", r.status_code == 200, f"status={r.status_code}")

    # ---------- 权限：匿名写接口 ----------
    r = c.delete(f"/api/packages/{pid}")
    check("TC-A-01", "匿名删除包裹被拒绝", r.status_code == 401, f"status={r.status_code}")

    # ---------- 汇总 ----------
    print("\n===== 汇总 =====")
    passed = sum(1 for x in results if x[2] == "PASS")
    print(f"共 {len(results)} 项，通过 {passed} 项，失败 {len(results) - passed} 项")
    return results


def cleanup():
    """还原测试产生的数据：通知 → 流水 → 包裹 → 格口 → 测试用户"""
    for pid in created["package_ids"]:
        db.execute("DELETE FROM t_notice WHERE package_id=%s", (pid,))
        db.execute("DELETE FROM t_exception_log WHERE package_id=%s", (pid,))
        db.execute("DELETE FROM t_pickup_record WHERE package_id=%s", (pid,))
        db.execute("DELETE FROM t_device_command WHERE package_id=%s", (pid,))
        db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
    for cid in created["cell_ids"]:
        if cid:
            db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cid,))
    # 测试过程中自动建档的收件用户
    db.execute("DELETE FROM t_user WHERE phone=%s", (TEST_PHONE,))
    print("[*] 已还原测试数据")


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup()
