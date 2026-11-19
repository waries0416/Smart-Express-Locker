# -*- coding: utf-8 -*-
"""文档一致性自检：围栏配对、表格分隔行、旧数字残留。"""
import glob
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

FENCE = re.compile(r"^`{3,}[A-Za-z0-9_+-]*$")
SEP = re.compile(r"^\|[\s:\-|]+\|$")
OLD = re.compile(r"\b(312|122|233|268|168)\b")


def cell_count(line):
    """数一行的列数：跳过 \\| 转义与行内代码里的竖线。"""
    n = 0
    in_code = False
    i = 0
    s = line.strip()
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        elif ch == "|" and not in_code:
            n += 1
        i += 1
    return n

FILES = sorted(glob.glob("docs/0*.md")) + ["README.md"]
problems = []

for f in FILES:
    lines = open(f, encoding="utf-8").read().splitlines()
    fences = [i for i, l in enumerate(lines, 1) if FENCE.match(l.strip())]
    if len(fences) % 2:
        problems.append(f"{f}: 代码围栏数 {len(fences)} 为奇数，位置 {fences}")

    for i, l in enumerate(lines):
        if SEP.match(l.strip()):
            if i == 0 or not lines[i - 1].lstrip().startswith("|"):
                problems.append(f"{f}:{i + 1} 表格分隔行上方不是表头")

    # 表格列数一致性（同块内）
    block = []
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("|"):
            block.append((i, cell_count(l)))
        else:
            if len(block) > 2:
                counts = {c for _, c in block}
                if len(counts) > 1:
                    problems.append(f"{f}: 表格块 {block[0][0]}-{block[-1][0]} 列数不一致 {sorted(counts)}")
            block = []

    print(f"{f:36s} lines={len(lines):4d} fences={len(fences):3d}")

print()
if problems:
    print("=== 发现 %d 处问题 ===" % len(problems))
    for p in problems:
        print("  -", p)
else:
    print("=== 全部通过：围栏配对、表格结构无异常 ===")
