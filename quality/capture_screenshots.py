#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""证据截图采集 · 智能快递柜管理系统（R3b）

为什么不用 Selenium/Playwright：
    本机两者都没装（见 quality/reports/00_env_facts.txt 的 packages 一栏）。
    但 Edge 自带 DevTools 协议（CDP），Node 也自带 WebSocket。
    所以这里用「启动 headless Edge + 原生 CDP」抓**真实页面**截图，
    不做任何 DOM 伪造、不拼静态 HTML —— 截出来的就是浏览器此刻渲染的样子。

采集内容（对应任务第 7 条）：
    · 触屏端 kiosk
    · H5 AI 推荐（真实调 /api/ai/pack-recommend 后截图）
    · 地图找柜
    · 支付
    · 管理端
    · 质量报告（把 quality/reports 的汇总渲染成一张给评委看的图）

产物：
    evidence/screenshots/*.png
    evidence/screenshots/_capture_log.json   每张图的 URL / 视口 / 是否白屏 / 控制台异常
    evidence/screenshots/INDEX.md            人读索引（由本脚本生成）

用法：
    python quality/capture_screenshots.py --host http://127.0.0.1:5000
    python quality/capture_screenshots.py --host http://127.0.0.1:5000 --only kiosk,mobile
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(ROOT, "evidence", "screenshots")
NODE_TOOLS = os.path.join(ROOT, "tools", "capture_cdp.js")

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for p in EDGE_CANDIDATES + CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def find_node():
    for cand in (shutil.which("node"),):
        if cand:
            return cand
    return None


def main():
    ap = argparse.ArgumentParser(description="截图采集（CDP）")
    ap.add_argument("--host", default="http://127.0.0.1:5000")
    ap.add_argument("--only", default="", help="只抓指定页面，逗号分隔")
    ap.add_argument("--port", type=int, default=9337)
    args = ap.parse_args()

    os.makedirs(OUTDIR, exist_ok=True)
    browser = find_browser()
    node = find_node()
    if not browser:
        print("[!] 未找到 Edge/Chrome，无法截图")
        return 2
    if not node:
        print("[!] 未找到 node，无法驱动 CDP")
        return 2
    print(f" 浏览器 : {browser}")
    print(f" node   : {node}")

    try:
        h = urllib.request.urlopen(f"{args.host}/api/health", timeout=8)
        print(f" 服务   : {args.host} health={h.status}")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 服务不可用: {exc}")
        return 2

    cmd = [node, NODE_TOOLS, "--base", args.host, "--out", OUTDIR,
           "--port", str(args.port), "--browser", browser]
    if args.only:
        cmd += ["--only", args.only]
    print(" 执行   :", " ".join(cmd))
    rc = subprocess.call(cmd, cwd=ROOT)
    return rc


if __name__ == "__main__":
    sys.exit(main())
