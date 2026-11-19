# 截图证据索引 · evidence/screenshots/

> 本目录收录 **两套**截图。两套不是版本冲突，而是**两次用途不同的采集**：
> 一套是 R3b 期间为**交付物（PPT / 实验报告）实际嵌入**而拍的，另一套是随后为**可复现流水线**
> 用 `quality/capture_screenshots.py` 重拍的。本文把两套的来历、差异、以及**哪一套被交付物真正采用**
> 写清楚，避免后来者按文件名排序误判"带连字符的是旧的、旧的不能用"。
>
> 采集事实：服务 `http://127.0.0.1:5000`，浏览器 `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，
> 驱动方式为原生 Chrome DevTools Protocol（本机无 Selenium / Playwright）。
> 两套图均未注入假数据、未拼接静态 HTML —— 截的是浏览器当时的真实渲染。

---

## 1. 两套来源

### A 套 · 连字符命名（`NN-功能名.png`），10 张

| 项 | 内容 |
|---|---|
| 文件 | `01-kiosk-home.png` `02-kiosk-ai.png` `03-kiosk-pickup.png` `04-admin-login.png` `05-admin-dashboard.png` `06-admin-view-packages.png` `07-mobile-login.png` `08-mobile-pickup.png` `09-mobile-ai.png` `10-mobile-map.png` |
| 采集时间 | 2026-11-18 **21:51:46 – 21:52:47**（相邻两张间隔 5–10 s，说明是同一次批量遍历） |
| 生成者 | R3b 期间的一次性 CDP 采集脚本，**仓库内已不留可复现入口**（当时的脚本未落盘） |
| 用途 | **交付物嵌入用**：`deliverables/智能快递柜系统答辩.pptx` 与 `deliverables/智能快递柜系统实验报告.docx` 里每一张截图都来自这一套 |
| 元数据 | 无 `_capture_log.json`；每张图的"功能"由文件名与画面内容人工确认（见第 3 节） |

> ⚠️ 正因为 A 套没有可复现脚本，本次才把 **B 套的流水线固化成 `quality/capture_screenshots.py`**。
> A 套保留不删，因为**它才是交付物里真正的那张图**（删掉就无法回溯 PPT 里的图从哪来）。

### B 套 · 下划线命名（`NN_功能名.png`），11 张 + 采集日志

| 项 | 内容 |
|---|---|
| 文件 | `01_kiosk_home.png` … `11_admin_packages.png` 共 11 张；另有 `_capture_log.json`（逐图 URL / 视口 / 是否白屏 / 控制台异常）与 `quality/reports/12_screenshots.txt`（人读摘要） |
| 采集时间 | 2026-11-18 **22:27:01 – 22:28:10** |
| 生成者 | **可复现流水线**：`python quality/capture_screenshots.py --host http://127.0.0.1:5000` → 内部调 `tools/capture_cdp.js` |
| 用途 | 作为**流水线产物与自检证据**（白屏检测、横向溢出检测、控制台异常检测） |
| 元数据 | `_capture_log.json` 11 条，字段含 `text_len` / `nodes` / `blank` / `h_overflow` / `wrong_screen` / `console_errors` |

---

## 2. 最终采用版标注

### 结论：**交付物当前实际采用的是 A 套**

判定方法不是看文件名、也不是看时间戳，而是**把 PPT / DOCX 里嵌入的图片二进制取出来做 SHA-256，
与目录内文件逐一比对**。结果：

| 交付物 | 嵌入图片数 | 命中 A 套 | 命中 B 套 | 命中率 |
|---|---|---|---|---|
| `deliverables/智能快递柜系统答辩.pptx` | 13 处（6 页，8 张去重） | **13 / 13** | 0 | A 套 100% |
| `deliverables/智能快递柜系统实验报告.docx` | 7 张 | **7 / 7** | 0 | A 套 100% |

PPT 逐页命中明细（页码 = 幻灯片序号）：

| PPT 页码 | 该页嵌入的图（A 套） |
|---|---|
| 第 8 页 核心流程一：扫码登录 → 柜机取件 | `01-kiosk-home.png`、`08-mobile-pickup.png` |
| 第 9 页 核心流程二：超时计费 → 支付闸门 → 自动开柜 | `08-mobile-pickup.png` |
| 第 11 页 创新 I-1：DeepSeek 智能问答与包装推荐 | `02-kiosk-ai.png`、`09-mobile-ai.png` |
| 第 12 页 创新 I-2 / I-3：包装协同 + 地图找柜 | `10-mobile-map.png` |
| 第 13 页 创新 I-4：支付降级口径 | `07-mobile-login.png` |
| 第 16 页 系统实拍：三端在最终版本上的真实运行 | `01-kiosk-home.png`、`02-kiosk-ai.png`、`05-admin-dashboard.png`、`06-admin-view-packages.png`、`09-mobile-ai.png`、`10-mobile-map.png` |

### 为什么"最新的 B 套"反而没被采用

B 套拍摄于 **22:27–22:28**，晚于 A 套 35 分钟，但它**晚于交付物的生成时间**：

