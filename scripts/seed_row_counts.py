# -*- coding: utf-8 -*-
"""从 init_database.sql 里统计各表 INSERT 的种子行数（权威基线，不受运行库漂移影响）。"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
s = open("init_database.sql", encoding="utf-8").read()

# 逐条 INSERT 语句，统计 VALUES 元组内、且该 INSERT 只针对一张表
pattern = re.compile(r"INSERT INTO `(\w+)`\s*\([^)]*\)\s*VALUES\s*(.*?);", re.S)
counts = {}
for m in pattern.finditer(s):
    table, body = m.group(1), m.group(2)
    # 顶层括号组数量 = 行数（忽略字符串内的括号：种子数据里手机号/文本极少含括号）
    depth = 0
    rows = 0
    for ch in body:
        if ch == "(":
            depth += 1
            if depth == 1:
                rows += 1
        elif ch == ")":
            depth -= 1
    counts[table] = counts.get(table, 0) + rows

for t in sorted(counts):
    print(f"{t:22s} {counts[t]:5d}")
print("-" * 30)
print(f"total rows: {sum(counts.values())}")
print("tables with INSERT:", len(counts))
