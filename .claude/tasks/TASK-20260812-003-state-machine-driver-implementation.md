# TASK-20260812-003：状态机与 STEP/DIR 骨架并行实现

> 状态：实施中  
> 日期：2026-08-12  
> 等级：L3，八项治理功能有限试行；不宣称机制已正式验证或激活  
> 实施范围：仅主机侧 Python、fake HAL 与 fake pulse；禁止接线、上电、烧录、投板和实机运动

## 1. 任务认知层

| 字段 | 当前记录 |
|---|---|
| 原始需求 | 按已审方案继续开发，状态机与 STEP/DIR 骨架多线程实施，并保留 Claude–Codex 独立审查闭环。 |
| 表面问题 | 缺少可执行的状态机与通用轴驱动骨架。 |
| 真正问题 | 在电机、引脚、定时器、限位、急停详细回路和完整帧协议未冻结时，先用纯逻辑测试证明任务幂等、安全门和脉冲适配边界不会被硬件细节绕过。 |
| 必须目标 | 状态机核心不变量与驱动骨架安全顺序均有 RED→GREEN 证据；目录所有权隔离；全套主机测试可复现。 |
| 非必须目标 | 不实现 MCU 外设、完整抓放轨迹、真实回零、真实 UART、运动学、加减速、限流或 A4988 专用功能。 |
| 环境与资源限制 | Windows/PowerShell；Python 标准库 `unittest`；共享工作区含其他协作者文件；不得撤销无关修改。 |
| 安全风险 | 急停、动力许可、15秒边界、重复任务和停止后脉冲若设计错误，会污染未来实机实现。 |
| 节点能力路由 | Codex 两个执行线程分别实现状态机和驱动；主 Codex 集成验证及对账；Claude 在代码形成后只读独立审查。 |
| 决策边界 | P0-001 的 `image_id/success_count` 来源需用户裁决；本轮只消费抽象 `DisplayAckReceived`，不得修改 V0.3。 |
| 当前阶段 | 协议冻结子集14项测试已通过，Claude REVIEW-005 有条件通过；进入无电机泳道 B/C。 |
| 验收方式 | 每线程保存预期 RED 和 GREEN 命令/结果；协议+状态机+驱动全套测试、Python编译、未冻结参数扫描与 `git diff --check`。 |

## 2. 八项治理功能

| 功能 | 本轮动作 |
|---|---|
| 文书 | 本文件记录目标、所有权、证据、阻塞与交接。 |
| 求是 | 测试输出为证据；事实、推断和未知分开；不把 fake HAL 结果写成实机结论。 |
| 建制 | 协议→领域事件→纯状态机→动作意图→驱动适配；禁止反向越权。 |
| 协同 | 两线程只编辑各自目录，主 Codex 统一更新任务与审查记录。 |
| 谏议 | REVIEW-005 P0-001 保持阻塞；发现不可实现接口须记录而非猜补。 |
| 试行 | 仅主机侧 Python 假实现；所有物理动作禁止。 |
| 审核 | 完成后跑自动化、编译、扫描和差异检查，再交 Claude 只读审查。 |
| 史官 | 保留 RED/GREEN、Claude原审查和新的Codex对账，不覆盖历史。 |

## 3. Skill 使用记录

已完整读取并使用：`using-superpowers`、`executing-plans`、`dispatching-parallel-agents`、`test-driven-development`、`verification-before-completion`、`requesting-code-review`、`receiving-code-review`。

- `executing-plans`：按已审设计执行；P0阻塞不强行穿透。
- `dispatching-parallel-agents`：使用两个目录所有权独立线程。
- `test-driven-development`：测试先行并实际观察 RED。
- `receiving-code-review`：完整读取 REVIEW-005，技术核验后分类，不盲目采纳。
- `verification-before-completion`：只有最新全套命令退出0才可声称通过。
- `requesting-code-review`：实现后生成 Claude 新审查提示词和独立文件目标。

未采用工作树：当前用户要求 Claude/Codex 在共享 VS Code 工作区通过文件协作，且工作区包含未提交的跨节点成果；本轮以互斥目录所有权避免冲突，不创建分离上下文。

## 4. 文件所有权与并行泳道

| 泳道 | 唯一可写目录 | 禁止修改 |
|---|---|---|
| B：纯状态机 + fake HAL | `电控/src/electrical_control/state_machine/`、`电控/tests/state_machine/` | 协议、驱动、设计文档、任务/审查文件 |
| C：STEP/DIR + fake pulse | `电控/src/electrical_control/drivers/`、`电控/tests/drivers/` | 协议、状态机、设计文档、任务/审查文件 |
| 主 Codex | 本任务文件、新审查/对账文件、最终集成所需最小公共入口 | 不覆盖两个线程正在编辑的文件 |

所有线程均不是仓库唯一编辑者，不得撤销、清理或格式化他人的无关修改。

## 5. 泳道 B 验收

