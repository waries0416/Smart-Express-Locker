# 质量工程与证据采集 · 智能快递柜管理系统

> 本目录是**质量证据的唯一入口**。所有数字都能从 `quality/reports/` 的原始文件复核，
> 没有一处是估算或手工填写的"看起来漂亮"的值。

---

## 一键跑全部检查

```powershell
# 在仓库根目录 D:\softwaretest —— 当前入口（R3b 口径）
python quality\run_quality.py
```

会依次跑：库干净性快照 → unittest 连跑两遍 → 残留扫描 → 交替解释器交叉验证 →
coverage → 跳过项清单 → 口径核对 → pylint（旧代码 / 新模块）→ cProfile，
并把原始输出全部落盘，最后写 `reports/99_summary.txt` 与 `reports/99_manifest.json`。

> **`run_all.ps1` 是 T3-prep 阶段的旧入口**（32 用例时代），它会写
> `01_unittest.txt` / `02_coverage_report.txt` / `04_pylint.txt` 这些已被标为
> 【历史基线·已停用】的文件，**跑完会覆盖 R3b 的权威口径**。
> 只在需要复核"改革前是什么样"时才用它，且跑完必须重新执行
> `python quality\run_quality.py` 恢复当前口径。

```powershell
# 【仅历史对比用】旧入口
powershell -ExecutionPolicy Bypass -File quality\run_all.ps1
```

> **本机注意**：`python` 命令指向 Windows Store 占位 exe，不可用。
> 脚本默认使用
> `C:\Users\31189\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`。

---

## 目录结构

```
quality/
├── README.md                  ← 本文件（总入口）
├── requirements-quality.txt   ← 质量工具依赖清单
├── pylintrc                   ← pylint 配置（每条 disable 都写明理由）
├── pylint_thresholds.ini      ← 分数门槛：旧代码基线 / 新模块 9.0 门槛
├── .coveragerc                ← coverage 配置（语句+分支，口径写在文件内）
├── run_quality.py             ← 【当前】质量门禁主入口（R3b 口径）
├── run_all.ps1                ← 【历史·T3-prep】旧入口，会覆盖 R3b 产物，慎用
├── tools/
│   ├── office_snapshot_diff.py          ← Office 改动前后结构快照比对（F2）
│   └── _selftest_office_snapshot_diff.py ← 上面工具的自测（三用例）
├── perf_profile.py            ← cProfile 固定场景脚本
├── load_test_v2.py            ← 【当前】并发压测（三重证据 + 根因定位）
├── load_test.py               ← 【历史】T3-prep 压测脚本
├── capture_screenshots.py     ← 截图采集（CDP，无 Selenium）
├── diagnose_store_locks.py    ← store 行锁现场取证（只读）
├── repro_store_deadlock.py    ← store 锁冲突对照复现
├── _r3c_payu_race_proof.py    ← 并发支付重复入账的确定性复现（可回滚、零残留）
├── jmeter/
│   ├── smart_locker_load.jmx  ← 标准 JMeter 测试计划（4 个 ThreadGroup）
│   └── README_JMeter.md       ← 装 JMeter 后的非 GUI 重跑命令
└── reports/                   ← 全部原始证据
    ├── 【当前·R3b 权威口径】
    ├── 02_unittest_run1/2.txt           unittest 连跑两遍（195 OK）
    ├── 02b_residue_after_run1/2.txt     两遍后残留扫描
    ├── 02_unittest_alt_interpreter.txt  安装版 Python 3.12.3 交叉验证
    ├── 03_coverage_report.txt           ★ 覆盖率 57.40%（R9b）
    ├── 04_skipped_tests.txt             跳过项清单（skipped=0）
    ├── 05_test_count_reconciliation.txt ★ 静态 195 = 执行 195
    ├── 06_pylint_baseline.txt           ★ 旧代码 9.60（R9b）
    ├── 07_pylint_new_modules.txt        ★ 新模块 9.77
    ├── 08_cprofile.txt                  cProfile 结论
    ├── 09_loadtest.txt                  ★ 并发压测 + 判重结论（顶部汇总）
    ├── 10_store_lock_deadlock.txt       ★ store 环形等待结论（未修复）
    ├── 11_verify_e2e_*.txt              E2E 闭环核验
    ├── 12_screenshots.txt               截图自检（blank/wrong_screen）
    ├── 99_summary.txt                   ★ 门禁汇总（UTF-8 BOM）
    ├── 99_manifest.json                 各步骤机器可读清单
    ├── coverage.xml / htmlcov/          覆盖率 XML / HTML
    ├── 【历史·T3-prep 已停用，文件开头均有标注，保留仅为可追溯】
    ├── 01_unittest.txt                  32 用例时代的 unittest 输出
    ├── 02_coverage_report.txt           旧覆盖率 36.86%
    ├── 02a_coverage_run.txt             旧 coverage run 输出
    ├── 03_skipped_tests.txt             旧跳过清单
    ├── 04_pylint.txt                    旧 pylint 全量（9.69）
    ├── pylint_baseline.md               旧基线清单（9.69）
    ├── 00_unittest_baseline.txt         首次接入时的原始输出
    └── perf/                            性能原始数据
        ├── perf.prof              cProfile 原始 profile
        ├── perf_tottime.txt       按自身耗时排序
        ├── perf_cumtime.txt       按累计耗时排序
        ├── perf_calls.txt         按调用次数排序
        ├── perf_callers.txt       热点函数调用关系
        ├── perf_summary.txt       结论摘要
        ├── loadtest_*.json        压测逐请求原始数据
        └── loadtest_latest.json   最近一次（便于"最新"引用）
```

