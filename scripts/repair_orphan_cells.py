# 格口状态一致性自愈脚本：把「OCCUPIED 但名下没有任何活动包裹」的格口复位为 FREE
#
# 背景（R9b 实测 2026-11-18）：
#   演示库里有 54 个格口 status='OCCUPIED'，但格口下没有 STORED/EXPIRED/EXCEPTION
#   包裹。这是历史压测 / e2e 收尾"只删包裹、没复位格口"留下的残留（正是它让
#   CAB-001/002/003 的 SMALL 格口 12/12 占满，test_pickup_payment_gate 三个用例
#   存件报 409「当前无可用格口」）。
#   这些格口不会丢数据（本来就没有包裹），但会：
#     · 管理端格口矩阵把空格口显示成"占用"，可用格口统计偏小、演示看起来"柜满了"；
#     · 任何"按柜体存件"的调用方误判该柜体已满。
#
# 安全边界：
#   · 只处理「OCCUPIED 且名下没有任何活动包裹」的格口；有包裹的格口一律不动；
#   · UPDATE 里带 NOT EXISTS 再判一次，避免与并发存件抢同一个格口（幂等，可反复跑）；
#   · 默认 dry-run 只打印，不改库；确认后加 --apply 才真正更新。
#
# 用法：
#   python scripts/repair_orphan_cells.py                 # 只体检（dry-run）
#   python scripts/repair_orphan_cells.py --apply         # 真正修复
#   python scripts/repair_orphan_cells.py --cabinet CAB-001   # 只看/只修某个柜体
import argparse
import os
import sys

# 与 reset_demo_data.py 一致的 GBK/重定向兜底（本脚本不打印 ¥，但保持同类脚本行为一致）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

import db  # noqa: E402

ACTIVE = "('STORED','EXPIRED','EXCEPTION')"

ORPHAN_SELECT = f"""
    SELECT cab.cabinet_code, cell.cell_id, cell.cell_code, cell.size_type
    FROM t_cell cell
    JOIN t_cabinet cab ON cab.cabinet_id = cell.cabinet_id
    WHERE cell.status = 'OCCUPIED'
      AND NOT EXISTS (SELECT 1 FROM t_package p
                      WHERE p.cell_id = cell.cell_id AND p.status IN {ACTIVE})
      {{cab_filter}}
    ORDER BY cab.cabinet_code, cell.cell_code
"""


def main():
    ap = argparse.ArgumentParser(description="把无主占用格口复位为 FREE（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正写库；不加则只打印")
    ap.add_argument("--cabinet", default=None, help="只处理指定柜体编号，如 CAB-001")
    args = ap.parse_args()

    cab_filter, params = "", ()
    if args.cabinet:
        cab_filter, params = "AND cab.cabinet_code = %s", (args.cabinet,)
    rows = db.query(ORPHAN_SELECT.format(cab_filter=cab_filter), params)

    if not rows:
        print("[*] 没有需要修复的格口：所有 OCCUPIED 格口都挂着活动包裹 ✅")
        return 0

    print(f"[*] 发现 {len(rows)} 个「OCCUPIED 但无活动包裹」的格口：")
    for r in rows:
        print(f"    {r['cabinet_code']} {r['cell_code']:<4} ({r['size_type']}) cell_id={r['cell_id']}")

    if not args.apply:
        print("\n[dry-run] 未修改任何数据。确认无误后加 --apply 执行修复。")
        return 0

    n = db.execute(
        f"""UPDATE t_cell cell SET cell.status='FREE'
            WHERE cell.status='OCCUPIED'
              AND NOT EXISTS (SELECT 1 FROM t_package p
                              WHERE p.cell_id = cell.cell_id AND p.status IN {ACTIVE})
              {cab_filter}""", params)
    print(f"\n[ok] 已复位 {n} 个格口为 FREE")
    left = db.query_one(ORPHAN_SELECT.format(cab_filter=cab_filter).replace(
        "SELECT cab.cabinet_code, cell.cell_id, cell.cell_code, cell.size_type",
        "SELECT COUNT(*) AS n"), params)["n"]
    print(f"[*] 复查：仍残留 {left} 个无主占用格口（0 = 已全部修复）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
