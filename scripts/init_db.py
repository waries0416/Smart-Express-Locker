#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""数据库初始化 / 升级脚本（全新安装 与 旧库升级 两条路径）。

背景
----
仓库自带的 `init_database.sql` / `db/objects.sql` 里含有触发器与存储过程
（`BEGIN ... END` 复合语句），而这两个文件**没有** `DELIMITER` 声明，
也没有可供切分的分隔标记（`db/objects.sql` 用 `/*OBJECTS_SPLIT*/` 但
`init_database.sql` 用的是整段 dump 风格）。用 `mysql < file.sql` 直接导入
会在触发器处报 `ERROR 1064 ... near ''`，导致：
  · 触发器 / 存储过程没有建出来；
  · 后续语句被判为语法错误，`ERROR 1064` 之后的部分数据可能缺失。

本脚本用 Python 侧切分语句（识别引号、注释，并对 `CREATE TRIGGER` /
`CREATE PROCEDURE` / `CREATE FUNCTION` / `CREATE EVENT` 按 `DELIMITER`
语义原样提交），从而：
  · 全新安装：`--fresh` 直接读 `init_database.sql`（含 DDL + 全量演示数据）；
  · 旧库升级：`--migrate` 只跑 `db/migrations/*.sql`，幂等、不 DROP 业务数据。

用法
----
    python scripts/init_db.py --fresh          # 建库 + 建表 + 灌演示数据
    python scripts/init_db.py --migrate        # 仅执行未应用的迁移
    python scripts/init_db.py --migrate --dry-run
    python scripts/init_db.py --verify         # 校验表/行数/触发器/过程

连接参数全部来自 `config.DB_CONFIG`（即 DB_HOST / DB_PORT / DB_USER /
DB_PASSWORD / DB_NAME 环境变量）。
"""
import argparse
import glob
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from config import DB_CONFIG, get_conn_no_db  # noqa: E402

MIGRATION_DIR = os.path.join(BASE_DIR, "db", "migrations")

# 迁移记录表：旧库升级靠它判断"哪些迁移已经跑过"，保证可重复执行。
MIGRATION_TABLE = "t_schema_migration"


# ---------------------------------------------------------------------------
# SQL 语句切分
# ---------------------------------------------------------------------------
_DELIMITER_RE = re.compile(r"^\s*DELIMITER\s+(\S+)\s*$", re.IGNORECASE)
_COMPOUND_RE = re.compile(
    r"^\s*CREATE\s+(DEFINER\s*=\s*\S+\s+)?(TRIGGER|PROCEDURE|FUNCTION|EVENT)\b",
    re.IGNORECASE,
)


def split_statements(sql_text):
    """把 SQL 文本切成可逐条 `cursor.execute()` 的语句列表。

    处理规则：
      · 识别 `'...'` / `"..."` / `` `...` `` 引号，引号内的 `;` 不切分；
      · 识别 `--` 行注释与 `/* */` 块注释；
      · `CREATE TRIGGER/PROCEDURE/FUNCTION/EVENT`（复合语句）整条保留，
        内部 `;` 不切分——直到遇到行首 `END` 结尾的语句；
      · 支持显式 `DELIMITER xxx` 声明（有则按它切，没有按上面规则推断）。
    """
    stmts = []
    buf = []
    i = 0
    n = len(sql_text)
    quote = None
    delimiter = ";"
    # compound 模式：遇到 CREATE TRIGGER 等后，只有"行首 END"结束整条
    compound = False
    end_seen = False

    def flush():
        nonlocal buf, compound, end_seen
        s = "".join(buf).strip()
        # 纯注释/空语句不提交
        if s and not _is_only_comment(s):
            stmts.append(s)
        buf = []
        compound = False
        end_seen = False

    while i < n:
        ch = sql_text[i]

        # --- 引号内 ---
        if quote:
            buf.append(ch)
            if ch == "\\" and quote in ("'", '"'):
                if i + 1 < n:
                    buf.append(sql_text[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                # 处理 '' 转义
                if i + 1 < n and sql_text[i + 1] == quote:
                    buf.append(sql_text[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if ch in ("'", '"', "`"):
            quote = ch
            buf.append(ch)
            i += 1
            continue

        # --- 行注释 ---
        if ch == "-" and sql_text[i:i + 2] == "--":
            j = sql_text.find("\n", i)
            if j < 0:
                break
            i = j + 1
            buf.append("\n")
            continue

        if ch == "#":
            j = sql_text.find("\n", i)
            if j < 0:
                break
            i = j + 1
            buf.append("\n")
            continue

        # --- 块注释 ---
        if ch == "/" and sql_text[i:i + 2] == "/*":
            j = sql_text.find("*/", i + 2)
            if j < 0:
                break
            i = j + 2
            buf.append(" ")
            continue

        # --- DELIMITER 声明（按整行处理）---
        if ch == "D" or ch == "d":
            m = _DELIMITER_RE.match(sql_text[i:sql_text.find("\n", i) if "\n" in sql_text[i:] else n])
            if m and (i == 0 or sql_text[i - 1] == "\n"):
                flush()
                delimiter = m.group(1)
                j = sql_text.find("\n", i)
                i = n if j < 0 else j + 1
                continue

        # --- 语句结束符 ---
        if sql_text.startswith(delimiter, i):
            if compound:
                # 复合语句内部：只有"最后一行恰好是 END"时这个 ';' 才是
                # 整条 CREATE TRIGGER/PROCEDURE 的结束符；`END IF;` /
                # `END LOOP;` 等块内结束符照常吞掉。
                tail = "".join(buf).rstrip()
                last_line = tail.splitlines()[-1].strip() if tail else ""
                if last_line.upper() != "END":
                    buf.append(ch)
                    i += 1
                    continue
            flush()
            i += len(delimiter)
            continue

        buf.append(ch)
        i += 1

        # 进入复合语句模式（只有 CREATE TRIGGER/PROCEDURE/FUNCTION/EVENT）。
        if not compound:
            head = "".join(buf).lstrip()
            if _COMPOUND_RE.match(head):
                compound = True

    flush()
    return stmts


def _is_only_comment(s):
    s2 = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s2 = re.sub(r"(?m)^\s*(--|#).*$", "", s2)
    return not s2.strip()


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
def _connect(database=None):
    cfg = dict(DB_CONFIG)
    if database:
        cfg["database"] = database
    else:
        cfg.pop("database", None)
    import pymysql
    return pymysql.connect(
        host=cfg["host"], port=int(cfg["port"]), user=cfg["user"],
        password=cfg["password"], database=cfg.get("database") or None,
        charset="utf8mb4", autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def run_sql_file(path, dry_run=False, verbose=True, database=None):
    """执行一个 .sql 文件，返回 (ok_count, errors)。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    stmts = split_statements(text)
    if verbose:
        print(f"[SQL] {os.path.relpath(path, BASE_DIR)}: {len(stmts)} 条语句")

    if dry_run:
        for idx, s in enumerate(stmts, 1):
            print(f"  #{idx}: {s.splitlines()[0][:100]}")
        return len(stmts), []

    conn = _connect(database)
    ok, errors = 0, []
    try:
        with conn.cursor() as cur:
            for idx, s in enumerate(stmts, 1):
                try:
                    cur.execute(s)
                    ok += 1
                except Exception as e:
                    # 幂等友好：已存在对象/库/表视为可跳过
                    msg = str(e)
                    benign = any(k in msg for k in (
                        "already exists", "Duplicate entry",
                        "Duplicate column name", "Duplicate key name",
                    ))
                    if benign:
                        ok += 1
                        if verbose:
                            print(f"  [skip] #{idx} {msg[:110]}")
                        continue
                    errors.append((idx, msg, s.splitlines()[0][:120]))
                    if verbose:
                        print(f"  [ERR ] #{idx} {msg[:160]}")
                        print(f"         {s.splitlines()[0][:120]}")
    finally:
        conn.close()
    return ok, errors