---

## 文件命名与新旧对应关系（**先读这张表，别读错数字**）

`reports/` 下并存两套口径文件。**旧文件不删**（保留可追溯），
但每份旧文件开头都已加 `【历史基线 · 已停用】` 标注。引用数字时**只认右列**。

| 用途 | ✅ 当前口径（R3b，引用这个） | ❌ 已停用（T3-prep，只作历史底片） | 旧值 → 新值 |
|---|---|---|---|
| 用例数 | `05_test_count_reconciliation.txt`（195） | `01_unittest.txt` | 32 → **195** |
| 覆盖率 | `03_coverage_report.txt`（**57.40%**） | `02_coverage_report.txt` | 36.86% → **57.40%** |
| pylint 旧代码 | `06_pylint_baseline.txt`（**9.60**） | `04_pylint.txt`、`pylint_baseline.md` | 9.69 → **9.60** |
| pylint 新模块 | `07_pylint_new_modules.txt`（**9.77**） | — | 本轮新增 |
| 跳过项 | `04_skipped_tests.txt`（skipped=0） | `03_skipped_tests.txt` | 口径同，用例数不同 |
| coverage run 日志 | `03_coverage_run.txt` | `02a_coverage_run.txt` | — |
| 汇总 | `99_summary.txt` + `99_manifest.json` | — | 本轮新增 |
| 入口脚本 | `run_quality.py` | `run_all.ps1` | 见下 |

> ⚠️ **`run_all.ps1` 会覆盖上表左列的文件**（它写的是旧文件名 01/02/04/03_skipped），
> 跑完就把 R3b 口径覆盖成 T3-prep 口径。要用旧入口做"改革前对比"，
> 请先备份 `reports/`，跑完再执行 `python quality/run_quality.py` 恢复。
> 脚本头部已加同样的警告。

**编码约定（重要）**：`99_summary.txt`、`09_loadtest.txt`、`10_store_lock_deadlock.txt`
三份"给人直接打开"的文件统一用 **UTF-8 with BOM** 写入。
原因：不带 BOM 的 UTF-8 被 Windows 记事本 / PowerShell 5.1 按 GBK 解析就是乱码
（评委打开会看到一屏乱码，实际内容是对的）。加 BOM 后 Windows 记事本、VS Code、
GitHub 都能正确识别。`run_quality.py` 写 `99_summary.txt` 时已改用 `utf-8-sig`。
`10_store_lock_deadlock.txt` 原为 UTF-16LE（更糟），R3c 已转 UTF-8-BOM，
原始快照另存 `10_store_lock_deadlock.utf16-original.bak.txt`。

---

## 各检查项说明

### B. 单元测试与覆盖率

| 项 | 内容 |
|---|---|
| 框架 | `unittest`（PyUnit）为主；`pytest` 已装但当前用例全是 unittest 风格 |
| 用例数 | **195 个，全部通过**（R3b 口径，见 `05_test_count_reconciliation.txt`） |
| 覆盖率口径 | 语句 + 分支；统计 `backend/*.py` 业务代码；排除 `backend/tests/*` |
| 排除项理由 | `config.py`（连接池装配）、`scripts/`（种子脚本）不是被测业务逻辑，不计入分母 |
| `fail_under` | **故意不设**，避免用参数把不达标隐藏成通过 |

