# 数据库初始化 · 唯一入口说明

> 本文件由 backend-engineer 维护，是 `db/` 目录下初始化流程的**权威说明**。
> 与 `README.md` / `docs/05-部署与运行手册.md` / `docs/09-答辩演示与复现索引.md`
> 的表述必须一致；若不一致，**以本文件为准**。

## 0. 一句话结论

```bash
python scripts/init_db.py --fresh      # 建库 + 建表 + 灌演示数据 + 建对象 + 跑迁移
python scripts/init_db.py --verify     # 校验结构完整性
```

**这就是"从空环境一条命令装好整库"的唯一正确入口。**
不要再手工 `mysql < init_database.sql`（原因见第 3 节）。

## 1. 前置条件

| 项 | 要求 |
|---|---|
| MySQL | ≥ 8.0（项目用了 `CHECK` 约束与 `utf8mb4_0900_ai_ci`；5.7 会静默忽略 CHECK） |
| Python | ≥ 3.10（实测 3.12） |
| 依赖 | `python -m pip install -r backend/requirements.txt` |
| 连接参数 | 环境变量 `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME`，默认 `127.0.0.1:3306 root/smart_locker` |
| 权限 | 该账号需有 `CREATE DATABASE` + `DROP DATABASE` 权限（`--fresh` 会重建库） |

## 2. 执行顺序与期望输出

`--fresh` 内部严格按以下顺序执行，**顺序本身就是正确性的保证**：

```
1) DROP + CREATE DATABASE            重建目标库（干净起点）
2) init_database.sql                 建表 + 全量演示数据 + 内嵌对象定义
3) db/objects.sql                    视图 / 触发器 / 存储过程（幂等补齐）
4) db/migrations/001_mobile.sql      手机端所需表与字段
5) db/migrations/002_qr_login.sql    扫码登录票据
6) db/migrations/003_innovations.sql 四组创新功能所需表与列（含 5 处幂等 ALTER）
7) db/migrations/003_seed_cabinet_coord.sql  柜体经纬度种子
```

实测输出（2026-11-18，MySQL 8.0.39）：

```
[fresh] 目标库: smart_locker
[SQL] init_database.sql: 2085 条语句
[SQL] db\objects.sql: 7 条语句
[migrate] 应用: 001_mobile.sql   → 3 条
[migrate] 应用: 002_qr_login.sql → 2 条
[migrate] 应用: 003_innovations.sql → 29 条
[migrate] 应用: 003_seed_cabinet_coord.sql → 31 条

[fresh] 成功 2157 条，失败 0 条          ← 期望：失败数为 0
```

`--verify` 实测输出（**格式就是"行数表 + problems 列表"，不要期待三行摘要**）：

```
[verify] 行数统计：
  t_cabinet              30
  t_cell                 720
  t_courier              60
  t_express_company      30
  t_user                 120
  t_package              310
  t_pickup_record        230
  t_exception_log        220
  t_notice               0
  t_sms_code             0
  t_device_command       0
  t_qr_ticket            0

[verify] 全部通过
```

**判断标准**：末尾出现 `[verify] 全部通过`（即 problems 列表为空），
且行数表里 `t_cabinet=30` / `t_cell=720` / `t_user=120` / `t_package=310` 非空。
若打印出 `[verify] 发现问题：` 并逐条列出缺表/缺视图/缺触发器，即为失败。

结构对象的期望值：**视图 2 个、触发器 1 个、存储过程 3 个**：

| 类型 | 名称 |
|---|---|
| 视图 | `v_package_detail`、`v_cabinet_occupancy` |
| 触发器 | `trg_package_after_update` |
| 存储过程 | `sp_cabinet_occupancy`、`sp_company_ranking`、`sp_daily_throughput` |

## 3. 为什么不能 `mysql < init_database.sql`

这是本项目踩过并已修好的坑，结论要讲准：

1. **`mysql < db/objects.sql` 这条路本身不可用。** `db/objects.sql` 里的
   `CREATE TRIGGER ... BEGIN ... END;` 是复合语句，MySQL 命令行客户端默认以分号
   切分，遇到 `BEGIN` 内部的 `;` 就提前截断 → `ERROR 1064`。**这不是"少了
   `/*OBJECTS_SPLIT*/` 标记"的问题**，标记只是给脚本切分用的便利声明，
   命令行客户端根本不看它。
2. 触发器没建出来 → 取件后格口不释放 → `test_pickup_succeeds_after_payment`
   报 `'OCCUPIED' != 'FREE'`；视图没建出来 → 详情接口 500。
3. `scripts/init_db.py` 的价值正是**在 Python 侧切分语句**：它识别
   `CREATE TRIGGER / PROCEDURE / FUNCTION / EVENT` 的复合语句边界（以行首 `END`
   作为整条结束），再逐条 `cursor.execute()` 提交，绕开了命令行客户端的切分缺陷。
   它还能正确处理 003 迁移里的
   `SET @sql := IF((SELECT ...)=0, 'ALTER ...', 'SELECT 1'); PREPARE/EXECUTE/DEALLOCATE`
   动态 SQL 序列。

因此：**`python scripts/init_db.py` 是唯一推荐入口；`init_database.sql` 是它的输入之一，不是入口。**

## 4. 库升级（已有数据，不想重建）

```bash
python scripts/init_db.py --migrate          # 只跑未应用的迁移，幂等、不 DROP
python scripts/init_db.py --migrate --dry-run # 只打印将执行的语句
```

已应用的迁移记录在 `t_schema_migration(filename, applied_at)`，重复执行自动跳过。

## 5. 快照一致性校验

根目录的 `init_database.sql` / `init_verify.sql` 是**可分发快照**，应与 `db/` 真源一致：

```bash
python tools/sync_init_dumps.py --check    # 只读检查；有漂移退出码 1
python tools/sync_init_dumps.py --write    # 依据当前库重建快照
```

变更 `db/migrations/*.sql` 后的推荐流程：

```
1) python scripts/init_db.py --fresh
2) python tools/sync_init_dumps.py --write     # 把已验证的库状态固化
3) python tools/sync_init_dumps.py --check     # 复核，再提交
```

> 注意方向：**库是中间态，快照是产物**。不要"改快照 → 建库"，
> 否则迁移脚本永远追不上快照，漂移会再次发生。

## 6. 备份与恢复

```bash
# 备份
mysqldump -h 127.0.0.1 -u root -p --databases smart_locker \
          --routines --triggers --single-transaction \
          --result-file db/backup_before_fresh.sql

# 恢复
mysql -u root -p < db/backup_before_fresh.sql
```

`db/backup_before_fresh.sql` 是 R6 执行 `--fresh` 前的备份（该次备份时库还是空的）。

## 7. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `--verify` 报 `缺触发器 trg_package_after_update` | 只跑了 `init_database.sql`，没跑 `objects.sql` 或没走 init_db.py | 用 `--fresh` 或 `--migrate` 重跑 |
| `test_pickup_succeeds_after_payment` 报 `'OCCUPIED' != 'FREE'` | 同上，触发器缺失 | 同上 |
| 详情接口 500，日志 `Table v_package_detail doesn't exist` | 视图缺失 | 同上 |
| `--fresh` 报 `Access denied` | 账号无 DROP/CREATE DATABASE 权限 | 换有权限账号，或改用 `--migrate` |
| `--verify` 行数全 0 | 只建了表没灌数据（如手工只跑了 `db/schema.sql`） | 用 `--fresh` |
| 迁移报 `Duplicate column name` | 003 的幂等 ALTER 已执行过 | 正常跳过，或检查 `t_schema_migration` |
