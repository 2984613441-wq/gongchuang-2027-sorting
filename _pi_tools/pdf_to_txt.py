#!/usr/bin/env python3
"""把 TOFSense-M 的两份 PDF 提取成纯文本，方便检索关键信息。

用法：
    python _pi_tools/pdf_to_txt.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    ROOT / "TOFSense-M_User_Manual_V3.0_zh.pdf",
    ROOT / "TOFSense-M_Datasheet_V3.0_zh.pdf",
]


def main() -> int:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("缺 pypdf，先 pip install pypdf")
        return 1

    out_dir = ROOT / "_tofsense_docs"
    out_dir.mkdir(exist_ok=True)

    for pdf in FILES:
        if not pdf.is_file():
            print("缺文件: %s" % pdf.name)
            continue
        try:
            reader = PdfReader(str(pdf))
        except Exception as e:
            print("%s 打开失败: %s" % (pdf.name, e))
            continue
        print("%s: %d 页" % (pdf.name, len(reader.pages)))
        parts = []
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception as e:
                t = "[第 %d 页提取失败: %s]" % (i + 1, e)
            parts.append("\n===== 第 %d 页 =====\n%s" % (i + 1, t))
        text = "\n".join(parts)
        # PDF 里偶尔有孤立代理字符（\ud8xx），直接写 utf-8 会报
        # "surrogates not allowed" ⇒ 先清洗
        text = text.encode("utf-8", errors="replace").decode("utf-8")
        dst = out_dir / (pdf.stem + ".txt")
        dst.write_text(text, encoding="utf-8")
        print("  -> %s  (%d 字符)" % (dst.name, len(text)))
    print()
    print("输出目录: %s" % out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
