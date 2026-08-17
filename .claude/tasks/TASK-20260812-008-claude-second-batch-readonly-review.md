# TASK-20260812-008：Claude第二批代码只读审核

> 当前状态：等待三条Codex泳道完成后执行；现在不得提前声称已审核。

## 可复制给Claude的提示词

```text
继续只读审核工创赛智能分拣装置第二批电控代码。

工作区：
C:\Users\29845\Desktop\工创赛

本任务为L3有限试行。开始前调用并遵守：
1. using-superpowers
2. code-review
3. verification-before-completion

若Skill缺失，记录真实缺失并采用最接近的安全流程；不得假装已调用。

八项治理必须有实际证据：
- 文书：记录文件、命令、结果和裁决；
- 求是：区分事实、推断、建议、未知；
- 建制：检查协议、集成层、STM32纯逻辑和树莓派应用边界；
- 协同：Claude只读，Codex实现，用户裁决；
- 谏议：主动找安全绕过和测试假绿；
- 试行：仅主机测试，禁止硬件动作；
- 审核：重新运行全部测试和静态检查；
- 史官：新建审查文件，不覆盖历史。

完整读取：
- 当前AGENTS.md与CLAUDE.md
- docs/requirements/analysis.md
- docs/design/interface-contract.md
- docs/design/code-first-principles-entry.md
- docs/design/stm32-state-machine-pseudocode.md
- docs/superpowers/plans/2026-08-12-second-batch-parallel-development.md
- .claude/tasks/TASK-20260812-005-cross-layer-integration.md
- .claude/tasks/TASK-20260812-006-stm32-c-logic-skeleton.md
- .claude/tasks/TASK-20260812-007-rpi-display-scheduler.md
- .claude/reviews/REVIEW-20260812-009-claude-enhanced-a-v04-comprehensive-review.md
- 第二批新增生产代码和测试

只允许新建：
.claude/reviews/REVIEW-20260812-010-claude-second-batch-code-review.md

不得修改生产代码、测试、计划、任务记录或旧审查文件。

必须检查：
1. 协议→上下文验证→状态机→fake HAL是否真实贯通；
2. CRC错误、目标错配和重复ACK是否不能错误放行；
3. 任一关键节点掉电/重启后是否锁定旧轮次，禁止自动续跑；
4. 固定容量缓存是否会静默覆盖旧身份，容量耗尽是否安全锁定；
5. C版CRC32是否通过01 02 03 04 05→0x470B99F4及Python↔C一致性测试；
6. C代码是否偷偷实现UART、GPIO、定时器、频率、电机或A4988参数；
7. 树莓派是否只有真实渲染成功后才生成DISPLAY_ACK意图；
8. 树莓派是否错误引入触摸控制或自行维护冲突的success_count规则；
9. RED/GREEN证据是否真实，失败是否来自目标行为而非环境；
10. 原有55项测试是否保持通过。

重新运行所有项目提供的验证命令，报告测试数量、failures、errors和退出状态。若缺少C工具链或显示硬件，记录为环境/实机阻塞，不得写成通过。

报告必须包含：总体裁决、P0/P1/P2、事实/推断/建议/未知、八项治理执行证据、采纳/驳回/待确认、允许继续的代码范围、仍禁止的硬件动作和独立性声明。
```

