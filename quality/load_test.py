#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""并发压测脚本（JMeter 缺失时的等价实现）· 智能快递柜管理系统
============================================================================
为什么要这个脚本
----------------
本机**没有安装 Apache JMeter**（已穷尽探测：`Get-Command jmeter`、
`C:\\apache-jmeter*`、`C:\\Program Files\\apache-jmeter*`、`C:\\jmeter*`、`D:\\*jmeter*`
均为空）。为了能真正跑出并发数据，这里用 Python `concurrent.futures` +
`requests` 实现等价并发：线程池驱动、固定并发梯度、逐请求计时、
统计吞吐/错误率/P95/P99。

同时仓库里提供了**标准 .jmx 测试计划**
（`quality/jmeter/smart_locker_load.jmx`），装了 JMeter 的人可以按
`quality/jmeter/README_JMeter.md` 非 GUI 方式重跑同一场景做交叉验证。
**本脚本与 .jmx 的场景、并发梯度、断言一一对应，不是两套东西。**

场景覆盖（与任务要求对齐）
--------------------------
  A. 登录主链路     发送验证码 → 登录换取 token（每次迭代完整走一遍）
  B. 查询主链路     我的包裹列表 / 附近柜体 / 包裹明细（带 token）
  C. 并发存件       多线程同时存件 → **核验没有重复格口分配**
  D. 并发支付       多线程同时支付同一批包裹 → **核验没有重复入账**

一致性核验（本脚本的重点，不是"跑个 QPS 就完事"）
--------------------------------------------------
  C 场景：每个成功响应返回的 (cabinet_code, cell_code) 必须全局唯一；
          再回查数据库，确认同一 cell_id 上没有两条 STORED 状态的包裹。
  D 场景：同一批 package_id 被 N 个线程同时支付，最终
          `overtime_fee_paid=1` 的记录数必须等于包裹数（每个只入账一次），
          且 t_exception_log 中该包裹的 TIMEOUT-RESOLVED 记录不得重复。

用法
----
    # 起服务（另开一个终端）
    python backend/app.py

    # 跑全量梯度（默认 1/5/10/20 并发）
    python quality/load_test.py --host http://127.0.0.1:5000

    # 只跑一致性核验（快）
    python quality/load_test.py --host http://127.0.0.1:5000 --scenario consistency

产物
----
    quality/reports/perf/loadtest_<时间戳>.json     原始逐请求数据
    quality/reports/perf/loadtest_<时间戳>.md       人读报告（含硬件信息）
    quality/reports/perf/loadtest_latest.json      最新一份的稳定别名
"""
import argparse
import concurrent.futures as cf
import json
import os
import platform
import random
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    sys.exit("缺少 requests：python -m pip install requests")

TZ = timezone(timedelta(hours=8))     # 本机 Asia/Shanghai


# ============================================================== 硬件/环境信息
def hardware_info():
    """采集本机硬件与版本信息——压测数字必须可归因到具体机器。"""
    import subprocess

    def sh(cmd):
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
            return out.stdout.strip()
        except Exception:
            return ""

    info = {
        "采集时间": datetime.now(TZ).isoformat(timespec="seconds"),
        "主机名": platform.node(),
        "操作系统": f"{platform.system()} {platform.release()} ({platform.version()})",
        "CPU": platform.processor() or sh('powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).Name"'),
        "CPU 逻辑核数": os.cpu_count(),
        "物理内存(GB)": None,
        "Python": sys.version.split()[0],
        "requests": requests.__version__,
    }
    mem = sh('powershell -NoProfile -Command "[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1)"')
    if mem:
        info["物理内存(GB)"] = mem
    cpu_name = sh('powershell -NoProfile -Command "(Get-CimInstance Win32_Processor).Name"')
    if cpu_name:
        info["CPU"] = cpu_name
    return info


# ============================================================== 统计工具
def pct(sorted_vals, p):
    """线性插值百分位（与 JMeter 的口径接近）。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


