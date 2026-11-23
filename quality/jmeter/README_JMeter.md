# JMeter 使用与重跑说明 · 智能快递柜管理系统

## 0. 先说明事实：本机**未安装** JMeter

已穷尽探测，结果均为空：

```powershell
Get-Command jmeter                    # → 找不到
Get-ChildItem C:\apache-jmeter*       # → 不存在
Get-ChildItem "C:\Program Files\apache-jmeter*"        # → 不存在
Get-ChildItem "C:\Program Files (x86)\apache-jmeter*"  # → 不存在
Get-ChildItem C:\jmeter*, D:\*jmeter* -Directory       # → 不存在
```

**因此本项目所有并发压测数字都来自 Python 等价脚本** `quality/load_test.py`
（`concurrent.futures` + `requests`），**不是 JMeter 跑出来的**。
本文件提供标准 `.jmx` 计划与完整重跑命令，供装了 JMeter 的人交叉验证。

> 2026-11-18 曾尝试下载 `apache-jmeter-5.6.3.zip`（archive.apache.org），
> 首次下载被截断（863,886 字节，`OpenRead` 报"找不到中央目录结尾记录"），
> 已判定为无效文件并删除，未用其产出任何结论。

**本机已有的运行时：** Java 21.0.5（`D:\jdk21.0.5\bin\java.exe`）——装 JMeter 无需再装 JDK。

---

## 1. 安装 JMeter（约 2 分钟）

```powershell
# 方式 A：winget（本机有 winget）
winget install --id Apache.JMeter -e

# 方式 B：手动下载（与 .jmx 中声明的 5.6.3 对应）
$url = "https://archive.apache.org/dist/jmeter/binaries/apache-jmeter-5.6.3.zip"
Invoke-WebRequest -Uri $url -OutFile "$env:USERPROFILE\apache-jmeter.zip"
# 下载后务必校验完整性（本次失败就是截断）
$expected = 863886   # 注意：这是被截断的字节数，正常应约 85MB；请以官网校验和为准
Expand-Archive "$env:USERPROFILE\apache-jmeter.zip" -DestinationPath "D:\tools\"
# 结果：D:\tools\apache-jmeter-5.6.3\bin\jmeter.bat
```

验证：

```powershell
& "D:\tools\apache-jmeter-5.6.3\bin\jmeter.bat" --version
```

---

## 2. 前置：启动被测服务

JMeter 打的是真实 HTTP，需要先把 Flask 起起来：

```powershell
# 终端 1
cd D:\softwaretest
$env:PYTHONPATH = "D:\softwaretest;D:\softwaretest\backend"
$env:NOTIFY_WORKER = "0"
$env:MOBILE_DEV_MODE = "1"          # 让 send-code 返回 dev_code，登录链路才能自动跑通
python backend\app.py                # 监听 127.0.0.1:5000
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:5000/api/health
# 期望：status=ok, db=connected
```

---

## 3. 非 GUI 重跑（命令行，推荐）

JMeter 官方明确要求压测必须用非 GUI 模式，否则 GUI 本身会吃掉吞吐。

```powershell
$JMETER = "D:\tools\apache-jmeter-5.6.3\bin\jmeter.bat"
$OUT    = "D:\softwaretest\quality\reports\perf"

# 基础跑法：10 并发 / 5 秒爬坡 / 每线程 5 次循环
& $JMETER -n `
  -t "D:\softwaretest\quality\jmeter\smart_locker_load.jmx" `
  -Jhost=127.0.0.1 -Jport=5000 `
  -Jthreads=10 -Jrampup=5 -Jloops=5 `
  -l "$OUT\jmeter_result.jtl" `
  -e -o "$OUT\jmeter_html" `
  -j "$OUT\jmeter.log"

# 并发梯度（对齐 load_test.py 的 1/5/10/20）：逐档改 -Jthreads 重跑
foreach ($t in 1,5,10,20) {
  & $JMETER -n -t "D:\softwaretest\quality\jmeter\smart_locker_load.jmx" `
    -Jthreads=$t -Jrampup=5 -Jloops=5 `
    -l "$OUT\jmeter_t$t.jtl" -e -o "$OUT\jmeter_html_t$t" -j "$OUT\jmeter_t$t.log"
}
```

参数含义：

| 参数 | 含义 |
|---|---|
| `-n` | 非 GUI 模式 |
| `-t` | 测试计划 `.jmx` 路径 |
| `-Jthreads` / `-Jrampup` / `-Jloops` | 覆盖 `.jmx` 里的 `${__P(...)}` 变量 |
| `-l` | 结果 `.jtl`（CSV，逐请求） |
| `-e -o` | 生成 HTML 仪表盘报告（**输出目录必须不存在或为空**） |
| `-j` | JMeter 自身运行日志 |

看结果：

```powershell
# HTML 报告
Start-Process "$OUT\jmeter_html\index.html"
```

HTML 报告里直接有：**吞吐量（Throughput）、平均响应时间、P90/P95/P99、错误率**，
与 `quality/reports/perf/loadtest_*.md` 的字段一一对应，可直接对照。

---

## 4. 关键核验：并发存件「无重复格口分配」

JMeter 的断言只保证"请求成功"，**格口唯一性必须事后比对**。`.jmx` 的 C 场景
已用 JSR223 把每次分配的 `(cabinet_code, cell_code)` 追加写入 CSV。

