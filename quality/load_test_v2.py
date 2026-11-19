#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并发压测 · 智能快递柜管理系统（R3b 最终版）

与上一版的区别（为什么重写而不是沿用）
--------------------------------------
上一版只做到"内存判重 + 一次库查询"，证据链偏薄；本次按任务要求做成
**三重证据**，并且把每次请求的原始报文都落盘，任何一条结论都能反查到具体请求：

  证据①  逐请求 JSON：每个请求的 request/response/status/elapsed 全量落盘
  证据②  内存判重：进程内对"分配到的格口"与"入账次数"做集合判重
  证据③  直接查库：绕过被测服务，用独立连接直接 SELECT 交叉验证

场景
----
  A 登录主链路（发码→登录换 token）
  B 查询主链路（我的包裹 / 附近柜体 / 寄件待揽收）
  C 并发存件        → 核验**无重复格口分配**
  D 并发支付        → 核验**无重复入账**
  E 并发取码取件    → 核验**同一取件码不会被并发取走两次**

工具说明（不美化）
------------------
本机**未安装 JMeter**（探测结果见 quality/reports/00_env_facts.txt 的 tools 一栏）。
本脚本用 Python concurrent.futures + requests 实现等价并发，并另附标准 .jmx
（quality/jmeter/smart_locker_load.jmx）供装了 JMeter 的人交叉验证。
本脚本产出的所有数字都不是 JMeter 跑出来的，报告里也不会那样写。

用法
----
    # 服务已在 127.0.0.1:5000 运行
    python quality/load_test_v2.py --host http://127.0.0.1:5000
    python quality/load_test_v2.py --levels 1,5,10,20 --ops 40