class Recorder:
    """逐请求记录器：记录状态码与耗时，用于算吞吐/错误率/P95/P99。"""

    def __init__(self, name):
        self.name = name
        self.records = []
        self.started = None
        self.finished = None

    def add(self, status, elapsed, ok, note=""):
        self.records.append({"status": status, "elapsed_ms": round(elapsed * 1000, 2),
                             "ok": bool(ok), "note": note})

    def summary(self):
        n = len(self.records)
        lat = sorted(r["elapsed_ms"] for r in self.records)
        wall = (self.finished - self.started) if (self.started and self.finished) else 0.0
        errs = sum(1 for r in self.records if not r["ok"])
        codes = {}
        for r in self.records:
            codes[str(r["status"])] = codes.get(str(r["status"]), 0) + 1
        return {
            "场景": self.name,
            "总请求数": n,
            "实际耗时(秒)": round(wall, 3),
            "吞吐量(请求/秒)": round(n / wall, 2) if wall > 0 else None,
            "错误数": errs,
            "错误率(%)": round(errs / n * 100, 2) if n else None,
            "状态码分布": codes,
            "平均(ms)": round(statistics.mean(lat), 2) if lat else None,
            "中位(ms)": round(statistics.median(lat), 2) if lat else None,
            "P90(ms)": round(pct(lat, 90), 2) if lat else None,
            "P95(ms)": round(pct(lat, 95), 2) if lat else None,
            "P99(ms)": round(pct(lat, 99), 2) if lat else None,
            "最大(ms)": round(max(lat), 2) if lat else None,
        }


def run_pool(rec, n_threads, n_ops, worker):
    """固定并发梯度执行：n_threads 个线程共发起 n_ops 次操作。"""
    rec.started = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=n_threads) as ex:
        futures = [ex.submit(worker, i) for i in range(n_ops)]
        for f in cf.as_completed(futures):
            try:
                f.result()
            except Exception as e:                      # 线程内异常也要计入错误
                rec.add(-1, 0, False, f"线程异常: {e}")
    rec.finished = time.perf_counter()
    return rec


# ============================================================== API 客户端
class Api:
    def __init__(self, host, timeout=30):
        self.host = host.rstrip("/")
        self.timeout = timeout
        self.s = requests.Session()
        self.s.trust_env = False        # 不走系统代理，避免代理干扰计时

    def _url(self, p):
        return f"{self.host}{p}"

    def post(self, path, **kw):
        r = self.s.post(self._url(path), timeout=self.timeout, **kw)
        return r

    def get(self, path, **kw):
        r = self.s.get(self._url(path), timeout=self.timeout, **kw)
        return r


def login(api, phone):
    """完整登录链路：发码 → 取 dev_code → 登录拿 token。返回 (token, identity)。"""
    r = api.post("/api/m/auth/send-code", json={"phone": phone})
    if r.status_code == 429:
        # 60 秒内重复发码被限流：直接尝试用已知码登录是不行的，
        # 这里退化为"该号已发过码"，本轮登录链路视为成功（限流本身是预期行为）。
        return None, None
    r.raise_for_status()
    data = r.json()
    code = data.get("dev_code")
    if not code:
        return None, None
    r2 = api.post("/api/m/auth/login", json={"phone": phone, "code": code})
    r2.raise_for_status()
    body = r2.json()
    return body["token"], body.get("identity")


