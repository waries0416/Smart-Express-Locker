#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""R2b 前端收尾核对：机械校验三端 API 封装对 15 个创新端点的覆盖。

只读脚本，不改任何业务文件。输出覆盖矩阵 + 退出码（缺项则非 0）。
用法： python tools/check_innovation_coverage.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = {
    "api.js": os.path.join(ROOT, "frontend", "js", "api.js"),
    "api-mobile.js": os.path.join(ROOT, "frontend", "mobile", "js", "api-mobile.js"),
}

# (端点, 方法, 契约要求的前端封装应出现的路径字面量正则)
ENDPOINTS = [
    ("/api/ai/health",                      "GET",  r'/ai/health'),
    ("/api/ai/pack-recommend",              "POST", r'/ai/pack-recommend'),
    ("/api/ai/chat",                        "POST", r'/ai/chat'),
    ("/api/map/config",                     "GET",  r'/map/config'),
    ("/api/cabinets/nearby",                "GET",  r'/cabinets/nearby'),
    ("/api/location/resolve",               "GET",  r'/location/resolve'),
    ("/api/pack-materials",                 "GET",  r'/pack-materials[`"\']'),
    ("/api/pack-materials/{id}",            "PUT",  r'/pack-materials/\$\{'),
    ("/api/courier/packaging-tasks",        "GET",  r'/courier/packaging-tasks'),
    ("/api/courier/packaging-tasks/{id}/done", "POST", r'/courier/packaging-tasks/\$\{[^}]+\}/done'),
    ("/api/pay/create",                     "POST", r'/pay/create'),
    ("/api/pay/{id}",                       "GET",  r'/pay/\$\{'),
    ("/api/pay/{id}/mock-succeed",          "POST", r'/pay/\$\{[^}]+\}/mock-succeed'),
    ("/api/pay/records",                    "GET",  r'/pay/records'),
    ("/api/pay/notify/alipay",              "POST", r'/pay/notify/alipay'),
]

# 服务端到服务端回调，前端不调用（契约 §0.2 例外）
SERVER_ONLY = {"/api/pay/notify/alipay"}


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def check_xkiosk():
    """全前端扫描 X-Kiosk-Token 实际发送（排除注释/文档说明）。"""
    bad = []
    for base, _dirs, names in os.walk(os.path.join(ROOT, "frontend")):
        for n in names:
            if not n.endswith((".js", ".html")):
                continue
            p = os.path.join(base, n)
            for i, line in enumerate(read(p).splitlines(), 1):
                if re.search(r'X-Kiosk-Token', line, re.I):
                    # 注释行（* // /* <!-- ）属于说明性文字，不算发送
                    stripped = line.strip()
                    is_comment = stripped.startswith(("*", "//", "/*", "<!--", "#"))
                    bad.append((os.path.relpath(p, ROOT), i, stripped, is_comment))
    return bad


def main():
    srcs = {k: read(v) for k, v in FILES.items()}
    print("=" * 78)
    print("创新端点覆盖矩阵（前端封装）")
    print("=" * 78)
    missing_total = []
    for ep, method, pat in ENDPOINTS:
        cells = []
        for name, src in srcs.items():
            hit = bool(re.search(pat, src))
            cells.append(("OK" if hit else "--", name))
        covered = [n for s, n in cells if s == "OK"]
        tag = "服务端专用(前端不调)" if ep in SERVER_ONLY else ("覆盖 %d/%d" % (len(covered), len(srcs)))
        mark = "  " if covered or ep in SERVER_ONLY else "!!"
        print("%s %-42s %-5s %s  %s" % (
            mark, ep, method, "/".join("%s:%s" % (n, s) for s, n in cells), tag))
        if not covered and ep not in SERVER_ONLY:
            missing_total.append((ep, method))

    print()
    print("=" * 78)
    print("X-Kiosk-Token 残留扫描")
    print("=" * 78)
    bad = check_xkiosk()
    if not bad:
        print("  [OK] frontend/ 下无任何 X-Kiosk-Token 出现")
    for path, ln, text, is_comment in bad:
        kind = "注释说明" if is_comment else "!! 实际发送"
        print("  %-14s %s:%d  %s" % (kind, path, ln, text[:90]))
    real_send = [b for b in bad if not b[3]]

    print()
    print("=" * 78)
    print("鉴权头一致性")
    print("=" * 78)
    core = read(os.path.join(ROOT, "frontend", "js", "api-core.js"))
    ok_bearer = bool(re.search(r'Authorization:\s*"Bearer "\s*\+\s*tk', core))
    print("  [%s] api-core.js authHdr() 返回 Authorization: Bearer <token>"
          % ("OK" if ok_bearer else "!!"))

    print()
    if missing_total or real_send or not ok_bearer:
        print("结果：存在缺口 -> %s" % (missing_total or real_send or ["authHdr"]))
        return 1
    print("结果：15 个端点全部覆盖（其中 notify/alipay 属服务端回调，前端不调用）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