- `SM-ONCE-001/002`：重复身份不重放，同身份异载荷锁定。
- `SM-GATE-001/002`：未消费首个有效 `DISPLAY_ACK` 前拒绝下一件；重复/错件ACK不放行。
- `SM-EVENT-001/002`：`MOTION_DONE`、成功结果、显示确认不互相替代。
- `SM-ESTOP-001`、`SM-POWER-001`：活动状态急停或动力许可丢失立即锁定。
- `SM-TIME-001/002`：内部消息不续时，只有新进度token或首个有效显示确认更新时间基准。
- `SM-RESET-001`：复位建立新轮，不恢复旧件。
- 纯状态机不得访问 GPIO、串口、定时器或真实驱动。

P0-001 处理：状态机可消费已由上下文验证层生成的 `DisplayAckReceived`，但不得决定 `image_id/success_count` 来源或修改 CRC 范围。

## 6. 泳道 C 验收

- `DRV-SKEL-001`：DIR在本动作段第一个STEP之前建立。
- `DRV-SKEL-002`：stop/disable后STEP不再增加。
- 未enable、未配置参数或已有故障时显式拒绝运动。
- 驱动故障向上传播，不自动重试/重放。
- 通用适配不绑定 A4988，不包含GPIO、定时器、频率、加速度、步数换算、电压、电流或限流默认值。

## 7. Claude REVIEW-005 接收决议

| 发现 | 当前决议 | 依据/下一步 |
|---|---|---|
| P0-001 显示期望值来源 | 采纳为实机显示闭环阻塞；不在本轮选择A/B/C | 三方案会改变跨节点协议，需用户裁决；不阻塞B/C泳道。 |
| P1-001 独立CRC对照 | 采纳 | 主Codex在集成验证阶段增加不依赖生产函数的参考验证证据。 |
| P1-002 边界测试 | 部分采纳 | 补长度与u8范围；`target_seq=0`是否保留未冻结，不自行规定。 |
| P2-001 parse/decode命名 | 暂缓 | 当前职责正确，不为命名扩大本轮生产变更。 |
| P2-002 去重/序号测试 | 采纳 | 纳入状态机泳道。 |

## 8. TDD 证据

| 泳道 | RED | GREEN | 状态 |
|---|---|---|---|
| B 状态机 | 初始11项测试已绿，但无可验证的旧RED，不能算完整TDD。随后新增截止时间、上电急停和回零/待机计时边界；实际运行15项时失败7处，退出状态1：过期任务/进度/ACK可绕过，POWER_ON/POST急停未锁定，HOMING/READY误超时。 | 修正事件处理前截止检查并拆分急停/动力许可/本轮计时状态集合后，最终19项全部通过，退出状态0。额外安全验证、旧轮次/非递增帧、领域事件输出测试及实现由共享工作区另一编辑者并发补入，按共同成果记录，不归因给本线程。 | 纠偏RED→GREEN完成；首批实现证据弱 |
| C 驱动骨架 | 初始6项测试已绿，但无可验证的旧RED。补入STEP端口故障后再次发步测试，实际失败1处；随后共享工作区又出现stop/disable端口失败后的本地锁存测试，实际9项中失败2处，退出状态1；最后新增enable故障后禁止重试，实际12项中失败1处，退出状态1。 | STEP/方向/enable故障锁存，stop先本地锁存，disable先本地锁存；最终12项全部通过，退出状态0。 | 纠偏RED→GREEN完成；首批实现证据弱 |

说明：两个执行线程开始时目标目录已存在完整未跟踪代码，且检查期间文件仍发生并发修改。因此史官记录保留“弱独立性/首轮RED不可证明”，不把文件时间先后冒充实际执行证据。

最终验证（2026-08-12，本轮完成前重新执行）：协议14项、状态机19项、驱动12项，共45项通过；Python编译检查通过；未知硬件参数禁写扫描0命中；`git diff --check`通过。该结论仅针对主机侧代码，不代表实机验证。

## 9. 完成边界

本任务完成只表示主机侧纯逻辑和假端口通过测试。继续阻塞：P0-001协议裁决、真实执行器参数、A4988适配、限位、挡板到位、重力轴防坠、急停详细回路、外层帧协议、MCU移植、HIL及所有实机操作。

## 10. REVIEW-005 补充验证

P1-001 已用独立于生产 `zlib.crc32()` 的逐位参考实现复算：输入 `01 02 03 04 05` 得到 `0x470B99F4`，断言通过；随后协议14项测试仍全部通过。该证据降低Python实现与测试同源错误风险，但不替代未来 STM32 C 实现的跨语言向量测试。

P0-001 技术核对：Claude 推荐的方案A若只给 `ITEM_TASK` 增加 `image_id`，仍不足以让 STM32 获得期望 `success_count`。完整A至少还需冻结“STM32与树莓派均只在成功 `ITEM_RESULT` 后以同一初值/溢出规则维护本轮成功计数”，或把期望成功数显式传入。该选择属于V0.4跨节点协议决策，等待用户裁决。

## 11. Claude 只读独立审查提示词

将以下内容复制给 Claude；Claude 不得修改生产代码，只写新的审查文件：