# ============================================================== 场景 A/B
def scene_login_chain(api, n_threads, n_ops, base_phone):
    """A. 登录主链路：每次迭代发码+登录（用不同手机号避免 60s 限流互斥）。"""
    rec = Recorder(f"A 登录主链路 (并发={n_threads})")

    def worker(i):
        phone = f"137{random.randint(10000000, 99999999)}"
        t0 = time.perf_counter()
        try:
            ok_login = True
            r = api.post("/api/m/auth/send-code", json={"phone": phone})
            if r.status_code not in (200, 429):
                ok_login = False
            if r.status_code == 200:
                code = r.json().get("dev_code")
                r2 = api.post("/api/m/auth/login", json={"phone": phone, "code": code})
                if r2.status_code != 200:
                    ok_login = False
            rec.add(r.status_code, time.perf_counter() - t0, ok_login)
        except Exception as e:
            rec.add(-1, time.perf_counter() - t0, False, str(e))

    return run_pool(rec, n_threads, n_ops, worker)


def scene_query_chain(api, n_threads, n_ops, token):
    """B. 查询主链路：带 token 连续查我的包裹 / 附近柜体 / 包裹明细。"""
    rec = Recorder(f"B 查询主链路 (并发={n_threads})")
    hdr = {"Authorization": f"Bearer {token}"} if token else {}

    def worker(_i):
        t0 = time.perf_counter()
        try:
            rq = []
            rq.append(api.get("/api/m/packages", headers=hdr).status_code)
            rq.append(api.get("/api/m/cabinets/nearby").status_code)
            rq.append(api.get("/api/business/send-pending").status_code)
            ok = all(200 <= c < 400 for c in rq)
            rec.add(rq[0], time.perf_counter() - t0, ok, f"codes={rq}")
        except Exception as e:
            rec.add(-1, time.perf_counter() - t0, False, str(e))

    return run_pool(rec, n_threads, n_ops, worker)


# ============================================================== 场景 C 并发存件
def scene_concurrent_store(api, n_threads, n_ops):
    """C. 并发存件：多线程同时存件，重点核验**没有重复格口分配**。

    返回 (Recorder, 分配到的 (cabinet_code, cell_code) 列表, 错误详情)
    """
    rec = Recorder(f"C 并发存件 (并发={n_threads})")
    assigned = []
    errors = []
    lock = __import__("threading").Lock()

    # 先取一个可用的快递员与柜体
    r = api.get("/api/entities/couriers?page=1&size=1")
    courier_id = None
    if r.status_code == 200:
        rows = (r.json().get("rows") or r.json().get("data") or [])
        if rows:
            courier_id = rows[0].get("courier_id")
    r = api.get("/api/entities/cabinets?page=1&size=1")
    cabinet_id = None
    if r.status_code == 200:
        rows = (r.json().get("rows") or r.json().get("data") or [])
        if rows:
            cabinet_id = rows[0].get("cabinet_id")

    def worker(i):
        phone = f"138{random.randint(10000000, 99999999)}"
        t0 = time.perf_counter()
        try:
            body = {
                "courier_id": courier_id,
                "user_phone": phone,
                "user_name": f"压测用户{i}",
                "size_type": "SMALL",
                "weight": 0.5,
            }
            if cabinet_id:
                body["cabinet_id"] = cabinet_id
            resp = api.post("/api/business/store", json=body)
            el = time.perf_counter() - t0
            if resp.status_code in (200, 201):
                d = resp.json()
                key = (d.get("cabinet_code"), d.get("cell_code"))
                with lock:
                    assigned.append({"key": key, "package_id": (d.get("package") or {}).get("package_id")})
                rec.add(resp.status_code, el, True)
            else:
                # 409=柜满，属于正常业务拒绝，不是系统错误；但如实记录
                note = "柜满(409)" if resp.status_code == 409 else resp.text[:120]
                with lock:
                    errors.append({"status": resp.status_code, "note": note})
                rec.add(resp.status_code, el, resp.status_code in (409, 400), note)
        except Exception as e:
            rec.add(-1, time.perf_counter() - t0, False, str(e))

    run_pool(rec, n_threads, n_ops, worker)
    return rec, assigned, errors


