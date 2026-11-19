# -*- coding: utf-8 -*-
"""把 CDP 抓到的真实操作帧装配成 8–12 分钟 1920x1080 H.264 静音演示视频。

设计要点（都是为了"不伪装"）：
  · 画面来源只有一个：quality/logs/video-shots/<场景>/frames/*.png，
    即 record_demo.js 驱动真实浏览器操作真实后端时逐帧抓下来的真实渲染。
    本脚本**不做任何静态幻灯片拼接**，只做"同一个真实画面在时间轴上的摆放"。
  · 每段前后加章节卡（纯文字，标场景名与对应讲稿时间码），
    让静音片也能看懂在讲哪一段 —— 字幕是辅助信息，不替代画面。
  · 片头 / 片尾用纯色底 + 文字，不冒充系统界面。
  · 总时长目标 8–12 分钟：通过"每个真实片段前后留白 + 章节卡"达成，
    **不是**靠放慢帧率或重复同一段来凑时长。

用法：
    python quality/tools/build_demo_video.py
    python quality/tools/build_demo_video.py --target-min 9
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOTS = os.path.join(ROOT, "quality", "logs", "video-shots")
WORK = os.path.join(ROOT, "quality", "logs", "video-build")
OUT = os.path.join(ROOT, "deliverables")

# 中文字体（Windows 自带）
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
FONT_REG = r"C:\Windows\Fonts\msyh.ttc"

# 讲稿第三节「演示视频分镜」的分段与配文
# intro_s / outro_s：该段进/出时的留白秒数（让观众读完字幕）
#
# ⚠️ 配文里**不要写死取件码**。取件码每次录制都会变（前一轮的已被取走，
#    reset_demo_data.py 按设计不会把 PICKED 改回 STORED），
#    写死就会造成"章节卡说 549548、画面却是 085093"这种字幕与画面对不上。
#    这里用 {stored_code} / {expired_code} 占位，构建时从 manifest 里取真实值。
SCENE_META = [
    ("01_kiosk_home", "一 · 柜机首页",
     "柜机只做两件高频的事：扫码取件、输码取件", 5.0, 4.0),
    ("02_admin_302", "二 · 端与端的边界",
     "未登录访问后台，由服务端 302 拦回登录页", 4.5, 4.0),
    ("03_admin_dashboard", "三 · 管理端看板",
     "7 个统计接口，指标卡与种子数据一一对应", 4.5, 4.0),
    ("04_kiosk_pickup", "四 · 取件主链路",
     "输入取件码 {stored_code}，格口号高亮并给 30 秒倒计时", 4.5, 4.5),
    ("05_kiosk_expired", "五 · 超时计费与支付闸门",
     "超时件 {expired_code} 先被 402 拦下，付完款才开柜", 4.5, 4.5),
    ("06_mobile_login", "六 · 手机端登录与待取",
     "登录后看到本人全部待取包裹与超时费", 4.5, 4.0),
    ("07_mobile_ai", "七 · AI 包装推荐",
     "模型只起草；未配 Key 时降级本地规则，仍完整可用", 4.5, 4.5),
    ("08_mobile_map", "八 · 地图找柜",
     "没有地图 Key 也不白屏：列表、空闲数、导航全保留", 4.5, 4.0),
    ("09_mobile_pay", "九 · 支付页",
     "金额由服务端快照，页面明示模拟支付不产生扣款", 4.5, 4.5),
    ("10_admin_payment", "十 · 支付流水与备包装清单",
     "流水与材料台账都能在后台核对", 4.5, 4.0),
    ("11_admin_matrix", "十一 · 格口矩阵",
     "按柜体实时状态着色，运营直接看到哪个柜子满了", 4.5, 4.5),
]


def find_ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        for c in ("ffmpeg", r"C:\ffmpeg\bin\ffmpeg.exe"):
            if shutil.which(c) or os.path.exists(c):
                return c
    raise SystemExit("[!] 找不到 ffmpeg：pip install imageio-ffmpeg")


def run(cmd, desc=""):
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(f"[!] 失败 {desc}")
        print((r.stderr or "")[-2500:])
        raise SystemExit(1)
    return r


def esc_text(s):
    """ffmpeg drawtext 需要转义的字符。"""
    return (s.replace("\\", "\\\\\\\\").replace(":", "\\:")
             .replace("'", "\\\\'").replace("%", "\\%")
             .replace(",", "\\,").replace("[", "\\[").replace("]", "\\]"))


def make_card(path, title, subtitle, seconds, kind="chapter"):
    """生成章节卡 / 片头 / 片尾（纯色底 + 文字，不冒充系统界面）。

    实现方式：用 Pillow 把文字画成整张 1920x1080 图，再让 ffmpeg 用它作为
    视频源。为什么不用 drawtext：
      该 ffmpeg 构建的 filter 参数解析对 Windows 路径里的 `:` 极其挑剔，
      `filter_complex_script` 选项也不存在（实测 "Unrecognized option"），
      转义在 PowerShell 下还会被再吃一层。用 Pillow 画字既绕开全部转义问题，
      又能精确控制中文字体，产出仍是 1920x1080 的 H.264 画面。
    """
    from PIL import Image, ImageDraw, ImageFont

    ff = find_ffmpeg()
    if kind == "chapter":
        bg = (17, 24, 39)
        big_size, sub_color = 64, (156, 163, 175)
    else:
        bg = (11, 18, 32)
        big_size, sub_color = 78, (156, 163, 175)

    img = Image.new("RGB", (1920, 1080), bg)
    d = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT_BOLD, big_size)
    f_sub = ImageFont.truetype(FONT_REG, 34)

    def center(text, font, y, fill):
        w = d.textlength(text, font=font)
        d.text(((1920 - w) / 2, y), text, font=font, fill=fill)

    center(title, f_big, 430, (255, 255, 255))
    center(subtitle, f_sub, 570, sub_color)
    # 极简装饰线，避免整片过空
    d.line([(760, 545), (1160, 545)], fill=(55, 65, 81), width=2)

    png = os.path.join(WORK, os.path.splitext(os.path.basename(path))[0] + ".png")
    img.save(png)

    run([ff, "-y", "-hide_banner", "-loglevel", "error",
         "-loop", "1", "-i", png,
         "-t", str(seconds), "-r", "30",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-an", path], desc=f"card {title}")
    return path


def build_scene_clip(ff, scene_id, in_s, out_s, dst):
    """把某场景的真实帧按 concat 清单编码成 1920x1080 片段，
    前后各留白 in_s / out_s 秒（用真实画面首帧/末帧定格，不是凭空造画面）。"""
    d = os.path.join(SHOTS, scene_id)
    concat = os.path.join(d, "concat.txt")
    frames = sorted(os.listdir(os.path.join(d, "frames")))
    if not frames:
        raise SystemExit(f"[!] {scene_id} 没有帧")
    first = os.path.join(d, "frames", frames[0]).replace("\\", "/")
    last = os.path.join(d, "frames", frames[-1]).replace("\\", "/")

    # 用 concat 清单里的实际时长；前后留白用首/末帧循环定格
    parts = []
    if in_s > 0:
        parts.append(f"file '{first}'\nduration {in_s:.3f}")
    with open(concat, encoding="utf-8") as fh:
        parts.append(fh.read().strip())
    if out_s > 0:
        parts.append(f"file '{last}'\nduration {out_s:.3f}")

    tmp_list = os.path.join(WORK, f"{scene_id}.txt")
    with open(tmp_list, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts) + "\n")

    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0b1220,"
          "fps=30,format=yuv420p")
    run([ff, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", tmp_list,
         "-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-an", dst], desc=f"scene {scene_id}")
    return dst


def main():
    ap = argparse.ArgumentParser(description="装配静音演示视频")
    ap.add_argument("--target-min", type=float, default=9.0,
                    help="目标时长（分钟），实际以素材为准，落在 8–12 之间")
    ap.add_argument("--out", default=os.path.join(
        OUT, "智能快递柜系统_静音演示视频.mp4"))
    args = ap.parse_args()

    ff = find_ffmpeg()
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    with open(os.path.join(SHOTS, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    have = {s["id"]: s for s in manifest["scenes"]}

    # 从 manifest 取本片实际使用的取件码，回填到章节卡配文里。
    # 这样字幕永远与画面对应，不会出现"卡上说 A 码、画面上是 B 码"。
    fmt = {
        "stored_code": (have.get("04_kiosk_pickup", {}) or {}).get("pickedCode", "—"),
        "expired_code": (have.get("05_kiosk_expired", {}) or {}).get("expiredCode", "—"),
    }
    print(f"[codes] 待取码={fmt['stored_code']} 超时码={fmt['expired_code']}")

    segments = []
    # ---------- 片头 ----------
    intro = os.path.join(WORK, "00_intro.mp4")
    make_card(intro,
              "智能快递柜管理系统",
              "三端分离 · 四组创新 · 静音演示（画面均为最终版本真实运行）",
              10.0, kind="intro")
    segments.append(intro)

    total = 10.0
    for scene_id, chapter, caption, in_s, out_s in SCENE_META:
        if scene_id not in have:
            print(f"[!] 缺少场景 {scene_id}，跳过")
            continue
        # 章节卡
        card = os.path.join(WORK, f"card_{scene_id}.mp4")
        make_card(card, chapter, caption.format(**fmt), 8.0)
        segments.append(card)
        total += 8.0

        clip = os.path.join(WORK, f"clip_{scene_id}.mp4")
        build_scene_clip(ff, scene_id, in_s, out_s, clip)
        seg_s = in_s + have[scene_id]["durationMs"] / 1000.0 + out_s
        segments.append(clip)
        total += seg_s
        print(f"  {scene_id:20s} +{seg_s:6.1f}s  (累计 {total/60:5.2f} min)")

    # ---------- 片尾 ----------
    outro = os.path.join(WORK, "99_outro.mp4")
    make_card(outro,
              "外部依赖挂了，业务不能挂",
              "质量证据：quality/reports/ ；截图：evidence/screenshots/INDEX.md",
              10.0, kind="outro")
    segments.append(outro)
    total += 10.0

    # ---------- 拼接 ----------
    list_path = os.path.join(WORK, "final_concat.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        for s in segments:
            fh.write(f"file '{s.replace(os.sep, '/')}'\n")

    # 先无损拼接，再统一重编码为 H.264 无音轨
    joined = os.path.join(WORK, "joined.mp4")
    run([ff, "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", list_path,
         "-c", "copy", joined], desc="concat")

    run([ff, "-y", "-hide_banner", "-loglevel", "error",
         "-i", joined,
         "-vf", "scale=1920:1080,fps=30,format=yuv420p",
         "-c:v", "libx264", "-preset", "medium", "-crf", "21",
         "-profile:v", "high", "-level", "4.1",
         "-movflags", "+faststart",
         "-an",                       # 关键：无音轨
         args.out], desc="final encode")

    size = os.path.getsize(args.out)
    print("\n" + "=" * 70)
    print(f"  产物 : {args.out}")
    print(f"  大小 : {size/1024/1024:.1f} MB")
    print(f"  总长 : 约 {total/60:.2f} 分钟")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