覆盖率结果表见下方「实测结果」。HTML 报告支持逐行查看未覆盖位置。

**跳过项**：`03_skipped_tests.txt` 单独记录，且**不计入通过数**。
当前唯一可能整类跳过的条件是 `skipUnless(_db_ready())`（MySQL 不可用），
本机 MySQL 可用故未触发。

### C. pylint

- 旧代码基线（**9.60**）：`reports/06_pylint_baseline.txt`
- 新模块（**9.77**）：`reports/07_pylint_new_modules.txt`
- 规则的量化口径：`pylint_thresholds.ini`
- 规则：旧代码**不得低于**基线分；新模块（AI/地图/支付）**必须 ≥ 9.0 且 E 类为 0**
- 反造假自查：业务代码中 `# pylint: disable` 出现次数 = **0**

> ⚠️ `04_pylint.txt`（9.69）与 `pylint_baseline.md`（9.69）是 T3-prep 阶段产物，
> 已加【历史基线·已停用】标注。**引用 pylint 分数请用上面两份。**

### D. cProfile 性能分析

固定可复现场景（`quality/perf_profile.py`）：

| 场景 | 内容 | 选择理由 |
|---|---|---|
| S1 | 批量寄件下单 `POST /api/business/send-order` × N | 写事务最重：`FOR UPDATE` 选格口 → INSERT → UPDATE 占用 |
| S2 | 包装推荐 `POST /api/ai/pack-recommend` × N | 含外部 AI 调用，波动最大 |
| S3 | 附近柜体 `GET /api/m/cabinets/nearby` × N | 30 柜 × 720 格口的 LEFT JOIN + 条件聚合 |
| S4 | 寄件待揽收 `GET /api/business/send-pending` × N | 联表 + 明细拼装 |

命令：

```powershell
python quality\perf_profile.py --root D:\softwaretest --out quality\reports\perf --orders 30 --repeat 3
```

产物：`perf.prof`（可用 `python -m pstats` 或 snakeviz 打开）、三种排序的 Top-N 文本、
热点函数调用关系、`perf_summary.txt` 结论摘要。

> 计时包含 Flask 分发 + JSON 序列化，是**接口真实耗时**，不是纯函数耗时。

### E. 并发压测

**JMeter 本机未安装**（探测命令与结果见 `jmeter/README_JMeter.md` 第 0 节）。
因此压测数字来自 Python 等价脚本 `quality/load_test_v2.py`，
同时提供标准 `.jmx` 供交叉验证——**没有假称跑过 JMeter**。

```powershell
# 1) 先起服务（另开终端）
python backend\app.py

# 2) 跑压测（并发梯度 1/5/10/20）
python quality\load_test_v2.py --host http://127.0.0.1:5000

# 只跑一致性核验（快）
python quality\load_test_v2.py --scenario consistency
```

> `load_test.py` 是 T3-prep 阶段的旧脚本（无根因定位），已由 `load_test_v2.py` 取代；
> 旧脚本保留仅为可追溯。

场景与核验（**结论以 `reports/09_loadtest.txt` 顶部的判重汇总为准**）：

| 场景 | 内容 | 一致性核验 | 实测结论 |
|---|---|---|---|
| A | 登录主链路（发码 → 登录换 token） | — | 错误率 0% |
| B | 查询主链路（我的包裹 / 附近柜体 / 寄件待揽收） | — | 错误率 0% |
| C | 并发存件（≤10 并发） | **无重复格口分配**：内存判重 + 数据库交叉验证 | ✅ 无重复（三重证据一致） |
| D | 并发支付 | **无重复入账**：每件包裹 TIMEOUT-RESOLVED 流水必须恰好 1 条 | ✅ **已修复**（5 件各 1 条；修复前 79 条） |
| E | 并发取件（同码 10 并发） | 同一件包裹不得被取走两次 | ✅ **已修复**（1×200 + 9×409；修复前 7×200） |

**D/E 的完整闭环（发现 → 定性复现 → 修复 → 回归验证）**：

