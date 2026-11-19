# 智能快递柜管理系统（Smart Express Locker）

Flask + PyMySQL + MySQL 8 · 触屏端 / 手机 H5 / 管理端 三端分离 · 含 4 组创新功能

> **这是仓库的唯一快速入口。** 不管你是老师要看演示、还是队友要接着开发，从这里开始。

---

## 一分钟跑起来

```bash
# 1) 建库 + 建表 + 种子数据 + 视图/触发器/存储过程 + 迁移（会 DROP DATABASE，重复执行即重置）
#    唯一入口以 db/INIT_README.md 为准；不要用 mysql < init_database.sql（原因见该文件 §3）
python scripts/init_db.py --fresh

# 2) 校验结构完整性（期望：每表行数表 + 末行 [verify] 全部通过）
python scripts/init_db.py --verify

# 3) 依赖
.venv\Scripts\pip.exe install -r backend\requirements.txt

# 4) 启动
scripts\start.bat
```

打开 <http://127.0.0.1:5000/> 就是柜机触屏端。

**验证是否成功**：

```bash
curl http://127.0.0.1:5000/api/health
# 预期：{"db":"connected","status":"ok"}
```

### 前置条件

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | ≥ 3.10（实测 3.13.5 / 3.12.14 均可） | 需带 `venv`、`pip` |
| MySQL | 8.0+（实测 8.0.39） | **5.7 不可用**：CHECK 约束会被静默忽略 |

### 三个入口

| 端 | 地址 | 演示账号 |
|---|---|---|
| 柜机触屏端 | <http://127.0.0.1:5000/> | 用户手机号 `15800000001`（验证码回显） |
| 管理端 | <http://127.0.0.1:5000/admin> | `admin` / `admin123`（备用 `operator` / `operator123`） |
| 手机端 H5 | <http://127.0.0.1:5000/m> | 快递员 `E00001` + `13900000001` |

> 手机访问需把 `127.0.0.1` 换成本机局域网 IP（`ipconfig` 查看）。手机与电脑不同网段时用
> `scripts\start-with-tunnel.bat` 起内网穿透。

### 超时缴费与演示数据

演示账号 `15800000001` 名下有三件包裹，供演示计费阻断：

| 柜体 | 格口 | 取件码 | 状态 |
|---|---|---|---|
| CAB-001 | B05 | 549548 | 待取 |
| CAB-001 | A01 | 878905 | 待取 |
| CAB-001 | C05 | 782116 | 超时待缴 ¥1.00 |

演示多次后包裹会被取走，一条命令复原：

```bash
python scripts\reset_demo_data.py
```

---

## 常见故障

| 症状 | 原因 | 处理 |
|---|---|---|
| 详情接口 500，日志 `v_package_detail doesn't exist` | 没执行 `db/objects.sql` | `python scripts/init_db.py --migrate` |
| 取件后格口仍显示"占用" | 缺触发器 `trg_package_after_update` | 同上 |
| 单元测试报 `'OCCUPIED' != 'FREE'` | 同上 | 同上 |
| 单元测试报 `400 != 201`（`test_entity_mutation_allowed_with_admin`） | 上次运行被强杀，残留 `ZZTEST` 公司行 | `DELETE FROM t_express_company WHERE company_code='ZZTEST';` |
| 存件返回 409「当前无可用格口」 | 该柜该规格格口占满 | 换柜体/规格，或重置数据库 |
| 手机端登录 401 | 验证码超 5 分钟，或 60 秒内重复发送 | 重新取验证码 |
| 扫码后柜机不跳转 | AP 隔离（不同网段） | 用 `scripts\start-with-tunnel.bat` |
| `python` 打开应用商店 | 本机 `python` 是 Store 占位符 | 用 `.venv\Scripts\python.exe` |

完整排查表见 `docs/09-答辩演示与复现索引.md` §4。

---

## 功能概览

### 基础功能（第一轮）

- **触屏端**：扫码登录、取件码取件、超时缴费、快递员存件/揽收/投递记录、空闲自动登出
- **手机端**：验证码登录、扫码确认登录柜机、待取列表、远程开柜、重新开门、寄件下单与撤回
- **管理端**：数据看板（7 个统计接口）、包裹管理、业务操作、通知中心、基础数据维护、格口矩阵与远程开锁
- **系统服务**：通知入队与异步投递（失败重试）、柜机指令队列与回执、票据生命周期

### 创新功能（第二轮）

| 组 | 能力 | 无凭据时 |
|---|---|---|
| DeepSeek 智能寄件 | 包装推荐、智能问答、禁寄判断 | 降级本地规则，仍 200 |
| 包装准备协同 | 备包装任务、材料台账 | 不适用（内部功能） |
| 高德地图找柜 | 距离计算、加权推荐最优柜 | 按柜号排序，`distance_m: null` |
| 支付宝沙箱 / 模拟支付 | 支付单、金额快照、幂等、回调验签 | 回落 mock，页面明示"模拟支付" |

**总原则：外部依赖不可用时业务接口一律 200 + `degraded: true`，绝不 500。**

---

## 文档索引