```text
继续审查工创赛智能分拣装置电控代码。工作区：C:\Users\29845\Desktop\工创赛。

请完整读取：
1. AGENTS.md / 当前治理指令
2. docs/requirements/analysis.md
3. docs/design/interface-contract.md V0.3
4. docs/design/code-first-principles-entry.md
5. docs/design/stm32-state-machine-pseudocode.md V0.2
6. .claude/tasks/TASK-20260812-003-state-machine-driver-implementation.md
7. .claude/reviews/REVIEW-20260812-005-claude-protocol-code-review.md
8. 电控/src/electrical_control/state_machine/ 与对应测试
9. 电控/src/electrical_control/drivers/ 与对应测试

这是只读独立审查。不得修改生产代码、测试、协议或设计文档。把报告写入：
.claude/reviews/REVIEW-20260812-007-claude-state-driver-code-review.md

必须检查：
- 任意本轮计时状态处理事件前是否先检查15秒截止，过期任务/进度/DISPLAY_ACK不能先执行或续时；
- POWER_ON/POST及全部活动状态急停是否进入FAULT_LOCK并产生停止、禁驱、动力抑制意图；
- HOMING/READY是否被错误纳入本轮15秒计时；
- 一件最多一次、旧轮次任务、同身份异载荷、下一件门禁、成功数更新是否闭合；
- DisplayAckAccepted与协议DisplayAckReceived之间是否存在接口缺口，并明确P0-001仍阻塞什么；
- STEP/DIR方向是否先于首步，stop/disable/端口故障后是否还能产生STEP，是否存在自动重试；
- 是否猜写A4988、GPIO、定时器、频率、加速度、电压、电流、限流、步距或机械参数；
- 测试是否真正覆盖反例，并复跑协议、状态机、驱动三套测试与Python编译检查；
- 共享工作区首批TDD证据缺失是否被如实标为弱证据。

报告按：裁决、事实证据、P0/P1/P2问题、采纳/驳回/待确认、测试复现、实机前门禁、与REVIEW-005的关系。不得声称已进行硬件验证。
```

## 12. Codex 弱独立性护栏审查

同一Codex体系的只读审查复跑45项测试，均退出0；不是Claude审查，独立性标记为弱。

- 无新增代码级P0；协议P0-001继续阻塞实机 `DISPLAY_ACK` 闭环。
- P1：状态机消费 `DisplayAckReceived` 时依赖上游已经验证 `target_seq`；本层没有保存明确的期望目标序号。需由Claude重点审查跨层集成错接风险，并在P0-001裁决后补集成测试或显式期望字段。
- P1：`stop/disable` 端口失败已先锁存本地安全状态，后续不会发步；但是否还要永久保留原始端口故障用于诊断/禁止重新enable，当前契约未冻结。
- P2：建议补非法人工复位组合、同task不同 `target_seq`、stop/disable失败后的poll/enable语义测试。

护栏裁决：主机侧有条件通过；上述P1和P0-001已加入Claude REVIEW-007审查重点，不扩写为未冻结规范。

## 12. 主 Codex 最终证据补充与勘误

本节以执行线程返回的真实命令输出和主节点新鲜复跑为准；用于纠正第8节“首批RED不可证明”的过时表述。两个目录在派发前不存在生产包，两个线程均先创建测试并实际观察到模块缺失RED：

- 状态机首批RED：退出1，`Ran 1 test`，`FAILED (errors=1)`，`ModuleNotFoundError: electrical_control.state_machine`；首批GREEN和重构后均为11项通过。
- 驱动首批RED：退出1，`Ran 1 test`，`FAILED (errors=1)`，`ModuleNotFoundError: electrical_control.drivers`；首批GREEN和重构后均为6项通过。

后续弱独立性只读审查发现并通过追加TDD关闭：旧轮任务可运动、显式安全验证门不可达、协议ACK类型不兼容、本地累计`success_count`越过阻塞、帧序水位缺失、结果报告意图缺失、急停覆盖不足，以及STOP/disable/DIR/ENABLE/STEP故障后可能继续STEP。

挡板门修复是唯一已知TDD流程偏差：测试与生产代码最初同补丁，没有先观察RED。主节点随后临时恢复错误的ACK→`WAIT_TASK`路径，真实结果为退出1、11项中`SM-GATE-002`失败；恢复ACK→`PREPARE_BARRIER`后11项通过。该证据只证明回归测试有效，不追溯宣称原始测试先行。

最终新鲜验证：协议14项、状态机19项、驱动12项，共45项，0失败/0错误，三套退出0；`compileall`退出0；生产源码未发现未授权硬件/协议参数绑定；`git diff --check`退出0。

继续开放：`image_id/success_count`权威来源、无界去重缓存的固件容量/淘汰策略、真实安全工作区与限位/挡板判据、X/Y与A4988验证、第三运动通道、重力轴防坠、急停详细回路、完整外层帧与所有实机验证。

Claude新审查提示词的两处勘误：状态机现在直接消费`protocol.DisplayAckReceived`，不再存在`DisplayAckAccepted`；状态机只保存当前件成功语义，不维护累计`success_count`。Claude应核查这两点是否确已消除接口越权，并把结果写入既定的`REVIEW-20260812-007-claude-state-driver-code-review.md`。
