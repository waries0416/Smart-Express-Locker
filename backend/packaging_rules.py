# 包装推荐 · 本地规则引擎（模型的"二次校验器" + 无 Key 兜底）
#
# 本模块是创新点 1 的**安全底线**，承担两件事：
#   1) 兜底：没有 DEEPSEEK_API_KEY 或调用失败时，用纯规则给出结构完全一致的推荐；
#   2) 校验：模型返回的 JSON 再经此模块二次校验后才落库/回前端。
#
# 为什么必须二次校验（docs/08 §1.3）：模型会返回数据字典外的枚举、漏掉禁运品、
# 给出 0 步或 20 步打包流程。若直接采信，前端渲染会崩、格口分配会静默失败、
# 甚至放行违禁品。因此：
#   · size_type    → 强制落回 t_cell.size_type 取值域 SMALL/MEDIUM/LARGE；
#   · forbidden    → 本地禁寄词表命中即**强制补全**，不依赖模型是否记得；
#   · sensitive    → 同上，本地敏感/易损词表兜底；
#   · packaging    → 步骤数裁剪到 [MIN_STEPS, MAX_STEPS]，step 连续重排；
#   · materials    → 归一到材料台账中存在的名称，去重限量；
#   · notice       → **固定文案**，含"以快递员/承运商审核为准"，模型改不动。
#
# 纯函数、零外部依赖、零 IO —— 因此可以完全离线单测（R1 验收要求）。
import re

SIZE_TYPES = ("SMALL", "MEDIUM", "LARGE")

# 固定提示文案（契约 §1.2：前端必须原样展示）
NOTICE = "结果仅供参考，以快递员/承运商审核为准"

MIN_STEPS = 2
MAX_STEPS = 8
MAX_ITEMS = 8
MAX_MATERIALS = 8

# ---------------------------------------------------------------------------
# 禁寄 / 限寄物品词表
#   命中即写入 forbidden（含原因）。之所以"本地强制补全"，是因为漏掉一条
#   违禁品是安全事故，而多提示一条只是体验问题——两者代价不对称。
# ---------------------------------------------------------------------------
FORBIDDEN_TERMS = [
    ("锂电池", ("锂电池", "锂电", "充电宝", "移动电源", "电池组"), "航空禁运，禁止寄递"),
    ("打火机", ("打火机", "火柴", "点火器"), "易燃易爆，禁止寄递"),
    ("酒精", ("酒精", "乙醇", "消毒液", "免洗洗手液"), "易燃液体，禁止寄递"),
    ("杀虫剂", ("杀虫剂", "农药", "灭鼠"), "有毒有害，禁止寄递"),
    ("香水", ("香水", "指甲油", "发胶", "摩丝"), "含易燃溶剂，限寄或禁运"),
    ("压缩气体", ("压缩气体", "气罐", "瓦斯罐", "氧气瓶"), "压力容器，禁止寄递"),
    ("管制刀具", ("管制刀具", "匕首", "弹簧刀", "砍刀"), "管制器具，禁止寄递"),
    ("枪支弹药", ("枪支", "子弹", "弹药", "仿真枪"), "违禁物品，禁止寄递"),
    ("毒品", ("毒品", "麻醉品", "大麻"), "违法物品，禁止寄递"),
    ("活体动物", ("活体动物", "宠物蛇", "活禽"), "活体动物禁止寄递"),
    ("强磁物品", ("强磁", "磁铁", "钕铁硼"), "可能干扰航空设备，需陆运并申报"),
    ("不明液体", ("不明液体", "无标签液体", "散装液体"), "成分不明，需开箱查验"),
]

