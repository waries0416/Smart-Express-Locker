# -*- coding: utf-8 -*-
"""只读烟雾测试：直接用 test_client 打关键接口，确认当前库能否跑通（不写数据）。"""
import os
import sys

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))
os.environ["NOTIFY_WORKER"] = "0"

import app as app_module  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
c = app_module.app.test_client()

CASES = [
    ("GET", "/api/health", None),
    ("GET", "/api/stats/overview", None),
    ("GET", "/api/packages/1/detail", None),
    ("GET", "/api/cabinets/1/cell-summary", None),
    ("GET", "/api/business/cabinets/1/availability", None),
    ("GET", "/api/m/cabinets/nearby?q=CAB-001", None),
    ("POST", "/api/qr/ticket", {"cabinet_id": 1}),
    ("GET", "/", None),
    ("GET", "/admin/dashboard", None),
]

for method, path, body in CASES:
    fn = getattr(c, method.lower())
    r = fn(path, json=body) if body is not None else fn(path)
    txt = r.get_data(as_text=True)[:180].replace("\n", " ")
    print(f"{method:5s} {path:44s} -> {r.status_code} {txt}")
