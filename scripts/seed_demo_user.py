# -*- coding: utf-8 -*-
"""从种子 SQL 直接核对演示账号 15800000001 名下包裹，避免运行库漂移干扰。"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
s = open("init_database.sql", encoding="utf-8").read()

# 找 t_package 的 INSERT，解析列名与每行
m = re.search(r"INSERT INTO `t_package`\s*\(([^)]*)\)\s*VALUES\s*(.*?);", s, re.S)
cols = [c.strip().strip("`") for c in m.group(1).split(",")]
body = m.group(2)

# 粗解析：按顶层括号切行，再按逗号切字段（忽略引号内逗号）
rows = []
i = 0
while i < len(body):
    if body[i] == "(":
        depth = 1
        buf = []
        i += 1
        inq = False
        while i < len(body) and depth > 0:
            ch = body[i]
            if ch == "'" and (i == 0 or body[i - 1] != "\\"):
                inq = not inq
                buf.append(ch)
            elif ch == "(" and not inq:
                depth += 1
                buf.append(ch)
            elif ch == ")" and not inq:
                depth -= 1
                if depth > 0:
                    buf.append(ch)
            else:
                buf.append(ch)
            i += 1
        rows.append("".join(buf))
    else:
        i += 1

print("packages parsed:", len(rows))
idx = {c: n for n, c in enumerate(cols)}
target = []
for r in rows:
    fields = []
    buf = []
    inq = False
    for ch in r:
        if ch == "'":
            inq = not inq
            buf.append(ch)
        elif ch == "," and not inq:
            fields.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    fields.append("".join(buf).strip())
    if len(fields) != len(cols):
        continue
    if fields[idx["recipient_phone"]].strip("'") == "15800000001":
        target.append(fields)

print("packages for 15800000001:", len(target))
for f in target:
    print("  pkg", f[idx["package_id"]], "cab", f[idx["cabinet_id"]],
          "cell", f[idx["cell_id"]], "code", f[idx["pickup_code"]].strip("'"),
          "status", f[idx["status"]].strip("'"))
