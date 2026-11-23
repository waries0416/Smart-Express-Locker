# -*- coding: utf-8 -*-
"""交付物质量数字自检：deliverables/ 三个文件不得出现旧口径数字。

用法：
    python scripts/check_deliverable_numbers.py

检查项（zip 内所有 XML 去标签后全文匹配，覆盖正文、表格、演讲者备注）：
  1. 旧数字：36.86 / 9.69 / "32 用例"或"32 条测试" / "覆盖率才 36%"
  2. 已停用的旧报告文件名：02_coverage_report.txt、04_pylint.txt
  3. 新口径数字（195 / 56.32% / 9.59 / 9.77）附近必须能指回 quality/reports 出处

退出码：0 = 全部通过；2 = 有残留。
"""
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [
    ROOT / "deliverables" / "智能快递柜系统实验报告.docx",
    ROOT / "deliverables" / "答辩讲稿与视频时间轴.docx",
    ROOT / "deliverables" / "智能快递柜系统答辩.pptx",
]

BAD = [
    # —— 第二代旧口径（T3-prep 阶段）——
    ("旧覆盖率 36.86", re.compile(r"36\.86")),
    ("旧 pylint 9.69", re.compile(r"9\.69")),
    ("旧用例数 32", re.compile(r"32\s*(个)?\s*(用例|条测试)")),
    ("旧口径“覆盖率才 36%”", re.compile(r"覆盖率才\s*36\s*%")),
    ("已停用 02_coverage_report.txt", re.compile(r"02_coverage_report\.txt")),
    ("已停用 04_pylint.txt", re.compile(r"04_pylint\.txt")),
    # —— 第一代旧口径（R3b 阶段，已被 R9b 重采样覆盖，材料中不得再出现具体数值）——
    # 现行口径：202 用例 / 57.40%（稳定）/ pylint 9.60 与 9.77 / 3634 语句 / 1426 未覆盖
    ("R3b 旧覆盖率 56.32", re.compile(r"56\.32")),
    ("R3b 旧 pylint 9.59", re.compile(r"9\.59")),
    ("R3b 旧用例数 195", re.compile(r"(?<![\d.])195(?![\d.])")),
    ("R3b 旧分母 3611", re.compile(r"(?<![\d.])3611(?![\d.])")),
    ("R3b 旧未覆盖 1453", re.compile(r"(?<![\d.])1453(?![\d.])")),
    ("R3b 旧分支数 1270", re.compile(r"(?<![\d.])1270(?![\d.])")),
    ("R3b 旧归因 73.2%", re.compile(r"73\.2\s*%")),
    ("R3b 旧归因 70.8%", re.compile(r"70\.8")),
    ("R3b 旧归因 76.6%", re.compile(r"76\.6")),
    ("R3b 旧归因 607 行", re.compile(r"(?<![\d.])607(?![\d.])")),
    ("R3b 旧归因 1529 语句", re.compile(r"(?<![\d.])1529(?![\d.])")),
    ("R3b 旧 business 555 语句", re.compile(r"(?<![\d.])555(?![\d.])")),
    ("R3b 旧归因 30.41%", re.compile(r"30\.41")),
    # —— 区间表述：抖动已由 test_force_unlock_empty_cell.py 消除，只写稳定值 ——
    ("覆盖率区间 57.34", re.compile(r"57\.34")),
]
CITE = re.compile(
    r"0\d[a-z]?_[A-Za-z0-9_]+\.(?:txt|md)|99_summary\.txt|coverage\.xml|htmlcov|quality/reports/"
)
# 现行口径的锚点数字：至少要在材料里出现过，防止"改着改着把新数字也删了"
EXPECTED = {
    "202": re.compile(r"(?<![\d.])202(?![\d.])"),
    "57.40%": re.compile(r"57\.40"),
    "9.60": re.compile(r"9\.60"),
    "9.77": re.compile(r"9\.77"),
    "3634": re.compile(r"(?<![\d.])3634(?![\d.])"),
}

