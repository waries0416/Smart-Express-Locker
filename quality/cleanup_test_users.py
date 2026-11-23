# -*- coding: utf-8 -*-
"""清理压测/录制脚本遗留的孤儿测试用户。

背景（这是我自己造成的真实问题，记在这里）：
    `load_test_v2.py`、`retest_race_fixes.py`、`record_demo.js` 等脚本
    为了隔离数据，每次都用**随机手机号**新建用户，但清理时只删包裹、不删用户。
    跑了几十轮之后 t_user 从种子的 120 涨到 2040，
    导致：① 全量测试从 12 秒劣化到 60~160 秒；
          ② 测试间出现外键失败 / 死锁等间歇性 ERROR（资源竞争）。
    这不是"测试用例有 bug"，是**我的脚本在污染共享数据库**。

清理规则（保守，宁少删不误删）：
    · 只删**没有关联包裹**的用户（有包裹的一律不动，避免外键断裂）；
    · 只删名字匹配测试特征的（并发*/压测*/复测*/用户*/收件人*）；
    · 保留 user_id <= 120 的种子用户（演示数据，PPT/截图依赖它）；
    · 保留手机号为演示账号 15800000001 的用户。

用法：
    python quality/cleanup_test_users.py --dry-run     # 只看会删多少
    python quality/cleanup_test_users.py               # 真删
"""
import argparse
import os
import sys

ROOT = r"D:\softwaretest"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SEED_MAX_ID = 120
DEMO_PHONES = {"15800000001", "13900000001"}
NAME_LIKES = ("并发%", "压测%", "复测%", "用户%", "收件人%")

WHERE = (
    " u.user_id > %s "
    " AND u.phone NOT IN ({phones}) "
    " AND u.user_id NOT IN (SELECT user_id FROM t_package WHERE user_id IS NOT NULL) "
    " AND ({name_clause}) "
)


def build():
    phones = ",".join(["%s"] * len(DEMO_PHONES))
    name_clause = " OR ".join(["u.name LIKE %s"] * len(NAME_LIKES))
    sql = "FROM t_user u WHERE" + WHERE.format(phones=phones, name_clause=name_clause)
    params = [SEED_MAX_ID] + list(DEMO_PHONES) + list(NAME_LIKES)
    return sql, params


def main():
    ap = argparse.ArgumentParser(description="清理孤儿测试用户")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删除")
    args = ap.parse_args()
    import db

    sql, params = build()
    total_before = db.query_one("SELECT COUNT(*) n FROM t_user")["n"]
    cand = db.query_one("SELECT COUNT(*) n " + sql, params)["n"]
    seed = db.query_one("SELECT COUNT(*) n FROM t_user WHERE user_id<=%s",
                        (SEED_MAX_ID,))["n"]

    print("=" * 70)
    print(" 孤儿测试用户清理")
    print("=" * 70)
    print(f"  t_user 现有总数 : {total_before}")
    print(f"  种子用户(<= {SEED_MAX_ID}) : {seed}")
    print(f"  可清理孤儿用户  : {cand}")
    print(f"  清理后预计      : {total_before - cand}")

    if args.dry_run:
        print("\n  [dry-run] 未执行删除")
        return 0

    if not cand:
        print("\n  没有需要清理的用户")
        return 0

    deleted = db.execute("DELETE u " + sql, params)
    after = db.query_one("SELECT COUNT(*) n FROM t_user")["n"]
    print(f"\n  已删除 {deleted} 个孤儿用户，t_user 现在 {after}")
    if after != total_before - cand:
        print(f"  ⚠️ 预期 {total_before - cand}，实际 {after}，请核对")
        return 2
    print("  ✅ 清理完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
