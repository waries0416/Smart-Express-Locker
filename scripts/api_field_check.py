# -*- coding: utf-8 -*-
"""字段级文档一致性检查：文档声明的响应字段 ↔ 代码实际返回的字段。

为什么需要这个模块（真实背景）：
    `check_docs_consistency.py` 原来只查三件格式问题：代码围栏配对、
    表格分隔行、旧数字残留。**它查不出"文档写了某字段、代码其实不返回"**。
    这类漂移最危险，因为：
      · 前端照文档取值 → 拿到 undefined → 页面静默错（不报错，最难查）；
      · 评委照文档验接口 → 发现字段不存在 → 认为文档是编的。

    真实案例（本模块的两个验收案例）：
      1. `GET /api/pay/{pay_id}` 文档明确写"**本接口不返回 qr_code_url**"，
         这是 BUG1 修复后的行为约定。若哪天有人把 `qr_code_url` 加回查询接口，
         或者文档误把它写进查询响应示例，必须能被检出。
      2. `POST /api/business/send-order` 的 `sender_address` / `recipient_address`
         必须**成对**出现（要么都有、要么都没有）；只加一个说明改漏了。

检查策略（静态 AST，不启动服务）：
    1. 从文档里按「标题小节」切段，抽出小节标题里的 METHOD + PATH，
       以及该小节内所有 ```json 代码块里**作为响应示例**的顶层字段名；
    2. 从代码里用 AST 找到对应路由函数，抽 JSON 响应的字典键；
    3. 比对：文档有、代码无 → **漂移（报告）**；代码有、文档无 → 提示（不报错）。

    为什么用静态分析而不是真跑接口：
      · 无环境依赖（不需要 DB/服务），CI 与本地都能跑；
      · 能覆盖"权限不足时看不到"的分支（例如仅 admin 可见的字段）；
      · 缺点是看不到动态拼装的键（`**kwargs` 展开）—— 这类会明确标注"未能静态确认"，
        不算通过也不算失败，列出来供人工确认，不做静默放过。
"""
import ast
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")


