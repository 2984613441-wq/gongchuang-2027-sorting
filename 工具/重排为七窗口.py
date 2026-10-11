#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex / ChatGPT 复线后，把派工包重排为 7 窗口版。

目标布局：
  01-Codex-T5-T9-固件补丁.md            Codex（复活，原 _下线-01）
  02a-ClaudeA-T6-T11-评审官.md          Claude 窗口 1（去掉 T9）
  02b-ClaudeB-T3-屏幕侧问题.md          Claude 窗口 2（去掉 T5；T13 另见 07）
  03-DeepSeek-T7-T8-时序与语义.md        不动
  04-豆包-T12-T2-赛规与流程.md           不动
  05-Grok-T4-接线单.md                  Grok（去掉 T1）
  06-ChatGPT-T1-几何核算.md             ChatGPT（新，从 05 的 T1 段重组）
  07-T13-转盘舵机代码.md                 T13（已单独写好，本脚本不动）
  99-总控汇总与第二轮复核模板.md           不动

幂等：重复运行不会重复处理（产物已存在则跳过）。

用法（在本工作区根目录）：
    py -3 工具/重排为七窗口.py
    然后：py -3 工具\\生成派工看板.py
"""

import pathlib
import sys

D = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"

OLD_N = "同时开着 6 个 AI 会话"
NEW_N = "同时开着 7 个 AI 会话"

OLD_L5 = "   - 网页版（DeepSeek / 豆包 / Grok / ChatGPT）：你本来就没有文件权限，这条对你只是提醒"
NEW_L5 = ("   - 其他 AI 会话：**无论你用什么方式接进来（IDE / 桌面端 / 直接读盘 / 上传文件），"
          "一律按只读执行**；有权限不等于可以写。")

CLAUDE_3 = ("你负责三项：**T6**（夹取策略接入前评审）、**T9**（硬件安全收口）、**T11**（方案 C 草案评审），"
            "都属「**批准前评审 / 安全收口**」。")
CLAUDE_2 = "你负责的两项都是「**批准前评审**」。"

GROK_2 = ("**你的定位**：联网查手册/规格最强。你负责两项：\n"
          "- **T1** 相机位移的几何核算 —— **纯计算，参数已内嵌，不需要任何文件，可以立刻开始**；\n"
          "- **T4** 转盘接线单 —— 要联网把每个器件参数落到官方手册，**每个数字给来源链接**。")
GROK_1 = ("**你的定位**：联网查手册/规格最强。你的任务是给出一张「照着就能接线」的接线单，"
          "**并且用联网查到的官方手册数据把每个参数落实**。")

B_POS_OLD = ("你负责两项：**T5** 固件台架脉宽白名单补丁（读 C 出 diff）+ **T3** 屏幕侧问题定位与修复方案"
             "（读 Python 出 diff）。两项都是「**定位根因 → 出补丁文本**」。")
B_POS_NEW = ("你负责 **T3** 屏幕侧问题定位与修复方案（读 Python 出 diff）：「**定位根因 → 出补丁文本**」。\n"
             "（另一件 **T13 转盘舵机代码**在单独一份提示词 `07-T13-转盘舵机代码.md` 里，"
             "请一并接做，同属树莓派侧 Python。）")

GPT_POS = ("**你的定位**：有代码解释器，可以**真算**几何与覆盖面积。你的任务是 **T1 相机位移的几何核算**——"
           "把旋转视场与「托盘 ∩ 夹爪可达带」做**多边形求交算面积**，"
           "**独立复算并指出我哪里可能错了**，不是照抄我的数。")

GPT_WARN_OLD = ("> ⚠️ **本任务的硬要求**：凡是**器件规格数字**（舵机额定电压/堵转电流、PCA9685 电气参数、光电开关输出类型、\n"
                "> 电源额定电流），**必须给出来源链接**；查不到就写「**未查到**，待现场测量」。\n"
                "> **宁可写\"未查到\"，也不要给一个看起来合理的编造值——这个项目已经因为编造数值返工过。**")
GPT_WARN_NEW = ("> ⚠️ **本任务的硬要求**：**每一个面积、每一个百分比都要用代码真算出来**，并把代码贴出来。\n"
                "> 不许「目测」「估算」「大概」。\n"
                "> **宁可写\"我算不出来\"，也不要给一个看起来合理的编造值。**")


def cut_before(text: str, marker: str):
    """取 marker 之前的部分，并修掉结尾悬空的 ---"""
    i = text.find(marker)
    if i < 0:
        return None
    head = text[:i].rstrip()
    while head.endswith("---"):
        head = head[:-3].rstrip()
    return head + "\n"


def main() -> int:
    if not D.is_dir():
        print(f"找不到目录：{D}", file=sys.stderr)
        return 1

    done = []

    # ---------- 1) 复活 Codex ----------
    down = D / "_下线-01-Codex-T5-T9-固件补丁.md"
    live = D / "01-Codex-T5-T9-固件补丁.md"
    if down.is_file() and not live.is_file():
        parts = down.read_text(encoding="utf-8").split("---\n\n", 1)
        if len(parts) != 2:
            print("Codex 素材结构异常", file=sys.stderr)
            return 1
        body = parts[1].replace(OLD_N, NEW_N).replace(OLD_L5, NEW_L5)
        live.write_text(body, encoding="utf-8", newline="\n")
        down.unlink()
        done.append(f"复活  {live.name}")
    elif live.is_file():
        print(f"  已就位 {live.name}")

    # ---------- 2) 02a 去掉 T9 ----------
    p = D / "02a-会话A-T6-T9-T11-评审官.md"
    n = D / "02a-ClaudeA-T6-T11-评审官.md"
    if p.is_file():
        t = cut_before(p.read_text(encoding="utf-8"), "# 任务 T9 · ")
        if t is None:
            print("02a 找不到 T9 段", file=sys.stderr)
            return 1
        t = t.replace("任务号: T6+T9+T11", "任务号: T6+T11").replace(CLAUDE_3, CLAUDE_2)
        n.write_text(t, encoding="utf-8", newline="\n")
        p.unlink()
        done.append(f"改  {p.name} -> {n.name}（去 T9）")
    elif n.is_file():
        print(f"  已就位 {n.name}")

    # ---------- 3) 02b 去掉 T5，只留 T3 ----------
    p = D / "02b-会话B-T5-T3-固件与屏幕.md"
    n = D / "02b-ClaudeB-T3-屏幕侧问题.md"
    if p.is_file():
        full = p.read_text(encoding="utf-8")
        head = cut_before(full, "# 任务 T5 · ")
        i3 = full.find("# 任务 T3 · ")
        if head is None or i3 < 0:
            print("02b 定位 T5/T3 失败", file=sys.stderr)
            return 1
        t = head.rstrip() + "\n\n---\n\n" + full[i3:].rstrip() + "\n"
        t = t.replace("任务号: T5+T3", "任务号: T3").replace(B_POS_OLD, B_POS_NEW)
        t = t.replace("3. `电控/firmware/stm32f407_m144z/` 下的固件本身（App/ Core/ MDK-ARM/）—— T5 用。\n"
                      "4. `电控/src/electrical_control/rpi/display_hdmi.py` 与 `电控/deploy/run_chain.py` —— T3 用。",
                      "3. `电控/src/electrical_control/rpi/display_hdmi.py` 与 `电控/deploy/run_chain.py` —— T3 / T13 用。")
        n.write_text(t, encoding="utf-8", newline="\n")
        p.unlink()
        done.append(f"改  {p.name} -> {n.name}（去 T5）")
    elif n.is_file():
        print(f"  已就位 {n.name}")

    # ---------- 4) 05 去掉 T1；同时把 T1 段做成 ChatGPT 那份 ----------
    p = D / "05-Grok-T1-T4-接线单.md"
    n = D / "05-Grok-T4-接线单.md"
    gpt = D / "06-ChatGPT-T1-几何核算.md"
    if p.is_file():
        full = p.read_text(encoding="utf-8")
        i_t4 = full.find("# 任务 T4 · ")
        i_t1 = full.find("# 任务 T1 · ")
        i_fact = full.find("## 【已核实的事实")
        i_readonly = full.find("## 【🔴 输出落点")
        if min(i_t4, i_t1, i_fact, i_readonly) < 0:
            print("05 定位各段失败", file=sys.stderr)
            return 1

        t1_block = full[i_t1:].rstrip()

        # --- 5a) Grok 只留 T4 ---
        grok = cut_before(full, "# 任务 T1 · ")
        grok = (grok.replace("任务号: T1+T4", "任务号: T4")
                    .replace(GROK_2, GROK_1).replace(OLD_N, NEW_N).replace(OLD_L5, NEW_L5))
        n.write_text(grok, encoding="utf-8", newline="\n")

        # --- 5b) ChatGPT 组装 ---
        partA = full[:i_fact]                                   # 开头 + 项目 + 硬红线 + 已定案
        partB = full[i_readonly:i_t4]                           # 只读条款 + 交付格式
        g = partA + partB + t1_block + "\n"
        g = (g.replace("你是 **Grok 节点**", "你是 **ChatGPT 节点**")
              .replace("的**硬件选型与接线核查**负责人", "的**几何核算与现场操作卡**负责人")
              .replace(GROK_2, GPT_POS).replace(GPT_WARN_OLD, GPT_WARN_NEW)
              .replace("AI: Grok", "AI: ChatGPT").replace("任务号: T1+T4", "任务号: T1")
              .replace(OLD_N, NEW_N).replace(OLD_L5, NEW_L5))
        gpt.write_text(g, encoding="utf-8", newline="\n")

        p.unlink()
        done.append(f"改  {p.name} -> {n.name}（去 T1）")
        done.append(f"新  {gpt.name}（由 T1 段重组）")
    elif n.is_file():
        print(f"  已就位 {n.name}")

    # ---------- 5) 清掉残留的 ChatGPT 下线文件 ----------
    d6 = D / "_下线-06-ChatGPT-T1-T3-几何与诊断.md"
    if d6.is_file():
        d6.unlink()
        done.append(f"删  {d6.name}（T1 已重组、T3 已在 02b）")

    for x in done:
        print(f"  {x}")
    print(f"\nOK  完成 {len(done) if done else 0} 项")
    print("    接着跑：py -3 工具\\生成派工看板.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