# 敏感 / 易损物品词表：不禁止，但必须额外处理（缓冲、易碎标、单独包装等）
SENSITIVE_TERMS = [
    ("玻璃杯", ("玻璃杯", "玻璃杯具", "玻璃器皿", "玻璃瓶"), "易碎，需气泡膜多层包裹"),
    ("陶瓷", ("陶瓷", "瓷器", "茶具", "花瓶"), "易碎，需单独格位与缓冲"),
    ("显示屏", ("显示器", "屏幕", "液晶", "电视"), "受压易损，需硬纸箱 + 泡沫板"),
    ("精密仪器", ("仪器", "相机", "镜头", "无人机"), "精密易损，需防震与固定"),
    ("液体", ("液体", "饮料", "酒", "食用油"), "可能渗漏，需密封并直立放置"),
    ("粉末", ("粉末", "面粉", "代餐粉"), "可能撒漏，需双层密封袋"),
    ("药品", ("药品", "保健品", "胶囊"), "需防潮避光，建议原包装寄递"),
    ("食品", ("食品", "生鲜", "水果", "熟食"), "易腐，建议冷链或当日达"),
    ("工艺品", ("工艺品", "摆件", "雕塑", "泥塑"), "易损，需泡沫棉填充"),
    ("文件证件", ("证件", "合同", "发票", "证书"), "重要文件，建议文件封 + 硬壳"),
]

# 材料台账标准名（与 t_pack_material 种子数据对齐，便于生成备包装任务时精确匹配）
MATERIAL_CANON = [
    "气泡膜", "5 号纸箱", "易碎标签", "缠绕膜", "泡沫板", "封箱胶带",
]

# 不同规格的推荐材料与打包步骤
_SIZE_MATERIALS = {
    "SMALL": ["气泡膜", "封箱胶带"],
    "MEDIUM": ["气泡膜", "5 号纸箱", "封箱胶带"],
    "LARGE": ["气泡膜", "5 号纸箱", "泡沫板", "封箱胶带"],
}

_BASE_STEPS = [
    "清点物品",
    "缓冲包装",
    "装入箱体",
    "封箱贴标",
]

_STEP_DETAIL = {
    "清点物品": "逐件清点数量并拍照留底，确认无禁寄品、无渗漏",
    "缓冲包装": "用气泡膜包裹每件物品，易碎件至少 3 层，边角加泡沫板",
    "装入箱体": "物品居中放置，四周填充缓冲材料，箱内不留晃动空间",
    "封箱贴标": "封箱胶带十字加固，贴易碎标签与运单，标签不得被遮挡",
}


def _norm(text):
    return re.sub(r"\s+", "", str(text or "")).lower()


def detect_forbidden(description):
    """从描述里检出禁寄/限寄物品，返回 [{'name','reason'}]（保持词表顺序、去重）。"""
    d = _norm(description)
    if not d:
        return []
    hits = []
    seen = set()
    for name, keywords, reason in FORBIDDEN_TERMS:
        if name in seen:
            continue
        if any(_norm(k) in d for k in keywords):
            hits.append({"name": name, "reason": reason})
            seen.add(name)
    return hits


def detect_sensitive(description):
    """从描述里检出敏感/易损物品（禁寄的也算敏感，但由 forbidden 表达，避免重复）。"""
    d = _norm(description)
    if not d:
        return []
    forbidden_names = {x["name"] for x in detect_forbidden(description)}
    hits = []
    seen = set()
    for name, keywords, reason in SENSITIVE_TERMS:
        if name in seen or name in forbidden_names:
            continue
        if any(_norm(k) in d for k in keywords):
            hits.append({"name": name, "reason": reason})
            seen.add(name)
    return hits


# 体积/重量线索词：用于在无模型时估算 size_type
_LARGE_HINTS = ("大件", "家电", "行李箱", "被褥", "棉被", "显示器", "自行车", "椅子", "微波炉")
_MEDIUM_HINTS = ("书", "鞋", "外套", "衣服", "锅", "收纳箱", "电脑", "笔记本", "文具盒")
_SMALL_HINTS = ("手机", "耳机", "钥匙", "口红", "首饰", "证件", "药", "小件", "文件")

# 数量词：出现 5 件以上默认往大一级靠
_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10}


