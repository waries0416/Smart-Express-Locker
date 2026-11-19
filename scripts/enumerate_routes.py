# -*- coding: utf-8 -*-
"""从蓝图对象实际枚举路由，与 docs/03 文档表格的行数交叉核对。"""
import os
import sys

sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))
os.environ.setdefault("NOTIFY_WORKER", "0")

from flask import Blueprint  # noqa: E402

import app as app_module  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
app = app_module.app

groups = {}
for rule in app.url_map.iter_rules():
    ep = rule.endpoint
    if ep == "static":
        continue
    bp = ep.split(".")[0] if "." in ep else "(app)"
    methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
    groups.setdefault(bp, []).append((sorted(methods), str(rule), ep))

total_api = 0
for bp in sorted(groups):
    api = [r for r in groups[bp] if r[1].startswith("/api")]
    pages = [r for r in groups[bp] if not r[1].startswith("/api")]
    print(f"== {bp}: {len(groups[bp])} rules ({len(api)} api, {len(pages)} pages)")
    for m, path, ep in sorted(groups[bp], key=lambda x: x[1]):
        print(f"   {','.join(m):16s} {path:48s} {ep}")
    total_api += len(api)
print("\nTOTAL API rules:", total_api)
print("TOTAL rules:", sum(len(v) for v in groups.values()))