- R3c 初判：D 重复入账（5 件 / 79 条）、E 重复取件（7 次 200 / 7 条）都是**真缺陷**；
  根因是 `_charge_overtime` 与 `pickup`/`_do_unlock` 的"读 → 判断 → 写"没有原子化。
- 定性复现：`quality/_r3c_payu_race_proof.py`（两组对照 + 可回滚零残留），
  输出 `reports/_r3c_payu_race.txt`。
- 修复：R9b 改为 **CAS 条件更新 + rowcount 兜底**（`backend/business.py:741`、`:937`、
  `:988`、`:1105` 四处）。
- 回归：`quality/retest_race_fixes.py` 与 `quality/retest_race_stability.py`
  （5 轮 × 三条路径全过），完整压测见 `reports/09_loadtest.txt` 三、四节的
  **修复前后对照表**。

> 两个必须注意的坑：
> 1. **旧数字要保留**：`09_loadtest.txt` 里 79 条 / 单件 20 条 / 7 次 200 这些修复前数字
>    **故意不删**，因为"改前 vs 改后"的对比本身就是证据。只改结论行会变成数字残留。
> 2. **别把行锁等待混进来**：20 并发存件的环形等待（`10_store_lock_deadlock.txt`）
>    是**另一个未修缺陷**，属可用性问题，不是这次修的数据一致性问题。

记录项：硬件信息、数据量、并发梯度、吞吐量、错误率、P95/P99、版本号，
全部写进 `reports/perf/loadtest_*.json`（含逐请求原始数据）。

### F. 截图与录屏

见 `evidence/screenshots/INDEX.md`（两套截图来源、最终采用版、截图 ↔ 功能 ↔ 建议 PPT 页码）。

> **两套截图并存**：`NN-功能名.png`（连字符）是交付物实际嵌入的那一套；
> `NN_功能名.png`（下划线）是 `capture_screenshots.py` 可复现流水线的产物。
> 两套的管理端看板数字不同（用户 120 vs 1703），换图必须同步改 PPT 旁注。
> 详见 INDEX.md 第 2 节。

录屏：`ffmpeg` **未安装**、`obs64` **未找到**（探测结果见 evidence 目录下的说明）。
处理方式：先尝试 `winget` 安装；若仍不可用，**如实报告阻塞**
并产出「精确到秒的分镜清单 + 可直接执行的录屏命令」，不使用静态幻灯片伪装操作视频。

### F2. Office 文档改动的结构快照比对（`tools/office_snapshot_diff.py`）

**为什么需要这条（一次真实事故）**

改 Office 文件时，只检查"目标数字改对了"是不够的——它只能证明**该改的改了**，
证明不了**别的内容还在**。

真实事故：用 python-pptx 往 PPT 备注里追加说明时，用了
`for r in p.runs: if r is not p.runs[0]: r.text = ""` 这类写法。
坑在于 `paragraph.runs` **每次访问都返回新的 proxy 对象**，
`r is not p.runs[0]` 永远为真，于是把刚写入的备注又清空成 0 字。
当时的自检只扫"目标数字是否存在"→ 数字没丢 → 自检通过 → 缺陷带进交付物。

这类盲区的共同点：**被误伤的内容不在你的检查范围内，而且往往不可见**
（演讲者备注不出现在幻灯片画面上，页眉页脚不出现在正文流里）。

**做法**：把文档拆成按位置索引的文本条目，改前改后各存一份快照，逐条比对，
**差异条数必须等于预期改动条数**。多了说明误伤别处，少了说明改动没生效。

```powershell
# 1) 改前存快照
python quality\tools\office_snapshot_diff.py snapshot `
    deliverables\智能快递柜系统答辩.pptx --out logs\ppt_before.json

# 2) 改文件（你自己的 python-docx / python-pptx 脚本）

# 3) 改后存快照
python quality\tools\office_snapshot_diff.py snapshot `
    deliverables\智能快递柜系统答辩.pptx --out logs\ppt_after.json

# 4) 断言"恰好改了 2 条"——不符则退出码 1
python quality\tools\office_snapshot_diff.py diff `
    logs\ppt_before.json logs\ppt_after.json --expect 2