def estimate_size(description):
    """按关键词估算格口规格，返回 (size_type, reason)。"""
    d = _norm(description)
    if not d:
        return "MEDIUM", "未提供描述，按中等规格兜底"

    score = 0
    reasons = []
    if any(k in d for k in _LARGE_HINTS):
        score += 2
        reasons.append("描述含大家电/大件类物品")
    if any(k in d for k in _MEDIUM_HINTS):
        score += 1
        reasons.append("描述含日常中件物品")
    if any(k in d for k in _SMALL_HINTS) and not any(k in d for k in _LARGE_HINTS):
        score -= 1
        reasons.append("描述以小件为主")

    # 数量线索：能识别出的最大数量
    count = 0
    for m in re.finditer(r"(\d+)\s*(?:个|件|本|只|盒|瓶|包|双|台|部|张)", d):
        try:
            count = max(count, int(m.group(1)))
        except ValueError:
            pass
    for ch, n in _CN_NUM.items():
        if re.search(ch + r"(?:个|件|本|只|盒|瓶|包|双|台|部|张)", d):
            count = max(count, n)
    if count >= 5:
        score += 1
        reasons.append(f"数量较多（约 {count} 件）")

    if score >= 2:
        size = "LARGE"
    elif score <= -1:
        size = "SMALL"
    else:
        size = "MEDIUM"
    if not reasons:
        reasons.append("无可识别线索，按体积中等估算")
    return size, "；".join(reasons)


def _canon_material(name):
    """把任意材料名归一到台账标准名；无法归一时返回原文（截断），供人工核对。"""
    s = str(name or "").strip()
    if not s:
        return None
    for canon in MATERIAL_CANON:
        if _norm(canon) == _norm(s):
            return canon
    # 模糊匹配：模型常写"气泡膜卷""纸箱（5号）"
    for canon in MATERIAL_CANON:
        if _norm(canon) in _norm(s) or _norm(s) in _norm(canon):
            return canon
    return s[:20]


def default_materials(size_type, sensitive=None):
    """按规格给出默认材料清单（敏感物品追加易碎标签）。"""
    mats = list(_SIZE_MATERIALS.get(size_type, _SIZE_MATERIALS["MEDIUM"]))
    if sensitive and "易碎标签" not in mats:
        mats.append("易碎标签")
    return mats[:MAX_MATERIALS]


def build_packaging(description, size_type, sensitive=None):
    """按规格与敏感度生成打包步骤（step 从 1 连续递增）。"""
    steps = list(_BASE_STEPS)
    if sensitive:
        steps.insert(2, "易碎加固")
    return [
        {
            "step": i + 1,
            "title": title,
            "detail": _STEP_DETAIL.get(
                title,
                "对易碎/敏感部位额外加缓冲材料并固定，避免运输途中晃动",
            ),
        }
        for i, title in enumerate(steps)
    ]


def recommend_by_rules(description):
    """纯规则生成一份完整推荐（与 /api/ai/pack-recommend 响应字段一一对应）。

    返回的 dict 不含 source / elapsed_ms / degraded —— 那三个由 assistant.py 决定，
    这样"模型路径"与"规则路径"共用同一个校验器，结构天然一致。
    """
    desc = str(description or "").strip()
    forbidden = detect_forbidden(desc)
    sensitive = detect_sensitive(desc)
    size_type, size_reason = estimate_size(desc)
    if forbidden:
        # 命中禁寄品时，规格不再是重点，明确提示"需人工审核"
        size_reason = f"{size_reason}；但含禁寄/限寄物品，需人工审核后方可收寄"
    return {
        "forbidden": forbidden,
        "sensitive": sensitive,
        "packaging": build_packaging(desc, size_type, sensitive),
        "size_type": size_type,
        "size_reason": size_reason[:255],
        "materials": default_materials(size_type, sensitive),
        "notice": NOTICE,
    }


# ---------------------------------------------------------------------------
# 模型输出 → 服务端可信结构（二次校验）
# ---------------------------------------------------------------------------
def _as_list(value):
    return value if isinstance(value, list) else []


def _clean_items(raw_items, limit=MAX_ITEMS):
    """归一 {name, reason} 列表：补全 reason、截断长度、去重。"""
    out, seen = [], set()
    for it in _as_list(raw_items)[:limit]:
        if isinstance(it, str):
            name, reason = it.strip(), ""
        elif isinstance(it, dict):
            name = str(it.get("name") or "").strip()
            reason = str(it.get("reason") or it.get("detail") or "").strip()
        else:
            continue
        if not name:
            continue
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name[:100], "reason": (reason or "建议人工核对")[:500]})
    return out


