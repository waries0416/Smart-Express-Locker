# -*- coding: utf-8 -*-
"""R9b 修复回归：并发支付重复入账 / 并发取件双取 的修复前后验证。

与 load_test_v2.py 的关系：
    load_test_v2.py 是"压力 + 判重"的综合压测（会跑 A/B/C/D/E 全套，
    吞吐数字与并发梯度绑定）。本脚本只做**回归判定**：
    用固定并发把目标缺陷打出来，只回答一个问题 —— 不变量是否成立。

    两者并发度不同（本脚本用 10 并发、3 件包裹；load_test_v2 用 40 次/档），
    所以数字必然不同，报告里必须注明口径，不能混用。

不变量（这是"可判定"的关键，不靠肉眼）：
    D 并发支付
        · 每件包裹 TIMEOUT-RESOLVED 流水**恰好 1 条**
        · Σ 各次调用自报 paid_count == 目标包裹数（其余为幂等空转 0）
    E 并发取件
        · 成功 200 恰好 1 次
        · SUCCESS 取件流水恰好 1 条
        · 其余 9 次必须 409

数据安全：
    · 用真实接口造件（/api/business/store），不改演示数据；
    · 结束后删除本次造出的包裹及其流水（reuse load_test_v2.cleanup 的思路）。

用法：
    python quality/retest_race_fixes.py
    python quality/retest_race_fixes.py --threads 10 --packages 3 --out quality/reports
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


# ----------------------------------------------------------------------
def make_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def run_pool(n_threads, n_ops, fn):
    """n_threads 个线程，共执行 n_ops 次；用 Barrier 保证尽可能同时起跑。"""
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads, timeout=30)

    def worker(i):
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        r = fn(i)
        with lock:
            results.append(r)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t0
    return results, wall


# ----------------------------------------------------------------------
def scene_d(host, threads, n_packages):
    """D：同一批「超时未缴」包裹被 threads 个请求同时计费。"""
    import db

    s = make_session()
    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")

    targets, created = [], []
    for i in range(n_packages):
        phone = f"139{random.randint(10 ** 7, 10 ** 8 - 1)}"
        r = s.post(f"{host}/api/business/store", json={
            "courier_id": courier["courier_id"], "user_phone": phone,
            "user_name": f"复测D{i}", "size_type": "SMALL", "weight": 0.4,
        }, timeout=30)
        if r.status_code not in (200, 201):
            continue
        pid = ((r.json() or {}).get("package") or {}).get("package_id")
        if not pid:
            continue
        created.append(pid)
        db.execute(
            "UPDATE t_package SET status='EXPIRED', overtime_fee=1.00, overtime_fee_paid=0, "
            "store_time=DATE_SUB(NOW(), INTERVAL 73 HOUR), "
            "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE package_id=%s", (pid,))
        targets.append(pid)

    if not targets:
        return {"结论": "⚠️ 造不出支付场景数据"}, created

    ph = ",".join(["%s"] * len(targets))
    # 清掉旧的 TIMEOUT 流水，保证计数只反映本轮
    db.execute(f"DELETE FROM t_exception_log WHERE package_id IN ({ph}) "
               f"AND exception_type='TIMEOUT'", targets)

    codes = []

    def worker(i):
        sess = make_session()
        try:
            rr = sess.post(f"{host}/api/business/pay-overtime",
                           json={"package_ids": targets}, timeout=30)
            d = rr.json() if rr.headers.get("Content-Type", "").startswith("application/json") else {}
            return {"status": rr.status_code, "paid_count": d.get("paid_count")}
        except Exception as exc:  # noqa: BLE001
            return {"status": -1, "error": str(exc)}

    results, wall = run_pool(threads, threads, worker)
    for r in results:
        codes.append(r.get("paid_count"))

    # ---- 证据③：直查库 ----
    rows = db.query(
        f"SELECT package_id, overtime_fee_paid FROM t_package WHERE package_id IN ({ph})",
        targets)
    logs = db.query(
        f"SELECT package_id, COUNT(*) AS n FROM t_exception_log "
        f"WHERE package_id IN ({ph}) AND exception_type='TIMEOUT' "
        f"AND handle_result='RESOLVED' GROUP BY package_id", targets)
    per = {r["package_id"]: int(r["n"]) for r in logs}

    declared = sum(int(x or 0) for x in codes)
    dup = [{"package_id": pid, "条数": n} for pid, n in per.items() if n > 1]
    missing = [pid for pid in targets if per.get(pid, 0) == 0]
    unpaid = [r["package_id"] for r in rows if int(r["overtime_fee_paid"]) != 1]

    ok = (not dup) and (not missing) and (not unpaid) and declared == len(targets)
    v = {
        "场景": f"D 并发支付（{threads} 并发 × {len(targets)} 件）",
        "并发度": threads,
        "目标包裹": targets,
        "墙钟(秒)": round(wall, 3),
        "各次调用paid_count": codes,
        "证据①-Σ自报paid_count": declared,
        "证据②-每件TIMEOUT-RESOLVED流水数": [{"package_id": p, "条数": per.get(p, 0)} for p in targets],
        "证据②-实际入账总条数": sum(per.values()),
        "证据③-重复入账": dup,
        "证据③-漏入账": missing,
        "证据③-未置已缴": unpaid,
        "不变量-每件恰好1条": not dup and not missing,
        "不变量-Σpaid_count==包裹数": declared == len(targets),
        "结论": ("✅ 已修复：每件恰好 1 条，Σpaid_count == 包裹数" if ok
                 else f"❌ 仍有缺陷：重复={dup} 漏={missing} 未缴={unpaid} Σ={declared}/{len(targets)}"),
    }
    return v, created


def scene_e(host, threads):
    """E：同一取件码被 threads 个请求同时取件。"""
    import db

    s = make_session()
    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    phone = f"135{random.randint(10 ** 7, 10 ** 8 - 1)}"
    r = s.post(f"{host}/api/business/store", json={
        "courier_id": courier["courier_id"], "user_phone": phone,
        "user_name": "复测E", "size_type": "SMALL", "weight": 0.3,
    }, timeout=30)
    if r.status_code not in (200, 201):
        return {"结论": "⚠️ 造件失败"}, []
    body = r.json() or {}
    code = body.get("pickup_code")
    pid = (body.get("package") or {}).get("package_id")
    cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))

    ok200, codes = [], []

    def worker(i):
        sess = make_session()
        try:
            rr = sess.post(f"{host}/api/business/pickup",
                           json={"pickup_code": code}, timeout=30)
            return {"status": rr.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"status": -1, "error": str(exc)}

    results, wall = run_pool(threads, threads, worker)
    for x in results:
        codes.append(x.get("status"))
        if x.get("status") == 200:
            ok200.append(200)

    final = db.query_one("SELECT status FROM t_package WHERE package_id=%s", (pid,))
    picks = db.query("SELECT COUNT(*) AS n FROM t_pickup_record "
                     "WHERE package_id=%s AND result='SUCCESS'", (pid,))
    n_success = int(picks[0]["n"])
    n_200 = len(ok200)
    n_409 = sum(1 for c in codes if c == 409)

    ok = (n_200 == 1 and n_success == 1 and n_409 == threads - 1
          and final["status"] == "PICKED")
    v = {
        "场景": f"E 并发取件（{threads} 并发，同码）",
        "并发度": threads,
        "取件码": code,
        "墙钟(秒)": round(wall, 3),
        "证据①-返回200次数": n_200,
        "证据①-返回409次数": n_409,
        "证据②-SUCCESS取件流水条数": n_success,
        "证据③-包裹最终状态": final["status"] if final else "?",
        "不变量-恰好1次200": n_200 == 1,
        "不变量-恰好1条SUCCESS流水": n_success == 1,
        "不变量-其余均409": n_409 == threads - 1,
        "结论": (f"✅ 已修复：1×200 + {threads-1}×409 + 1 条 SUCCESS" if ok
                 else f"❌ 仍有缺陷：200×{n_200} / 409×{n_409} / 流水{n_success}"),
    }
    return v, [{"package_id": pid, "cell_id": cell["cell_id"] if cell else None}]


# ----------------------------------------------------------------------
def cleanup(items):
    """只删本次复测造的包裹与流水，绝不动演示数据。"""
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
        for sql, args in (
            ("DELETE FROM t_pack_task WHERE package_id=%s", (pid,)),
            ("DELETE FROM t_pay_order WHERE biz_type='OVERTIME' AND biz_id=%s", (pid,)),
            ("DELETE FROM t_package WHERE package_id=%s", (pid,)),
        ):
            try:
                db.execute(sql, args)
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
    ap = argparse.ArgumentParser(description="R9b 修复回归：D/E 并发判重")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--threads", type=int, default=10)
    ap.add_argument("--packages", type=int, default=3, help="D 场景目标包裹数")
    ap.add_argument("--out", default=os.path.join(ROOT, "quality", "reports"))
    args = ap.parse_args()

    host = args.host.rstrip("/")
    print("=" * 78)
    print(" R9b 修复回归 · 并发判重不变量验证")
    print("=" * 78)
    try:
        h = requests.get(f"{host}/api/health", timeout=10)
        print(f"  健康检查 : {h.status_code} {h.text[:60]}")
        if h.status_code != 200:
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 服务不可用: {exc}")
        return 2
    print(f"  并发度   : {args.threads}  ·  D 目标包裹数: {args.packages}")

    payload = {"生成时间": datetime.now().astimezone().isoformat(timespec="seconds"),
               "目标服务": host, "并发度": args.threads}

    to_clean = []
    print("\n--- D 并发支付（不变量：每件恰好 1 条 + Σpaid_count == 包裹数）---")
    dv, dcreated = scene_d(host, args.threads, args.packages)
    to_clean.extend({"package_id": p} for p in dcreated)
    print(f"  {dv.get('结论')}")
    if "证据①-Σ自报paid_count" in dv:
        print(f"    Σpaid_count={dv['证据①-Σ自报paid_count']} / 包裹数={len(dv['目标包裹'])}")
        print(f"    每件流水数={dv['证据②-每件TIMEOUT-RESOLVED流水数']}")
    payload["D_并发支付"] = dv

    print("\n--- E 并发取件（不变量：1×200 + 9×409 + 1 条 SUCCESS）---")
    ev, ecreated = scene_e(host, args.threads)
    to_clean.extend(ecreated)
    print(f"  {ev.get('结论')}")
    if "证据①-返回200次数" in ev:
        print(f"    200×{ev['证据①-返回200次数']} / 409×{ev['证据①-返回409次数']} "
              f"/ SUCCESS 流水 {ev['证据②-SUCCESS取件流水条数']} 条"
              f" / 最终状态 {ev['证据③-包裹最终状态']}")
    payload["E_并发取件"] = ev

    cleanup(to_clean)
    print(f"\n  已清理本次复测产生的 {len(to_clean)} 件包裹")

    os.makedirs(args.out, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    jpath = os.path.join(args.out, f"retest_race_{ts}.json")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"\n  原始结果 JSON : {jpath}")

    all_ok = (dv.get("不变量-每件恰好1条") and dv.get("不变量-Σpaid_count==包裹数")
              and ev.get("不变量-恰好1次200") and ev.get("不变量-恰好1条SUCCESS流水")
              and ev.get("不变量-其余均409"))
    print("\n" + "=" * 78)
    print(" 总判定： " + ("✅ 两项缺陷均已修复" if all_ok else "❌ 仍有不变量不成立，详见上"))
    print("=" * 78)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