```
21:51–21:52  A 套拍摄
22:24:48     智能快递柜系统答辩.pptx 生成（嵌入 A 套）
22:26:36     智能快递柜系统实验报告.docx 生成（嵌入 A 套）
22:27–22:28  B 套重拍（本目录新增，未被回填进交付物）
```

即：B 套是交付物封版**之后**补拍的可复现流水线产物，**尚未回填**。

### 两套的差异与取舍建议

| 对比项 | A 套 | B 套 | 说明 |
|---|---|---|---|
| 可复现性 | ❌ 脚本未落盘 | ✅ 一条命令重跑 | 长期应迁到 B 套 |
| `05_mobile_pickup` | ✅ `08-mobile-pickup.png` 画面正常（待取 5 件，含超时待缴） | ❌ `05_mobile_pickup.png` **白屏**：`blank=true, wrong_screen=true, text_len=11`，仍是登录页 | B 套这张**不可用**，`12_screenshots.txt` 已自标 `!!` |
| 管理端看板数字 | 用户 **120**、格口占用 130 / 空闲 590 | 用户 **1703**、格口占用 131 / 空闲 589 | 用户数被压测自建账号抬高，导致两套图**数字不一致** |
| 重复图 | 无 | `06_admin_login.png` 与 `09_admin_login.png` **字节完全相同**（SHA 一致） | B 套重复，用一张即可 |

> **由此产生的一条真实风险（必须记录）**：PPT 第 16 页的旁注写着
> "快递公司 30 · 快递员 60 · **用户 120** · 包裹总数 310 · 格口占用 130 · 空闲 590"，
> 这组数字与 A 套那张看板图**严格对应**；若日后改用 B 套的 `10_admin_dashboard.png` 替换，
> 画面上的用户数会变成 1703，与页面旁注**对不上**。换图时必须同步改旁注数字。
> 根因是压测会自建用户账号（本次 195 个用例 + 压测新增，用户表从 120 涨到 1703），
> 属于**演示数据的可漂移项**，不是截图质量问题。

---

## 3. 截图 ↔ 功能 ↔ 建议 PPT 页码

> "建议 PPT 页码"优先填**当前已采用**的页码（A 套实际嵌入处，用 ✅ 标）；
> 未进 PPT 的图给出**建议落点**（用 ○ 标），供后续排版参考。页码 = 幻灯片序号（共 20 页）。

### 3.1 A 套（连字符 · 当前采用）

| 截图 | 功能 | 建议 PPT 页码 |
|---|---|---|
| `01-kiosk-home.png` | 触屏端首页：扫码出码 + 6 位取件码双入口，倒计时与快递员/帮助按钮 | ✅ 第 8 页（核心流程一）、第 16 页（系统实拍） |
| `02-kiosk-ai.png` | 触屏端智能助手对话：真实调 `/api/ai/chat`，无 Key 时降级为本地规则并标"本地规则"角标 | ✅ 第 11 页（创新 I-1）、第 16 页（系统实拍） |
| `03-kiosk-pickup.png` | 触屏端取件输入页：6 位取件码输入框 + 取件/返回首页 | ○ 第 8 页（补第 8 页取件一侧的中间态） |
| `04-admin-login.png` | 管理端独立登录页（`/admin/login`，与触屏端物理分离），已填账号 | ○ 第 10 页（四组创新之前的权限铺垫）或第 20 页附录 |
| `05-admin-dashboard.png` | 管理端看板：11 个指标卡 + 包裹状态分布环图 + 各柜体吞吐 Top10 + 近 14 天趋势 + 异常类型分布 | ✅ 第 16 页（系统实拍）——旁注数字取自本图 |
| `06-admin-view-packages.png` | 管理端包裹列表：按方向/状态/快递员筛选，分页与状态标签 | ✅ 第 16 页（系统实拍） |
| `07-mobile-login.png` | H5 手机端登录页：手机号 + 验证码，可切换"我是用户/我是快递员" | ✅ 第 13 页（创新 I-4 手机端入口） |
| `08-mobile-pickup.png` | H5 取件页：待取 5 件、超时待缴 ¥1.00、逐条"开柜取件"、底部五页签导航 | ✅ 第 8 页（核心流程一）、第 9 页（核心流程二） |
| `09-mobile-ai.png` | H5 包装推荐结果：敏感品类提示 + 五步包装法 + 建议格口规格 + 需携带材料（降级为规则） | ✅ 第 11 页（创新 I-1）、第 16 页（系统实拍） |
| `10-mobile-map.png` | H5 地图找柜：地图不可用时降级为柜体列表，按距离排序、显示空闲数与导航 | ✅ 第 12 页（创新 I-2/I-3） |

### 3.2 B 套（下划线 · 可复现流水线产物，待回填）

