# 2026-08-22 电控+视觉集成交接提示词（Codex 版）

> 用途：新 Codex 对话继续 2026-08-21/22 的电控与视觉集成工作；假设新对话无上下文，先完整读取本文件与下列基线文件，再决定下一步。
> 前序交接：`docs/prompts/codex-handoff-20260821-next-conversation-prompt.md`

## 可直接发送的提示词

```text
你是接手 2026-08-22 工创赛电控+视觉集成工作的 Codex。工作区：C:\Users\29845\Desktop\工创赛。
当前目标：把“视觉/树莓派 → STM32”链路做成可实操闭环，重点是 JSONL 视觉输出、
完整 ASCII 指令桥接、树莓派部署入口和仓库卫生；实机仍未授权。

先完整读取以下文件，再决定下一步：
1. CLAUDE.md 与 AGENTS.md（治理约束）
2. docs/prompts/codex-handoff-20260821-next-conversation-prompt.md（前序交接）
3. docs/prompts/codex-handoff-20260822-next-conversation-prompt.md（本交接）
4. docs/design/2026-08-20-motion-command-list-v1.md（冻结 ASCII 指令清单）
5. docs/reports/2026-08-21-vision-stm32-action-bridge.md（桥接实施记录）
6. docs/reports/2026-08-21-open-source-reference-review.md（参考材料审查）
7. docs/prompts/claude-review-20260821-vision-stm32-action-bridge-readonly-review-prompt.md
8. docs/prompts/claude-review-20260822-git-commits-repo-hygiene-readonly-review-prompt.md
9. 集成/demo_bridge/action_bridge.py、bridge.py、config.full.example.json
10. 视觉/src/jsonl_emitter.py、集成/deployment/run_pipeline.py

已确认事实（截至本交接）：
- 分支 codex/stm32-motion-test-v1，工作区 git status 除本交接文档与新增审核词外干净。
- 4 笔提交已落地：dee8e836、d8496e04、ae13b00f、fd369a28，合计 40 文件、+3514 行。
- 桥接层：集成/demo_bridge/action_bridge.py，支持 MOVE / MOVE STEPS / SERVO /
  GROUP / BARRIER；默认 dry-run，全部动作默认 enabled=false，故障锁存、不自动重发运动。
- 视觉输出端：视觉/src/jsonl_emitter.py，输出四字段 JSONL（frame_id/label/
  confidence/ts_ms），fake source 可主机干跑。
- 树莓派入口：集成/deployment/run_pipeline.py + README。
- 主机测试：集成/demo_bridge 24/24 通过；视觉/src 4/4 通过；端到端干跑
  输出 IGNORED disabled（安全默认生效）。
- 参考材料已拆分：开源参考/电控、视觉、机械，原 zip 仍在根目录且被 .gitignore 忽略。
- 已知风险：git 对象库仍约 3.42 GiB（历史/远端残留 + 3 个 tmp 垃圾对象约 224 MB）；
  fd369a28 混入 easyeda-api.zip 与 sketch_apr05a/，与 20260821 交接清单冲突；
  尚未 push，尚未清理 .git。
- 实机未烧录、未串口实测、未运动验证；XY 标定、挡板/舵机脉宽、方向均未冻结。

下一步顺序：
1. 等 Claude 对两份审核词给出只读审核结论（桥接代码 + 提交/仓库卫生）。
2. 若 Claude 有 P1/P2 发现，逐项对照工作区核验后形成采纳/驳回记录。
3. 仓库卫生（每个动作需用户授权）：确认 tmp 垃圾对象可清理、远端分支历史
   是否保留，再执行安全清理；决定 easyeda-api.zip / sketch_apr05a 是否移出提交。
4. 视觉端把真实 YOLO 检测器接到 jsonl_emitter.py；串口实测和实机动作仍需
   用户对具体动作授权。

约束：
- 不得把主机测试或构建写成实机通过。
- 不得猜写未冻结的二进制帧、CRC16、波特率、GPIO、定时器、电机、限位、
  挡板角度、XY 步数/方向参数。
- 接线、上电、烧录、投板、采购、实机运动、push、git 改写和 .git 清理均需
  用户对具体动作授权。
- 每个 L2+ 步骤完成后更新交接单、验证记录和审核记录。
```

## 1. 用户指令时间线（摘要）

1. 2026-08-21：完成 P1 修复、Keil 重建、git 提交（37b06182）。
2. 2026-08-21：用户提供开源参考压缩包，要求拆分电控/视觉，方便分开推进。
3. 2026-08-21：完成 开源参考 拆分与 README，核对 venv 内容（缺 pyserial/PyQt5）。
4. 2026-08-21：完成视觉→STM32 桥接层、JSONL 输出端、部署入口与测试。
5. 2026-08-22：4 笔提交落地（dee8e836 等）；Codex 只读核验发现对象库残留与
   提交夹带问题；生成两份 Claude 审核词；本交接文档生成。

## 2. 已完成工作

- 固件 P1 超时修复已提交（37b06182），HEX 哈希 `A977A9FA...458DE`。
- 开源参考拆分：
  - `开源参考/电控/`：Arduino 固件 + README
  - `开源参考/视觉/`：YOLOv5 源码/权重/数据 + README（排除 venv 与视频）
  - `开源参考/机械/`：SolidWorks 模型 + README