def _clean_steps(raw_steps):
    """归一打包步骤：step 连续重排，裁剪到 [MIN_STEPS, MAX_STEPS]。"""
    steps = []
    for it in _as_list(raw_steps):
        if isinstance(it, str):
            title, detail = it.strip(), ""
        elif isinstance(it, dict):
            title = str(it.get("title") or it.get("name") or "").strip()
            detail = str(it.get("detail") or it.get("reason") or "").strip()
        else:
            continue
        if not title and not detail:
            continue
        steps.append({
            "title": (title or detail)[:60],
            "detail": (detail or title)[:500],
        })
    return [
        {"step": i + 1, "title": s["title"], "detail": s["detail"]}
        for i, s in enumerate(steps[:MAX_STEPS])
    ]


def _clean_size(raw_size, fallback="MEDIUM"):
    """枚举修正：任何字典外取值一律落回合法档位。"""
    s = str(raw_size or "").strip().upper()
    if s in SIZE_TYPES:
        return s
    # 常见近义写法归一
    alias = {
        "S": "SMALL", "小": "SMALL", "小件": "SMALL", "SMALL_SIZE": "SMALL",
        "M": "MEDIUM", "中": "MEDIUM", "中件": "MEDIUM", "MEDIUM_SIZE": "MEDIUM",
        "L": "LARGE", "大": "LARGE", "大件": "LARGE", "XL": "LARGE", "LARGE_SIZE": "LARGE",
    }
    if s in alias:
        return alias[s]
    return fallback if fallback in SIZE_TYPES else "MEDIUM"


