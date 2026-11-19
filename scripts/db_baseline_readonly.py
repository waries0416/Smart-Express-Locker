# -*- coding: utf-8 -*-
"""只读核对数据库基线：表清单、行数、视图/触发器/存储过程、接口返回。
不修改任何数据（仅 SELECT / SHOW）。"""
import json
import sys

import pymysql

sys.stdout.reconfigure(encoding="utf-8")

CONN = dict(host="127.0.0.1", port=3306, user="root", password="123456",
            database="smart_locker", charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor, autocommit=True)


def main():
    cn = pymysql.connect(**CONN)
    cur = cn.cursor()

    cur.execute("""SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES
                   WHERE TABLE_SCHEMA='smart_locker' ORDER BY TABLE_TYPE, TABLE_NAME""")
    rows = cur.fetchall()
    tables = [r["TABLE_NAME"] for r in rows if r["TABLE_TYPE"] == "BASE TABLE"]
    views = [r["TABLE_NAME"] for r in rows if r["TABLE_TYPE"] == "VIEW"]
    print("BASE TABLES:", len(tables))
    print(tables)
    print("VIEWS:", views)

    cur.execute("""SELECT TRIGGER_NAME FROM information_schema.TRIGGERS
                   WHERE TRIGGER_SCHEMA='smart_locker'""")
    print("TRIGGERS:", [r["TRIGGER_NAME"] for r in cur.fetchall()])
    cur.execute("""SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES
                   WHERE ROUTINE_SCHEMA='smart_locker'""")
    print("ROUTINES:", [(r["ROUTINE_NAME"], r["ROUTINE_TYPE"]) for r in cur.fetchall()])
    cur.execute("""SELECT COUNT(*) c FROM information_schema.STATISTICS
                   WHERE TABLE_SCHEMA='smart_locker'""")
    print("INDEX ROWS:", cur.fetchone()["c"])

    print("--- row counts ---")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) c FROM `{t}`")
        print(f"  {t:22s} {cur.fetchone()['c']}")

    print("--- demo account 15800000001 ---")
    cur.execute("SELECT user_id, name, phone FROM t_user WHERE phone='15800000001'")
    u = cur.fetchone()
    print("  user:", u)
    if u:
        cur.execute("""SELECT p.package_id, cab.cabinet_code, c.cell_code, p.pickup_code,
                              p.status, p.overtime_fee, p.overtime_fee_paid
                       FROM t_package p
                       JOIN t_cabinet cab ON cab.cabinet_id=p.cabinet_id
                       JOIN t_cell c ON c.cell_id=p.cell_id
                       WHERE p.user_id=%s
                       ORDER BY p.package_id DESC LIMIT 12""", (u["user_id"],))
        for r in cur.fetchall():
            print("   ", r)

    print("--- courier E00001 ---")
    cur.execute("SELECT courier_id, employee_no, name, phone FROM t_courier WHERE employee_no='E00001'")
    print("  ", cur.fetchone())

    print("--- admins (from code, not DB) ---")
    cn.close()


main()