| 截图 | 功能 | 建议 PPT 页码 |
|---|---|---|
| `01_kiosk_home.png` | 触屏端首页（同 A 套 01，重新采集） | ○ 第 16 页（替换时需同步旁注） |
| `02_mobile_login.png` | H5 登录页，420×880 视口 | ○ 第 13 页 |
| `03_kiosk_ai.png` | 触屏端智能助手 —— **画面与 `01_kiosk_home.png` 几乎相同**（像素均值差 1.73），AI 屏未出现在首屏 | ⚠️ 不可直接用，见第 4 节 |
| `04_kiosk_pickup.png` | 触屏端取件 —— 同上，**与首页几乎相同**（差 3.21），取件屏未切到 | ⚠️ 不可直接用，见第 4 节 |
| `05_mobile_pickup.png` | H5 取件页 —— **白屏/停在登录页**，`_capture_log.json` 自标 `blank=true, wrong_screen=true` | ❌ 不可用 |
| `06_ai_recommend.png` | H5 包装推荐结果（真实调用 `/api/ai/pack-recommend`，降级为规则） | ○ 第 11 页（可替换 A 套 `09-mobile-ai.png`） |
| `07_map_nearby.png` | H5 地图找柜（`/api/cabinets/nearby` 距离排序，地图不可用降级） | ○ 第 12 页（可替换 A 套 `10-mobile-map.png`） |
| `08_payment.png` | H5 超时支付页：模拟支付角标、应付 ¥1.00、支付单号、待支付状态 | ○ 第 13 页（比 A 套用的登录页更贴题） |
| `09_admin_login.png` | 管理端登录页 —— **与 `06_admin_login.png` 字节相同** | ○ 第 20 页附录（二选一即可） |
| `10_admin_dashboard.png` | 管理端看板（同 `05-admin-dashboard.png` 版式，用户数 1703） | ○ 第 16 页（替换需同步旁注） |
| `11_admin_packages.png` | 管理端包裹列表（1440×980 视口，比 A 套高 80px，多露出 1 行数据） | ○ 第 16 页（可替换 A 套 `06-admin-view-packages.png`） |

---

## 4. 已知问题清单（不粉饰）

| # | 文件 | 问题 | 证据 | 处置 |
|---|---|---|---|---|
| 1 | `05_mobile_pickup.png`（B 套） | 白屏，仍停在登录页 | `_capture_log.json`：`blank=true, wrong_screen=true, text_len=11`；登录被限流 `status=429 验证码已发送，请 60 秒后再试` | **不要采用**；重拍时把该场景单独跑在限流窗口之外 |
| 2 | `06_admin_login.png` / `09_admin_login.png`（B 套） | 字节完全相同（重复图） | 两者 SHA-256 均为 `0d545e307894…` | 保留一张，另一张可删 |
| 3 | `03_kiosk_ai.png` / `04_kiosk_pickup.png`（B 套） | 声称是 AI 屏 / 取件屏，实际画面与首页一致（AI 气泡、取件屏都未激活） | 与 `01_kiosk_home.png` 像素均值差仅 1.73 / 3.21；`_capture_log.json` 里 `active_screen=null` | **不要采用**；触屏端切屏需等 AI 面板真正可见再截 |
| 4 | A 套整体 | 无可复现脚本，只有结果 | 仓库内无生成 A 套命名的脚本 | 保留作历史证据；新图一律走 B 套流水线 |
| 5 | A/B 两套管理端看板 | 用户数不同（120 vs 1703），与 PPT 旁注绑定 | 见第 2 节对比表 | 换图必须同步改旁注；或截图前先复位演示数据 |

> 上述第 1、3 条正是 `quality/reports/12_screenshots.txt` 输出的意义：
> 采集脚本会逐图判 `blank` / `wrong_screen` / `console_errors`，
> **而不是靠人眼抽查**。B 套流水线的价值就在这条自检上，即便它这次产出的图没被采用。

---

## 5. 复现命令

```powershell
# 前置：服务须先起，且 /api/health 返回 200
#   先起服务： python backend/app.py

# 重拍全部 11 张（输出到 evidence/screenshots/，文件名走 B 套下划线命名）
python quality\capture_screenshots.py --host http://127.0.0.1:5000

# 只重拍手机端三张
python quality\capture_screenshots.py --host http://127.0.0.1:5000 --only mobile

# 拍完看自检结论（白屏 / 横向溢出 / 控制台异常）
Get-Content quality\reports\12_screenshots.txt -Encoding UTF8
```

> 采集脚本 `quality/capture_screenshots.py` 会先做健康检查，服务不可用时直接退出码 2，不会产出一堆白图。

---

## 6. 与其它证据的对应关系

| 证据 | 位置 | 关系 |
|---|---|---|
| 截图自检摘要 | `quality/reports/12_screenshots.txt` | B 套逐图 `OK / !!` 结论（本次 11 张、1 个问题） |
| 逐图元数据 | `evidence/screenshots/_capture_log.json` | URL、视口、`blank`、`h_overflow`、`wrong_screen`、`console_errors` |
| 性能证据 | `evidence/perf/`、`quality/reports/09_loadtest.txt` | 并发压测与 cProfile 原始输出 |
| 质量门禁汇总 | `quality/reports/99_summary.txt` | 195 用例 / 56.32% 覆盖率 / pylint 9.59·9.77 |
| 答辩材料索引 | `docs/09-答辩演示与复现索引.md` | 全项目证据入口（本文只覆盖截图一支） |
