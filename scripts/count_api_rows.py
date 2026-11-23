# -*- coding: utf-8 -*-
"""统计 docs/03 接口清单的表行数，用于与代码路由数交叉核对。"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
s = open("docs/03-详细设计说明书.md", encoding="utf-8").read()
i = s.find("## 3. 接口清单")
j = s.find("## 4. 关键流程时序")
seg = s[i:j]
cur = None
total = 0
for line in seg.splitlines():
    m = re.match(r"###\s+(3\.\d+.*)", line)
    if m:
        cur = m.group(1)
        print("\n" + cur)
        continue
    if line.startswith("| ") and not line.startswith("|---") and "方法" not in line:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            total += 1
            print("   ", " | ".join(cells[:3]))
print("\nTOTAL rows in 3.x tables:", total)
