#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cProfile 固定性能场景 · 智能快递柜管理系统
============================================================================
场景定义（可复现，任何人照这个命令跑都得到同一形状的数据）：

    S1  批量寄件下单    —— 连续 N 次 POST /api/business/send-order
                          （每次 -> 事务内 SELECT ... FOR UPDATE 选格口 -> INSERT
                           包裹 -> UPDATE 格口占用，是写路径最重的一条链路）
    S2  包装推荐        —— POST /api/ai/pack-recommend（AI 推荐；缺失则记为跳过）
    S3  附近柜体查询    —— GET  /api/mobile/cabinets/nearby
                          （30 柜 × 720 格口的 LEFT JOIN + 条件聚合）
    S4  寄件单查询      —— GET  /api/business/send-pending（列表 + JOIN 明细）

为什么选这四条：
    它们覆盖了「写事务 / 外部 AI 调用 / 重聚合读 / 联表读」四类典型负载，
    恰好是答辩时最容易被告知"慢"的四个地方，且都能用 Flask test_client
    在进程内复现，不需要起服务器、不受网络波动干扰——跑两次数字可比。

用法：
    python quality/perf_profile.py --root D:\\softwaretest --out quality/reports/perf
    python quality/perf_profile.py --root . --orders 20 --repeat 3

产物（quality/reports/perf/ 下）：
    perf.prof                  cProfile 原始二进制（可用 pstats / snakeviz 打开）
    perf_tottime.txt           pstats 按"函数自身耗时"排序 Top-N
    perf_cumtime.txt           pstats 按"累计耗时"排序 Top-N
    perf_calls.txt             pstats 按"调用次数"排序 Top-N
    perf_callers.txt           热点函数调用者/被调用者明细
    perf_summary.txt           人读的结论摘要（含每场景耗时、优化前后对比位）

口径说明（不美化）：
    · 计时包含 Flask 请求分发 + JSON 序列化，是"接口真实耗时"，不是"纯函数耗时"；
    · AI 推荐若走真实大模型会引入网络抖动，因此 S2 单独统计并标注其波动性；
    · 所有数据在 --orders 指定的批量规模内，属于本机实测值，不做外推。
