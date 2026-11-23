# -*- coding: utf-8 -*-
"""核对三个 SQL 脚本的表/对象清单，与运行库实际状态对比。"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")


def tables_of(path):
    s = open(path, encoding="utf-8").read()
    return re.findall(r"(?i)create\s+table\s+(?:if\s+not\s+exists\s+)?`?(\w+)`?", s)


for f in ["db/schema.sql", "init_database.sql", "init_verify.sql"]:
    t = tables_of(f)
    print(f"{f}: {len(t)} tables")
    print("   ", t)
    s = open(f, encoding="utf-8").read()
    for kind in ("view", "trigger", "procedure"):
        found = re.findall(rf"(?i)create\s+(?:algorithm=\w+\s+)?(?:definer=`[^`]*`@`[^`]*`\s+)?(?:sql\s+security\s+\w+\s+)?{kind}\s+`?(\w+)`?", s)
        if found:
            print(f"    {kind}: {found}")
