#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ChatGPT / Codex 下线后的重新分派。

变更：
  T1（相机位移几何核算）  ChatGPT -> Grok      （不需要文件，纯计算）
  T3（屏幕侧问题）        ChatGPT -> DSH 总控   （需读本地源码）
  T5（脉宽白名单补丁）    Codex   -> DSH 总控   （需读本地固件源码）
  T9（硬件安全收口）      Codex   -> Claude    （安全审查，Claude 强项）

做法：
  - 从 01-Codex 里抽出 `# 任务 T9 ·` 之后整段，追加进 02-Claude；
  - 从 06-ChatGPT 里抽出 `# 任务 T1 ·` 到 `# 任务 T3 ·` 之间整段，追加进 05-Grok；
  - 改 02 / 05 的定位说明与回执头任务号；
  - 把 01 / 06 改名为 `_下线-*` 并在文件头加说明（**不删除**，防止误发造成重复劳动）。

幂等：重复运行不会重复追加。

用法（在本工作区根目录）：
    py -3 工具/重新分派-ChatGPT与Codex下线.py
    然后：py -3 工具\\生成派工看板.py
"""

import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"

F_CODEX = "01-Codex-T5-T9-固件补丁.md"
F_CLAUDE = "02-Claude-T6-T11-评审官.md"
F_GROK = "05-Grok-T4-接线单.md"
F_GPT = "06-ChatGPT-T1-T3-几何与诊断.md"

# ---- Claude 侧：追加 T9 ----
CLAUDE_OLD_POS = ("**你的定位**：架构安全审查、边界/合规、多角度审议。**你的价值是找漏洞、找反例、找"
                  "「看起来对但其实不成立」的结论**——不是复述我的方案。你负责的两项都是「**批准前评审**」。")
CLAUDE_NEW_POS = ("**你的定位**：架构安全审查、边界/合规、多角度审议。**你的价值是找漏洞、找反例、找"
                  "「看起来对但其实不成立」的结论**——不是复述我的方案。\n"
                  "你负责三项：**T6**（夹取策略接入前评审）、**T9**（硬件安全收口）、**T11**（方案 C 草案评审），"
                  "都属「**批准前评审 / 安全收口**」。")
CLAUDE_OLD_TASK = "任务号: T6+T11"
CLAUDE_NEW_TASK = "任务号: T6+T9+T11"

# ---- Grok 侧：追加 T1 ----
GROK_OLD_POS = ("**你的定位**：联网查手册/规格最强。你的任务是给出一张「照着就能接线」的接线单，"
                "**并且用联网查到的官方手册数据把每个参数落实**。")
GROK_NEW_POS = ("**你的定位**：联网查手册/规格最强。你负责两项：\n"
                "- **T1** 相机位移的几何核算 —— **纯计算，参数已内嵌，不需要任何文件，可以立刻开始**；\n"
                "- **T4** 转盘接线单 —— 要联网把每个器件参数落到官方手册，**每个数字给来源链接**。")
GROK_OLD_TASK = "任务号: T4\n"
GROK_NEW_TASK = "任务号: T1+T4\n"

T1_TAIL = """
---

## 【附：T1 的额外要求】

T1 的每个数字都要能被**独立重算**出来，请把**计算过程 / 代码片段一并贴出**——
我要能照着复算，而不是只接受一个结论数字。
特别地：视场是**旋转**的（约 84.4°），不是轴对齐的，请确认你用对了旋转矩形求交；
并且「可用区 = 托盘 ∩ 夹爪可达带」，**不能只看其中一个**。
"""

MARK_T9 = "# 任务 T9 · "
MARK_T1 = "# 任务 T1 · "
MARK_T3 = "# 任务 T3 · "

DOWN_NOTE = """> 🔴 **本文件已下线，请勿发送。**
> 原派给 {who} 的任务已重新分派：
{items}
> 保留本文件只为 Codex / ChatGPT 恢复后可直接复用。**若误发，会造成重复劳动。**
> 现行分工见 `00-总控索引与分工.md`。

