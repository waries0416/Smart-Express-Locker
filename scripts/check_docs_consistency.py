# -*- coding: utf-8 -*-
"""文档一致性自检。

两层检查：
  第一层（原有）· 格式层
    · 代码围栏配对
    · 表格分隔行上方必须是表头
    · 表格块内列数一致
    · 旧数字残留
  第二层（本次新增）· 字段层
    · docs/api-innovations.md 里每个端点声明的**响应字段**，
      必须能在后端代码里找到（沿调用链静态分析，不启动服务）
    · 两个硬断言：
        - GET /api/pay/{pay_id} 不得返回 qr_code_url（BUG1 修复后的约定）
        - POST /api/business/send-order 的 sender_address /
          recipient_address 必须成对出现

为什么要加第二层：
    格式层再干净，也证明不了"文档写的字段代码真的返回"。这类漂移最坑——
    前端照文档取值得 undefined、页面静默错；评委照文档验接口会发现字段不存在。
    真实案例：`GET /api/pay/{id}` 文档明确"不返回 qr_code_url"，
    若哪天有人把它加回去，格式层完全发现不了。

用法：
    python scripts/check_docs_consistency.py            # 两层都跑
    python scripts/check_docs_consistency.py --format-only   # 只跑格式层
"""
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

# 支持从任意 cwd 运行：脚本在 scripts/ 下，仓库根是其父目录
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)

FENCE = re.compile(r"^`{3,}[A-Za-z0-9_+-]*$")
SEP = re.compile(r"^\|[\s:\-|]+\|$")
OLD = re.compile(r"\b(312|122|233|268|168)\b")

# 旧数字残留检查的**误报抑制**。
#
# 原实现是裸正则 \b(312|122|233|268|168)\b，实测产生 9 处全是误报：
#   · docs/01 第 10 行的修订记录："修正 §8.1 数据约束（312→310 包裹、122→120 用户）"
#     —— 这是**变更说明**，不写旧值就说不清改了什么；
#   · docs/03 第 75 行："早期 v1.0 版本此列记为 122 / 312 / 233 / 268 / 168 … 已校正"
#     —— 同样是刻意的历史说明；
#   · docs/06 第 111 行：`http://192.168.1.20:5000/m` —— **168 是 IP 段**，纯误报。
#
# 所以改成两条抑制规则：
#   1) 该行含"变更/修订/校正/改为/旧值/原为/早期"等字样 → 视为**变更说明**，不算残留；
#   2) 数字出现在 IP / 版本号 / 端口上下文（前后有 '.' 或 ':'）→ 不算残留。
# 这样既保留"真的残留"检出能力，又不制造噪声。
OLD_CONTEXT_EXEMPT = re.compile(
    r"变更|修订|校正|改为|改成|旧值|原为|早期|历史|→|->|曾经"
    r"|误记|当时|此前|口径|记的|记为|读数")
OLD_NUMBER_EXEMPT = {
    os.path.normpath("docs/00-现状盘点与差距表.md"),
}


def cell_count(line):
    """数一行的列数：跳过 \\| 转义与行内代码里的竖线。"""
    n = 0
    in_code = False
    i = 0
    s = line.strip()
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            i += 2
            continue
        if ch == "`":
            in_code = not in_code
        elif ch == "|" and not in_code:
            n += 1
        i += 1
    return n


# docs/0*.md + docs/api-innovations.md + README.md
FILES = (sorted(glob.glob("docs/0*.md"))
         + (["docs/api-innovations.md"] if os.path.exists("docs/api-innovations.md") else [])
         + (["README.md"] if os.path.exists("README.md") else []))
problems = []

for f in FILES:
    lines = open(f, encoding="utf-8").read().splitlines()
    fences = [i for i, l in enumerate(lines, 1) if FENCE.match(l.strip())]
    if len(fences) % 2:
        problems.append(f"{f}: 代码围栏数 {len(fences)} 为奇数，位置 {fences}")

    for i, l in enumerate(lines):
        if SEP.match(l.strip()):
            if i == 0 or not lines[i - 1].lstrip().startswith("|"):
                problems.append(f"{f}:{i + 1} 表格分隔行上方不是表头")

    # 表格列数一致性（同块内）
    block = []
    for i, l in enumerate(lines, 1):
        if l.strip().startswith("|"):
            block.append((i, cell_count(l)))
        else:
            if len(block) > 2:
                counts = {c for _, c in block}
                if len(counts) > 1:
                    problems.append(
                        f"{f}: 表格块 {block[0][0]}-{block[-1][0]} 列数不一致 {sorted(counts)}")
            block = []
    if len(block) > 2:
        counts = {c for _, c in block}
        if len(counts) > 1:
            problems.append(
                f"{f}: 表格块 {block[0][0]}-{block[-1][0]} 列数不一致 {sorted(counts)}")

    # 旧数字残留（差距表类文件豁免 + 变更说明/IP 上下文豁免，见上方注释）
    if os.path.normpath(f) not in OLD_NUMBER_EXEMPT:
        for i, l in enumerate(lines, 1):
            m = OLD.search(l)
            if not m:
                continue
            # 规则 1：变更说明行
            if OLD_CONTEXT_EXEMPT.search(l):
                continue
            # 规则 2：数字嵌在 IP / 版本号里（前后紧邻 . 或 :）
            s, e = m.span(1)
            prev_ch = l[s - 1] if s > 0 else ""
            next_ch = l[e] if e < len(l) else ""
            if prev_ch in ".:" or next_ch in ".:":
                continue
            problems.append(f"{f}:{i} 疑似旧数字 {m.group(0)}")

    print(f"{f:38s} lines={len(lines):4d} fences={len(fences):3d}")

print()
if problems:
    print("=== 格式层：发现 %d 处问题 ===" % len(problems))
    for p in problems:
        print("  -", p)
else:
    print("=== 格式层：全部通过（围栏配对、表格结构、无旧数字）===")


# ---------------------------------------------------------------------------
# 第二层：字段级
# ---------------------------------------------------------------------------
def run_field_layer():
    fmt_only = "--format-only" in sys.argv
    if fmt_only:
        print("\n[字段层] 已按 --format-only 跳过")
        return 0
    try:
        import api_field_check as chk
    except ImportError:
        sys.path.insert(0, os.path.join(_ROOT, "scripts"))
        import api_field_check as chk

    print("\n" + "=" * 78)
    print(" 字段级检查 · docs/api-innovations.md")
    print("=" * 78)
    fproblems, notes = chk.check_api_fields()
    case_problems = chk.assert_known_cases()

    if notes:
        print(f"\n[提示] {len(notes)} 条（不阻断，含'未做校验'需人工确认）")
        for n in notes:
            print("  · ", n)

    allp = fproblems + case_problems
    print("-" * 78)
    if allp:
        print(f"❌ 字段层：发现 {len(allp)} 处漂移")
        for p in allp:
            print("  - ", p)
        return 1
    print("✅ 字段层：通过（所有声明字段均能在代码中找到；两个已知案例断言成立）")
    return 0


field_rc = run_field_layer()

sys.exit(1 if (problems or field_rc) else 0)
