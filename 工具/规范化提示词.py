#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词规范化：修掉重新分派留下的三处小瑕疵。

1. 会话数：共享条款里写的是「同时开着 6 个 AI 会话」，现在实际是 5 个（2 Claude + DeepSeek + 豆包 + Grok）。
2. 分隔线：块拼接处出现 `---` 连续两行，收敛成一行。
3. 02b 的附注：原写「T1 与 T3 的共同要求」，但 T1 已转给 Grok，改成 T3 专用。

幂等：重复运行结果不变。

用法（在本工作区根目录）：
    py -3 工具/规范化提示词.py
    然后：py -3 工具\\生成派工看板.py
"""

import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"
SKIP_PREFIX = ("_", "00", "99")

OLD_N = "我现在**同时开着 6 个 AI 会话**，全部指向同一个工作目录"
NEW_N = "我现在**同时开着 5 个 AI 会话**（2 个 Claude + DeepSeek + 豆包 + Grok），全部指向同一个工作目录"

F_B = "02b-ClaudeB-T5-T3-固件与屏幕.md"
OLD_TAIL = """## 【附：T1 与 T3 的共同要求】

两件任务都要求「**能被别人照着复核**」：
- T1 的每个数字都要能在代码解释器里重跑出来，请把**代码片段一并贴出**；
- T3 的每条修复都要写清「**改完怎么证明修好了**」（一条命令或一行日志）。"""
NEW_TAIL = """## 【附：T3 的额外要求】

每条修复都要写清「**改完怎么证明修好了**」——一条命令，或一行日志。
我要能照着验证，而不是接受一个「已修复」的结论。"""


def main() -> int:
    if not DIR.is_dir():
        print(f"找不到目录：{DIR}", file=sys.stderr)
        return 1

    touched = 0
    for p in sorted(DIR.glob("*.md")):
        if p.name.startswith(SKIP_PREFIX):
            continue
        text = orig = p.read_text(encoding="utf-8")

        text = text.replace(OLD_N, NEW_N)
        while "---\n\n---\n\n" in text:
            text = text.replace("---\n\n---\n\n", "---\n\n")
        if p.name == F_B and OLD_TAIL in text:
            text = text.replace(OLD_TAIL, NEW_TAIL)

        if text != orig:
            p.write_text(text, encoding="utf-8", newline="\n")
            print(f"  规范化  {p.name}")
            touched += 1
        else:
            print(f"  无需改  {p.name}")

    print(f"\nOK  改动 {touched} 份")
    print("    接着跑：py -3 工具\\生成派工看板.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