---

"""


def main() -> int:
    if not DIR.is_dir():
        print(f"找不到目录：{DIR}", file=sys.stderr)
        return 1

    for name in (F_CODEX, F_CLAUDE, F_GROK, F_GPT):
        if not (DIR / name).is_file():
            print(f"缺文件：{name}", file=sys.stderr)
            return 1

    codex = (DIR / F_CODEX).read_text(encoding="utf-8")
    claude = (DIR / F_CLAUDE).read_text(encoding="utf-8")
    grok = (DIR / F_GROK).read_text(encoding="utf-8")
    gpt = (DIR / F_GPT).read_text(encoding="utf-8")

    changed = []

    # ---------- T9: Codex -> Claude ----------
    if MARK_T9 not in claude:
        i = codex.find(MARK_T9)
        if i < 0:
            print("在 01-Codex 里找不到「# 任务 T9 ·」", file=sys.stderr)
            return 1
        t9 = codex[i:].rstrip()

        if CLAUDE_OLD_POS not in claude or CLAUDE_OLD_TASK not in claude:
            print("02-Claude 的定位段/任务号锚点未命中", file=sys.stderr)
            return 1
        claude = claude.replace(CLAUDE_OLD_POS, CLAUDE_NEW_POS, 1)
        claude = claude.replace(CLAUDE_OLD_TASK, CLAUDE_NEW_TASK, 1)
        claude = claude.rstrip() + "\n\n---\n\n" + t9 + "\n"
        (DIR / F_CLAUDE).write_text(claude, encoding="utf-8", newline="\n")
        changed.append(f"{F_CLAUDE}  <- 追加 T9（{len(t9):,} 字）")

    # ---------- T1: ChatGPT -> Grok ----------
    if MARK_T1 not in grok:
        i1 = gpt.find(MARK_T1)
        i3 = gpt.find(MARK_T3)
        if i1 < 0 or i3 < 0 or i3 <= i1:
            print("在 06-ChatGPT 里定位 T1/T3 边界失败", file=sys.stderr)
            return 1
        t1 = gpt[i1:i3].rstrip()

        if GROK_OLD_POS not in grok or GROK_OLD_TASK not in grok:
            print("05-Grok 的定位段/任务号锚点未命中", file=sys.stderr)
            return 1
        grok = grok.replace(GROK_OLD_POS, GROK_NEW_POS, 1)
        grok = grok.replace(GROK_OLD_TASK, GROK_NEW_TASK, 1)
        grok = grok.rstrip() + "\n\n---\n\n" + t1 + T1_TAIL
        (DIR / F_GROK).write_text(grok, encoding="utf-8", newline="\n")
        changed.append(f"{F_GROK}  <- 追加 T1（{len(t1):,} 字）")

    # ---------- 01 / 06 下线标记 ----------
    for src, who, items in (
        (F_CODEX, "Codex",
         ">   · **T5 台架脉宽白名单补丁 → 改派 DSH 总控**\n"
         ">   · **T9 硬件安全收口 → 改派 Claude**\n"),
        (F_GPT, "ChatGPT",
         ">   · **T1 相机位移几何核算 → 改派 Grok**\n"
         ">   · **T3 屏幕侧问题 → 改派 DSH 总控**\n"),
    ):
        p = DIR / src
        text = p.read_text(encoding="utf-8")
        if "本文件已下线，请勿发送" in text:
            continue
        p.write_text(DOWN_NOTE.format(who=who, items=items) + text,
                     encoding="utf-8", newline="\n")
        new_name = f"_下线-{src.split('-', 1)[0]}-{src.split('-', 1)[1]}"
        p.rename(DIR / new_name)
        changed.append(f"{src}  ->  {new_name}（已加下线说明）")

    if changed:
        for c in changed:
            print(f"  {c}")
        print(f"\nOK  完成 {len(changed)} 项变更")
        print("    接着跑：py -3 工具\\生成派工看板.py")
    else:
        print("OK  无事可做（已是最新，幂等）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