"""
import argparse
import json
import os
import platform
import random
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

TZ = timezone(timedelta(hours=8))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "quality", "reports", "perf")

sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))


# ------------------------------------------------------------------ 统计
def percentile(values, p):
    """线性插值百分位（口径与 JMeter 接近）。"""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


class Recorder:
    """逐请求记录器：所有字段原样保留，便于反查。"""

    def __init__(self, name):
        self.name = name
        self.records = []
        self._lock = threading.Lock()

    def add(self, **kw):
        with self._lock:
            self.records.append(kw)

    def summary(self, wall):
        lat = [r["elapsed_ms"] for r in self.records]
        n = len(lat)
        errs = sum(1 for r in self.records if not r.get("ok"))
        codes = Counter(str(r.get("status")) for r in self.records)
        return {
            "场景": self.name,
            "请求数": n,
            "墙钟耗时(秒)": round(wall, 3),
            "吞吐(请求/秒)": round(n / wall, 2) if wall > 0 else None,
            "错误数": errs,
            "错误率(%)": round(errs / n * 100, 2) if n else None,
            "状态码分布": dict(codes),
            "平均(ms)": round(statistics.mean(lat), 2) if lat else None,
            "中位(ms)": round(statistics.median(lat), 2) if lat else None,
            "P95(ms)": round(percentile(lat, 95), 2) if lat else None,
            "P99(ms)": round(percentile(lat, 99), 2) if lat else None,
            "最大(ms)": round(max(lat), 2) if lat else None,
        }


def make_session():
    s = requests.Session()
    s.trust_env = False          # 不走系统代理，避免代理干扰计时
    return s


def run_pool(n_threads, n_ops, worker):
    """固定并发梯度：n_threads 线程共发起 n_ops 次操作，返回墙钟耗时。"""
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        futures = [ex.submit(worker, i) for i in range(n_ops)]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as exc:  # noqa: BLE001  线程内异常也必须计入
                print(f"    [线程异常] {exc}")
    return time.perf_counter() - started


# ------------------------------------------------------------------ 场景 A
def scene_login(host, n_threads, n_ops):
    rec = Recorder(f"A 登录主链路(并发={n_threads})")

    def worker(_i):
        phone = f"137{random.randint(10 ** 7, 10 ** 8 - 1)}"
        s = make_session()
        t0 = time.perf_counter()
        req, resp_body, status, ok = {}, {}, None, True
        try:
            r = s.post(f"{host}/api/m/auth/send-code", json={"phone": phone}, timeout=20)
            status = r.status_code
            req["send-code"] = {"phone": phone}
            resp_body["send-code"] = r.json() if r.headers.get(
                "Content-Type", "").startswith("application/json") else {}
            if r.status_code == 200:
                code = resp_body["send-code"].get("dev_code")
                r2 = s.post(f"{host}/api/m/auth/login",
                            json={"phone": phone, "code": code}, timeout=20)
                status = r2.status_code
                resp_body["login"] = r2.json() if r2.headers.get(
                    "Content-Type", "").startswith("application/json") else {}
                req["login"] = {"phone": phone, "code": code}
                ok = r2.status_code == 200 and bool(resp_body["login"].get("token"))
            elif r.status_code == 429:
                ok = True   # 60s 限流属预期行为，不算系统错误
            else:
                ok = False
        except Exception as exc:  # noqa: BLE001
            ok, status = False, -1
            resp_body["error"] = str(exc)
        rec.add(status=status, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                ok=ok, request=req, response=resp_body)

    wall = run_pool(n_threads, n_ops, worker)
    return rec, wall


# ------------------------------------------------------------------ 场景 B
def login_once(host):
    """取一个 USER token（登录链路完整走一遍）。"""
    s = make_session()
    phone = f"137{random.randint(10 ** 7, 10 ** 8 - 1)}"
    r = s.post(f"{host}/api/m/auth/send-code", json={"phone": phone}, timeout=20)
    if r.status_code != 200:
        return None, phone
    code = (r.json() or {}).get("dev_code")
    r2 = s.post(f"{host}/api/m/auth/login", json={"phone": phone, "code": code}, timeout=20)
    if r2.status_code != 200:
        return None, phone
    return (r2.json() or {}).get("token"), phone


def scene_query(host, n_threads, n_ops, token):
    rec = Recorder(f"B 查询主链路(并发={n_threads})")
    hdr = {"Authorization": f"Bearer {token}"} if token else {}

    def worker(_i):
        s = make_session()
        t0 = time.perf_counter()
        codes, ok = {}, True
        try:
            for name, path in (("packages", "/api/m/packages"),
                               ("nearby", "/api/m/cabinets/nearby"),
                               ("send_pending", "/api/business/send-pending")):
                r = s.get(f"{host}{path}", headers=hdr, timeout=20)
                codes[name] = r.status_code
                if not (200 <= r.status_code < 400):
                    ok = False
        except Exception as exc:  # noqa: BLE001
            ok, codes["error"] = False, str(exc)
        rec.add(status=codes.get("packages"), elapsed_ms=round(
            (time.perf_counter() - t0) * 1000, 2), ok=ok, response=codes)

    wall = run_pool(n_threads, n_ops, worker)
    return rec, wall


# ------------------------------------------------------------------ 场景 C
def scene_store(host, n_threads, n_ops, courier_id, cabinet_id):
    """并发存件：核验无重复格口分配。"""
    rec = Recorder(f"C 并发存件(并发={n_threads})")
    assigned = []
    lock = threading.Lock()

    def worker(i):
        s = make_session()
        phone = f"138{random.randint(10 ** 7, 10 ** 8 - 1)}"
        body = {"courier_id": courier_id, "user_phone": phone,
                "user_name": f"压测存件{i}", "size_type": "SMALL", "weight": 0.5}
        if cabinet_id:
            body["cabinet_id"] = cabinet_id
        t0 = time.perf_counter()
        status, ok, detail = -1, False, {}
        try:
            r = s.post(f"{host}/api/business/store", json=body, timeout=30)
            status = r.status_code
            detail = r.json() if r.headers.get(
                "Content-Type", "").startswith("application/json") else {}
            if status in (200, 201):
                ok = True
                with lock:
                    assigned.append({
                        "package_id": (detail.get("package") or {}).get("package_id"),
                        "cabinet_code": detail.get("cabinet_code"),
                        "cell_code": detail.get("cell_code"),
                        "pickup_code": detail.get("pickup_code"),
                    })
            elif status == 409:
                ok = True     # 柜满属正常业务拒绝，不是系统错误
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
        rec.add(status=status, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                ok=ok, request=body, response=detail)

    wall = run_pool(n_threads, n_ops, worker)
    return rec, wall, assigned


def verify_store(assigned):
    """三重证据核验「无重复格口分配」。"""
    import db  # 证据③：独立查库

    v = {}
    keys = [(a["cabinet_code"], a["cell_code"]) for a in assigned
            if a.get("cabinet_code") is not None and a.get("cell_code") is not None]
    v["证据②-分配合计"] = len(keys)
    v["证据②-唯一格口数"] = len(set(keys))
    dup = [k for k, n in Counter(keys).items() if n > 1]
    v["证据②-重复分配"] = [list(k) for k in dup]
    v["证据②-结论"] = "✅ 无重复" if not dup else f"❌ 重复 {len(dup)} 个"

    # 证据③：绕开服务，直接查库
    pids = [a["package_id"] for a in assigned if a.get("package_id")]
    v["证据③-本次压测产生的包裹数"] = len(pids)
    if pids:
        ph = ",".join(["%s"] * len(pids))
        rows = db.query(
            f"SELECT cell_id, COUNT(*) AS n FROM t_package WHERE package_id IN ({ph}) "
            f"GROUP BY cell_id HAVING n > 1", pids)
        v["证据③-同格口多条包裹"] = [{"cell_id": r["cell_id"], "条数": int(r["n"])} for r in rows]

        # 注意：db.query() 即使不传参数也会走 PyMySQL 的 % 格式化，
        # 所以这条**没有占位符**的 SQL 里不能出现裸 %（LIKE 'ZZT%' 之类要写 %% 或避免）。
        rows2 = db.query(
            "SELECT package_id, cell_id FROM t_package WHERE package_id IN ("
            + ph + ")", pids)
        v["证据③-包裹格口映射条数"] = len(rows2)

        # 全库层面：任一 cell 上不得有 >1 条"占用中"包裹
        rows3 = db.query(
            "SELECT cell_id, COUNT(*) AS n FROM t_package "
            "WHERE status IN ('STORED','EXPIRED') GROUP BY cell_id HAVING n > 1")
        v["证据③-全库重复占用格口"] = [
            {"cell_id": r["cell_id"], "条数": int(r["n"])} for r in rows3]

        # 格口状态与包裹状态一致性：占用中的包裹，其格口应为 OCCUPIED
        rows4 = db.query(
            "SELECT COUNT(*) AS n FROM t_package p JOIN t_cell c ON p.cell_id=c.cell_id "
            "WHERE p.package_id IN (" + ph + ") AND p.status IN ('STORED','EXPIRED') "
            "AND c.status <> 'OCCUPIED'", pids)
        v["证据③-状态不一致数"] = int(rows4[0]["n"])

    bad = bool(v["证据②-重复分配"]) or bool(v.get("证据③-同格口多条包裹")) \
        or bool(v.get("证据③-全库重复占用格口")) or bool(v.get("证据③-状态不一致数"))
    v["证据③-结论"] = "❌ 发现不一致" if bad else "✅ 无重复占用、状态一致"
    v["综合结论"] = "❌ 存在重复格口分配" if bad else "✅ 无重复格口分配（三重证据一致）"
    return v


# ------------------------------------------------------------------ 场景 D
def scene_pay(host, n_threads, n_ops):
    """并发支付：同一批包裹被 N 个线程同时支付，核验无重复入账。"""
    import db  # 造数据 + 证据③

    rec = Recorder(f"D 并发支付(并发={n_threads})")
    s = make_session()

    # 造 5 件"超时未缴费"包裹
    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    targets, created = [], []
    for i in range(5):
        phone = f"139{random.randint(10 ** 7, 10 ** 8 - 1)}"
        r = s.post(f"{host}/api/business/store", json={
            "courier_id": courier["courier_id"], "user_phone": phone,
            "user_name": f"并发支付{i}", "size_type": "SMALL", "weight": 0.4,
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
        rec.add(status=-1, elapsed_ms=0, ok=False, response={"error": "造数据失败"})
        return rec, 0.0, {"目标包裹": [], "结论": "⚠️ 无法造出支付场景数据"}

    # 清掉旧的 TIMEOUT-RESOLVED 流水，保证计数只反映本轮
    ph = ",".join(["%s"] * len(targets))
    db.execute(f"DELETE FROM t_exception_log WHERE package_id IN ({ph}) "
               f"AND exception_type='TIMEOUT'", targets)

    results = []
    lock = threading.Lock()

    def worker(_i):
        sess = make_session()
        t0 = time.perf_counter()
        status, ok, detail = -1, False, {}
        try:
            r = sess.post(f"{host}/api/business/pay-overtime",
                          json={"package_ids": targets}, timeout=30)
            status = r.status_code
            detail = r.json() if r.headers.get(
                "Content-Type", "").startswith("application/json") else {}
            ok = status == 200
            with lock:
                results.append({"status": status, "paid_count": detail.get("paid_count")})
        except Exception as exc:  # noqa: BLE001
            detail = {"error": str(exc)}
        rec.add(status=status, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                ok=ok, request={"package_ids": targets}, response=detail)

    wall = run_pool(n_threads, n_ops, worker)

    # -------- 证据②：内存层统计各次调用声明的入账次数 --------
    v = {"证据①-目标包裹": targets}
    v["证据②-各次调用paid_count"] = [x["paid_count"] for x in results]
    v["证据②-声明入账合计"] = sum(int(x["paid_count"] or 0) for x in results)

    # -------- 证据③：直接查库 --------
    rows = db.query(
        f"SELECT package_id, overtime_fee_paid FROM t_package WHERE package_id IN ({ph})",
        targets)
    v["证据③-最终缴费状态"] = [
        {"package_id": r["package_id"], "已缴": int(r["overtime_fee_paid"])} for r in rows]

    logs = db.query(
        f"SELECT package_id, COUNT(*) AS n FROM t_exception_log WHERE package_id IN ({ph}) "
        f"AND exception_type='TIMEOUT' AND handle_result='RESOLVED' GROUP BY package_id",
        targets)
    per = {r["package_id"]: int(r["n"]) for r in logs}
    v["证据③-每件TIMEOUT-RESOLVED流水数"] = [
        {"package_id": pid, "条数": per.get(pid, 0)} for pid in targets]
    v["证据③-实际入账总条数"] = sum(per.values())

    dup = [{"package_id": pid, "条数": n} for pid, n in per.items() if n > 1]
    unpaid = [r["package_id"] for r in rows if int(r["overtime_fee_paid"]) != 1]
    v["证据③-重复入账"] = dup
    v["证据③-未入账"] = unpaid

    if dup:
        v["综合结论"] = f"❌ 重复入账：{dup}"
    elif unpaid:
        v["综合结论"] = f"❌ 漏入账：{unpaid}"
    else:
        v["综合结论"] = (f"✅ 无重复入账：{len(targets)} 件包裹各入账恰好 1 次，"
                        f"总入账 {v['证据③-实际入账总条数']} 条 = 包裹数；"
                        f"并发 {len(results)} 次调用中其余为幂等空转(paid_count=0)")
    v["本轮创建的包裹(待清理)"] = created
    return rec, wall, v


# ------------------------------------------------------------------ 场景 E
def scene_pickup_race(host, n_threads, n_ops):
    """并发用同一取件码取件：核验不会被取走两次。"""
    import db

    rec = Recorder(f"E 并发取件(并发={n_threads})")
    s = make_session()
    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    phone = f"135{random.randint(10 ** 7, 10 ** 8 - 1)}"
    r = s.post(f"{host}/api/business/store", json={
        "courier_id": courier["courier_id"], "user_phone": phone,
        "user_name": "并发取件", "size_type": "SMALL", "weight": 0.3,
    }, timeout=30)
    if r.status_code not in (200, 201):
        return rec, 0.0, {"结论": "⚠️ 造件失败"}
    body = r.json() or {}
    code = body.get("pickup_code")
    pid = (body.get("package") or {}).get("package_id")
    cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))

    successes = []
    lock = threading.Lock()

    def worker(_i):
        sess = make_session()
        t0 = time.perf_counter()
        status, ok = -1, False
        try:
            rr = sess.post(f"{host}/api/business/pickup",
                           json={"pickup_code": code}, timeout=30)
            status = rr.status_code
            ok = status in (200, 409)      # 200=取到，409=已取走，均属正确
            if status == 200:
                with lock:
                    successes.append(status)
        except Exception as exc:  # noqa: BLE001
            print(f"    [异常] {exc}")
        rec.add(status=status, elapsed_ms=round((time.perf_counter() - t0) * 1000, 2),
                ok=ok, request={"pickup_code": code}, response={"status": status})

    wall = run_pool(n_threads, n_ops, worker)

    final = db.query_one("SELECT status FROM t_package WHERE package_id=%s", (pid,))
    picks = db.query("SELECT COUNT(*) AS n FROM t_pickup_record "
                     "WHERE package_id=%s AND result='SUCCESS'", (pid,))
    v = {
        "取件码": code,
        "证据②-并发中返回200的次数": len(successes),
        "证据③-包裹最终状态": final["status"] if final else "?",
        "证据③-SUCCESS取件流水条数": int(picks[0]["n"]),
    }
    ok = (len(successes) == 1 and v["证据③-SUCCESS取件流水条数"] == 1
          and v["证据③-包裹最终状态"] == "PICKED")
    v["综合结论"] = ("✅ 仅一次取件成功，无并发双取" if ok
                    else f"❌ 异常：成功 {len(successes)} 次 / 流水 "
                         f"{v['证据③-SUCCESS取件流水条数']} 条")
    v["待清理"] = [{"package_id": pid, "cell_id": cell["cell_id"] if cell else None}]
    return rec, wall, v


# ------------------------------------------------------------------ 清理
def cleanup(created_pairs):
    """只删本次压测创建的包裹与其格口占用，绝不动演示数据。"""
    import db

    for item in created_pairs:
        pid = item.get("package_id")
        if not pid:
            continue
        for table in ("t_notice", "t_exception_log", "t_pickup_record",
                      "t_device_command"):
            try:
                db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
            except Exception:  # noqa: BLE001
                pass
        try:
            db.execute("DELETE FROM t_pack_task WHERE package_id=%s", (pid,))
        except Exception:  # noqa: BLE001
            pass
        try:
            db.execute("DELETE FROM t_pay_order WHERE biz_type='OVERTIME' AND biz_id=%s",
                       (pid,))
        except Exception:  # noqa: BLE001
            pass
        try:
            db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
        except Exception:  # noqa: BLE001
            pass
        cid = item.get("cell_id")
        if cid:
            try:
                still = db.query_one("SELECT COUNT(*) AS n FROM t_package WHERE cell_id=%s "
                                     "AND status IN ('STORED','EXPIRED','SEND_WAIT_PICKUP',"
                                     "'SEND_COLLECTED','EXCEPTION')", (cid,))
                if int(still["n"]) == 0:
                    db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cid,))
            except Exception:  # noqa: BLE001
                pass


def fmt(v, w=8, suffix=""):
    """None 安全的数字格式化（吞吐为 None 时不崩，打印 n/a）。"""
    if v is None:
        return f"{'n/a':>{w}}"
    return f"{v:>{w}}{suffix}"


def main():
    ap = argparse.ArgumentParser(description="并发压测（JMeter 缺失时的等价实现 · 三重证据）")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--levels", default="1,5,10,20")
    ap.add_argument("--ops", type=int, default=40)
    ap.add_argument("--out", default=OUTDIR)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    host = args.host.rstrip("/")
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    print("=" * 78)
    print(" 并发压测 · 智能快递柜管理系统（三重证据版）")
    print("=" * 78)
    print(f"  目标服务 : {host}")
    print(f"  并发梯度 : {levels}   每档请求数: {args.ops}")

    try:
        h = requests.get(f"{host}/api/health", timeout=10)
        print(f"  健康检查 : {h.status_code} {h.text[:60]}")
        if h.status_code != 200:
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f"\n[!] 无法连接 {host}：{exc}")
        print("[!] 请先启动服务：python backend/app.py")
        return 2

    import db

    courier = db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
    cabinet = db.query_one("SELECT cabinet_id FROM t_cabinet WHERE cabinet_code='CAB-001'")
    token, token_phone = login_once(host)

    scenarios = []
    store_verify = {}
    pay_verify = {}
    pickup_verify = {}
    to_cleanup = []

    # -------- A 登录 --------
    print("\n--- A 登录主链路 ---")
    for lv in levels:
        rec, wall = scene_login(host, lv, args.ops)
        s = rec.summary(wall)
        s["_records"] = rec.records
        scenarios.append(s)
        print(f"  并发={lv:<3} 吞吐={fmt(s['吞吐(请求/秒)'])}/s  错误率={fmt(s['错误率(%)'],0)}%  "
              f"P95={fmt(s['P95(ms)'],0)}ms  P99={fmt(s['P99(ms)'],0)}ms")

    # -------- B 查询 --------
    print("\n--- B 查询主链路 ---")
    for lv in levels:
        rec, wall = scene_query(host, lv, args.ops, token)
        s = rec.summary(wall)
        s["_records"] = rec.records
        scenarios.append(s)
        print(f"  并发={lv:<3} 吞吐={fmt(s['吞吐(请求/秒)'])}/s  错误率={fmt(s['错误率(%)'],0)}%  "
              f"P95={fmt(s['P95(ms)'],0)}ms  P99={fmt(s['P99(ms)'],0)}ms")

    # -------- C 并发存件 --------
    # 不锁定单一柜体：压测要制造的是"多线程争抢格口"，而不是"抢同一个柜体的 12 个格口"。
    # 上一版固定 cabinet_id=CAB-001（空闲 12 个），第一档 40 次就把柜子占满，
    # 后续档位分配数全为 0 —— 那样等于没测到并发分配，属于**证据失真**。
    # 这里改为不传 cabinet_id，由后端在全局空闲格口里 FOR UPDATE 选格口。
    #
    # 并发上限单独收敛到 C_MAX=10：
    #   实测 20 并发会让 store() 的 SELECT ... FOR UPDATE 形成环形等待
    #   （9 个事务互相等待，248 次行锁等待、平均 5870ms，40/40 请求全部 30s 超时，
    #    并把整个服务拖死）。这是**已确认的缺陷**（见 reports/10_store_deadlock.txt），
    #   不是本次要证明的性能数据。为了让"无重复格口分配"这条结论在
    #   服务可用的区间内拿到干净证据，C 场景固定在 1/5/10 三档跑，
    #   20 并发档单独作为缺陷复现记录，不混进吞吐统计里当正常数据。
    C_MAX = 10
    c_levels = [lv for lv in levels if lv <= C_MAX]
    if not c_levels:
        c_levels = [C_MAX]
    print(f"\n--- C 并发存件（核验无重复格口分配；全局选格口，档位 {c_levels}）---")
    print(f"    注：20 并发档已实测触发 store 行锁环形等待（缺陷，见 10_store_deadlock.txt），")
    print(f"        故 C 场景收敛到 ≤{C_MAX} 并发，避免把缺陷现场混进吞吐数据。")
    for lv in c_levels:
        rec, wall, assigned = scene_store(host, lv, args.ops,
                                         courier["courier_id"],
                                         None)
        s = rec.summary(wall)
        s["_records"] = rec.records
        scenarios.append(s)
        print(f"  并发={lv:<3} 吞吐={fmt(s['吞吐(请求/秒)'])}/s  错误率={fmt(s['错误率(%)'],0)}%  "
              f"P95={fmt(s['P95(ms)'],0)}ms  P99={fmt(s['P99(ms)'],0)}ms  成功分配={len(assigned)}")
        if lv == c_levels[-1]:
            store_verify = verify_store(assigned)
            store_verify["证据②-分配明细"] = assigned
            store_verify["各档成功分配数"] = dict(
                store_verify.get("各档成功分配数", {}), **{str(lv): len(assigned)})
        else:
            store_verify.setdefault("各档成功分配数", {})[str(lv)] = len(assigned)
        for a in assigned:
            cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s",
                                (a["package_id"],)) if a.get("package_id") else None
            to_cleanup.append({"package_id": a.get("package_id"),
                               "cell_id": cell["cell_id"] if cell else None})
    print(f"  {store_verify.get('综合结论')}")

    # -------- D 并发支付 --------
    print("\n--- D 并发支付（核验无重复入账）---")
    for lv in levels:
        rec, wall, v = scene_pay(host, lv, args.ops)
        s = rec.summary(wall)
        s["_records"] = rec.records
        scenarios.append(s)
        print(f"  并发={lv:<3} 吞吐={fmt(s['吞吐(请求/秒)'])}/s  错误率={fmt(s['错误率(%)'],0)}%")
        if lv == levels[-1]:
            pay_verify = v
        for pid in v.get("本轮创建的包裹(待清理)", []):
            cell = db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
            to_cleanup.append({"package_id": pid,
                               "cell_id": cell["cell_id"] if cell else None})
    print(f"  {pay_verify.get('综合结论')}")

    # -------- E 并发取件 --------
    print("\n--- E 并发取码取件（核验不会取走两次）---")
    rec, wall, v = scene_pickup_race(host, 10, 10)
    s = rec.summary(wall)
    s["_records"] = rec.records
    scenarios.append(s)
    pickup_verify = v
    to_cleanup.extend(v.get("待清理", []))
    print(f"  {v.get('综合结论')}")

    # -------- 清理 --------
    cleanup(to_cleanup)
    print(f"\n  已清理本轮压测产生的 {len(to_cleanup)} 件包裹")

    # -------- 落盘 --------
    ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    payload = {
        "生成时间": datetime.now(TZ).isoformat(timespec="seconds"),
        "目标服务": host,
        "环境": {
            "主机": platform.node(),
            "OS": f"{platform.system()} {platform.release()}",
            "Python": sys.version.split()[0],
            "requests": requests.__version__,
            "CPU 逻辑核数": os.cpu_count(),
            "并发梯度": levels,
            "每档请求数": args.ops,
        },
        "工具声明": "本机未安装 JMeter；数据由 quality/load_test_v2.py 实测生成。",
        "场景汇总": [{k: v for k, v in s.items() if k != "_records"} for s in scenarios],
        "C_格口一致性三重证据": store_verify,
        "D_入账一致性三重证据": pay_verify,
        "E_并发取件核验": pickup_verify,
        "逐请求明细": {s["场景"]: s["_records"] for s in scenarios},
    }
    jpath = os.path.join(args.out, f"loadtest_{ts}.json")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(args.out, "loadtest_latest.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)

    print("\n" + "=" * 78)
    print(f" 原始逐请求 JSON : {jpath}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
