#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户澄清：各 AI 都能读本地文件。据此修正派工包。

修正内容：
1. 「网页版本来就没有文件权限」这句说明是错的 —— 从全部提示词里改掉，
   换成「无论你用什么方式接进来，一律按只读执行」。
2. 02a / 02b 不再绑定 Claude：改成「会话 A」「会话 B」，模型不限，文件改名。
   （回执头的 AI 字段改成让模型自己填。）

幂等：重复运行结果不变。

用法（在本工作区根目录）：
    py -3 工具/泛化会话AB并修正只读条款.py
    然后：py -3 工具\\生成派工看板.py
"""

import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"

SKIP_PREFIX = ("_", "00", "99")

# --- 1) 只读条款第 5 条：措辞修正（三种历史写法都要吃掉）---
OLD_L5 = [
    "   - 网页版（DeepSeek / 豆包 / Grok / ChatGPT）：你本来就没有文件权限，这条对你只是提醒",
    "   - 网页版（DeepSeek / 豆包 / Grok）：你本来就没有文件权限，这条对你只是提醒",
    "   - 网页版（DeepSeek / 豆包 / Grok / ChatGPT）：你本来就没有文件权限，这条对你只是提醒。",
    "   - 网页版（DeepSeek / 豆包 / Grok）：你本来就没有文件权限，这条对你只是提醒。",
]
NEW_L5 = ("   - 其他 AI 会话：**无论你用什么方式接进来（IDE / 桌面端 / 直接读盘 / 上传文件），"
          "一律按只读执行**；有权限不等于可以写。")

# --- 2) 会话 A / B 去 Claude 化 ---
A_OLD, A_NEW = "02a-ClaudeA-T6-T9-T11-评审官.md", "02a-会话A-T6-T9-T11-评审官.md"
B_OLD, B_NEW = "02b-ClaudeB-T5-T3-固件与屏幕.md", "02b-会话B-T5-T3-固件与屏幕.md"

FILE_REPL = {
    A_OLD: [
        ("你是 **Claude 节点**，本项目（2027 工创赛 · 智能分拣装置）的**评审官（Reviewer）**。",
         "你是**并行会话 A**（默认给 Claude，换成别的模型也完全没问题），"
         "本项目（2027 工创赛 · 智能分拣装置）的**评审官（Reviewer）**。"),
        ("AI: Claude\n", "AI: <你的名字>（会话 A）\n"),
    ],
    B_OLD: [
        ("你是 **Claude 节点（会话 B）**，本项目（2027 工创赛 · 智能分拣装置）的**固件补丁与屏幕侧定位**负责人。",
         "你是**并行会话 B**（模型不限，你想开给哪个 AI 都行），"
         "本项目（2027 工创赛 · 智能分拣装置）的**固件补丁与屏幕侧定位**负责人。"),
        ("AI: Claude（会话 B）", "AI: <你的名字>（会话 B）"),
    ],
}


def main() -> int:
    if not DIR.is_dir():
        print(f"找不到目录：{DIR}", file=sys.stderr)
        return 1

    touched = 0
    for p in sorted(DIR.glob("*.md")):
        if p.name.startswith(SKIP_PREFIX):
            continue
        text = orig = p.read_text(encoding="utf-8")

        for old in OLD_L5:
            if old in text:
                text = text.replace(old, NEW_L5)
        for old, new in FILE_REPL.get(p.name, []):
            if old in text:
                text = text.replace(old, new, 1)

        if text != orig:
            p.write_text(text, encoding="utf-8", newline="\n")
            print(f"  修正  {p.name}")
            touched += 1
        else:
            print(f"  无需改 {p.name}")

    # 改名
    for old, new in ((A_OLD, A_NEW), (B_OLD, B_NEW)):
        po, pn = DIR / old, DIR / new
        if po.is_file():
            po.rename(pn)
            print(f"  改名  {old}  ->  {new}")
        elif pn.is_file():
            print(f"  已就位 {new}")

    print(f"\nOK  内容改动 {touched} 份")
    print("    ⚠ 记得同步 工具/生成派工看板.py 里的 META 文件名，然后：py -3 工具\\生成派工看板.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
