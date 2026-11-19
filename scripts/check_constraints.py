# -*- coding: utf-8 -*-
"""核对文档声称的约束数量：CHECK / FOREIGN KEY / UNIQUE KEY。"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
s = open("db/schema.sql", encoding="utf-8").read()
checks = re.findall(r"(?i)CONSTRAINT\s+(\w*chk\w*)\s+CHECK", s)
fks = re.findall(r"(?i)CONSTRAINT\s+(fk_\w+)\s+FOREIGN\s+KEY", s)
uks = re.findall(r"(?i)UNIQUE\s+KEY\s+(\w+)", s)
pks = re.findall(r"(?i)PRIMARY\s+KEY", s)
idx = re.findall(r"(?i)INDEX\s+(\w+)|KEY\s+(idx_\w+)", s)
print("CHECK constraints:", len(checks))
print("  ", checks)
print("FOREIGN KEY:", len(fks))
print("  ", fks)
print("UNIQUE KEY:", len(uks))
print("  ", uks)
print("non-PK INDEX:", len(idx))
print("PRIMARY KEY decls:", len(pks))