def ensure_migration_table(conn):
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS `{MIGRATION_TABLE}` (
              `filename`   varchar(120) NOT NULL COMMENT '迁移文件名',
              `applied_at` datetime     NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (`filename`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
              COMMENT='数据库迁移应用记录（旧库升级幂等依据）'
        """)


def applied_migrations(conn):
    ensure_migration_table(conn)
    with conn.cursor() as cur:
        cur.execute(f"SELECT filename FROM `{MIGRATION_TABLE}`")
        return {r["filename"] for r in cur.fetchall()}


def mark_applied(conn, filename):
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT IGNORE INTO `{MIGRATION_TABLE}` (filename) VALUES (%s)",
            (filename,),
        )


def do_fresh(verbose=True):
    """全新安装：DROP + CREATE 库，再导入 init_database.sql 全量。"""
    target = os.path.join(BASE_DIR, "init_database.sql")
    if not os.path.isfile(target):
        print(f"[ERR] 找不到 {target}")
        return 1

    dbname = DB_CONFIG["database"]
    if verbose:
        print(f"[fresh] 目标库: {dbname}")

    conn = _connect(None)
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS `{dbname}`")
            cur.execute(
                f"CREATE DATABASE `{dbname}` DEFAULT CHARACTER SET utf8mb4 "
                f"COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        conn.close()

    # init_database.sql 自带 DROP/CREATE DATABASE，重复执行无害
    ok, errors = run_sql_file(target, verbose=verbose)

    # 视图/触发器/存储过程单独一份 objects.sql 更可靠（有 /*OBJECTS_SPLIT*/）
    obj = os.path.join(BASE_DIR, "db", "objects.sql")
    if os.path.isfile(obj):
        ok2, err2 = run_sql_file(obj, verbose=verbose)
        ok += ok2
        errors += err2

    # 全新安装也把迁移跑一遍（幂等），避免 schema.sql 与 migrations 漂移
    ok3, err3 = do_migrate(verbose=verbose, fresh=True)
    ok += ok3
    errors += err3

    print(f"\n[fresh] 成功 {ok} 条，失败 {len(errors)} 条")
    for idx, msg, head in errors[:10]:
        print(f"  #{idx} {msg[:140]}\n      {head}")
    return 0 if not errors else 2


def do_migrate(verbose=True, fresh=False):
    """旧库升级：按文件名顺序跑 db/migrations/*.sql，已应用的跳过。"""
    files = sorted(glob.glob(os.path.join(MIGRATION_DIR, "*.sql")))
    if not files:
        print("[migrate] 没有迁移文件")
        return 0, []

    conn = _connect(DB_CONFIG["database"])
    try:
        done = set() if fresh else applied_migrations(conn)
    finally:
        conn.close()

    total_ok, all_errors = 0, []
    for path in files:
        name = os.path.basename(path)
        if name in done:
            if verbose:
                print(f"[migrate] 跳过（已应用）: {name}")
            continue
        if verbose:
            print(f"[migrate] 应用: {name}")
        ok, errors = run_sql_file(path, verbose=verbose)
        total_ok += ok
        all_errors += errors
        if not errors:
            conn = _connect(DB_CONFIG["database"])
            try:
                ensure_migration_table(conn)
                mark_applied(conn, name)
            finally:
                conn.close()
        else:
            print(f"[migrate] {name} 有 {len(errors)} 条失败，未记录为已应用")
    return total_ok, all_errors


def do_verify():
    """校验：核心表、行数、视图、触发器、存储过程、新增创新表。"""
    expect_tables = [
        "t_cabinet", "t_cell", "t_courier", "t_express_company", "t_user",
        "t_package", "t_pickup_record", "t_exception_log", "t_notice",
        # 001 / 002 迁移
        "t_sms_code", "t_device_command", "t_qr_ticket",
    ]
    expect_views = ["v_cabinet_occupancy", "v_package_detail"]
    expect_triggers = ["trg_package_after_update"]
    expect_procs = ["sp_cabinet_occupancy", "sp_company_ranking", "sp_daily_throughput"]

    conn = _connect(DB_CONFIG["database"])
    problems = []
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            have = {list(r.values())[0] for r in cur.fetchall()}
            for t in expect_tables:
                if t not in have:
                    problems.append(f"缺表 {t}")
            cur.execute("SHOW FULL TABLES WHERE Table_type='VIEW'")
            views = {list(r.values())[0] for r in cur.fetchall()}
            for v in expect_views:
                if v not in views:
                    problems.append(f"缺视图 {v}")
            cur.execute(
                "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
                "WHERE TRIGGER_SCHEMA=%s", (DB_CONFIG["database"],))
            trigs = {r["TRIGGER_NAME"] for r in cur.fetchall()}
            for t in expect_triggers:
                if t not in trigs:
                    problems.append(f"缺触发器 {t}")
            cur.execute(
                "SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA=%s", (DB_CONFIG["database"],))
            procs = {r["ROUTINE_NAME"] for r in cur.fetchall()}
            for p in expect_procs:
                if p not in procs:
                    problems.append(f"缺存储过程 {p}")

            print("[verify] 行数统计：")
            for t in expect_tables:
                if t in have:
                    cur.execute(f"SELECT COUNT(*) c FROM `{t}`")
                    print(f"  {t:22s} {cur.fetchone()['c']}")
    finally:
        conn.close()

    if problems:
        print("\n[verify] 发现问题：")
        for p in problems:
            print("  -", p)
        return 1
    print("\n[verify] 全部通过")
    return 0


def main():
    ap = argparse.ArgumentParser(description="数据库初始化 / 迁移 / 校验")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fresh", action="store_true", help="全新安装（会 DROP 数据库）")
    g.add_argument("--migrate", action="store_true", help="旧库升级（幂等）")
    g.add_argument("--verify", action="store_true", help="校验结构完整性")
    ap.add_argument("--dry-run", action="store_true", help="只打印将执行的语句")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    verbose = not args.quiet

    if args.fresh:
        if args.dry_run:
            ok, err = run_sql_file(
                os.path.join(BASE_DIR, "init_database.sql"), dry_run=True)
            return 0
        return do_fresh(verbose=verbose)
    if args.migrate:
        if args.dry_run:
            for path in sorted(glob.glob(os.path.join(MIGRATION_DIR, "*.sql"))):
                run_sql_file(path, dry_run=True)
            return 0
        ok, errors = do_migrate(verbose=verbose)
        print(f"\n[migrate] 成功 {ok} 条，失败 {len(errors)} 条")
        for idx, msg, head in errors[:10]:
            print(f"  #{idx} {msg[:140]}\n      {head}")
        return 0 if not errors else 2
    return do_verify()


if __name__ == "__main__":
    sys.exit(main())
