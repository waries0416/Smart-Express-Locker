#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Office 文档结构快照与差异比对（.docx / .pptx 通用）。

为什么需要这个工具
------------------
改 Office 文件时，只校验"目标数字改对了"是不够的 —— 它只能证明**该改的改了**，
证明不了**别的内容还在**。真实事故：某次用 python-pptx 改 PPT 备注，
因为误用 `paragraph.runs` 的代理对象（每次访问都构造新 proxy，
`run is not first_run` 永远为真），把刚写入的备注又清空成了 0 字；
当时的自检只扫"目标数字是否存在"，数字没丢 → 自检通过 → 缺陷被带到交付物里。

本工具的思路：把文档拆成**按位置索引的文本条目**（段落/表格单元格/形状/备注），
改前改后各存一份快照，逐条比对。差异条数必须等于预期的改动条数：
多了 = 误伤了别处，少了 = 改动没生效。两个方向都能抓出来。

用法
----
    # 1) 改前：存快照
    python quality/tools/office_snapshot_diff.py snapshot \
        deliverables/xxx.pptx --out logs/before.json

    # 2) 改文件（你自己的 python-docx / python-pptx 脚本）

    # 3) 改后：存快照
    python quality/tools/office_snapshot_diff.py snapshot \
        deliverables/xxx.pptx --out logs/after.json

    # 4) 比对：断言"恰好改了 2 条"
    python quality/tools/office_snapshot_diff.py diff \
        logs/before.json logs/after.json --expect 2

退出码：0 = 符合预期；1 = 差异数与 --expect 不符；2 = 输入/解析错误。

设计取舍
--------
· 只比较**文本内容**，不比较样式/字体/配色 —— 样式改动不产生条目差异，
  这是有意的：本工具用于校验"内容有没有被误伤"，不是做视觉回归。
· 每条记录带**稳定定位键**（如 `slides[13].notes`、`body[42]`），
  差异输出直接给位置，便于人工复核，也便于写进提交信息。
· 文档整体文本长度（`total_chars`）单独记录：即使逐条 diff 全部匹配，
  只要总字数变了也要能看出来 —— 这是上一次事故的直接防线。