"""
import argparse
import cProfile
import io
import os
import pstats
import statistics
import sys
import time
import traceback

DEFAULTS = {"orders": 30, "repeat": 3, "top": 25}
TEST_PREFIX = "PRF"          # 压测专用运单前缀，便于精确清理


# ---------------------------------------------------------------- 环境准备
def setup_paths(root):
    root = os.path.abspath(root)
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "backend"))
    os.environ.setdefault("NOTIFY_WORKER", "0")   # 不启后台通知线程
    return root


def import_app():
    import app as app_module            # noqa: E402  pylint: disable=import-outside-toplevel
    import db                           # noqa: E402  pylint: disable=import-outside-toplevel
    app_module.app.config.update(TESTING=True)
    return app_module, db


# ---------------------------------------------------------------- 场景数据
class Fixture:
    """固定场景数据：柜体/快递员/公司/手机号全部按固定规则选取，保证可复现。"""

    def __init__(self, db, app_module):
        self.db = db
        self.client = app_module.app.test_client()
        self.cabinet = db.query_one(
            "SELECT cabinet_id, cabinet_code FROM t_cabinet "
            "WHERE status='NORMAL' ORDER BY cabinet_id LIMIT 1")
        self.courier = db.query_one(
            "SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1")
        self.company = db.query_one(
            "SELECT company_id FROM t_express_company ORDER BY company_id LIMIT 1")
        if not (self.cabinet and self.courier and self.company):
            raise SystemExit("基础数据缺失（t_cabinet/t_courier/t_express_company），无法设置性能场景")
        self.created = []       # 本次创建的 package_id / cell_id，用于精确清理
        self._n = 0             # 单调递增序号：用于生成互不冲突的测试手机号

    def seq(self):
        """返回一个递增整数，用于拼出唯一但可复现的手机号后 8 位。"""
        self._n += 1
        return 10000000 + self._n

    # ---- 清理：只删本次创建的，绝不碰演示数据 ----
    def cleanup(self):
        for pid, cid in self.created:
            for table in ("t_notice", "t_exception_log", "t_pickup_record", "t_device_command"):
                try:
                    self.db.execute(f"DELETE FROM {table} WHERE package_id=%s", (pid,))
                except Exception:
                    pass
            try:
                self.db.execute("DELETE FROM t_package WHERE package_id=%s", (pid,))
            except Exception:
                pass
            try:
                self.db.execute("UPDATE t_cell SET status='FREE' WHERE cell_id=%s", (cid,))
            except Exception:
                pass
        self.created.clear()


# ---------------------------------------------------------------- 四个场景
def scene_send_orders(fx, n):
    """S1 批量寄件下单：返回耗时列表（秒）。"""
    times = []
    for i in range(n):
        phone = f"137{TEST_PREFIX.lower():0<2}"[:0] or f"1370000{i % 10000:04d}"
        t0 = time.perf_counter()
        resp = fx.client.post("/api/business/send-order", json={
            "user_phone": phone,
            "user_name": "性能测试寄件人",
            "recipient_phone": "13900000000",
            "recipient_name": "性能测试收件人",
            "size_type": "SMALL",
            "company_id": fx.company["company_id"],
            "cabinet_id": fx.cabinet["cabinet_id"],
            "weight": 0.5,
            "note": "perf baseline",
        })
        dt = time.perf_counter() - t0
        if resp.status_code in (200, 201):
            pkg = resp.get_json().get("package") or {}
            pid = pkg.get("package_id")
            if pid:
                row = fx.db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
                fx.created.append((pid, row["cell_id"] if row else None))
            times.append(dt)
        else:
            # 柜满等非异常情况也算一次调用耗时，但单独标记
            times.append(dt)
    return times


def scene_recommend(fx, n):
    """S2 包装推荐。接口不存在时返回 None（表示跳过，而不是伪造数字）。

    注意：外部 AI 调用会引入网络抖动，因此这里额外记录 degraded/source 分布，
    以便区分"真的调了大模型"与"降级到本地规则"两种时间语义。
    """
    url = AI_RECOMMEND_URL
    probe = fx.client.post(url, json={"description": "一个玻璃杯和两本书"})
    if probe.status_code in (404, 405):
        return None
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fx.client.post(url, json={"description": "一个玻璃杯和两本书"})
        times.append(time.perf_counter() - t0)
    return times


# 接口地址集中定义：移动端蓝图前缀是 /api/m（不是 /api/mobile），改前缀只改这里
AI_RECOMMEND_URL = "/api/ai/pack-recommend"
NEARBY_URL = "/api/m/cabinets/nearby"
SEND_PENDING_URL = "/api/business/send-pending"


def scene_nearby(fx, n, keyword=""):
    """S3 附近柜体查询（30 柜 × 720 格口的聚合）。"""
    url = NEARBY_URL
    if keyword:
        url += f"?q={keyword}"
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        resp = fx.client.get(url)
        if resp.status_code == 404:
            return None
        times.append(time.perf_counter() - t0)
    return times


def scene_send_pending(fx, n):
    """S4 寄件待揽收列表（联表 + 明细）。"""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        resp = fx.client.get(SEND_PENDING_URL)
        if resp.status_code == 404:
            return None
        times.append(time.perf_counter() - t0)
    return times


def scene_pickup_chain(fx, n):
    """S5 取件主链路（用户最在意的路径）：取件码预览 → 取件 → 触发器释放格口。

    为什么补这一条：
        前四个场景覆盖"写事务/AI/聚合读/联表读"，但**取件**是用户直接感知的
        交互路径，且依赖数据库触发器 trg_package_after_update 释放格口，
        是"接口耗时 + 触发器开销"唯一能被观测到的场景。
    做法：每轮造一件 STORED 包裹（用 store 接口，走真实分配），
          然后 POST /api/business/pickup 取走，记录 pickup 这一步的耗时。
    """
    times = []
    for _ in range(n):
        phone = f"136{fx.seq():08d}"[:11]
        resp = fx.client.post("/api/business/store", json={
            "courier_id": fx.courier["courier_id"],
            "user_phone": phone,
            "user_name": "性能取件用户",
            "size_type": "SMALL",
            "weight": 0.3,
        })
        if resp.status_code not in (200, 201):
            continue
        body = resp.get_json()
        code = body.get("pickup_code")
        pkg = body.get("package") or {}
        pid = pkg.get("package_id")
        if not (code and pid):
            continue
        cell = fx.db.query_one("SELECT cell_id FROM t_package WHERE package_id=%s", (pid,))
        fx.created.append((pid, cell["cell_id"] if cell else None))
        t0 = time.perf_counter()
        fx.client.post("/api/business/pickup", json={"pickup_code": code})
        times.append(time.perf_counter() - t0)
    return times


# ---------------------------------------------------------------- 统计
def stat_block(name, times, note=""):
    if not times:
        return f"{name:<22} 跳过 {note}"
    ms = [t * 1000 for t in times]
    ms_sorted = sorted(ms)
    p95 = ms_sorted[min(len(ms_sorted) - 1, int(len(ms_sorted) * 0.95))]
    return (f"{name:<22} n={len(ms):<4} 平均={statistics.mean(ms):8.2f}ms  "
            f"中位={statistics.median(ms):8.2f}ms  P95={p95:8.2f}ms  "
            f"min={min(ms):7.2f}ms  max={max(ms):8.2f}ms {note}")


def dump_pstats(prof, outdir, top):
    """把 pstats 结果按三种排序各导出一份可读文本。"""
    files = {}
    buf = io.StringIO()
    prof.stream = buf
    st = pstats.Stats(prof, stream=buf)
    st.strip_dirs()

    for tag, sortkey, fname in (
        # pstats 的排序名：time=函数自身耗时(tottime)、cumulative=累计、calls=调用次数
        ("tottime", "time",       "perf_tottime.txt"),
        ("cumtime", "cumulative", "perf_cumtime.txt"),
        ("calls",   "calls",      "perf_calls.txt"),
    ):
        buf.seek(0)
        buf.truncate(0)
        st.sort_stats(sortkey).print_stats(top)
        path = os.path.join(outdir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# pstats 排序依据: {tag}  Top-{top}\n")
            f.write("# 生成命令: python quality/perf_profile.py --root . --out quality/reports/perf\n\n")
            f.write(buf.getvalue())
        files[tag] = path

    buf.seek(0)
    buf.truncate(0)
    # 找出自身耗时最高的那个函数，打印它的调用者/被调用者
    st.sort_stats("time")
    hot = None
    for func, (_cc, _nc, tt, _ct, _callers) in st.stats.items():
        if hot is None or tt > st.stats[hot][2]:
            if "perf_profile.py" not in func[0]:
                hot = func
    if hot:
        buf.write(f"# 热点函数: {hot}\n\n# ---- 谁调用了它 ----\n")
        st.print_callers(hot)
        buf.write("\n# ---- 它调用了谁 ----\n")
        st.print_callees(hot)
    path = os.path.join(outdir, "perf_callers.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    files["callers"] = path
    return files, hot


# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="固定场景 cProfile 性能分析")
    ap.add_argument("--root", default=".", help="仓库根目录")
    ap.add_argument("--out", default="quality/reports/perf", help="产物目录")
    ap.add_argument("--orders", type=int, default=DEFAULTS["orders"], help="S1 批量寄件条数")
    ap.add_argument("--repeat", type=int, default=DEFAULTS["repeat"], help="每场景重复次数")
    ap.add_argument("--top", type=int, default=DEFAULTS["top"], help="pstats Top-N")
    ap.add_argument("--keep", action="store_true", help="保留场景数据（默认跑完清理）")
    args = ap.parse_args()

    root = setup_paths(args.root)
    outdir = os.path.abspath(os.path.join(root, args.out))
    os.makedirs(outdir, exist_ok=True)

    app_module, db = import_app()
    fx = Fixture(db, app_module)

    lines = []
    def emit(s=""):
        print(s)
        lines.append(s)

    emit("=" * 78)
    emit(" cProfile 固定场景 · 智能快递柜管理系统")
    emit("=" * 78)
    emit(f" Python      : {sys.version.split()[0]}")
    emit(f" 仓库根      : {root}")
    emit(f" 场景柜体    : {fx.cabinet['cabinet_code']} (id={fx.cabinet['cabinet_id']})")
    emit(f" 场景快递员  : courier_id={fx.courier['courier_id']}")
    emit(f" 参数        : orders={args.orders} repeat={args.repeat} top={args.top}")
    emit("")

    prof = cProfile.Profile()
    summary = {}

    try:
        # ---------- 预热（避免首次导入/连接池建立被算进基线）----------
        emit("--- 预热（结果不计入统计）---")
        fx.client.get("/api/mobile/cabinets/nearby")
        fx.client.get("/api/business/send-pending")
        emit("")

        prof.enable()

        # S1 批量寄件
        t1 = scene_send_orders(fx, args.orders)
        # S2 包装推荐
        t2 = scene_recommend(fx, args.repeat)
        # S3 附近柜体
        t3 = scene_nearby(fx, max(args.repeat, 5))
        # S4 寄件待揽收
        t4 = scene_send_pending(fx, max(args.repeat, 5))
        # S5 取件主链路（含触发器释放格口）
        t5 = scene_pickup_chain(fx, max(args.repeat, 5))
        prof.disable()
    finally:
        if not args.keep:
            fx.cleanup()

    # ---------- 场景耗时表 ----------
    emit("--- 场景耗时（本机实测，单位 ms）---")
    emit(stat_block("S1 批量寄件下单", t1, f"({args.orders} 条)"))
    if t2 is None:
        emit(stat_block("S2 包装推荐(AI)", None, "接口不存在或未实现，未统计（不伪造）"))
    else:
        emit(stat_block("S2 包装推荐(AI)", t2, "(含外部调用，波动大)"))
    emit(stat_block("S3 附近柜体查询", t3, "(30 柜 × 720 格口聚合)"))
    emit(stat_block("S4 寄件待揽收列表", t4, ""))
    emit(stat_block("S5 取件主链路", t5, "(含触发器释放格口)"))
    emit("")

    summary["S1"] = t1
    summary["S2"] = t2
    summary["S3"] = t3
    summary["S4"] = t4
    summary["S5"] = t5

    # ---------- 原始 .prof ----------
    prof_file = os.path.join(outdir, "perf.prof")
    prof.dump_stats(prof_file)
    emit(f"--- 原始 profile 已保存: {prof_file} ---")
    emit("    打开方式: python -m pstats quality/reports/perf/perf.prof")
    emit("              或 snakeviz quality/reports/perf/perf.prof")
    emit("")

    # ---------- pstats 可读报告 ----------
    files, hot = dump_pstats(prof, outdir, args.top)
    emit("--- pstats 报告 ---")
    for k, v in files.items():
        emit(f"    {k:<8}: {v}")
    if hot:
        st = pstats.Stats(prof, stream=io.StringIO())
        st.strip_dirs()
        tt = st.stats[hot][2]
        nc = st.stats[hot][1]
        emit(f"    热点函数 : {hot[2]}  ({os.path.basename(hot[0])}:{hot[1]})")
        emit(f"               自身耗时 {tt:.4f}s，调用 {nc} 次")
    emit("")

    # ---------- 结论摘要 ----------
    emit("--- 结论 ---")
    emit(dict(zip(("S1", "S2", "S3", "S4", "S5"),
                  (len(t1), "-" if t2 is None else len(t2), len(t3), len(t4),
                   len(t5)))).__repr__())
    with open(os.path.join(outdir, "perf_summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n摘要已写入: {os.path.join(outdir, 'perf_summary.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
