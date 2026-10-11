#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 派工-多AI并行-2026-09-20/01~06 六份提示词统一插入「只读模式 / 输出落点」硬条款。

背景：用户同时开 6 个 AI 会话，全部指向同一个工作目录。只要有任意两个会话同时写文件，
就会互相覆盖且不报错。因此所有派工提示词必须：
  1. 禁止一切文件写入（含新建笔记/草稿、跑测试产生的 __pycache__）；
  2. 全部产出改为「写进回复正文 + 代码块 + 落点标注」；
  3. 不自己跑验证，改为给出 `[建议执行]` 命令，由总控串行执行；
  4. 在回执头里增加「文件写入」自报字段。

幂等：重复运行不会重复插入。

用法（在本工作区根目录）：
    py -3 工具/加固派工提示词-只读模式.py
"""

import pathlib
import sys

DIR = pathlib.Path(__file__).resolve().parent.parent / "派工-多AI并行-2026-09-20"
TARGETS = [
    "01-Codex-T5-T9-固件补丁.md",
    "02-Claude-T6-T11-评审官.md",
    "03-DeepSeek-T7-T8-时序与语义.md",
    "04-豆包-T12-T2-赛规与流程.md",
    "05-Grok-T4-接线单.md",
    "06-ChatGPT-T1-T3-几何与诊断.md",
]

# 插入锚点：每份提示词里「交付格式」小节之前（该标题在 6 份中格式一致）
ANCHOR = "\n## 【交付格式（严格照写"
MARK = "【🔴 输出落点"

BLOCK = """## 【🔴 输出落点：只准写在回复里，禁止碰我任何一个文件】

**这一条优先于本提示词里的其它一切要求。若与别处冲突，以这条为准。**

我现在**同时开着 6 个 AI 会话**，全部指向同一个工作目录 `C:\\Users\\29845\\Desktop\\工创赛`。
只要有**两个**会话同时写文件，就会互相覆盖——后写的把先写的结果吃掉，**而且不会有任何报错**。
所以：

1. **绝对不要创建 / 修改 / 删除 / 移动 / 重命名任何文件**，
   包括**新建** `.md` / `.txt` / 计划文件 / 笔记 / 待办 / 报告 / 草稿 / 临时文件。**没有例外。**
2. **不要执行任何会产生文件的命令**：不要跑测试、不要编译、不要格式化、不要 `pip install`、
   不要动 `__pycache__` / `.pytest_cache` / `build/`（跑测试会生成这些目录，**也算写文件**）。
3. **你全部的产出都写在回复正文里**，用代码块包起来。
   每条产出前面**先写一行「落点」**，格式：

   ```
   [落点] 目标文件：<相对路径> ｜ 方式：整体新建 / 整体替换 / 替换 :起-止 行 ｜ 语言：<x>
   ```

   然后紧接着放代码块。**新建文件也一样——把内容贴在回复里，不要落盘。**
   我自己会在 6 个 AI 全部回来、比对完冲突之后，统一决定什么时候写入。
4. **不许自己跑验证**（会写文件）。改成写一句 `[建议执行] <完整命令>`，
   由我**串行**统一执行并回填结果。
5. **能切只读模式就先切**（强烈建议，这是最可靠的一道锁）：
   - Codex：`--sandbox read-only`
   - Claude Code：plan mode，或只放行 `Read / Grep / Glob` 三个工具
   - 网页版（DeepSeek / 豆包 / Grok / ChatGPT）：你本来就没有文件权限，这条对你只是提醒
6. **偏离自报**：如果你确实写了任何文件（哪怕一个字节），**必须在回执里如实列出完整路径**。
   **隐瞒比犯错严重得多**；如实报告不会让你这次任务作废。

---

"""

OLD_FIELD = "我改动过的文件: 无"
NEW_FIELD = "我改动过的文件: 无\n文件写入: 无（我只读，一个文件都没碰）"


def main() -> int:
    if not DIR.is_dir():
        print(f"找不到目录：{DIR}", file=sys.stderr)
        return 1

    changed, skipped, missing = [], [], []
    for name in TARGETS:
        p = DIR / name
        if not p.is_file():
            missing.append(name)
            continue

        text = p.read_text(encoding="utf-8")
        if MARK in text:
            skipped.append(name)
            continue

        if ANCHOR not in text:
            print(f"锚点未命中，跳过：{name}", file=sys.stderr)
            missing.append(name)
            continue

        text = text.replace(ANCHOR, "\n" + BLOCK + ANCHOR.lstrip("\n"), 1)
        if OLD_FIELD in text:
            text = text.replace(OLD_FIELD, NEW_FIELD, 1)

        p.write_text(text, encoding="utf-8", newline="\n")
        changed.append(name)

    for n in changed:
        print(f"  已加固  {n}")
    for n in skipped:
        print(f"  已存在  {n}（跳过，幂等）")
    for n in missing:
        print(f"  ⚠ 未处理 {n}", file=sys.stderr)

    print(f"\nOK  改动 {len(changed)} 份 / 跳过 {len(skipped)} 份 / 异常 {len(missing)} 份")
    if changed:
        print("    接着跑：py -3 工具\\生成派工看板.py")
    return 0 if not missing or changed else 1


if __name__ == "__main__":
    raise SystemExit(main())