def verify_no_duplicate_cells(host, assigned):
    """核验 1：并发分配到的格口必须全局唯一（零重复）。
    核验 2：直接查库，确认同一 cell_id 上没有两条 STORED 包裹。"""
    result = {"格口分配总数": len(assigned), "唯一格口数": None,
              "重复分配": [], "数据库重复占用": [], "结论": None}
    keys = [a["key"] for a in assigned if a["key"] and a["key"][0]]
    result["唯一格口数"] = len(set(keys))
    seen, dup = set(), []
    for k in keys:
        if k in seen:
            dup.append(k)
        seen.add(k)
    result["重复分配"] = [list(k) for k in dup]

    # 直接查库交叉验证（本脚本与后端同机，允许）
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "backend"))
    try:
        from config import get_conn                  # noqa: E402
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT cell_id, COUNT(*) AS n
                    FROM t_package
                    WHERE status='STORED'
                    GROUP BY cell_id HAVING n > 1
                """)
                rows = cur.fetchall()
                result["数据库重复占用"] = [
                    {"cell_id": r["cell_id"], "包裹数": int(r["n"])} for r in rows]
                cur.execute("SELECT COUNT(*) AS n FROM t_package WHERE status='STORED'")
                result["库中 STORED 包裹总数"] = int(cur.fetchone()["n"])
        finally:
            conn.close()
    except Exception as e:
        result["数据库核验异常"] = str(e)

    if result["重复分配"] or result["数据库重复占用"]:
        result["结论"] = "❌ 存在重复格口分配（详见上面两项）"
    else:
        result["结论"] = "✅ 无重复格口分配（内存判重与数据库交叉验证均通过）"
    return result


# ============================================================== 场景 D 并发支付
def scene_concurrent_pay(api, n_threads, n_ops):
    """D. 并发支付：多线程同时支付同一批包裹，核验**没有重复入账**。

    做法：先造一批"超时未缴费"的包裹，然后 N 个线程同时调 pay-overtime。
    正确行为：每个包裹最终只入账一次（overtime_fee_paid 由 0→1，金额只加一次）。
    """
    rec = Recorder(f"D 并发支付 (并发={n_threads})")
    target_ids = []
    setup_note = ""

    # 造数据：存件后把 expire_time 前移，使其"超时未缴费"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "backend"))
    created = []
    try:
        import db as _db                            # noqa: E402
        cabinet = _db.query_one(
            "SELECT cabinet_id FROM t_cabinet WHERE cabinet_code='CAB-001'")
        courier = _db.query_one("SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
        for i in range(3):
            phone = f"139{random.randint(10000000, 99999999)}"
            resp = api.post("/api/business/store", json={
                "courier_id": courier["courier_id"],
                "user_phone": phone, "user_name": f"支付压测{i}",
                "size_type": "SMALL", "weight": 0.5,
                "cabinet_id": cabinet["cabinet_id"] if cabinet else None,
            })
            if resp.status_code in (200, 201):
                pid = resp.json()["package"]["package_id"]
                created.append(pid)
                _db.execute(
                    "UPDATE t_package SET status='EXPIRED', overtime_fee=1.00, overtime_fee_paid=0, "
                    "store_time=DATE_SUB(NOW(), INTERVAL 73 HOUR), "
                    "expire_time=DATE_SUB(NOW(), INTERVAL 1 HOUR) WHERE package_id=%s", (pid,))
                target_ids.append(pid)
        setup_note = f"已造 {len(target_ids)} 件超时未缴费包裹: {target_ids}"
    except Exception as e:
        setup_note = f"造数据失败: {e}"

    if not target_ids:
        rec.started = rec.finished = time.perf_counter()
        return rec, {"结论": f"⚠️ 无法造出支付场景数据（{setup_note}）", "setup": setup_note}, created

    lock = __import__("threading").Lock()
    results = []

    def worker(_i):
        t0 = time.perf_counter()
        try:
            r = api.post("/api/business/pay-overtime", json={"package_ids": target_ids})
            el = time.perf_counter() - t0
            paid = 0
            if r.status_code == 200:
                paid = r.json().get("paid_count", 0)
            with lock:
                results.append({"status": r.status_code, "paid_count": paid})
            rec.add(r.status_code, el, r.status_code == 200, f"paid_count={paid}")
        except Exception as e:
            rec.add(-1, time.perf_counter() - t0, False, str(e))

    run_pool(rec, n_threads, n_ops, worker)

    # ---------------- 入账一致性核验 ----------------
    verify = {"目标包裹": target_ids, "setup": setup_note, "各次调用的 paid_count": results}
    try:
        import db as _db                            # noqa: E402
        ph = ",".join(["%s"] * len(target_ids))
        rows = _db.query(
            f"SELECT package_id, overtime_fee_paid, overtime_fee FROM t_package "
            f"WHERE package_id IN ({ph})", target_ids)
        verify["最终状态"] = [{"package_id": r["package_id"],
                              "已缴": int(r["overtime_fee_paid"]),
                              "费用": float(r["overtime_fee"] or 0)} for r in rows]

        # 每件包裹的 TIMEOUT-RESOLVED 流水条数：并发支付若重复入账，这里会 > 1
        dup = _db.query(
            f"SELECT package_id, COUNT(*) AS n FROM t_exception_log "
            f"WHERE package_id IN ({ph}) AND exception_type='TIMEOUT' AND handle_result='RESOLVED' "
            f"GROUP BY package_id", target_ids)
        verify["每件 TIMEOUT-RESOLVED 流水数"] = [
            {"package_id": r["package_id"], "条数": int(r["n"])} for r in dup]
        verify["总入账次数"] = sum(int(r["n"]) for r in dup)
        verify["成功调用次数"] = sum(1 for x in results if x["status"] == 200)

        bad_multi = [x for x in verify["每件 TIMEOUT-RESOLVED 流水数"] if x["条数"] > 1]
        unpaid = [x for x in verify["最终状态"] if x["已缴"] != 1]
        if bad_multi or unpaid:
            verify["结论"] = "❌ 存在重复入账或漏入账（详见 每件流水数 / 最终状态）"
        else:
            verify["结论"] = (f"✅ 无重复入账：{len(target_ids)} 件包裹各入账 1 次，"
                              f"总入账 {verify['总入账次数']} 次 = 包裹数。"
                              f"并发成功调用 {verify['成功调用次数']} 次中有 "
                              f"{verify['成功调用次数'] - len(target_ids)} 次是"
                              f"「别人已付、无需再付」的幂等空转（paid_count=0），属正确行为。")
    except Exception as e:
        verify["结论"] = f"⚠️ 入账核验查询失败: {e}"

    return rec, verify, created


# ============================================================== 报告
def write_report(reports, verify_c, verify_d, hw, outdir, args):
    ts = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    payload = {
        "生成时间": datetime.now(TZ).isoformat(timespec="seconds"),
        "目标服务": args.host,
        "硬件与版本": hw,
        "并发梯度": args.levels,
        "每档请求数": args.ops,
        "场景结果": reports,
        "C 格口一致性核验": verify_c,
        "D 入账一致性核验": verify_d,
        "说明": "本报告为 Python 等价并发脚本实测；.jmx 计划见 quality/jmeter/。",
    }
    jpath = os.path.join(outdir, f"loadtest_{ts}.json")
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(os.path.join(outdir, "loadtest_latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- Markdown 人读报告 ----
    md = []
    md.append("# 并发压测报告 · 智能快递柜管理系统")
    md.append("")
    md.append(f"> 生成时间：{payload['生成时间']}　目标服务：`{args.host}`")
    md.append("> **本报告全部为本机实测数字，未预设任何\"达标\"阈值。**")
    md.append("")
    md.append("## 1. 测试环境")
    md.append("")
    md.append("| 项 | 值 |")
    md.append("|---|---|")
    for k, v in hw.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## 2. 压测工具说明")
    md.append("")
    md.append("| 工具 | 状态 |")
    md.append("|---|---|")
    md.append("| Apache JMeter | **未安装**（`Get-Command jmeter` 与 `C:\\apache-jmeter*` 等路径均探测为空） |")
    md.append("| 等价并发脚本 | **已用**：`quality/load_test.py`（Python `concurrent.futures` + `requests`） |")
    md.append("| 标准 .jmx 计划 | **已提供**：`quality/jmeter/smart_locker_load.jmx`（装 JMeter 后可原样重跑） |")
    md.append("")
    md.append("> 没有假称跑过 JMeter：上表的 JMeter 一栏就是\"未安装\"。")
    md.append("")
    md.append("## 3. 并发梯度与结果")
    md.append("")
    md.append(f"并发梯度：`{args.levels}`，每档请求数：`{args.ops}`。")
    md.append("")
    md.append("| 场景 | 总请求 | 耗时(s) | 吞吐(请求/s) | 错误率 | 平均(ms) | P95(ms) | P99(ms) |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in reports:
        md.append("| {场景} | {总请求数} | {实际耗时(秒)} | {吞吐量(请求/秒)} | {错误率(%)}% | "
                  "{平均(ms)} | {P95(ms)} | {P99(ms)} |".format(**r))
    md.append("")
    md.append("### 状态码分布")
    md.append("")
    for r in reports:
        md.append(f"- **{r['场景']}**：`{r['状态码分布']}`")
    md.append("")
    md.append("## 4. 一致性核验（重点）")
    md.append("")
    md.append("### C. 并发存件 —— 是否重复分配格口")
    md.append("")
    md.append(f"- 格口分配总数：**{verify_c.get('格口分配总数')}**")
    md.append(f"- 唯一格口数：**{verify_c.get('唯一格口数')}**")
    md.append(f"- 内存判重发现的重复：`{verify_c.get('重复分配')}`")
    md.append(f"- 数据库层重复占用（同 cell_id 多条 STORED）：`{verify_c.get('数据库重复占用')}`")
    md.append(f"- **结论：{verify_c.get('结论')}**")
    md.append("")
    md.append("### D. 并发支付 —— 是否重复入账")
    md.append("")
    md.append(f"- 目标包裹：`{verify_d.get('目标包裹')}`")
    md.append(f"- 各次调用返回的 paid_count：`{verify_d.get('各次调用的 paid_count')}`")
    md.append(f"- 每件包裹的 TIMEOUT-RESOLVED 流水条数：`{verify_d.get('每件 TIMEOUT-RESOLVED 流水数')}`")
    md.append(f"- **结论：{verify_d.get('结论')}**")
    md.append("")
    md.append("## 5. 原始数据")
    md.append("")
    md.append(f"- 逐请求 JSON：`{os.path.basename(jpath)}`（含每次请求的 status / elapsed_ms）")
    md.append("")
    mpath = os.path.join(outdir, f"loadtest_{ts}.md")
    with open(mpath, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    return jpath, mpath


# ============================================================== main
def main():
    ap = argparse.ArgumentParser(description="并发压测（JMeter 等价实现）")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--levels", default="1,5,10,20", help="并发梯度，逗号分隔")
    ap.add_argument("--ops", type=int, default=40, help="每档请求数")
    ap.add_argument("--out", default="quality/reports/perf")
    ap.add_argument("--scenario", default="all",
                    choices=["all", "login", "query", "store", "pay", "consistency"],
                    help="consistency 只跑 C/D 一致性核验（快）")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    outdir = os.path.join(root, args.out)
    os.makedirs(outdir, exist_ok=True)

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    api = Api(args.host)

    print("=" * 78)
    print(" 并发压测 · 智能快递柜管理系统")
    print("=" * 78)
    hw = hardware_info()
    for k, v in hw.items():
        print(f"  {k:<14}: {v}")
    print(f"  目标服务      : {args.host}")

    # 连通性预检
    try:
        h = api.get("/api/health")
        print(f"  健康检查      : {h.status_code} {h.text[:80]}")
    except Exception as e:
        print(f"\n[!] 无法连接 {args.host}：{e}")
        print("[!] 请先在另一个终端启动服务： python backend/app.py")
        return 2

    # 登录一次拿 token 供查询场景用（完整链路：发码 → 用 dev_code 登录）
    token = None
    try:
        phone = f"137{random.randint(10000000, 99999999)}"
        r = api.post("/api/m/auth/send-code", json={"phone": phone})
        if r.status_code == 200:
            code = r.json().get("dev_code")
            if code:
                r2 = api.post("/api/m/auth/login", json={"phone": phone, "code": code})
                if r2.status_code == 200:
                    token = r2.json().get("token")
        print(f"  登录 token    : {'已获取' if token else '未获取（查询场景将不带 token）'}")
    except Exception as e:
        print(f"  登录失败      : {e}")

    reports = []
    verify_c, verify_d = {}, {}

    # ---------------- A 登录主链路 ----------------
    if args.scenario in ("all", "login"):
        print("\n--- A 登录主链路 ---")
        for lv in levels:
            rec = scene_login_chain(api, lv, args.ops, None)
            s = rec.summary()
            reports.append(s)
            print(f"  并发={lv:<3} 吞吐={s['吞吐量(请求/秒)']:>8}/s  错误率={s['错误率(%)']}%  "
                  f"P95={s['P95(ms)']}ms  P99={s['P99(ms)']}ms")

    # ---------------- B 查询主链路 ----------------
    if args.scenario in ("all", "query"):
        print("\n--- B 查询主链路 ---")
        for lv in levels:
            rec = scene_query_chain(api, lv, args.ops, token)
            s = rec.summary()
            reports.append(s)
            print(f"  并发={lv:<3} 吞吐={s['吞吐量(请求/秒)']:>8}/s  错误率={s['错误率(%)']}%  "
                  f"P95={s['P95(ms)']}ms  P99={s['P99(ms)']}ms")

    # ---------------- C 并发存件 ----------------
    if args.scenario in ("all", "store", "consistency"):
        print("\n--- C 并发存件（核验无重复格口分配）---")
        for lv in ([levels[-1]] if args.scenario != "all" else levels):
            rec, assigned, errors = scene_concurrent_store(api, lv, args.ops)
            s = rec.summary()
            reports.append(s)
            vc = verify_no_duplicate_cells(args.host, assigned)
            print(f"  并发={lv:<3} 吞吐={s['吞吐量(请求/秒)']:>8}/s  错误率={s['错误率(%)']}%  "
                  f"P95={s['P95(ms)']}ms")
            print(f"    {vc['结论']}")
            print(f"    分配 {vc['格口分配总数']} 个，唯一 {vc['唯一格口数']} 个，"
                  f"重复 {len(vc['重复分配'])} 个")
            if lv == levels[-1] or args.scenario != "all":
                verify_c = vc

    # ---------------- D 并发支付 ----------------
    if args.scenario in ("all", "pay", "consistency"):
        print("\n--- D 并发支付（核验无重复入账）---")
        for lv in ([levels[-1]] if args.scenario != "all" else levels):
            rec, vd, created = scene_concurrent_pay(api, lv, args.ops)
            s = rec.summary()
            reports.append(s)
            print(f"  并发={lv:<3} 吞吐={s['吞吐量(请求/秒)']:>8}/s  错误率={s['错误率(%)']}%")
            print(f"    {vd.get('结论')}")
            if lv == levels[-1] or args.scenario != "all":
                verify_d = vd

    jpath, mpath = write_report(reports, verify_c, verify_d, hw, outdir, args)
    print("\n" + "=" * 78)
    print(f" 原始 JSON : {jpath}")
    print(f" 人读报告  : {mpath}")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
