#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按「多开一个 Claude 会话」的方案重排派工包。

目标配置（Codex / ChatGPT 下线后）：
  02a-ClaudeA  T6 + T9 + T11   （= 现有的 02-Claude 文件，只改名）
  02b-ClaudeB  T5 + T3         （新生成：Claude 风格头 + T5 + T3）
  05-Grok      T1 + T4         （= 现有的 05-Grok 文件，只改名）
  03-DeepSeek  T7 + T8         （不动）
  04-豆包       T12 + T2       （不动）
  DSH 总控     T10 + 汇总       （不动）

素材来源：
  T5、T9 来自 `_下线-01-Codex-*.md`
  T1、T3 来自 `_下线-06-ChatGPT-*.md`

幂等：重复运行不会重复生成。

用法（在本工作区根目录）：
    py -3 工具/重排为双Claude会话.py
    然后：py -3 工具\\生成派工看板.py
"""

import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"

RENAME = [
    ("02-Claude-T6-T11-评审官.md", "02a-ClaudeA-T6-T9-T11-评审官.md"),
    ("05-Grok-T4-接线单.md", "05-Grok-T1-T4-接线单.md"),
]

SRC_CODEX = "_下线-01-Codex-T5-T9-固件补丁.md"
SRC_GPT = "_下线-06-ChatGPT-T1-T3-几何与诊断.md"
OUT_B = "02b-ClaudeB-T5-T3-固件与屏幕.md"

# Claude-B 的头部改写
REPL = [
    ("你是 **Codex 节点**，本项目（2027 工创赛 · 智能分拣装置）的**嵌入式固件工程**负责人。",
     "你是 **Claude 节点（会话 B）**，本项目（2027 工创赛 · 智能分拣装置）的**固件补丁与屏幕侧定位**负责人。"),
    ("**你的定位**：能直接读本机代码、能出可编译级 diff。你负责的两项都是「读固件 C 代码 → 出最小补丁」。",
     "**你的定位**：能直接读本机代码、能出可编译级 diff。\n"
     "你负责两项：**T5** 固件台架脉宽白名单补丁（读 C 出 diff）+ **T3** 屏幕侧问题定位与修复方案（读 Python 出 diff）。"
     "两项都是「**定位根因 → 出补丁文本**」。"),
    ("3. `电控/firmware/stm32f407_m144z/` 下的固件本身（App/ Core/ MDK-ARM/）。",
     "3. `电控/firmware/stm32f407_m144z/` 下的固件本身（App/ Core/ MDK-ARM/）—— T5 用。\n"
     "4. `电控/src/electrical_control/rpi/display_hdmi.py` 与 `电控/deploy/run_chain.py` —— T3 用。"),
    ("AI: Codex", "AI: Claude（会话 B）"),
    ("任务号: T5+T9", "任务号: T5+T3"),
]

MARK_T5 = "# 任务 T5 · "
MARK_T9 = "# 任务 T9 · "
MARK_T3 = "# 任务 T3 · "


def main() -> int:
    if not DIR.is_dir():
        print(f"找不到目录：{DIR}", file=sys.stderr)
        return 1

    # ---------- 1) 改名 ----------
    for old, new in RENAME:
        po, pn = DIR / old, DIR / new
        if po.is_file():
            po.rename(pn)
            print(f"  改名  {old}  ->  {new}")
        elif pn.is_file():
            print(f"  已就位 {new}（跳过）")
        else:
            print(f"  ⚠ 两者都不存在：{old} / {new}", file=sys.stderr)

    # ---------- 2) 生成 Claude-B ----------
    out = DIR / OUT_B
    if out.is_file():
        print(f"  已存在 {OUT_B}（跳过，幂等）")
        print("\nOK  接着跑：py -3 工具\\生成派工看板.py")
        return 0

    pc, pg = DIR / SRC_CODEX, DIR / SRC_GPT
    for p in (pc, pg):
        if not p.is_file():
            print(f"缺素材：{p.name}", file=sys.stderr)
            return 1

    codex = pc.read_text(encoding="utf-8")
    gpt = pg.read_text(encoding="utf-8")

    # 去掉「已下线」说明块，取原始正文
    if "---\n\n" not in codex:
        print("下线说明块结构异常", file=sys.stderr)
        return 1
    body = codex.split("---\n\n", 1)[1]

    i5 = body.find(MARK_T5)
    i9 = body.find(MARK_T9)
    if i5 < 0 or i9 < 0 or i9 <= i5:
        print("在 Codex 素材里定位 T5/T9 失败", file=sys.stderr)
        return 1
    prefix = body[:i5]
    t5 = body[i5:i9].rstrip()

    i3 = gpt.find(MARK_T3)
    if i3 < 0:
        print("在 ChatGPT 素材里定位 T3 失败", file=sys.stderr)
        return 1
    t3 = gpt[i3:].rstrip()

    for old, new in REPL:
        if old not in prefix:
            print(f"Claude-B 头部锚点未命中：{old[:36]}…", file=sys.stderr)
            return 1
        prefix = prefix.replace(old, new, 1)

    text = prefix.rstrip() + "\n\n---\n\n" + t5 + "\n\n---\n\n" + t3 + "\n"
    out.write_text(text, encoding="utf-8", newline="\n")

    print(f"  生成  {OUT_B}   （头部 {len(prefix):,} 字 + T5 {len(t5):,} 字 + T3 {len(t3):,} 字）")
    print("\nOK  接着跑：py -3 工具\\生成派工看板.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