| 文档 | 内容 | 谁看 |
|---|---|---|
| `docs/00-现状盘点与差距表.md` | 文档与现实差异的账本（G-01～G-23） | 答辩前自查 |
| `docs/01-需求规格说明书.md` | 需求、业务规则、非功能需求、用例 | 评审、测试 |
| `docs/02-概要设计说明书.md` | 架构、模块划分、技术选型、关键决策 | 评审 |
| `docs/03-详细设计说明书.md` | 表结构、接口清单、时序、状态机 | 开发 |
| `docs/04-测试计划与报告.md` | 三层测试策略、用例、缺陷记录 | 评审、测试 |
| `docs/05-部署与运行手册.md` | 从零部署、配置项、运维、故障排查 | 部署者 |
| `docs/06-用户手册.md` | 三端使用说明（含创新功能） | 最终用户 |
| `docs/07-项目计划与迭代复盘.md` | 计划、迭代、问题与解决、复盘 | 答辩 |
| `docs/08-创新功能与外部接口.md` | 4 组创新的设计、接口、降级策略 | 答辩、开发 |
| `docs/09-答辩演示与复现索引.md` | 演示时间轴、复现命令、故障排查 | 答辩现场 |
| `docs/api-innovations.md` | 创新接口 API 契约（backend-engineer 维护） | 前后端联调 |

---

## 目录结构

```
.
├── backend/            # Flask 应用（蓝图按端拆分）
│   ├── app.py          # 入口、页面路由、管理端门禁、缓存头
│   ├── auth.py         # 管理员会话 + 触屏端身份
│   ├── business.py     # 存件/取件/寄件/揽收/计费/开柜
│   ├── entities.py     # 通用 CRUD + 引用预检
│   ├── mobile_api.py   # 手机端聚合 + 柜机指令队列
│   ├── notify.py       # 通知入队与异步投递
│   ├── qr_login.py     # 扫码登录票据
│   ├── stats.py        # 看板统计
│   ├── db.py           # 数据访问封装
│   └── tests/          # PyUnit 测试
├── frontend/           # 三端页面（纯静态，无构建）
├── db/
│   ├── schema.sql      # 建表（供阅读）
│   ├── objects.sql     # 视图/触发器/存储过程（必须单独执行）
│   └── migrations/     # 增量迁移
├── scripts/            # 启动、演示数据复原、文档核验脚本
├── quality/reports/    # 质量工具输出（所有测试数字的唯一来源）
├── evidence/           # 截图与性能证据
├── deliverables/       # 实验报告、答辩 PPT、讲稿
├── docs/               # 项目文档 00–09
├── config.py           # 数据库与通知配置（环境变量可覆盖）
└── init_database.sql   # 全量初始化
```

---

## 文档核验脚本

文档里的数字都可以一键复核，不用人工数：

| 命令 | 核验什么 |
|---|---|
| `python scripts/seed_row_counts.py` | 种子数据行数（30 柜 / 720 格口 / 120 用户 / 310 包裹） |
| `python scripts/verify_line_counts.py` | 代码行数（合计 6522 行） |
| `python scripts/enumerate_routes.py` | 接口数量（86 条规则，72 条 `/api`） |
| `python scripts/check_constraints.py` | 约束数量（36 CHECK / 15 外键 / 10 唯一键） |
| `python scripts/check_sql_scripts.py` | 数据库对象清单（2 视图 / 1 触发器 / 3 存储过程） |

---

## 运行测试

```bash
# 前置：确认视图与触发器已建（权威检查，期望末行 [verify] 全部通过）
python scripts/init_db.py --verify

# 跑测试（必须 cd backend；不要加 -t .）
cd backend
python -m unittest discover -s tests -p "test_*.py" -v
```

> 必须 `cd backend` 再跑。在仓库根目录用 `-s backend/tests -t .` 会报
> `ImportError: Start directory is not importable`。
> 测试结果与覆盖率原始输出在 `quality/reports/`。

---

## 文档纪律

1. **PPT 与报告里的每张截图都必须来自最终版本系统的真实运行**，不得用旧图、不得拼接。
2. **引用任何测试数字必须能指回 `quality/reports/` 下的原始文件**；那里没有的数字不写。
3. 数字类结论优先用 `scripts/` 下的核验脚本生成，不手工抄写。
4. `plugins/` 与 `智能纪要：门诊管理系统开发.docx` 是参考材料，**只读**。

---

## 配置

全部通过环境变量注入，改完重启生效。常用几项：

| 变量 | 默认 | 作用 |
|---|---|---|
| `PORT` | `5000` | 监听端口 |
| `ADMIN_PATH` | `admin` | 管理端 URL 前缀 |
| `DB_HOST` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `127.0.0.1` / `root` / `123456` / `smart_locker` | 数据库连接 |
| `MOBILE_DEV_MODE` | `1` | `1` 时验证码回显 `dev_code`（仅演示） |
| `AUTH_SECRET` | 演示值 | 会话签名密钥（生产必改） |
| `NOTIFY_ENABLED` / `NOTIFY_WORKER` | `1` / `1` | 通知总开关 / 后台投递线程 |

完整清单见 `docs/05` §6；创新功能相关变量见 `docs/08`。
