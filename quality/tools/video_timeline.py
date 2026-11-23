# -*- coding: utf-8 -*-
"""按实际装配顺序与实测段长，算出成片里每段的精确时间码。

用途：把 docs/10-静音演示视频分镜与复现.md 里手写的时间码换成实数，
避免"文档说 00:32 起、实际 00:30 起"这种对不上的情况。
"""
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
import imageio_ffmpeg

BUILD = r"D:\softwaretest\quality\logs\video-build"
SHOTS = r"D:\softwaretest\quality\logs\video-shots"
ff = imageio_ffmpeg.get_ffmpeg_exe()


def dur(path):
    r = subprocess.run([ff, "-hide_banner", "-i", path],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr or "")
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def tc(sec):
    m, s = divmod(sec, 60)
    return f"{int(m):02d}:{s:05.2f}"[:8]


def main():
    with open(os.path.join(SHOTS, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    titles = {s["id"]: s["title"] for s in manifest["scenes"]}

    order = ["00_intro.mp4"]
    for sid in ["01_kiosk_home", "02_admin_302", "03_admin_dashboard",
                "04_kiosk_pickup", "05_kiosk_expired", "06_mobile_login",
                "07_mobile_ai", "08_mobile_map", "09_mobile_pay",
                "10_admin_payment", "11_admin_matrix"]:
        order.append(f"card_{sid}.mp4")
        order.append(f"clip_{sid}.mp4")
    order.append("99_outro.mp4")

    t = 0.0
    print(f"{'段':<32}{'起':>10}{'止':>10}{'时长':>8}")
    print("-" * 62)
    for name in order:
        p = os.path.join(BUILD, name)
        if not os.path.exists(p):
            print(f"{name:<32}  缺失")
            continue
        d = dur(p)
        label = name
        if name.startswith("card_"):
            sid = name[5:-4]
            label = f"章节卡 {sid} · {titles.get(sid,'')[:18]}"
        elif name.startswith("clip_"):
            sid = name[5:-4]
            label = f"真实画面 {sid}"
        elif name == "00_intro.mp4":
            label = "片头"
        elif name == "99_outro.mp4":
            label = "片尾"
        print(f"{label:<32}{tc(t):>10}{tc(t+d):>10}{d:>7.1f}s")
        t += d
    print("-" * 62)
    print(f"合计 {t:.2f}s = {t/60:.2f} 分钟")


if __name__ == "__main__":
    main()