def _clean_materials(raw_materials, size_type, sensitive):
    """材料清单：归一标准名、去重、保底为空时用默认清单。"""
    out, seen = [], set()
    for m in _as_list(raw_materials):
        name = _canon_material(m.get("name") if isinstance(m, dict) else m)
        if not name:
            continue
        key = _norm(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= MAX_MATERIALS:
            break
    if not out:
        return default_materials(size_type, sensitive)
    return out


def validate_model_output(raw, description):
    """把模型返回的 dict 校验成与规则路径**完全同构**的结果。

    这是"模型只给建议、服务端说了算"的落地实现：
      · 结构不合法不在这里抛错（由 assistant.py 判定），这里只做**纠偏**；
      · 本地禁寄词表强制补全，模型漏了也能被兜住；
      · 若模型整体没给出可用字段，则退回纯规则结果。
    """
    base = recommend_by_rules(description)
    if not isinstance(raw, dict):
        return base

    forbidden = _clean_items(raw.get("forbidden"))
    # 强制补全：本地词表命中但模型没提的，一律追加（安全事故代价不对称）
    local_forbidden = detect_forbidden(description)
    have = {_norm(x["name"]) for x in forbidden}
    for item in local_forbidden:
        if _norm(item["name"]) not in have:
            forbidden.append(item)
            have.add(_norm(item["name"]))

    sensitive = _clean_items(raw.get("sensitive"))
    local_sensitive = detect_sensitive(description)
    have_s = {_norm(x["name"]) for x in sensitive}
    for item in local_sensitive:
        if _norm(item["name"]) not in have_s:
            sensitive.append(item)
            have_s.add(_norm(item["name"]))
    # 禁寄物品不应同时出现在 sensitive 里（语义重复，前端会显示两遍）
    f_names = {_norm(x["name"]) for x in forbidden}
    sensitive = [x for x in sensitive if _norm(x["name"]) not in f_names][:MAX_ITEMS]

    size_type = _clean_size(raw.get("size_type"), base["size_type"])

    steps = _clean_steps(raw.get("packaging"))
    if len(steps) < MIN_STEPS:
        # 模型给的步骤太少（或没给）：用规则步骤补齐，保证前端能渲染
        steps = base["packaging"] if not steps else steps + base["packaging"][len(steps):]
        steps = [
            {"step": i + 1, "title": s["title"], "detail": s["detail"]}
            for i, s in enumerate(steps[:MAX_STEPS])
        ]

    size_reason = str(raw.get("size_reason") or "").strip() or base["size_reason"]

    return {
        "forbidden": forbidden[:MAX_ITEMS],
        "sensitive": sensitive,
        "packaging": steps,
        "size_type": size_type,
        "size_reason": size_reason[:255],
        "materials": _clean_materials(raw.get("materials"), size_type, sensitive),
        # 固定文案，模型改不动（契约 §1.2）
        "notice": NOTICE,
    }


# ---------------------------------------------------------------------------
# 本地 FAQ（无模型时的 AI 问答兜底）
# ---------------------------------------------------------------------------
FAQ_RULES = [
    (("超时", "过期", "收费", "保管费", "罚款"),
     "包裹超过免费保管期会转为超时状态，需要先支付超时保管费（每件 ¥1.00）才能取件。"
     "操作路径：手机端「我的包裹」→ 选择该包裹 → 完成支付 → 柜门会自动弹开；"
     "也可以在柜机屏幕输入取件码后按提示缴费。若缴费后仍无法取件，请联系现场工作人员。"),
    (("取件码", "输码", "取件", "怎么取"),
     "取件方式有三种：① 柜机屏幕输入 6 位取件码；② 手机扫码登录后远程开柜；"
     "③ 用手机系统相机扫描柜机屏幕上的二维码，直接进入取件页。"
     "取件码由快递员存件时生成，会通过短信发送到收件手机号。"),
    (("寄件", "怎么寄", "下单", "下单流程"),
     "寄件流程：① 在手机端选择目标柜体与格口规格 → ② 填写寄件人/收件人手机号并选择快递公司 → "
     "③ 格口自动弹开后放入物品并关门 → ④ 快递员凭揽收码取走包裹。"
     "如果拿不准规格，可以先用「智能包装推荐」描述物品，系统会建议格口大小和包装材料。"),
    (("禁寄", "能不能寄", "违禁", "锂电池", "电池"),
     "常见的禁寄/限寄物品包括：锂电池与充电宝（航空禁运）、打火机与酒精等易燃品、"
     "香水与指甲油等含溶剂物品、管制刀具、压缩气罐、活体动物等。"
     "具体以快递公司与承运商的审核为准，可在寄件前用「智能包装推荐」做一次预检。"),
    (("包装", "怎么包", "气泡膜", "纸箱"),
     "通用包装建议：易碎品（玻璃、陶瓷、屏幕）每件至少包 3 层气泡膜并加易碎标签；"
     "液体需密封后直立放置；箱内四周用泡沫板填充，确保晃动无空隙；"
     "封箱后十字加固胶带，运单标签不要遮挡封口。"),
    (("尺寸", "规格", "格口", "多大"),
     "格口分三档：小件（SMALL，限重 5kg）、中件（MEDIUM，限重 10kg）、大件（LARGE，限重 20kg）。"
     "超重会被系统拒绝，建议改用更大规格或拆单寄递。"),
    (("退件", "退回", "没取", "过期没取"),
     "包裹超过免费保管期且长时间未取，会被快递员退回。退回后请联系快递公司客服，"
     "凭运单号查询后续安排，也可以在手机端「我的包裹」查看退回状态。"),
    (("异常", "破损", "打不开", "柜门"),
     "如果柜门无法弹开或包裹破损，请先不要离开柜机：在柜机屏幕点击「异常登记」，"
     "或联系现场工作人员。管理员可以在后台远程开锁，系统会保留完整处理流水。"),
    (("隐私", "信息", "手机号"),
     "系统仅在取件/寄件必需环节使用手机号，页面上展示时做了脱敏（中间四位打码）。"
     "AI 包装推荐只发送物品描述文本，不会发送姓名、手机号或地址。"),
    (("客服", "人工", "投诉", "电话"),
     "各快递公司客服热线可在柜机「关于」页与运单上查看；"
     "柜体故障、取件异常请联系现场工作人员或校园/社区服务台。"),
]
FAQ_FALLBACK = (
    "这个问题暂时无法从本地知识库给出准确答案。建议：① 使用柜机屏幕的「取件」「寄件」引导；"
    "② 拨打快递公司客服热线；③ 联系现场工作人员。你也可以换个说法再问一次，"
    "例如「超时费怎么交」「快递柜打不开怎么办」。"
)


def answer_by_rules(message):
    """本地 FAQ 规则匹配；命中返回答案，未命中返回兜底引导文案。"""
    m = _norm(message)
    if not m:
        return FAQ_FALLBACK
    for keywords, answer in FAQ_RULES:
        if any(_norm(k) in m for k in keywords):
            return answer
    return FAQ_FALLBACK
