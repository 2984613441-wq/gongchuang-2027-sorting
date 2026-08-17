# 给 Codex 的 REVIEW-011 对账提示词

## 用途

用于在 Claude 完成 `REVIEW-20260813-011`（对 REVIEW-010 对账的独立只读回归审核）后，委托 Codex 对照工作区证据逐项验证 Claude 的发现项，形成新的采纳/驳回/待确认记录，并落地 3 项 P2 整改。

## 可直接发送的提示词

```text
你是本项目的执行方（Codex）。请对 Claude 的独立回归审核 REVIEW-20260813-011 做技术对账：逐项验证其发现项、形成采纳/驳回/待确认结论，并落地 P2 整改。你不是审核方，可修改本提示词明确授权的文件；其余只读。

工作区：
C:\Users\29845\Desktop\工创赛

先完整读取：
1. 电控/.claude/reviews/REVIEW-20260813-011-claude-review010-reconciliation.md（本轮要复核的审核结论）
2. 电控/.claude/reviews/REVIEW-20260812-010-claude-second-batch-code-review.md（上一轮被复核对象）
3. docs/reports/2026-08-13-review010-codex-reconciliation.md（上一轮你的对账记录）
4. docs/reports/2026-08-12-second-batch-codex-implementation.md（第二批实施记录）
5. 电控/stm32_logic/src/ec_state_machine.c、ec_dedup.c 与 tests/test_state_machine.c、test_dedup.c
6. 电控/src/electrical_control/rpi/__init__.py 及其测试
7. 电控/stm32_logic/evidence/ 现有全部证据文件

REVIEW-011 的总体裁决是「条件采纳（主机侧纯逻辑范围）」。它的核心结论是：
- P1-001（C 测试环境）与 P1-002（跨语言 CRC）已由 Claude 独立新鲜复跑关闭：C 35/35、CTest 1/1、CRC_MATCH=470B99F4、Python 90/90。
- P2-001/P2-002/P2-003 三处改动真实、正确、未越权、未改生产逻辑。
- 保留 3 项 P2（非阻塞）发现：P2-a、P2-b、P2-c。

请按下列顺序处理，并给出可复查的文件与行号定位。

一、逐项验证 Claude 的三项 P2 发现

P2-a：REVIEW-010 的 P2-001 实为误报（INVALID 处理已存在）
- Claude 声称：ec_state_machine.c:126-128 已把 EC_DEDUP_FULL 与 EC_DEDUP_INVALID 一并锁定为 EC_FAULT_DEDUP_CAPACITY_EXHAUSTED；ec_state_machine.c 的 mtime 是 2026-08-12 16:05，本轮（08-13）未改动，故「INVALID 处理在补回归测试前已存在」成立；REVIEW-010 的 P2-001 引用的代码片段（变量名 dedup_result、分支顺序、缺 || EC_DEDUP_INVALID 子句）是重建引用而非逐字引读。
- 你的动作：对照代码与 mtime（或你有更权威的 git/版本证据）确认后，给出采纳/驳回/待确认结论。若你有证据证明 ec_state_machine.c 本轮确被修改，必须如实推翻 Claude 结论并升级为 P1。不得修改 REVIEW-010 原文；澄清只写入你的新对账记录。

P2-b：本轮改动缺独立 RED/GREEN 证据文件
- Claude 声称：evidence/review-fix-red.txt、review-fix-green.txt 记录的是上一轮「弱独立审查整改」的 32 个测试 ID（9 个失败）；final-verification*.txt 记录 28 个 ID；没有任何证据文件记录本轮 35 个 ID 的新鲜 GREEN，也没有 P2-003 所述「首轮 1 个失败（测试自身期望错误）」的 RED 留痕。
- 你的动作：补存 evidence 文件（建议 电控/stm32_logic/evidence/p2-reconciliation-green.txt），内容须包含：新鲜 35 个测试 ID 的 GREEN 摘要（`ALL 35 STM32 LOGIC TESTS PASSED`、退出码 0）、CTest 1/1、CRC_MATCH=470B99F4，并附 P2-003 修正前/后的关键断言差异（把未插入的 first 误当已插入 → 改为先显式插入）。不得改动或删除任何历史证据文件。

P2-c：审核词要求读取的 AGENTS.md 在工作区不存在
- Claude 声称：全工作区无 AGENTS.md，审核词模板把它列为必读基线会落空；当前入口是 工创赛/CLAUDE.md 与全局 CLAUDE.md。
- 你的动作（用户已裁决补建）：在仓库根目录新建 工创赛/AGENTS.md。内容要求：(1) 明确 CLAUDE.md（项目级 + 全局）为唯一治理权威，AGENTS.md 不新增、不改写任何治理规则；(2) 摘录面向执行 agent 的最小必读要点——主机侧纯逻辑范围、只读审核与独立回归立场、禁止接线/上电/烧录/投板/采购/实机运动、不得猜写未冻结硬件参数；(3) 保持为「指针 + 摘要」，不整篇照抄 CLAUDE.md。不得与现有 CLAUDE.md 冲突。

二、验证方式

- 只读核对上述文件的当前内容与 mtime；可运行只读命令（git status、git diff --check、文件时间戳）。
- 若你要复跑 90 项 Python、35 项 C、CTest 或 CRC，按原有命令执行即可；C 构建若需临时 subst S: 映射，用后必须 subst S: /D 清理。
- 不得修改生产代码、测试、设计、接口契约，不得修改 REVIEW-010 或 REVIEW-011 原文，不得覆盖历史证据文件。

三、安全边界

- 本轮唯一允许写入：补存 P2-b 的证据文件、新建本对账记录、新建 工创赛/AGENTS.md（仅限 P2-c 授权范围）。其余一律只读。
- 禁止接线、上电、烧录、投板、采购、实机运动。
- 禁止修改或猜写任何未冻结硬件参数（完整 ITEM_TASK wire 格式、外层帧、CRC16、波特率、GPIO、定时器、电机、限位、A4988）。

四、输出

新建对账记录：
docs/reports/2026-08-13-review011-codex-reconciliation.md

格式：
1. 总体结论（采纳闭环 / 条件采纳 / 驳回，注明主机侧范围）。
2. 采纳/驳回/待确认清单（对应 P2-a、P2-b、P2-c，每项给结论 + 事实/证据 + 定位）。
3. 落地整改说明（P2-b 证据文件路径与内容要点；P2-a/P2-c 的澄清或待确认去向）。
4. 验证汇总（若复跑，给实际数字与退出码；未复跑则明确标注，不得沿用 Claude 的旧数字冒充你的结果）。
5. 安全边界确认。

不得以对账建议替代用户对实机、采购、投板等外部写入动作的授权。
```

## 对账完成后的处理

Codex 形成新的采纳/驳回/待确认记录后，P2-a 若仍有分歧（如 Codex 有证据推翻 Claude 的「未改生产逻辑」结论）交回用户裁决；P2-b 证据补存与 P2-c 的 AGENTS.md 补建完成后，本轮 REVIEW-010 对账即闭环。