# ---------------------------------------------------------------------------
# 一、从文档抽「小节 → 端点 → 响应字段」
# ---------------------------------------------------------------------------
HEAD_RE = re.compile(r"^(#{2,5})\s+(.*)$")
EP_RE = re.compile(r"(GET|POST|PUT|DELETE|PATCH)\s+`?(/api/[^\s`）)]+)")
JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)```", re.S)


def split_sections(text):
    """按标题切分为 [(level, title, start_line, body_lines)]。"""
    lines = text.splitlines()
    marks = []
    for i, line in enumerate(lines):
        m = HEAD_RE.match(line)
        if m:
            marks.append((i, len(m.group(1)), m.group(2).strip()))
    out = []
    for idx, (i, level, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        out.append({
            "level": level, "title": title, "start": i + 1,
            "body": lines[i + 1:end],
        })
    return out


def top_level_keys(obj):
    """取 JSON 对象的顶层键（只取第一层，嵌套不算响应字段漂移）。"""
    if isinstance(obj, dict):
        return [k for k in obj.keys() if not k.startswith("_")]
    return []


def parse_json_blocks(body_lines):
    """解析小节里的 json 代码块，返回 [(raw_text, parsed_or_None, kind)]。

    ⚠️ 必须区分**请求示例**与**响应示例**：
        POST /api/business/send-order 的小节里同时有请求示例
        （含 user_phone / weight / size_type...）和响应说明。
        如果把请求示例的键也算进"文档声明的响应字段"，
        就会把 weight / size_type 判成"代码未返回"——纯假阳性，
        且会让报告塞满噪声、掩盖真问题。第一版就踩了这个坑。

    判定方法（就近取**最近的非空行**，不要看一大段窗口）：
        取该块**正上方紧邻的一行**（跳过空行），
          含「请求体 / 请求示例 / 请求：」→ request
          含「响应 / 返回」              → response
        都不含 → 再向上最多看 4 行找线索；仍无 → unknown

    教训：一开始用"前 8 行窗口"，结果 4.1 小节的响应示例上方 8 行里
    同时有"请求体"和"响应"，被判成 unknown 而整块丢弃 ——
    于是那个端点"文档 0 字段"，检查形同空转（通过但没验任何东西）。
    必须就近判定，并且**把 unknown 数量计入统计**，防止静默失效。
    """
    text = "\n".join(body_lines)
    out = []
    for m in JSON_FENCE_RE.finditer(text):
        raw = m.group(1).strip()
        before = [l for l in text[:m.start()].splitlines() if l.strip()]
        kind = "unknown"
        # 就近向上找：先紧邻 1 行，再放宽到 4 行
        for window in (1, 4):
            ctx = " ".join(before[-window:])
            if not ctx:
                continue
            has_req = ("请求" in ctx) or ("request" in ctx.lower())
            has_resp = ("响应" in ctx) or ("返回" in ctx) or ("response" in ctx.lower())
            if has_resp and not has_req:
                kind = "response"
                break
            if has_req and not has_resp:
                kind = "request"
                break
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001  示例可能带注释/省略号
            parsed = None
        out.append((raw, parsed, kind))
    return out


def doc_endpoint_fields(doc_path):
    """抽出文档里每个端点小节声明的响应字段。

    返回 {endpoint_key: {"fields": set, "section": str, "line": int, "unparsed": [...]}}
    endpoint_key 形如 "GET /api/pay/{pay_id}"。
    """
    text = open(doc_path, encoding="utf-8").read()
    sections = split_sections(text)
    result = {}

    for sec in sections:
        m = EP_RE.search(sec["title"])
        if not m:
            continue
        method, path = m.group(1), m.group(2).rstrip("`")
        key = f"{method} {path}"
        blocks = parse_json_blocks(sec["body"])

        fields, unparsed = set(), []
        unknown_blocks = 0
        for raw, parsed, kind in blocks:
            if parsed is None:
                unparsed.append(raw[:80])
                continue
            if kind != "response":
                # 请求示例：**不计入**响应字段（否则必然假阳性）
                if kind == "unknown":
                    unknown_blocks += 1
                continue
            fields.update(top_level_keys(parsed))

        entry = result.setdefault(key, {
            "fields": set(), "section": sec["title"],
            "line": sec["start"], "unparsed": [], "unknown": 0,
        })
        entry["fields"] |= fields
        entry["unparsed"].extend(unparsed)
        entry["unknown"] += unknown_blocks

    return result


# ---------------------------------------------------------------------------
# 二、从代码抽「路由 → 返回字段」
# ---------------------------------------------------------------------------
def _route_paths(dec):
    """从 @bp.route(...) 装饰器取路径与方法。"""
    paths, methods = [], []
    if not isinstance(dec, ast.Call):
        return paths, methods
    for arg in dec.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            paths.append(arg.value)
    for kw in dec.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            for e in kw.value.elts:
                if isinstance(e, ast.Constant):
                    methods.append(e.value)
    return paths, methods or ["GET"]


def _dict_keys(node):
    """递归收集函数体内所有 dict 字面量的键（含 return / 赋值里的）。"""
    keys = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
    return keys


def _has_kwargs_splat(node):
    """检测是否有 **xxx 展开（静态无法穷举字段）。"""
    for n in ast.walk(node):
        if isinstance(n, ast.Dict) and any(k is None for k in n.keys):
            return True
        if isinstance(n, ast.keyword) and n.arg is None:
            return True
    return False


def _called_names(node):
    """收集函数体内的调用：(本地函数名集合, [(模块别名, 函数名)] 集合)。

    为什么要区分两种：
        return jsonify(payment.get_order(pid))   → 模块别名 payment + 函数 get_order
        return foo()                             → 本地函数 foo
    之前把两者混成一个"函数名集合"，导致 `amap_client.client_config()` 里的
    client_config 按名字全局查找，可能命中别的模块同名函数，或（更常见）
    找不到而把字段全判成缺失。必须按 `模块限定名` 精确定位。
    """
    local_calls = set()
    attr_calls = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                local_calls.add(f.id)
            elif isinstance(f, ast.Attribute):
                base = f.value
                if isinstance(base, ast.Name):
                    attr_calls.add((base.id, f.attr))
                else:
                    attr_calls.add(("", f.attr))
    return local_calls, attr_calls