# 语义排除：HTTP 201 Created 是状态码，与"测试用例数"无关，永远不该被算作旧口径残留。
# 不做这层排除，脚本就会把 `400 != 201` 也报成残留，逼着人把状态码"改对"——
# 那才是真的技术错误。允许的例外必须显式白名单，而不是模糊匹配。
HTTP_201 = re.compile(
    r"(?:\d{3}\s*!=\s*201|201\s*!=\s*\d{3}|==\s*201|201\s*Created|"
    r"status[^\d]{0,8}201|response[^\d]{0,8}201|HTTP\s*201)"
)


def split_http_201(text):
    """把文本按 HTTP 201 上下文切掉，返回剩余部分（用于判断测试数类残留）。"""
    text = HTTP_201.sub(" [HTTP-STATUS-CODE] ", text)
    # XML 去标签会把「PPT P2」「00:40–01:30」这类相邻单元格拼成 "P201:30"，
    # 其中的 201 是页码 P2 + 时间码 01:30，不是用例数，必须排除。
    text = re.sub(r"P20(\d):", r"P2 0\1:", text)
    return text


def plain_texts(path):
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if name.endswith(".xml"):
                xml = z.read(name).decode("utf-8", "ignore")
                yield name, re.sub(r"<[^>]+>", "", xml)


def main():
    bad_total = 0
    for path in TARGETS:
        print("=" * 78)
        print(path.relative_to(ROOT))
        if not path.exists():
            print("  [缺失] 文件不存在")
            bad_total += 1
            continue
        seen = {"202": False, "57.40%": False, "9.60": False, "9.77": False, "3634": False}
        http201_kept = 0
        for name, text in plain_texts(path):
            # 先把 HTTP 201 上下文挖掉，剩下的才是"可能是测试数"的区域；
            # HTTP 201 是状态码，不参与旧的用例数判定，也不能被改。
            http201_kept += len(HTTP_201.findall(text))
            scan = split_http_201(text)
            for label, pat in BAD:
                for m in pat.finditer(scan):
                    bad_total += 1
                    a, b = max(0, m.start() - 80), min(len(scan), m.end() + 80)
                    ctx = re.sub(r"\s+", " ", scan[a:b])
                    print(f"  [残留] {label} @ {name}: ...{ctx}...")
            for key, pat in EXPECTED.items():
                if pat.search(scan):
                    seen[key] = True
            # 现行口径数字必须有出处（窗口前后各 600 字，兼容“原文引用”段落
            # 把文件名写在区块标题里的写法）
            for m in re.finditer(r"\b202\b|57\.40|9\.60|9\.77|3634", scan):
                window = scan[max(0, m.start() - 600): m.end() + 600]
                if not CITE.search(window):
                    print(f"  [提示·不阻断] {m.group(0)} 附近 600 字内无出处 @ {name}")
        # 用例数口径：挖掉 HTTP 201 后，不应再有孤立的 "201" 当作用例数
        for name, text in plain_texts(path):
            scan = split_http_201(text)
            for m in re.finditer(r"(?<![\d.])201(?![\d.])", scan):
                bad_total += 1
                a, b = max(0, m.start() - 70), min(len(scan), m.end() + 70)
                print(f"  [残留] 非 HTTP 语境的 201（疑为用例数未同步）@ {name}: "
                      f"...{re.sub(r'\s+', ' ', scan[a:b])}...")
        if http201_kept:
            print(f"  [信息] HTTP 201（Created）上下文 {http201_kept} 处，按状态码保留、不计残留")
        # 现行口径的锚点数字缺失也算问题（防止把新数字一起删掉）
        missing = [k for k, v in seen.items() if not v]
        if missing:
            bad_total += len(missing)
            print(f"  [缺锚点] 未出现现行口径数字：{missing}")
    print("=" * 78)
    print("旧数字残留合计:", bad_total)
    return 0 if bad_total == 0 else 2


if __name__ == "__main__":
    sys.exit(main())