- 视觉→STM32 链路：
  - `集成/demo_bridge/action_bridge.py`（完整 ASCII 指令事务层）
  - `集成/demo_bridge/config.full.example.json`（全动作默认禁用）
  - `视觉/src/jsonl_emitter.py`（JSONL 输出 + fake source）
  - `集成/deployment/run_pipeline.py`（树莓派部署入口）
  - 测试：`test_action_bridge.py`、`test_jsonl_emitter.py`
- 文档：桥接实施记录、参考材料审查记录、两份 Claude 审核词。

## 3. 当前状态

- 分支：`codex/stm32-motion-test-v1`
- 最近 4 笔提交：
  - `dee8e836` 忽略参考/供应商/编译产物
  - `d8496e04` 归档任务/审核/经验记录
  - `ae13b00f` 设计/报告/审查文档
  - `fd369a28` 视觉 JSONL + STM32 桥接 + 固件文档
- 工作区：仅新增本交接文档和 20260822 审核词为未跟踪。
- 未 push。

## 4. 未完成 / 待办

1. Claude 审核两份：桥接代码、提交/仓库卫生。
2. 仓库卫生：清理 3 个 tmp 垃圾对象（约 224 MB）与 3.42 GiB 历史对象；
   需要用户授权并决定远端历史保留策略。
3. 提交修正：fd369a28 中 `easyeda-api.zip`、`sketch_apr05a/` 是否移出，
   由用户裁决。
4. 视觉推理端：真实 YOLO/摄像头检测器接入 `jsonl_emitter.py`。
5. 实机流程（每个具体动作需授权）：串口 PING/STATUS/INPUTS → 低风险单轴
   MOVE STEPS → XY 每毫米步数与正方向标定 → 挡板/舵机脉宽标定。

## 5. 关键文件

- 治理：`CLAUDE.md`、`AGENTS.md`
- 指令清单：`docs/design/2026-08-20-motion-command-list-v1.md`
- 桥接代码：`集成/demo_bridge/action_bridge.py`
- 视觉输出：`视觉/src/jsonl_emitter.py`
- 部署入口：`集成/deployment/run_pipeline.py`
- 实施记录：`docs/reports/2026-08-21-vision-stm32-action-bridge.md`
- 参考审查：`docs/reports/2026-08-21-open-source-reference-review.md`
- 审核词：`docs/prompts/claude-review-20260821-vision-stm32-action-bridge-readonly-review-prompt.md`
- 审核词：`docs/prompts/claude-review-20260822-git-commits-repo-hygiene-readonly-review-prompt.md`

## 6. 约束

- 不得把主机测试/Keil 构建写成实机通过。
- 不得猜写未冻结的正式二进制帧、CRC16、波特率、GPIO、定时器、电机、限位、
  挡板角度、XY 步数/方向参数。
- 接线、上电、烧录、投板、采购、实机运动、push、git 改写、.git 清理均需
  用户对具体动作授权。
- 新知识先作为候选，经验证、脱敏、限定范围和独立审核后才可建议升格。

## 7. 进展更新（2026-08-22 追加）

- Claude 电控运动测试只读审核结论已转交并归档：
  `.claude/reviews/REVIEW-20260822-001-claude-ec-motion-test-firmware.md`（P0 计数运动
  update 中断未使能；P1 掩码 7/9 语义；P2 四项）。早期摘要归档另存为
  `REVIEW-20260822-001a-claude-ec-motion-test-summary.md`。
- Codex 已完成逐项核验：
  `.claude/reviews/REVIEW-20260822-002-codex-ec-motion-test-reconciliation.md`
  （P0 采纳待修法确认；P1 与冻结清单第 3 节一致，待用户裁决；P2 采纳建议）。
- 补充核验结论：NVIC 已在 `stm32f4xx_hal_msp.c` 使能，P0 修法 A 可行；TIM8 CC
  NVIC 未使能，Claude 的连带提示在当前工程不成立。
- 待办更新：用户确认 P0 修法、P1 掩码裁决后，实施 P0/P2 整改并更新记录；
  实机复核 `STEP_RESULT=DONE` 仍属逐项授权范围。
- 2026-08-22 追加：用户裁决 P0 修法 A、P1 保留 7/9 后，Codex 已实施
  P0/P2-1/P2-3/P2-4 与 P1 文档澄清；主机测试 2/2、Keil 0 Error(s)/0 Warning(s)，
  新 HEX SHA256=`1A565E56B11B2D564798D96D15295AD204820EA58A439AF3833A4E83FA8D8196`，
  记录见 `.claude/reviews/REVIEW-20260822-003-codex-p0-p2-ec-fixes.md`；
  实机 `STEP_RESULT=DONE` 复核仍未授权。
- Claude 回归审核已归档：
  `.claude/reviews/REVIEW-20260822-004-claude-ec-p0-p2-fixes.md`
  （电控固件 P0/P2 整改：通过（静态层面）；实机动作门禁：不允许；
  001 撞号已处理为 001a）。