```powershell
$JMETER = "D:\tools\apache-jmeter-5.6.3\bin\jmeter.bat"
$OUT    = "D:\softwaretest\quality\reports\perf"

# 清空上一次的分配记录
Remove-Item "$OUT\allocations.csv" -ErrorAction SilentlyContinue

# 跑 C 场景（20 并发）
& $JMETER -n -t "D:\softwaretest\quality\jmeter\smart_locker_load.jmx" `
  -Jthreads=20 -Jrampup=0 -Jloops=5 `
  -Jalloc_csv="$OUT\allocations.csv" `
  -l "$OUT\jmeter_store.jtl" -j "$OUT\jmeter_store.log"

# 判重 + 数据库交叉验证
python -c @"
import collections, io
p = r'$OUT\allocations.csv'
rows = [l.strip() for l in io.open(p, encoding='utf-8') if l.strip()]
keys = [tuple(r.split(',')[:2]) for r in rows]
dup  = [k for k, n in collections.Counter(keys).items() if n > 1]
print('分配总数 :', len(keys))
print('唯一格口 :', len(set(keys)))
print('重复分配 :', dup if dup else '无 ✅')
"@
```

数据库交叉验证（更强，直接看有没有一个格口压着两条 STORED 包裹）：

```powershell
$py = "C:\Users\31189\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $py -c @"
import sys; sys.path.insert(0,'D:/softwaretest'); sys.path.insert(0,'D:/softwaretest/backend')
import db
rows = db.query('''SELECT cell_id, COUNT(*) n FROM t_package
                   WHERE status='STORED' GROUP BY cell_id HAVING n>1''')
print('重复占用的格口:', rows if rows else '无 ✅')
"@
```

**判定标准：** 上两步都应为"无"。任何一条出现重复，就是并发存件的分配缺陷。

---

## 5. 关键核验：并发支付「无重复入账」

### 5.1 造数据（3 件超时未缴费包裹）

```powershell
$py = "C:\Users\31189\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
& $py -c @"
import sys, random
sys.path.insert(0,'D:/softwaretest'); sys.path.insert(0,'D:/softwaretest/backend')
import app as m, db
c = m.app.test_client()
cou = db.query_one('SELECT courier_id FROM t_courier ORDER BY courier_id LIMIT 1')
cab = db.query_one(\"SELECT cabinet_id FROM t_cabinet WHERE cabinet_code='CAB-001'\")
ids = []
for i in range(3):
    r = c.post('/api/business/store', json={
        'courier_id': cou['courier_id'],
        'user_phone': f'139{random.randint(10000000,99999999)}',
        'user_name': f'支付压测{i}', 'size_type':'SMALL', 'weight':0.5,
        'cabinet_id': cab['cabinet_id']})
    if r.status_code in (200,201):
        pid = r.get_json()['package']['package_id']
        db.execute('''UPDATE t_package SET status='EXPIRED', overtime_fee=1.00,
                      overtime_fee_paid=0, store_time=DATE_SUB(NOW(),INTERVAL 73 HOUR),
                      expire_time=DATE_SUB(NOW(),INTERVAL 1 HOUR) WHERE package_id=%s''', (pid,))
        ids.append(pid)
print('PAY_IDS=' + ','.join(map(str,ids)))
"@
# 把输出的 PAY_IDS 填到下一步的 -Jpay_ids
```

### 5.2 并发打支付接口

```powershell
& $JMETER -n -t "D:\softwaretest\quality\jmeter\smart_locker_load.jmx" `
  -Jthreads=20 -Jrampup=0 -Jloops=1 `
  -Jpay_ids=101,102,103 `
  -l "$OUT\jmeter_pay.jtl" -j "$OUT\jmeter_pay.log"
```

### 5.3 核验入账次数（核心）

```powershell
& $py -c @"
import sys
sys.path.insert(0,'D:/softwaretest'); sys.path.insert(0,'D:/softwaretest/backend')
import db
ids = [101,102,103]   # 换成 5.1 输出的 PAY_IDS
ph = ','.join(['%s']*len(ids))
rows = db.query(f'''SELECT package_id, overtime_fee_paid FROM t_package
                    WHERE package_id IN ({ph})''', ids)
print('最终缴费状态:', rows)
log = db.query(f'''SELECT package_id, COUNT(*) n FROM t_exception_log
                   WHERE package_id IN ({ph}) AND exception_type='TIMEOUT'
                     AND handle_result='RESOLVED'
                   GROUP BY package_id''', ids)
print('每件入账流水条数:', log)
bad = [r for r in log if r['n'] > 1]
print('重复入账:', bad if bad else '无 ✅（每件恰好 1 条）')
"@
```

**判定标准：** 每件包裹的 `TIMEOUT-RESOLVED` 流水必须**恰好 1 条**，
`overtime_fee_paid` 必须为 1。并发下若出现 2 条以上，即重复入账缺陷。

---

## 6. 与 Python 脚本的结果对照

两套工具跑同一场景后，把数字并排放进答辩材料：

| 指标 | JMeter（`jmeter_html/index.html`） | Python（`perf/loadtest_*.md`） |
|---|---|---|
| 吞吐量 | Throughput | 吞吐量(请求/秒) |
| 平均响应 | Average | 平均(ms) |
| P95 | 95% Line | P95(ms) |
| P99 | 99% Line | P99(ms) |
| 错误率 | Error % | 错误率(%) |

两套数字不应完全一致（实现与连接复用方式不同），**只要量级与趋势一致即可交叉印证**。
若差异很大，优先怀疑：① JMeter 是否跑在 GUI 模式；② 是否开启了 keep-alive；
③ Python 侧是否走了系统代理（`load_test.py` 已设 `trust_env=False` 规避）。