```

快照覆盖范围：

| 文档类型 | 采集的条目 | 定位键示例 |
|---|---|---|
| `.docx` | 正文段落、表格单元格、页眉页脚 | `body[42]` · `tables[3].r[2].c[1]` |
| `.pptx` | 每个形状的文本、表格单元格、**演讲者备注** | `slides[13].shape[TextBox 3]` · `slides[13].notes` |

额外记录 `total_chars`（全文总字数）：即使逐条 diff 全部匹配，
只要总字数变了也说明有内容被改动——这是"整体被清空"的最后一道防线。

**自测**（三个用例，覆盖正常改 / 误伤备注 / 什么都没改）：

```powershell
python quality\tools\_selftest_office_snapshot_diff.py
```

自测在 `logs/snapshot-selftest/` 下的**副本**上做，不动 `deliverables/` 原件。
当前结果：三个用例全部符合预期；其中 case B 精确复现了上述事故——
改 1 处正文 + 备注被清空 → 差异 2 条 ≠ 预期 1 → 断言失败并指出
`slides[13].notes`；输出留档 `reports/_selftest_office_snapshot_diff.txt`。

> 与 `scripts/check_deliverable_numbers.py` 的分工：
> 后者检查**数字口径**（旧值有没有残留、新值有没有出处），
> 本工具检查**内容完整性**（有没有误伤）。两者互补，都要跑。

### F3. 静音演示视频（`video/record_demo.js` + `tools/build_demo_video.py`）

成片：`deliverables/智能快递柜系统_静音演示视频.mp4`
（1920×1080 · H.264 · 30 fps · **无音轨** · 8 分 11 秒）
分镜与复现说明：`docs/10-静音演示视频分镜与复现.md`

**本机没有 OBS，也没有命令行 ffmpeg**，所以不走"录屏软件"路线：

| 方案 | 本机实测 |
|---|---|
| OBS Studio | ❌ 未安装 |
| ffmpeg CLI | ❌ 未安装 |
| Edge / Chrome CDP | ✅ 可用；Node 22 自带 WebSocket |

做法：headless 浏览器 + CDP `Page.captureScreenshot` 固定间隔抓帧 →
ffmpeg 合成。ffmpeg 二进制来自 `pip install imageio-ffmpeg`（自带 libx264），
不是系统级安装。**画面是浏览器真实渲染结果**，鼠标移动、逐字输入、切页
都会真实反映，与录屏软件等价；**不是静态幻灯片拼接**。

```powershell
# 1) 造演示数据（走真实 /api/business/store，在 CAB-001 上现造待取+超时各一件）
python quality\tools\prepare_demo_packages.py

# 2) 抓帧（按 11 个场景执行真实操作）
node quality\video\record_demo.js --out quality\logs\video-shots --fps 4 --pace 2 --hold 4500

# 3) 装配成片（章节卡 + 真实画面 + 片头片尾）
python quality\tools\build_demo_video.py

# 4) 核对时间码（按实测段长算，不靠估算）
python quality\tools\video_timeline.py
```

核验：

```powershell
ffmpeg -hide_banner -i deliverables\智能快递柜系统_静音演示视频.mp4
# 期望：Duration 00:08:11.93；只有 Stream #0:0 (h264 1920x1080)，无 Audio 流
```

录制时踩过的 5 个坑（都已在脚本里修掉，详见 `docs/10` 第五节）：
抓帧在模糊背景弹窗下会卡死（需超时保护）、`send-code` 有 60 秒限流、
`reset_demo_data.py` 不会把 PICKED 改回 STORED（讲稿里的取件码会被取走）、
取件码有柜体归属校验、该 ffmpeg 构建不支持 `filter_complex_script`
（中文文字改用 Pillow 画图再推流）。

### G. E2E 核验

`scripts/verify_e2e.py` 跑通完整闭环：

```
寄件下单 → AI 包装推荐 → 地图找柜 → 快递员投递(揽收+存柜)
        → 用户取件 → 超时支付
```

输出可读的通过/失败清单（每步标注实际 HTTP 状态码与关键字段断言）。

### H. 文档一致性检查（`scripts/check_docs_consistency.py`）

**一条命令，按需运行**（**不接 CI / 不进 `run_quality.py`** —— 本项目没有 CI 环境，
目标是课程答辩演示，避免为"看起来规范"增加维护面）：

```powershell
# 在仓库根目录
python scripts\check_docs_consistency.py

