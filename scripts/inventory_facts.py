# -*- coding: utf-8 -*-
"""盘点数据库对象与真实实现事实，供文档差距表使用。"""
import re
import sys
import glob

sys.stdout.reconfigure(encoding="utf-8")


def main():
    for f in ["db/schema.sql", "db/objects.sql"]:
        s = open(f, encoding="utf-8").read()
        print("==", f)
        for m in re.finditer(
            r"(?i)create\s+(?:or\s+replace\s+)?(?:algorithm\s*=\s*\w+\s+)?"
            r"(view|trigger|procedure|function|event)\s+([A-Za-z_0-9.`]+)", s):
            print("    ", m.group(1).upper(), m.group(2))
        idx = re.findall(r"(?i)\b(?:key|index)\s+`?(\w+)`?\s*\(", s)
        print("    indexes:", len(idx))

    print("== migrations")
    for f in sorted(glob.glob("db/migrations/*.sql")):
        t = open(f, encoding="utf-8").read()
        print("  ", f, len(t.splitlines()), "lines")
        for m in re.finditer(r"(?i)create\s+table\s+if\s+not\s+exists\s+(\w+)|alter\s+table\s+(\w+)", t):
            print("      ", (m.group(1) or m.group(2)))

    print("== requirements.txt")
    print(open("backend/requirements.txt", encoding="utf-8").read().strip())

    print("== frontend pages")
    for f in ["frontend/kiosk.html", "frontend/login.html", "frontend/admin.html",
              "frontend/mobile/index.html"]:
        s = open(f, encoding="utf-8").read()
        print(f"   {f}: {len(s.splitlines())} lines")

    print("== e2e script")
    s = open("logs/e2e_check.py", encoding="utf-8").read()
    print("   cases:", len(re.findall(r"(?i)^def check|^def case|check\(", s, re.M)))

    print("== reset script")
    s = open("scripts/reset_demo_data.py", encoding="utf-8").read()
    print("   ", len(s.splitlines()), "lines")


main()
