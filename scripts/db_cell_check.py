# -*- coding: utf-8 -*-
"""只读：格口空闲分布，用于诊断测试前置条件。"""
import sys

import pymysql

sys.stdout.reconfigure(encoding="utf-8")
cn = pymysql.connect(host="127.0.0.1", user="root", password="123456",
                     database="smart_locker", charset="utf8mb4",
                     cursorclass=pymysql.cursors.DictCursor)
cur = cn.cursor()
cur.execute("SELECT status, COUNT(*) c FROM t_cell GROUP BY status")
print("cell status:", cur.fetchall())
cur.execute("SELECT size_type, status, COUNT(*) c FROM t_cell GROUP BY size_type, status")
print("by size:", cur.fetchall())
cur.execute("""SELECT cabinet_id, size_type, status, COUNT(*) c FROM t_cell
               GROUP BY cabinet_id, size_type, status
               HAVING cabinet_id IN (1,2,3) ORDER BY cabinet_id, size_type""")
for r in cur.fetchall():
    print(r)
cur.execute("SELECT MAX(package_id) FROM t_package")
print("max package_id:", cur.fetchone())
cn.close()