# 只查格式层（跳过字段层，快）
python scripts\check_docs_consistency.py --format-only
```

退出码：`0` = 两层全过；`1` = 有问题（会逐条列出）。

#### 它查什么

**第一层 · 格式层**（`docs/0*.md`、`docs/api-innovations.md`、`README.md`）

| 检查项 | 说明 |
|---|---|
| 代码围栏配对 | ` ``` ` 数量必须为偶数 |
| 表格分隔行位置 | `|---|` 上面必须是表头行 |
| 表格列数一致 | 同一个表格块内列数必须相同 |
| 旧数字残留 | 检出 312 / 122 / 233 / 268 / 168 等历史值 |

> 旧数字检查有**误报抑制**：变更说明（"312→310"）、IP 段（`192.168.**168**`）、
> 口径说明（"当时库内为 312 条"）不算残留。`docs/00-现状盘点与差距表.md`
> 整篇是"改前→改后"对照，整文件豁免。
> 抑制规则经**注入验证**：塞一条真实残留仍能检出，没有豁免过宽。

**第二层 · 字段层**（`scripts/api_field_check.py`，仅针对 `docs/api-innovations.md`）

用 **AST 静态分析**（不启动服务、不连数据库）比对：
文档某个端点声明的**响应字段**，必须能在后端代码里找到。

覆盖 16 个端点小节，其中 **12 个完成字段级校验**。
另有两个**硬断言**（不论文档怎么写都查）：

| 断言 | 约定 |
|---|---|
| `GET /api/pay/{pay_id}` 不得返回 `qr_code_url` | 该字段只在 `POST /api/pay/create` 的建单响应里；查询接口用于轮询状态，不含收款码 |
| `POST /api/business/send-order` 的 `sender_address` / `recipient_address` 必须成对 | 只加一个说明改漏了 |

#### ⚠️ 它**不查**什么（4 个端点标记为"未校验"）

以下 4 个小节在文档里**没有 JSON 响应示例**（用表格或文字描述），
无法做字段级比对，脚本会如实打印 `文档 0 字段（未校验）`：

- `POST /api/business/send-order`
- `POST /api/courier/packaging-tasks/{task_id}/done`
- `POST /api/notify/alipay`（返回纯文本 `success`/`fail`，本就不是 JSON）
- `PUT /api/pack-materials/{id}`

> **"未校验" ≠ "通过"**。看到这行说明该端点需要人工确认，
> 不要因为脚本退出码是 0 就认为这 4 个也被验证过了。

另外两类情况也会明确标注、不计入通过：

- **`**` 展开**：函数里有 `**kwargs`/`{**d}`，静态无法穷举字段 → 标"未做自动判定"；
- **代码有、文档无**：只在"提示"里列出（供补文档参考），不报错 ——
  这类不会让前端踩坑，与"文档有、代码无"的风险方向相反。

#### 自测：证明检查器真能抓到漂移

```powershell
python scripts\_selftest_api_field_check.py
```

三个用例（**注入法**，跑在临时副本上，不动仓库文件）：

| 用例 | 期望 | 当前结果 |
|---|---|---|
| C 基线（不注入） | 0 问题 | ✅ 0 |
| A 文档塞入虚构字段 `phantom_field_xyz` | 必须检出 | ✅ 检出 |
| B 代码删掉 `recipient_address` | 必须报"不成对" | ✅ 检出 |

> 为什么必须做这个自测：一个"永远通过"的检查器最危险 —— 给人虚假的安全感。
> 本项目真实踩过：早期版本因请求/响应示例判定过严，响应块被整块丢弃，
> 某端点"文档 0 字段"、检查空转，**脚本却仍报通过**。

#### 已知的实现坑（改这个脚本前先看）

| # | 坑 | 处理 |
|---|---|---|
| 1 | `Blueprint(url_prefix="/api/pay")` 已含 `/api`，若再统一加前缀 → `/api/api/pay/...` 全部匹配失败 | 按每个文件实际 `url_prefix` 拼接 |
| 2 | 路由多是薄壳（`return jsonify(payment.get_order(pid))`），字段在被调函数里 | AST 沿调用链展开，**限深 2 层** |
| 3 | 文档里请求示例与响应示例混排，不区分必假阳性（`weight`/`size_type` 会被当成响应字段） | 看 JSON 块正上方最近非空行含"请求"还是"响应" |
| 4 | 递归太深会把配置常量键（`SMALL_SIZE`/`api_key`）全收进来，提示变成噪声 | 深度限 2 层，够覆盖"路由→业务→字典" |