def _module_func_index():
    """建立 {模块名: {函数名: 节点}} 与 {函数名: [节点]}（后者仅作兜底）。"""
    by_module, by_name = {}, {}
    roots = [BACKEND, os.path.join(BACKEND, "integrations")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for fn in sorted(os.listdir(root)):
            if not fn.endswith(".py"):
                continue
            full = os.path.join(root, fn)
            try:
                tree = ast.parse(open(full, encoding="utf-8").read())
            except SyntaxError:
                continue
            mod = fn[:-3]
            by_module.setdefault(mod, {})
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    by_module[mod][node.name] = node
                    by_name.setdefault(node.name, []).append(node)
    return by_module, by_name


def resolve_fields(tree, max_depth=2, cur_mod=None):
    """在函数体内收集 JSON 字段，并沿被调用函数递归展开（限深防环）。

    重要取舍：**只展开本项目内的业务函数，且深度压到 2 层**。
    原因（实测踩坑）：
        早期用了 4 层深度 + 全模块展开，结果把 amap_client.load_config()、
        deepseek_client 的配置字典、甚至常量映射表（SMALL_SIZE/MEDIUM_SIZE…）
        里的键全收了进来。于是"代码多出未文档化字段"一栏里出现
        Accept / Authorization / api_key / 中 / 小件 这类噪声，
        提示完全失去可读性，反而掩盖真问题。

    现在的策略：深 2 层足够覆盖常见形态
        路由函数 → 业务函数 → 返回字典
    再深就是配置/常量层，对"响应字段"没有判定价值。
    """
    by_module, by_name = _module_func_index()
    keys, truncated = set(), False
    seen = set()          # 已展开的 (模块, 函数) 或 函数名

    def walk(node, depth, cur_mod):
        nonlocal truncated
        if depth > max_depth:
            truncated = True
            return
        keys.update(_dict_keys(node))
        if _has_kwargs_splat(node):
            truncated = True

        local_calls, attr_calls = _called_names(node)

        # 本地调用：优先同模块，其次同名兜底
        for name in local_calls:
            if (cur_mod, name) in seen:
                continue
            seen.add((cur_mod, name))
            target = by_module.get(cur_mod, {}).get(name)
            if target is not None:
                walk(target, depth + 1, cur_mod)
            else:
                for t in by_name.get(name, []):
                    walk(t, depth + 1, cur_mod)

        # 模块限定调用：按 (模块名, 函数) 精确定位
        for mod, name in attr_calls:
            if (mod or "*", name) in seen:
                continue
            seen.add((mod or "*", name))
            target = by_module.get(mod, {}).get(name)
            if target is not None:
                walk(target, depth + 1, mod)
            elif not mod:
                for t in by_name.get(name, []):
                    walk(t, depth + 1, cur_mod)

    walk(tree, 0, cur_mod)
    return keys, truncated


def _blueprint_prefix(tree):
    """取文件里 Blueprint(...) 的 url_prefix，用于拼出完整路由路径。

    坑：`Blueprint(..., url_prefix="/api/pay")` 里的 prefix 已经包含 /api，
    若再统一加 "/api" 前缀就会变成 /api/api/pay/... 从而全部匹配失败。
    这里按文件各自的 prefix 拼，缺省才退回 /api。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if fn != "Blueprint":
                continue
            for kw in node.keywords:
                if kw.arg == "url_prefix" and isinstance(kw.value, ast.Constant):
                    return kw.value.value
    return ""


def code_route_fields():
    """扫描 backend/*.py，返回 [{"method","path","func","file","keys","splat"}]。

    path 为**拼上 blueprints 前缀后的完整路径**。
    """
    out = []
    for fn in sorted(os.listdir(BACKEND)):
        if not fn.endswith(".py"):
            continue
        full = os.path.join(BACKEND, fn)
        try:
            tree = ast.parse(open(full, encoding="utf-8").read())
        except SyntaxError:
            continue
        prefix = _blueprint_prefix(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                name = getattr(target, "attr", "") or getattr(target, "id", "")
                if name != "route":
                    continue
                paths, methods = _route_paths(dec)
                # 沿调用链收集字段（路由常是薄壳，真正字段在被调函数里）
                # 传入本文件的模块名，这样本地调用能优先在同一模块内解析
                keys, truncated = resolve_fields(node, cur_mod=fn[:-3])
                splat = truncated or _has_kwargs_splat(node)
                for p in paths:
                    for meth in methods:
                        out.append({
                            "method": meth.upper(),
                            "path": prefix + p,
                            "func": node.name,
                            "file": fn, "line": node.lineno,
                            "keys": keys, "splat": splat,
                        })
    return out


# ---------------------------------------------------------------------------
# 三、路径归一（把文档的 {pay_id} 与代码的 <int:pay_id> 对齐）
# ---------------------------------------------------------------------------
VAR_RE = re.compile(r"\{[^}]+\}|<[^>]+>")


def norm_path(p):
    p = re.sub(r"<int:(\w+)>", "{}", p)
    p = re.sub(r"<(\w+)>", "{}", p)
    p = re.sub(r"\{[^}]+\}", "{}", p)
    return p.rstrip("/") or "/"


def match_code(doc_key, code_routes):
    """把文档端点匹配到代码路由。

    代码侧的 path 已在 code_route_fields() 里拼好了 blueprints 前缀（含 /api），
    所以这里**不再**额外加 /api —— 否则会变成 /api/api/... 匹配不上。
    """
    method, path = doc_key.split(" ", 1)
    target = norm_path(path)
    for r in code_routes:
        if r["method"] != method:
            continue
        if norm_path(r["path"]) == target:
            return r
    return None


# ---------------------------------------------------------------------------
# 四、主检查
# ---------------------------------------------------------------------------
def check_api_fields(doc_path=os.path.join(ROOT, "docs", "api-innovations.md"),
                     verbose=True):
    """返回 (problems, notes)。problems 为必须修复的漂移。"""
    if not os.path.exists(doc_path):
        return [f"文档不存在：{doc_path}"], []

    doc = doc_endpoint_fields(doc_path)
    code = code_route_fields()
    problems, notes = [], []

    if verbose:
        print(f"\n[字段级] 文档端点小节 {len(doc)} 个，代码路由 {len(code)} 条")

    for key, info in sorted(doc.items()):
        route = match_code(key, code)
        if not route:
            notes.append(f"{key}：代码中未找到对应路由（可能未实现或路径不同），跳过字段比对")
            continue

        declared = info["fields"]
        actual = route["keys"]

        # 文档里根本没有可解析的响应示例块 → 无法做字段级校验。
        # 这不是"通过"，要如实标成"未校验"，否则会给出一份虚假的全面通过。
        if not declared:
            reason = ("小节内没有 json 响应示例（可能用表格/文字描述）"
                      if info.get("unknown", 0) == 0
                      else f"有 {info['unknown']} 个无法判定请求/响应的 json 块")
            notes.append(
                f"{key}：**未做字段级校验** —— {reason}。"
                f"（代码侧可收集 {len(actual)} 个字段，仅供参考）")
            if verbose:
                print(f"  {key:44s} 文档  0 字段（未校验）")
            continue

        if route["splat"]:
            notes.append(
                f"{key}：`{route['file']}:{route['line']}` {route['func']}() "
                f"含 ** 展开，字段无法静态穷举，**未做自动判定**，需人工确认")
        missing = sorted(declared - actual)
        extra = sorted(actual - declared)

        if verbose:
            print(f"  {key:44s} 文档 {len(declared):2d} 字段 / 代码 {len(actual):2d} 字段"
                  + (f"  ⚠️ 缺 {missing}" if missing else "  ✅"))

        # 只报"文档有、代码无" —— 这是会让前端/评委踩坑的方向
        for f in missing:
            problems.append(
                f"{key}：文档声明字段 `{f}`，但代码 "
                f"{route['file']}:{route['line']} {route['func']}() 未返回 → 文档漂移")
        if extra and not route["splat"]:
            notes.append(f"{key}：代码多出未文档化字段 {extra}（不报错，供补充文档参考）")

    return problems, notes


# ---------------------------------------------------------------------------
# 五、两个验收案例的**独立断言**（不依赖文档解析好坏）
# ---------------------------------------------------------------------------
def assert_known_cases(verbose=True):
    """两个已知案例的硬断言。

    这两个案例刻意写成"独立的断言"，而不是依赖上面的通用比对：
    通用比对只能发现"文档有、代码无"；而案例 1 要求的是
    "**文档不该有、代码也不该有**"（反向断言），通用逻辑覆盖不到。
    """
    problems = []
    code = code_route_fields()

    # ---- 案例 1：GET /api/pay/{pay_id} 不得出现 qr_code_url ----
    route = match_code("GET /api/pay/{pay_id}", code)
    if route is None:
        problems.append("案例1：代码中未找到 GET /api/pay/{pay_id} 路由")
    else:
        if "qr_code_url" in route["keys"]:
            problems.append(
                f"案例1：{route['file']}:{route['line']} {route['func']}() "
                f"返回了 qr_code_url —— 违反『查询接口不返回收款码』的约定")
        else:
            if verbose:
                print("  ✅ 案例1：GET /api/pay/{pay_id} 未返回 qr_code_url（符合约定）")

        # 文档侧也要反查：4.2 小节的 json 块里不得出现 qr_code_url
        doc_path = os.path.join(ROOT, "docs", "api-innovations.md")
        text = open(doc_path, encoding="utf-8").read()
        sections = split_sections(text)
        for sec in sections:
            if "GET /api/pay/{pay_id}" in sec["title"]:
                for raw, parsed, kind in parse_json_blocks(sec["body"]):
                    if parsed and kind == "response" and "qr_code_url" in top_level_keys(parsed):
                        problems.append(
                            f"案例1：文档 {sec['start']} 行的查询接口响应示例里"
                            f"出现了 qr_code_url（应只在 create 的示例里）")
                break
        else:
            problems.append("案例1：文档中未找到 GET /api/pay/{pay_id} 小节")

    # ---- 案例 2：send-order 的 sender_address / recipient_address 必须成对 ----
    route2 = match_code("POST /api/business/send-order", code)
    if route2 is None:
        problems.append("案例2：代码中未找到 POST /api/business/send-order 路由")
    else:
        a = "sender_address" in route2["keys"]
        b = "recipient_address" in route2["keys"]
        if a != b:
            problems.append(
                f"案例2：{route2['file']}:{route2['line']} {route2['func']}() "
                f"只返回了 {'sender_address' if a else 'recipient_address'}，"
                f"两个地址字段必须成对出现")
        elif not a:
            problems.append(
                f"案例2：{route2['file']}:{route2['line']} {route2['func']}() "
                f"两个地址字段都没有 —— 与文档声明的 send-order 新增字段不符")
        elif verbose:
            print("  ✅ 案例2：send-order 的 sender_address / recipient_address 成对出现")

    return problems


def main():
    print("=" * 78)
    print(" 字段级文档一致性检查 · docs/api-innovations.md")
    print("=" * 78)
    problems, notes = check_api_fields()
    case_problems = assert_known_cases()

    print("\n" + "-" * 78)
    if notes:
        print(f"[提示] {len(notes)} 条（不阻断，供人工确认）")
        for n in notes:
            print("  · ", n)

    allp = problems + case_problems
    print("-" * 78)
    if allp:
        print(f"❌ 发现 {len(allp)} 处字段级漂移：")
        for p in allp:
            print("  - ", p)
        return 1
    print("✅ 字段级检查通过：文档声明的响应字段均能在代码中找到，两个已知案例断言成立")
    return 0


if __name__ == "__main__":
    sys.exit(main())