· 不写死文件名，任何 .docx/.pptx 都能处理。
"""
import argparse
import json
import os
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SNAPSHOT_VERSION = 1


# --------------------------------------------------------------------------
# 快照：docx
# --------------------------------------------------------------------------
def snapshot_docx(path):
    """拆 .docx：正文段落 + 表格单元格 + 页眉页脚。

    定位键约定：
      body[i]                     第 i 个正文段落的整段文本
      tables[t].r[r].c[c]         第 t 张表第 r 行第 c 列
      sections[s].header/footer   第 s 节的页眉/页脚
    """
    from docx import Document

    doc = Document(path)
    entries = {}

    for i, para in enumerate(doc.paragraphs):
        entries[f"body[{i}]"] = para.text

    for t, table in enumerate(doc.tables):
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row.cells):
                entries[f"tables[{t}].r[{r}].c[{c}]"] = cell.text

    for s, section in enumerate(doc.sections):
        for name, part in (("header", section.header), ("footer", section.footer)):
            try:
                texts = [p.text for p in part.paragraphs]
                entries[f"sections[{s}].{name}"] = "\n".join(texts)
            except Exception:  # noqa: BLE001  某些节没有页眉页脚
                pass

    meta = {"paragraphs": len(doc.paragraphs), "tables": len(doc.tables),
            "sections": len(doc.sections)}
    return entries, meta


# --------------------------------------------------------------------------
# 快照：pptx
# --------------------------------------------------------------------------
def snapshot_pptx(path):
    """拆 .pptx：每页的形状文本 + 表格单元格 + 演讲者备注。

    定位键约定：
      slides[i].shape[name]       第 i 页（0 基）某形状的文本
      slides[i].table[t].r[r].c[c] 第 i 页某表格的单元格
      slides[i].notes             第 i 页演讲者备注整段文本

    ⚠️ 为什么备注要单独记：备注是**最容易在改正文时被误伤**的地方，
       而且它不出现在幻灯片画面上，肉眼检查不到，只有回读才能发现。
    """
    from pptx import Presentation

    prs = Presentation(path)
    entries = {}

    for i, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            try:
                if shape.has_text_frame:
                    entries[f"slides[{i}].shape[{shape.name}]"] = shape.text_frame.text
                if getattr(shape, "has_table", False) and shape.has_table:
                    for r, row in enumerate(shape.table.rows):
                        for c, cell in enumerate(row.cells):
                            entries[f"slides[{i}].table[{shape.name}].r[{r}].c[{c}]"] = cell.text
            except Exception:  # noqa: BLE001
                continue
        try:
            notes = slide.notes_slide.notes_text_frame.text
            entries[f"slides[{i}].notes"] = notes
        except Exception:  # noqa: BLE001  没有备注页
            entries[f"slides[{i}].notes"] = ""

    meta = {"slides": len(prs.slides)}
    return entries, meta


# --------------------------------------------------------------------------
# 通用入口
# --------------------------------------------------------------------------
def build_snapshot(path):
    if not os.path.exists(path):
        raise SystemExit(f"[!] 文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        entries, meta = snapshot_docx(path)
    elif ext == ".pptx":
        entries, meta = snapshot_pptx(path)
    else:
        raise SystemExit(f"[!] 不支持的扩展名 {ext}（只支持 .docx / .pptx）")

    total_chars = sum(len(v) for v in entries.values())
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "source": os.path.abspath(path),
        "file_name": os.path.basename(path),
        "kind": ext.lstrip("."),
        "meta": meta,
        "total_chars": total_chars,
        "entry_count": len(entries),
        "entries": entries,
    }


def cmd_snapshot(args):
    snap = build_snapshot(args.input)
    out = args.out or (args.input + ".snapshot.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(snap, fh, ensure_ascii=False, indent=2)
    print(f"[snapshot] {snap['file_name']} ({snap['kind']})")
    print(f"  条目数 : {snap['entry_count']}")
    print(f"  总字数 : {snap['total_chars']}（这是防'整体被清空'的第一道防线）")
    print(f"  结构   : {snap['meta']}")
    print(f"  落盘   : {out}")
    return 0


def diff_snapshots(before, after):
    """逐条比对，返回 (changes, stats)。

    change 类型：
      added     after 有、before 没有（新增条目，如新增段落）
      removed   before 有、after 没有（条目消失，最危险：可能是误删整段）
      modified  两边都有但文本不同
    """
    b, a = before["entries"], after["entries"]
    changes = []
    for key in b:
        if key not in a:
            changes.append({"type": "removed", "key": key,
                            "before": b[key], "after": None})
        elif a[key] != b[key]:
            changes.append({"type": "modified", "key": key,
                            "before": b[key], "after": a[key]})
    for key in a:
        if key not in b:
            changes.append({"type": "added", "key": key,
                            "before": None, "after": a[key]})
    stats = {
        "before_entry_count": before["entry_count"],
        "after_entry_count": after["entry_count"],
        "before_total_chars": before["total_chars"],
        "after_total_chars": after["total_chars"],
        "char_delta": after["total_chars"] - before["total_chars"],
        "added": sum(1 for c in changes if c["type"] == "added"),
        "removed": sum(1 for c in changes if c["type"] == "removed"),
        "modified": sum(1 for c in changes if c["type"] == "modified"),
        "total": len(changes),
    }
    return changes, stats


def _preview(text, n=110):
    if text is None:
        return "(不存在)"
    flat = text.replace("\n", "\\n")
    return flat if len(flat) <= n else flat[:n] + f"…(+{len(flat) - n})"


def cmd_diff(args):
    with open(args.before, encoding="utf-8") as fh:
        before = json.load(fh)
    with open(args.after, encoding="utf-8") as fh:
        after = json.load(fh)

    if before.get("file_name") != after.get("file_name"):
        print(f"[!] 警告：两份快照来自不同文件 "
              f"({before.get('file_name')} vs {after.get('file_name')})")

    changes, stats = diff_snapshots(before, after)

    print("=" * 78)
    print(f" 快照差异 · {after.get('file_name')}")
    print("=" * 78)
    print(f"  条目数 : {stats['before_entry_count']} → {stats['after_entry_count']}")
    print(f"  总字数 : {stats['before_total_chars']} → {stats['after_total_chars']}"
          f"  ({stats['char_delta']:+d})")
    print(f"  差异   : 新增 {stats['added']} · 删除 {stats['removed']} · "
          f"修改 {stats['modified']} · 合计 {stats['total']}")

    if changes:
        print("\n--- 差异清单 ---")
        for i, c in enumerate(changes, 1):
            tag = {"added": "＋新增", "removed": "－删除", "modified": "～修改"}[c["type"]]
            print(f"  {i:>2}. [{tag}] {c['key']}")
            print(f"        改前: {_preview(c['before'])}")
            print(f"        改后: {_preview(c['after'])}")

    # ---- 核心断言：差异数必须等于预期 ----
    print("\n" + "-" * 78)
    if args.expect is None:
        print(f"  未指定 --expect，仅报告差异数 {stats['total']}（不做断言）")
        return 0
    ok = stats["total"] == args.expect
    if ok:
        print(f"  ✅ 差异数 {stats['total']} == 预期 {args.expect}，符合预期")
    else:
        print(f"  ❌ 差异数 {stats['total']} != 预期 {args.expect}  —— 断言失败")
        if stats["total"] < args.expect:
            print("     差异偏少：改动可能没生效（检查是否写到了错误的 run/段落上，")
            print("     尤其是 python-pptx 的 paragraph.runs 代理对象问题）。")
        else:
            print("     差异偏多：**可能误伤了别处**（例如把某页备注清空、")
            print("     或多改了一个段落）。逐条看上面的差异清单确认。")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(
        description="Office 文档结构快照与差异比对（.docx / .pptx）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法\n----")[-1])
    sub = ap.add_subparsers(dest="cmd", required=True)

    s1 = sub.add_parser("snapshot", help="生成结构快照 JSON")
    s1.add_argument("input", help=".docx 或 .pptx 路径")
    s1.add_argument("--out", default="", help="输出 JSON 路径（默认 <input>.snapshot.json）")
    s1.set_defaults(func=cmd_snapshot)

    s2 = sub.add_parser("diff", help="比对两份快照并断言差异数")
    s2.add_argument("before", help="改前快照 JSON")
    s2.add_argument("after", help="改后快照 JSON")
    s2.add_argument("--expect", type=int, default=None,
                    help="预期差异条数；不符则退出码 1")
    s2.set_defaults(func=cmd_diff)

    args = ap.parse_args()
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[!] 出错: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