---

## 实测结果（R9b 当前口径）

> **R9b 口径变更（重要）**：R9b 修复了两个并发缺陷并新增 6 个回归用例，
> 用例数 195 → **202**，覆盖率 56.32% → **57.40%**，pylint 旧代码 9.59 → **9.60**。
> 完整变更说明与"为什么覆盖率不是降而是升"见
> `reports/00_质量数字口径变更记录_R3b到R9b.md`。
> R3b 的 195 / 56.32% 已不再适用，其原始文件已被原地覆盖（不复原、不伪造）。
>
> **覆盖率口径说明（对外引用前请读完）**：
> 1. **直接引用下面这段**（抖动已消除，不再需要写区间）：
>    ```
>    综合覆盖率 57.40%（3634 语句 / 1426 未覆盖）；连跑 5 次稳定，无抖动。
>    （此前曾观测到 57.34%–57.40% 的摆动，已由 backend 新增的
>      backend/tests/test_force_unlock_empty_cell.py 消除。）
>    复现：python quality/check_coverage_stability.py --runs 5
>    ```
>    **抖动的来龙去脉**：曾因 `business.py` 的 `force_unlock_cell()` 中
>    「空格口复位 FREE」的 `else` 分支只在并发时序碰巧命中时被覆盖，
>    导致 Miss 在 1426↔1428 摆动。backend 补了确定性用例后，
>    该分支稳定被覆盖，连跑 5 次 Miss 恒为 1426。
> 2. **`omit` 只允许排除 `backend/_*.py`**：即下划线开头的临时运维脚本。
>    **严禁扩展**到任何业务模块（`integrations/*`、`*_api.py`、`business.py` 等）。
>    当前 `backend/` 下已无 `_*.py`，故该规则**不影响任何现存数字**，仅防御未来污染；
>    删掉此行重跑仍为 57.40%。
> 3. **htmlcov 已整目录重建**：清掉了 5 个已删脚本的孤儿页面（35 → 30 个文件），
>    重算覆盖率不变（数据源本来就不含这些脚本，只是 HTML 渲染滞后）。


> 采集时间：2026-11-18　解释器：CPython 3.12.14（DSH 运行时）　pylint：4.1.4　coverage：7.17.3
> 数据源：`99_summary.txt` / `99_manifest.json`。**旧口径（32 用例 / 36.86% / 9.69）已停用**，
> 见上文「文件命名与新旧对应关系」。

| 检查项 | 实测值 | 结论 |
|---|---|---|
| unittest | **202 用例，202 通过 / 0 失败 / 0 跳过**，连跑两遍均稳（`02_unittest_run1/2.txt`） | ✅ PASS |
| 用例数口径核对 | 静态 `def test_` 195 = 实际 Ran 195，差值 0（`05_test_count_reconciliation.txt`） | ✅ PASS |
| coverage（语句+分支） | **57.40%**（3634 语句 / 1426 未覆盖；分支 1284 / 207 部分）<br>连跑 5 次稳定，抖动已消除 | ⚠️ 未达 NFR-M-02 的 70% |
| pylint 旧代码 | **9.60 / 10**，E 类 **0** 条（`06_pylint_baseline.txt`） | ✅ PASS |
| pylint 新模块 | **9.77 / 10**，E 类 **0** 条（`07_pylint_new_modules.txt`） | ✅ PASS（门槛 ≥9.0） |
| cProfile S1 批量寄件 | 平均 11.31 ms（`08_cprofile.txt`） | ✅ 已采集 |
| 并发压测 C（存件判重） | 40 次分配 40 个唯一格口，无重复占用 | ✅ 无重复格口分配 |
| 并发压测 D（支付判重） | 修复后：5 件各 1 条，Σpaid_count=5；修复前：79 条 / 单件 20 | ✅ **已修复** |
| 并发压测 E（取件判重） | 修复后：1×200 + 9×409 + 1 条流水；修复前：7×200 / 7 条 | ✅ **已修复** |
| 20 并发存件 | 10 个 LOCK WAIT 事务、环形等待、服务不可用 | ❌ **未修复，已知限制**（另一缺陷） |
| 截图自检 | 11 张，1 张白屏（`05_mobile_pickup`） | ⚠️ 已标注不采用 |

