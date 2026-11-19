# -*- coding: utf-8 -*-
"""工具自测：在**副本**上改动，验证 office_snapshot_diff.py 能否精确抓住改动。

三个用例，覆盖工具设计要防的三类事故：
  case A 正常改一处   → 差异应恰好 1 条（modified）
  case B 误伤备注     → 除目标改外，备注被清空 → 差异数 > 预期，必须被 --expect 抓住
  case C 什么都没改   → 差异应恰好 0 条

全部在 logs/snapshot-selftest/ 下的副本上做，不动 deliverables/ 原件。
"""
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"D:\softwaretest")
PY = sys.executable
TOOL = ROOT / "quality" / "tools" / "office_snapshot_diff.py"
WORK = ROOT / "logs" / "snapshot-selftest"
SRC = ROOT / "deliverables" / "智能快递柜系统答辩.pptx"


def run(*args):
    r = subprocess.run([PY, str(TOOL), *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def snapshot(path, out):
    code, log = run("snapshot", path, "--out", out)
    assert code == 0, log
    return out


def main():
    WORK.mkdir(parents=True, exist_ok=True)

    # ---------- case C：完全不动 ----------
    p0 = WORK / "c_untouched.pptx"
    shutil.copy2(SRC, p0)
    snap_a = snapshot(p0, WORK / "c_a.json")
    snap_b = snapshot(p0, WORK / "c_b.json")
    code, log = run("diff", snap_a, snap_b, "--expect", "0")
    print("=" * 70)
    print("case C · 什么都没改 → 期望差异 0")
    print("  exit=", code)
    print("  " + [l for l in log.splitlines() if "差异数" in l][-1].strip())
    assert code == 0, log

    # ---------- case A：正文改一处 ----------
    from pptx import Presentation
    p1 = WORK / "a_one_edit.pptx"
    shutil.copy2(SRC, p1)
    snap_a1 = snapshot(p1, WORK / "a_before.json")

    prs = Presentation(p1)
    target = prs.slides[13]                       # 第 14 页，质量页
    edited = False
    for sh in target.shapes:
        if sh.has_text_frame and "质量工具实测" in sh.text_frame.text:
            tf = sh.text_frame.paragraphs[0]
            tf.runs[0].text = tf.runs[0].text + "（自测标记）"
            edited = True
            break
    assert edited, "没找到目标段落"
    prs.save(p1)

    snap_a2 = snapshot(p1, WORK / "a_after.json")
    code, log = run("diff", snap_a1, snap_a2, "--expect", "1")
    print("=" * 70)
    print("case A · 正文改一处 → 期望差异 1")
    print("  exit=", code)
    for line in log.splitlines():
        if "差异数" in line or "个." in line or "改前:" in line or "改后:" in line:
            print("  " + line.strip())
    assert code == 0, log

    # ---------- case B：改一处 + 误伤备注（复刻真实事故） ----------
    p2 = WORK / "b_wipe_notes.pptx"
    shutil.copy2(SRC, p2)
    snap_b1 = snapshot(p2, WORK / "b_before.json")

    prs = Presentation(p2)
    slide = prs.slides[13]
    # 目标改动：追加一句话
    for sh in slide.shapes:
        if sh.has_text_frame and "质量工具实测" in sh.text_frame.text:
            tf = sh.text_frame.paragraphs[0]
            tf.runs[0].text = tf.runs[0].text + "（自测标记）"
            break
    # 误伤：把备注整段清空（上一版真实事故就是这个效果）
    notes_tf = slide.notes_slide.notes_text_frame
    notes_tf.paragraphs[0].runs[0].text = ""
    prs.save(p2)

    snap_b2 = snapshot(p2, WORK / "b_after.json")
    code, log = run("diff", snap_b1, snap_b2, "--expect", "1")
    print("=" * 70)
    print("case B · 改一处 + 备注被清空 → 期望差异 1，实际应为 2 → 必须报错")
    print("  exit=", code, "(非 0 才是正确行为)")
    for line in log.splitlines():
        if "差异数" in line or "notes" in line or "误伤" in line:
            print("  " + line.strip())
    assert code == 1, f"case B 应该断言失败，实际 exit={code}"

    print("\n" + "=" * 70)
    print("自测结论：三个用例全部符合预期")
    print(f"  产物在 {WORK}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
