# 电控实操方案与 Claude–Codex 协作闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将方案 B 细化为不绑定执行器型号的实操电控文档、状态机伪代码和 VS Code 协作文档。

**Architecture:** 三个互不写入彼此文件的模块并行产出：硬件接口与选型门禁、STM32 状态机伪代码、Claude–Codex 交接审查闭环。根索引只链接模块并固化跨模块不变量。

**Tech Stack:** Markdown、现有方案 B、STM32F407 抽象伪代码、VS Code 共享工作区。

## Global Constraints

- 校赛只实施方案 B：`MaixCAM Pro → Raspberry Pi 4B → STM32F407 → 执行器`。
- 不创建可烧录固件，不采购，不上电，不锁定电机、驱动器、电池、保险、线径或引脚电流数值。
- STM32 是唯一的运动、安全与15秒边界控制端；树莓派只发送单件高层任务。
- `BARRIER_READY`、`MOTION_DONE`、`ITEM_RESULT`、`DISPLAY_ACK` 是不同事件；只有成功 `ITEM_RESULT` 更新计数。
- 急停硬件切断危险执行器动力支路；同轮不得自动跳件、重放运动、自动回零、重抓或复位后续跑。

---

### Task 1: 硬件接口与选型门禁模块

**Files:**
- Create: `docs/design/electrical-control-practical-hardware.md`

**Produces:** 单电源分区、端子/通道预留、执行器参数卡、选型门禁、接线前验收表。

- [ ] 写明电源区、逻辑区、驱动区与急停边界。
- [ ] 定义三条运动通道、四路挡板、夹爪、限位、急停、故障、补光与通信的功能接口。
- [ ] 建立不含型号数值的参数卡与四步选型门禁。
- [ ] 检查文档不含具体执行器和保护器件型号或未验证电气数值。

### Task 2: STM32 状态机与伪代码模块

**Files:**
- Create: `docs/design/stm32-state-machine-pseudocode.md`

**Produces:** 硬件适配层接口、状态/事件表、伪代码、不变量与故障场景验证表。

- [ ] 定义 `AxisDriver`、`ServoBarrier`、`Gripper`、`LimitInput`、`SafetyPower` 抽象接口及失败返回。
- [ ] 写出从上电自检至完成/故障锁定/人工复位的状态机伪代码。
- [ ] 将幂等、显示确认、15秒计时与三条恢复闸口写为可检查不变量。
- [ ] 用场景表覆盖急停、限位、驱动故障、丢帧、显示超时、重复帧和人工复位。

### Task 3: VS Code 协作、任务和审查模块

**Files:**
- Create: `docs/design/claude-codex-collaboration.md`
- Create: `.claude/tasks/TASK-20260811-001-electrical-practical.md`
- Create: `.claude/reviews/REVIEW-20260811-001-electrical-practical-initial.md`

**Produces:** 模块并行协议、交接格式、决策与阻塞项规则，以及首轮弱独立性审查基线。

- [ ] 定义三模块可并行编辑的文件所有权及跨模块接口。
- [ ] 定义 Claude 与 Codex 的贡献/复核轮次，不预设固定主写角色。
- [ ] 记录本轮事实、推断、未知项、外部依赖和禁止的外部动作。
- [ ] 创建首轮审查记录，列明尚待 Claude 或机械组确认的项。

### Task 4: 集成索引与静态验收

**Files:**
- Create: `docs/design/electrical-control-practical-index.md`

**Consumes:** Tasks 1–3 的文档。

- [ ] 列出模块链接、共享不变量与交接顺序。
- [ ] 对所有新文档执行路径、必备标题、禁止具体选型、关键事件与15秒规则扫描。
- [ ] 将验收结果写入首轮审查记录；若发现冲突，记录为阻塞项而不是自行假定。
