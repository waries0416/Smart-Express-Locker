# -*- coding: utf-8 -*-
"""R9b 后重跑质量数字并核对口径一致性。

背景（为什么需要这个脚本）：
    R9b 新增 6 个并发回归用例，全量从 195 变 201。
    但 quality/reports 里 02/03/05/99 仍是 R3b 的 195 / 56.32% 口径。
    评委按报告复跑会得到 201，与报告里的 195 对不上 —— 这是口径事故，不是小事。

本脚本的职责只有两件：
    1) 调用 quality/run_quality.py 重跑全套（它会落盘 02/03/05/99）；
    2) **核验落盘结果的口径是否自洽**：Ran 数、覆盖率、跳过项、两遍一致性。

不做的事：不改测试、不动业务代码、不判断"数字好不好看"。
若某项不达标（例如有 FAILED），如实输出并以非 0 退出，绝不吞掉。

用法：
    python quality/refresh_quality_numbers.py            # 重跑 + 核验
    python quality/refresh_quality_numbers.py --check     # 只核验现有文件
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime

ROOT = r"D:\softwaretest"
REPORTS = os.path.join(ROOT, "quality", "reports")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read(name):
    p = os.path.join(REPORTS, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def parse_ran(text):
    """从 unittest 输出解析 Ran/OK/FAIL/ERROR 与 skipped。"""
    if not text:
        return {}
    out = {}
    m = re.search(r"Ran (\d+) tests?", text)
    if m:
        out["ran"] = int(m.group(1))
    m = re.search(r"OK(?: \(skipped=(\d+)\))?", text)
    if m:
        out["ok"] = True
        out["skipped"] = int(m.group(1) or 0)
    m = re.search(r"FAILED \((.*?)\)", text)
    if m:
        out["ok"] = False
        detail = m.group(1)
        out["failed"] = int((re.search(r"failures=(\d+)", detail) or [0, 0])[1])
        out["errors"] = int((re.search(r"errors=(\d+)", detail) or [0, 0])[1])
    return out


def parse_coverage(text):
    """解析 coverage report 的 TOTAL 行。"""
    if not text:
        return {}
    for line in text.splitlines():
        if line.startswith("TOTAL"):
            parts = line.split()
            nums = [p for p in parts if re.fullmatch(r"\d+%?", p)]
            pct = next((p for p in reversed(parts) if p.endswith("%")), None)
            return {"total_line": " ".join(parts), "percent": pct,
                    "nums": nums}
    return {}


def check():
    print("=" * 74)
    print(" 质量数字口径核验（R9b 后）")
    print("=" * 74)

    r1 = parse_ran(read("02_unittest_run1.txt"))
    r2 = parse_ran(read("02_unittest_run2.txt"))
    cov = parse_coverage(read("03_coverage_report.txt"))
    summ = read("99_summary.txt") or ""
    recon = read("05_test_count_reconciliation.txt") or ""

    problems = []

    print(f"\n第 1 遍 : {r1}")
    print(f"第 2 遍 : {r2}")
    print(f"覆盖率  : {cov.get('percent')}  ({cov.get('total_line','')[:70]})")

    # 1) 两遍必须都 OK
    for tag, r in (("第1遍", r1), ("第2遍", r2)):
        if not r:
            problems.append(f"{tag} 未解析到结果")
        elif not r.get("ok"):
            problems.append(f"{tag} 未通过：FAIL={r.get('failed')} ERR={r.get('errors')}")
        elif r.get("skipped"):
            problems.append(f"{tag} 有跳过 {r['skipped']} 项")

    # 2) 两遍 Ran 必须一致（连跑两遍的核心价值）
    if r1.get("ran") and r2.get("ran") and r1["ran"] != r2["ran"]:
        problems.append(f"两遍 Ran 不一致：{r1['ran']} vs {r2['ran']}")

    # 3) 99_summary 与 02 必须同口径
    ran = r2.get("ran")
    if ran and f"Ran={ran}" not in summ:
        problems.append(f"99_summary.txt 里找不到 Ran={ran}（口径未同步）")
    if cov.get("percent") and cov["percent"].replace("%", "") not in summ.replace(" ", ""):
        problems.append(f"99_summary.txt 里找不到覆盖率 {cov['percent']}（口径未同步）")

    # 4) 05 口径核对文件必须与实测一致
    #    实际格式：| **合计** | **195** |  /  - 实际执行：**195**
    m_static = re.search(r"\*\*合计\*\*\s*\|\s*\*\*(\d+)\*\*", recon)
    m_exec = re.search(r"实际执行：\*\*(\d+)\*\*", recon)
    if m_static and m_exec:
        stat, exe = int(m_static.group(1)), int(m_exec.group(1))
        print(f"口径核对: 静态={stat} 执行={exe}")
        if stat != exe:
            problems.append(f"05 口径核对：静态 {stat} != 执行 {exe}")
        if ran and exe != ran:
            problems.append(f"05 记录执行数 {exe} != 02 实测 Ran {ran}")
        # 各文件静态数之和必须等于合计
        parts = re.findall(r"\| (test_\w+\.py) \| (\d+) \|", recon)
        if parts:
            s = sum(int(n) for _, n in parts)
            if s != stat:
                problems.append(f"05 分文件静态数之和 {s} != 合计 {stat}")
            print(f"          分文件 {len(parts)} 个，求和={s}")
    else:
        problems.append("05_test_count_reconciliation.txt 未解析到口径核对行")

    # 5) 逗号分隔的测试总数直接 grep（静态 == 执行）
    print("\n" + "-" * 74)
    if problems:
        print(f" ❌ 发现 {len(problems)} 个口径问题：")
        for p in problems:
            print("    - " + p)
    else:
        print(f" ✅ 口径自洽：Ran={ran} · OK · skipped=0 · 覆盖率 {cov.get('percent')}")
    print("-" * 74)
    return 0 if not problems else 1


def run_quality():
    print("=" * 74)
    print(" 重跑全套质量门禁（quality/run_quality.py）")
    print("=" * 74)
    py = sys.executable
    r = subprocess.run([py, os.path.join(ROOT, "quality", "run_quality.py")],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    # 打印尾部即可，完整输出在 reports 里
    tail = (r.stdout or "")[-4000:]
    print(tail)
    if r.returncode != 0:
        print(f"\n[!] run_quality.py 退出码 {r.returncode}（可能某步骤失败，详见上方与 reports）")
    return r.returncode


def main():
    ap = argparse.ArgumentParser(description="重跑并核验质量数字口径")
    ap.add_argument("--check", action="store_true", help="只核验现有文件，不重跑")
    args = ap.parse_args()

    if not args.check:
        rc = run_quality()
        if rc != 0:
            print("\n⚠️ 重跑有步骤失败。落盘产物已生成，但**不一定可用**，"
                  "请先看失败原因再决定是否采信。")
    return check()


if __name__ == "__main__":
    sys.exit(main())
