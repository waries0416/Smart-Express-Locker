# -*- coding: utf-8 -*-
"""Dump the structure of the reference defence docx (read-only)."""
import sys
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

SRC = r"D:\softwaretest\智能纪要：门诊管理系统开发.docx"


def iter_block_items(parent):
    from docx.oxml.ns import qn
    body = parent.element.body
    for child in body.iterchildren():
        if child.tag == qn('w:p'):
            yield Paragraph(child, parent)
        elif child.tag == qn('w:tbl'):
            yield Table(child, parent)


def main():
    doc = Document(SRC)
    out = []
    ti = 0
    for block in iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            style = block.style.name if block.style is not None else ''
            if not text:
                continue
            out.append(f"[{style}] {text}")
        else:
            ti += 1
            rows = len(block.rows)
            cols = len(block.columns)
            first = []
            if rows:
                first = [c.text.strip().replace('\n', ' ') for c in block.rows[0].cells][:6]
            out.append(f"[TABLE#{ti} {rows}x{cols}] header={first}")
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(out))
    print(f"\n=== total blocks: {len(out)}, tables: {ti} ===")


main()
