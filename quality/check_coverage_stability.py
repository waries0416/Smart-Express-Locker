# -*- coding: utf-8 -*-
"""覆盖率稳定性检测：连续跑 N 次 coverage，看 TOTAL 是否完全一致。

为什么需要：
    重跑前后出现过 57.40% → 57.34% 的 0.06pp 波动（未覆盖 1426 → 1428）。
    这种"小数位级别的抖动"必须查清是**非确定性代码路径**（例如时间相关的
    分支、随机、并发）还是**我自己的操作差异**，否则报告里的覆盖率
    每次跑都不一样，评委复现会对不上。

用法：
    python quality/check_coverage_stability.py --runs 3
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = r"D:\softwaretest"
BACKEND = os.path.join(ROOT, "backend")
RC = os.path.join(ROOT, "quality", ".coveragerc")
OUT = os.path.join(ROOT, "quality", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_cov(py, idx, outdir):
    """跑一次 coverage。

    注意：必须从**项目根目录**执行（不是 backend/），因为 .coveragerc 里
    `source = backend` 是相对路径。在 backend/ 下设 cwd 会让
    coverage 找不到 `backend` 这个包，报 "Module backend was never imported /
    No data was collected"，报告为空 —— 这个坑我踩过。

    测试发现目录用绝对路径传给 unittest，不需要 cd。
    """
    env = dict(os.environ)
    env["COVERAGE_FILE"] = os.path.join(outdir, f".coverage_r{idx}")
    env["PYTHONPATH"] = ROOT + os.pathsep + os.path.join(ROOT, "backend")

    subprocess.run([py, "-m", "coverage", "erase", f"--rcfile={RC}"],
                   cwd=ROOT, env=env, capture_output=True)
    r1 = subprocess.run(
        [py, "-m", "coverage", "run", f"--rcfile={RC}",
         "-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py"],
        cwd=ROOT, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    r2 = subprocess.run([py, "-m", "coverage", "report", f"--rcfile={RC}"],
                        cwd=ROOT, env=env, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    text = r2.stdout or ""
    log = os.path.join(outdir, f"cov_r{idx}.txt")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write((r1.stdout or "") + (r1.stderr or "") + "\n" + text)
    total = next((l.strip() for l in text.splitlines() if l.startswith("TOTAL")), "")
    m = re.search(r"(\d+\.\d+)%", total)
    ran_ok = bool(re.search(r"^OK", (r1.stdout or "") + (r1.stderr or ""), re.M))
    return {"idx": idx, "total": total, "pct": float(m.group(1)) if m else None,
            "ran": ran_ok, "log": log}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(OUT, f"covstab_{stamp}")
    os.makedirs(outdir, exist_ok=True)

    print("=" * 74)
    print(f" 覆盖率稳定性检测 · 连跑 {args.runs} 次")
    print("=" * 74)

    res = []
    for i in range(1, args.runs + 1):
        r = run_cov(args.python, i, outdir)
        res.append(r)
        print(f"  第 {i} 次  OK={r['ran']}  {r['total']}")

    pcts = [r["pct"] for r in res if r["pct"] is not None]
    uniq = sorted(set(pcts))
    print("\n" + "-" * 74)
    if len(uniq) == 1:
        print(f"  ✅ 稳定：{args.runs} 次均为 {uniq[0]}%")
        print("     说明目标分支已被确定性测试覆盖，覆盖率可放心引用。")
        print("     （若此前观测到过抖动，通常是某条时序相关分支未被子测试固定，")
        print("       典型修法是补一个直接构造该场景的确定性用例。）")
    else:
        print(f"  ⚠️ 不稳定：出现 {uniq}")
        print("     说明存在非确定性代码路径（时间/随机/并发）。")
        print("     报告里必须写明覆盖率有小数位波动并给出观测区间，")
        print("     不能只报一个点值；同时应定位到具体文件与行号。")
    print("-" * 74)
    print(f"  日志目录：{outdir}")
    return 0 if len(uniq) == 1 else 1


if __name__ == "__main__":
    sys.exit(main())
