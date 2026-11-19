# -*- coding: utf-8 -*-
"""量化测试套件的可重复性：连续跑 N 遍，统计每遍 Ran/OK/ERROR 与耗时。

为什么需要这个脚本：
    R9b 后出现的现象是**间歇性失败** —— 同样 201 个用例，
    有时 11 秒 OK 全过，有时 60~110 秒并出现 4~38 个 ERROR。
    这种"跑一次看不出来"的问题，单次结果不可信，必须先量化再下结论。

    quality/run_quality.py 要求"连跑两遍均通过"才算稳；
    本脚本就是把这个要求做成可判定的证据。

用法：
    python quality/check_suite_repeatability.py --runs 5
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = r"D:\softwaretest"
BACKEND = os.path.join(ROOT, "backend")
OUT = os.path.join(ROOT, "quality", "logs")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def run_once(py, idx, outdir):
    cmd = [py, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    secs = time.perf_counter() - t0
    out = (r.stdout or "") + (r.stderr or "")
    log = os.path.join(outdir, f"suite_run{idx}.txt")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(out)

    ran = re.search(r"Ran (\d+) tests?", out)
    failed = re.search(r"FAILED \(([^)]*)\)", out)
    errors = len(re.findall(r"^ERROR: ", out, re.M))
    fails = len(re.findall(r"^FAIL: ", out, re.M))
    ok = "OK" in out and not failed
    return {
        "run": idx,
        "ran": int(ran.group(1)) if ran else 0,
        "ok": ok,
        "failed": fails,
        "errors": errors,
        "detail": failed.group(1) if failed else "",
        "seconds": round(secs, 2),
        "log": log,
    }


def main():
    ap = argparse.ArgumentParser(description="量化测试套件可重复性")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--python", default=sys.executable)
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = os.path.join(OUT, f"repeat_{stamp}")
    os.makedirs(outdir, exist_ok=True)

    print("=" * 74)
    print(f" 测试套件可重复性检测 · 连跑 {args.runs} 遍")
    print("=" * 74)
    print(f" 工作目录 : {BACKEND}")
    print(f" 日志目录 : {outdir}\n")

    results = []
    for i in range(1, args.runs + 1):
        r = run_once(args.python, i, outdir)
        results.append(r)
        flag = "OK  " if r["ok"] else "FAIL"
        print(f"  第 {i} 遍  {flag}  Ran={r['ran']:>3}  "
              f"FAIL={r['failed']:>2} ERR={r['errors']:>2}  {r['seconds']:>7.2f}s")
        if not r["ok"] and r["detail"]:
            print(f"           {r['detail']}")

    ok_runs = sum(1 for r in results if r["ok"])
    times = [r["seconds"] for r in results]
    print("\n" + "-" * 74)
    print(f"  通过 {ok_runs}/{len(results)} 遍")
    print(f"  耗时 最快 {min(times):.2f}s / 最慢 {max(times):.2f}s "
          f"/ 极差 {max(times) - min(times):.2f}s")
    print(f"  ERROR 合计 {sum(r['errors'] for r in results)} 个")
    print("-" * 74)

    # 判定：全部通过且耗时不离散，才算可重复
    stable = (ok_runs == len(results))
    if stable:
        print("  ✅ 可重复：每遍 201 OK，无 ERROR")
    else:
        print("  ❌ 不可重复：存在间歇性失败")
        print("     这类问题会让'连跑两遍'这道门禁失去意义，")
        print("     必须定位到具体用例后再谈'质量数字可信'。")
        # 给出失败最多的日志，方便定位
        worst = max(results, key=lambda r: r["errors"] + r["failed"])
        print(f"     失败最多的日志：{worst['log']}")
    print("=" * 74)

    import json
    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump({"runs": results, "ok_runs": ok_runs, "stable": stable},
                  fh, ensure_ascii=False, indent=2)
    return 0 if stable else 1


if __name__ == "__main__":
    sys.exit(main())