> 相比 T3-prep 阶段：用例 32 → **202**（+170），覆盖率 36.86% → **57.40%**（+20.54 个百分点）。
> 覆盖率仍未达 70%，原因见下；**不粉饰**。

**覆盖率 57.40% 的真实原因（不美化）：**

覆盖率提升主要来自新增的创新模块：`location.py` 96.14%、`apiutil.py` 94.38%、
`app.py` 91.43%、`packaging_tasks.py` 84.17%、`packaging_rules.py` 83.71%。

被覆盖最少的是**四个既有聚合层**：`entities.py` 23.71%、`business.py` 27.24%、
`mobile_api.py` 22.12%、`notify.py` 31.28%。
1453 行未覆盖里约 **73.2%** 集中在这四处（合计 1529 语句，覆盖率仅 30.41%），
它们都需要 DB fixture 才能测得动。
若 `business + entities` 补到 70%，整体到约 **70.8%**；四件套全补到 70%，整体约 **76.6%**。
**这是本项目的真实覆盖率短板，已如实记录，不做任何加权美化。**

提升覆盖率的建议（留给后续迭代，不在本阶段硬凑）：

| 优先级 | 模块 | 建议补的用例 |
|---|---|---|
| 高 | `business.py` | 存件/取件/退回/异常/强制过期各一条正常+异常路径 |
| 高 | `mobile_api.py` | 手机端登录、预览、开柜、批量支付的鉴权与幂等 |
| 中 | `entities.py` | 实体增删改的级联删除与引用校验 |
| 中 | `notify.py` | 重试退避、失败率注入、渠道分发 |
| 低 | `stats.py` | 统计接口的边界（空数据、非法天数参数） |

---

## 环境限制（如实记录）

| 项 | 状态 | 影响 |
|---|---|---|
| `python` 命令 | ❌ Windows Store 占位 exe | 脚本内一律用绝对路径调度 DSH 运行时 Python |
| MySQL 8.0 | ✅ 运行中，`smart_locker` 可用 | — |
| JMeter | ❌ 未安装 | 用 Python 等价脚本，另附 `.jmx` 计划 |
| ffmpeg | ❌ 未安装 | 录屏受限，见 F 项说明 |
| OBS | ❌ 未找到 | 同上 |
| Chrome | ❌ 未找到 | 用 Edge（`msedge.exe`）headless 截图 |
| Edge | ✅ `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` | 截图主力 |
| Java | ✅ 21.0.5 | 装 JMeter 无需再装 JDK |

---

## 数据库环境修复记录（重要，影响所有测试）

首次接入时 `smart_locker` 库**缺少 3 张表**：`t_sms_code`、`t_device_command`、`t_qr_ticket`，
导致 32 个用例中 19 个报错（`Table 'smart_locker.t_qr_ticket' doesn't exist`）。

**根因**：仓库的 `db/migrations/001_mobile.sql` 与 `002_qr_login.sql` 从未被应用到本机库。

**额外发现（已修）**：`db/objects.sql` 与 `init_database.sql` 里的
`CREATE TRIGGER` / `CREATE PROCEDURE` 含 `BEGIN...END` 复合语句，
但两个文件**都没有 `DELIMITER` 声明**，`mysql < file.sql` 直接导入会在触发器处
报 `ERROR 1064`，导致**触发器与存储过程静默丢失**。

这直接造成过一个真实的测试失败：`test_pickup_succeeds_after_payment` 断言
"取件后格口应释放" 失败（`OCCUPIED != FREE`）——因为业务代码**依赖触发器**
`trg_package_after_update` 在包裹置 `PICKED` 时释放格口，而触发器没建出来。

修复后状态（`python scripts/init_db.py --verify` 全部通过）：

| 对象类型 | 数量 |
|---|---|
| 表 | 12 |
| 视图 | 2（`v_package_detail`、`v_cabinet_occupancy`） |
| 触发器 | 1（`trg_package_after_update`） |
| 存储过程 | 3（`sp_cabinet_occupancy`、`sp_company_ranking`、`sp_daily_throughput`） |

> **这是一处基建缺陷，建议属主（backend-engineer）把迁移应用写进启动流程**，
> 否则任何人 clone 后按 `README` 起服务都会踩到"触发器不存在 → 格口不释放"。

数据库改动前的完整备份：`reports/smart_locker_backup_before_reset.sql`。
