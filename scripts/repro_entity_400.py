# -*- coding: utf-8 -*-
"""复现 test_entity_mutation_allowed_with_admin 的 400，打印服务端返回原因。"""
import os
import sys

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))
os.environ["NOTIFY_WORKER"] = "0"

import app as app_module  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
c = app_module.app.test_client()
r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
print("login:", r.status_code, r.get_json())
r = c.post("/api/companies", json={"company_code": "ZZTEST", "company_name": "门禁回归测试"})
print("create:", r.status_code, r.get_json())
if r.status_code == 201:
    nid = r.get_json()["id"]
    print("delete:", c.delete(f"/api/companies/{nid}").status_code)
