# -*- coding: utf-8 -*-
"""核对文档中声称的代码行数 / 页面数量与实际文件是否一致。"""
import sys

sys.stdout.reconfigure(encoding="utf-8")

BE = ["backend/app.py", "backend/auth.py", "backend/business.py", "backend/entities.py",
      "backend/mobile_api.py", "backend/notify.py", "backend/qr_login.py",
      "backend/stats.py", "backend/db.py"]
FE = ["frontend/js/admin.js", "frontend/js/kiosk.js", "frontend/js/api.js",
      "frontend/mobile/js/app.js"]
CLAIM = {
    "backend/app.py": 196, "backend/auth.py": 326, "backend/business.py": 1020,
    "backend/entities.py": 725, "backend/mobile_api.py": 535, "backend/notify.py": 672,
    "backend/qr_login.py": 250, "backend/stats.py": 118, "backend/db.py": 94,
    "frontend/js/admin.js": 909, "frontend/js/kiosk.js": 797,
    "frontend/js/api.js": 256, "frontend/mobile/js/app.js": 624,
}
rows = []
for f in BE + FE:
    n = len(open(f, encoding="utf-8").read().splitlines())
    rows.append((f, n, CLAIM.get(f), n - CLAIM.get(f, n)))
for f, n, c, d in rows:
    flag = "OK" if d == 0 else f"DIFF {d:+d}"
    print(f"{f:32s} actual={n:5d} claimed={c:5d} {flag}")
print("total actual backend:", sum(len(open(f, encoding='utf-8').read().splitlines()) for f in BE))
print("total actual all    :", sum(n for _, n, _, _ in rows))
print("claimed total       :", sum(CLAIM.values()))
