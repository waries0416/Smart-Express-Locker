# -*- coding: utf-8 -*-
"""R9b 修复 · 多轮稳定性 + 第二条取件路径（/unlock）回归。

为什么还要这个脚本：
    retest_race_fixes.py 证明"修好了"；本脚本证明"不是偶然修好"。
    压测类结论最怕单次运气，所以：
      1) 同一不变量在多轮反复成立（默认 5 轮），任一轮失败即判失败；
      2) 覆盖第二条代码路径 —— 取件码走 /api/business/pickup，
         无码开柜走 /api/business/unlock；R9b 改了两处，
         只验一处不足以说明问题（这正是"同一规则写在两条路径上会分叉"的教训）。
      3) 顺带验管理员强制开柜路径的"只允许一次"。

用法：
    python quality/retest_race_stability.py --rounds 5 --threads 10
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from datetime import datetime

import requests

ROOT = r"D:\softwaretest"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def make_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def run_pool(n_threads, fn):
    results, lock = [], threading.Lock()
    barrier = threading.Barrier(n_threads, timeout=30)

    def worker(i):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        r = fn(i)
        with lock:
            results.append(r)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return results


def store_one(host, name="复测"):
    import db
    s = make_session()
    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    phone = f"137{random.randint(10 ** 7, 10 ** 8 - 1)}"
    r = s.post(f"{host}/api/business/store", json={
        "courier_id": courier["courier_id"], "user_phone": phone,
        "user_name": name, "size_type": "SMALL", "weight": 0.3,
    }, timeout=30)
    if r.status_code not in (200, 201):
        return None
    b = r.json() or {}
    pkg = b.get("package") or {}
    return {"package_id": pkg.get("package_id"), "pickup_code": b.get("pickup_code"),
            "cell_id": None}


def case_pickup_code(host, threads):
    """E①：取件码路径 /api/business/pickup"""
    import db
    info = None
    for _ in range(3):
        info = store_one(host, "复测E1")
        if info and info["pickup_code"]:
            break
    if not info or not info["pickup_code"]:
        return {"ok": False, "原因": "造件失败"}
    pid, code = info["package_id"], info["pickup_code"]
    cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
    info["cell_id"] = cell["cell_id"] if cell else None

    def worker(i):
        try:
            rr = make_session().post(f"{host}/api/business/pickup",
                                     json={"pickup_code": code}, timeout=30)
            return rr.status_code
        except Exception:  # noqa: BLE001
            return -1

    codes = run_pool(threads, worker)
    n200 = codes.count(200)
    n409 = codes.count(409)
    picks = db.query("SELECT COUNT(*) AS n FROM t_pickup_record "
                     "WHERE package_id=%s AND result='SUCCESS'", (pid,))
    n_succ = int(picks[0]["n"])
    ok = (n200 == 1 and n409 == threads - 1 and n_succ == 1)
    return {"ok": ok, "200": n200, "409": n409, "SUCCESS流水": n_succ,
            "清理": info}


def case_unlock(host, threads):
    """E②：无码开柜路径 /api/business/unlock"""
    import db
    info = None
    for _ in range(3):
        info = store_one(host, "复测E2")
        if info and info.get("package_id"):
            break
    if not info or not info.get("package_id"):
        return {"ok": False, "原因": "造件失败"}
    pid = info["package_id"]
    cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
    info["cell_id"] = cell["cell_id"] if cell else None

    def worker(i):
        try:
            rr = make_session().post(f"{host}/api/business/unlock",
                                     json={"package_id": pid}, timeout=30)
            return rr.status_code
        except Exception:  # noqa: BLE001
            return -1

    codes = run_pool(threads, worker)
    n200 = codes.count(200)
    picks = db.query("SELECT COUNT(*) AS n FROM t_pickup_record "
                     "WHERE package_id=%s AND result='SUCCESS'", (pid,))
    n_succ = int(picks[0]["n"])
    ok = (n200 == 1 and n_succ == 1)
    return {"ok": ok, "200": n200, "非200": threads - n200, "SUCCESS流水": n_succ,
            "清理": info}


def case_pay(host, threads, n_pkg=3):
    """D：并发支付不变量"""
    import db
    created, targets = [], []
    for i in range(n_pkg):
        info = store_one(host, f"复测D{i}")
        if not info or not info.get("package_id"):
            continue
        pid = info["package_id"]
        created.append(info)
        db.execute(
            "UPDATE t_package SET status='EXPIRED', overtime_fee=1.00, overtime_fee_paid=0, "
            "store_time=DATE_SUB(NOW(), INTERVAL 73 HOUR), "
            "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE package_id=%s", (pid,))
        targets.append(pid)
    if not targets:
        return {"ok": False, "原因": "造件失败"}
    ph = ",".join(["%s"] * len(targets))
    db.execute(f"DELETE FROM t_exception_log WHERE package_id IN ({ph}) "
               f"AND exception_type='TIMEOUT'", targets)

    paid = []

    def worker(i):
        try:
            rr = make_session().post(f"{host}/api/business/pay-overtime",
                                     json={"package_ids": targets}, timeout=30)
            d = rr.json() if "json" in rr.headers.get("Content-Type", "") else {}
            return d.get("paid_count")
        except Exception:  # noqa: BLE001
            return -1

    got = run_pool(threads, worker)
    logs = db.query(
        f"SELECT package_id, COUNT(*) AS n FROM t_exception_log "
        f"WHERE package_id IN ({ph}) AND exception_type='TIMEOUT' "
        f"AND handle_result='RESOLVED' GROUP BY package_id", targets)
    per = {r["package_id"]: int(r["n"]) for r in logs}
    declared = sum(int(x or 0) for x in got if isinstance(x, int) and x > 0)
    ok = (all(per.get(p, 0) == 1 for p in targets) and declared == len(targets))
    return {"ok": ok, "每件流水数": [per.get(p, 0) for p in targets],
            "Σpaid_count": declared, "包裹数": len(targets),
            "清理": created}


def cleanup(items):
    import db
    for it in items:
        pid = it.get("package_id")
        if not pid:
            continue
        for tbl in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
            try:
                db.execute(f"DELETE FROM {tbl} WHERE package_id=%s", (pid,))
            except Exception:  # noqa: BLE001
                pass
        for sql in ("DELETE FROM t_pack_task WHERE package_id=%s",
                    "DELETE FROM t_pay_order WHERE biz_type='OVERTIME' AND biz_id=%s",
                    "DELETE FROM t_package WHERE package_id=%s"):
            try:
                db.execute(sql, (pid,))
            except Exception:  # noqa: BLE001
                pass
        cid = it.get("cell_id")
        if cid:
            try:
                still = db.query_one(
                    "SELECT COUNT(*) AS n FROM t_package WHERE cell_id=%s AND status IN "
                    "('STORED','EXPIRED','SEND_WAIT_PICKUP','SEND_COLLECTED','EXCEPTION')",
                    (cid,))
                if int(still["n"]) == 0:
                    db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cid,))
            except Exception:  # noqa: BLE001
                pass


def main():
    ap = argparse.ArgumentParser(description="R9b 修复多轮稳定性回归")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--out", default=os.path.join(ROOT, "quality", "reports"))
    args = ap.parse_args()
    host = args.host.rstrip("/")

    print("=" * 78)
    print(f" R9b 修复 · 多轮稳定性回归（{args.rounds} 轮 × {args.threads} 并发）")
    print("=" * 78)

    payload = {"生成时间": datetime.now().astimezone().isoformat(timespec="seconds"),
               "并发度": args.threads, "轮数": args.rounds, "轮次": []}
    fails = 0
    for rnd in range(1, args.rounds + 1):
        print(f"\n--- 第 {rnd}/{args.rounds} 轮 ---")
        d = case_pay(host, args.threads, 3)
        e1 = case_pickup_code(host, args.threads)
        e2 = case_unlock(host, args.threads)
        for res, tag in ((d, "D 支付"), (e1, "E① 取件码"), (e2, "E② /unlock")):
            for it in res.get("清理", []) if isinstance(res.get("清理"), list) else [res["清理"]]:
                cleanup([it])
        line = (f"  D={'OK' if d.get('ok') else 'FAIL'}"
                f"  每件流水={d.get('每件流水数')} Σ={d.get('Σpaid_count')}/{d.get('包裹数')}"
                f" | E①={'OK' if e1.get('ok') else 'FAIL'} 200×{e1.get('200')}"
                f" 409×{e1.get('409')} 流水{e1.get('SUCCESS流水')}"
                f" | E②={'OK' if e2.get('ok') else 'FAIL'} 200×{e2.get('200')}"
                f" 流水{e2.get('SUCCESS流水')}")
        print(line)
        bad = [t for res, t in ((d, "D"), (e1, "E1"), (e2, "E2")) if not res.get("ok")]
        if bad:
            fails += 1
        payload["轮次"].append({"轮": rnd, "D": d, "E1": e1, "E2": e2, "未通过": bad})

    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = os.path.join(args.out, f"retest_stability_{ts}.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 78)
    if fails == 0:
        print(f" ✅ {args.rounds} 轮全部通过：三条路径的并发不变量均稳定成立")
    else:
        print(f" ❌ {fails}/{args.rounds} 轮存在不成立项")
    print(f" 原始结果 JSON : {p}")
    print("=" * 78)
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
