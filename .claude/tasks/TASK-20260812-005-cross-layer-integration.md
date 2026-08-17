# TASK-20260812-005：跨层集成、重启锁定与固定容量去重

> 状态：待 Codex 新对话执行  
> 日期：2026-08-12  
> 等级：L3，八项治理功能有限试行；不宣称治理机制已正式验证或激活  
> 安全范围：仅主机侧 Python、纯状态机、fake HAL 与自动化测试；禁止接线、上电、烧录、投板和实机运动

## 1. 任务认知层

| 字段 | 当前记录 |
|---|---|
| 原始需求 | 先处理主要风险：补齐“协议→上下文校验→状态机→fake HAL”跨层测试；采用“任一关键节点掉电或重启即锁定，禁止原轮续跑”的用户裁决；固定容量去重缓存先设计后实现。状态灯优化延期。 |
| 表面问题 | 协议、状态机和驱动的 55 项单元测试分别通过，但没有证明合法确认帧进入状态机后的完整行为，也没有固定重启和缓存耗尽语义。 |
| 真正问题 | 必须证明一条合法任务最多触发一次运动，错误或错件确认不能放行；一旦运行上下文因节点重启而不可证明一致，系统必须停在 `FAULT_LOCK`，不能靠清零或覆盖历史继续旧轮。 |
| 必须目标 | 建立可复现的跨层集成测试；冻结并实现重启故障事件；将运行期去重历史改为显式固定容量、无淘汰、容量耗尽即故障；保存真实 RED→GREEN 证据。 |
| 非必须目标 | 不实现 STM32 C、树莓派 UI、真实显示器、UART、统一外层帧、持久化续跑、状态灯、A4988 或任何真实运动。 |
| 环境与资源限制 | Windows/PowerShell；Python 标准库 `unittest`；共享工作区存在其他编辑者；不得撤销、覆盖、清理或格式化他人的无关修改。 |
| 风险 | 跨层错接可能让错误显示被放行；重启后自动续跑可能重放运动；无界缓存不能直接移植到 MCU；伪造未冻结线格式会制造错误协议事实。 |
| 节点能力建议 | Codex 新对话负责测试先行、最小生产修改和验证；完成后交 Claude 只读审查。Claude意见是证据输入而非自动裁决。 |
| 决策边界 | 用户已裁决“任一关键节点掉电或重启后立即锁定，禁止原轮续跑，人工确认后重新自检、回零并开始新轮”；完整 `ITEM_TASK` wire codec、外层帧和硬件参数仍未冻结。 |
| 当前阶段 | REVIEW-009 对主机侧 Python 有条件通过；本任务是进入第二批生产代码前的 P1 关闭任务。 |
| 验收方式 | 指定测试先观察 RED，再做最小 GREEN；运行集成、协议、状态机、驱动全套测试、编译检查、未冻结项扫描和 `git diff --check`。 |

## 2. 事实、推断、观点与未知

### 2.1 事实

- 协议 V0.4 已冻结 `DISPLAY_ACK` 的 6 字节载荷、五字段 CRC32 内容和树莓派→STM32方向。
- `ProtocolCodec.to_validated_message()` 只完成方向与载荷结构解析；`DisplayAckContextValidator.to_domain_event()` 才完成活动件上下文校验；`PureStateMachine.consume()` 消费 `DisplayAckReceived` 并向 `FakeHal` 记录动作意图。
- 当前状态机去重历史 `accepted_tasks` 和 `consumed_display_acks` 为无界容器，人工复位时清空。
- `ITEM_TASK` 的 `image_id` 逻辑字段已冻结，但 X/Y/角度单位、表达、端序、完整载荷长度和统一外层帧仍未冻结；现有代码按契约拒绝编码完整 `ITEM_TASK`。
- 用户已裁决：掉电或重启不进行旧轮自动恢复；必须故障锁定，经人工确认后重新自检、回零并开始新轮次。

### 2.2 推断

- 通过真实调用现有协议解码器、上下文验证器、状态机和 fake HAL，可以关闭 REVIEW-009 P1-001 的主机侧跨层测试缺口。
- 显式容量、无淘汰和耗尽即锁定比覆盖旧身份更适合安全去重；但主机侧通过不代表 STM32 SRAM 容量已经选定。

### 2.3 本任务采用的工程观点

- 不实现 Flash/文件持久化和跨节点续跑握手；重启事件是不可恢复故障，只能走人工新轮流程。
- 不给缓存猜写 64、128 等产品容量。主机对象必须由调用者显式注入正整数容量；未来固件容量须在单轮最大任务数和内存预算确认后另行冻结。

### 2.4 未知及处理

| 未知 | 本任务处理 |
|---|---|
| 完整 `ITEM_TASK` 线格式 | 保持拒绝；不得创建临时编码。 |
| 外层帧头、CRC16、波特率、超时、重传和心跳数值 | 不实现、不默认、不写入测试常量。 |
| STM32 最终缓存容量 | 仅验证显式小容量语义，不宣称固件容量已确定。 |
| 电机、GPIO、定时器、限位、PWM、电流、电压和机械参数 | 全部禁止写入。 |

## 3. 八项治理功能

| 功能 | 本任务动作 |
|---|---|
| 文书 | 本任务文件作为新对话唯一执行基线，记录边界、测试 ID、命令和证据字段。 |
| 求是 | 区分“主机侧跨层通过”与“串口/MCU/实机通过”；只引用实际命令输出。 |
| 建制 | 固定单向边界：抽象帧→方向/载荷解析→活动上下文验证→领域事件→纯状态机→fake HAL；后层不得反向解释线格式。 |
| 协同 | 以文件所有权隔离新对话；开始前读取当前差异，发现他人正在修改所有权文件时停止并报告冲突。 |
| 谏议 | 若实现必须猜写未冻结参数、覆盖去重历史或允许旧轮恢复，立即拒绝该路径并保留阻塞。 |
| 试行 | 仅主机侧 fake 测试；不把试行结论扩张为任何硬件执行授权。 |
| 审核 | GREEN 后运行全套回归、编译、静态扫描和差异检查，再交 Claude 只读审核；同体系自检标“弱独立性”。 |
| 史官 | 在本文件末尾追加 RED/GREEN 和最终命令原始摘要；不得改写 REVIEW-009 或删除旧报告。 |

## 4. 冻结设计

### 4.1 跨层边界

`DISPLAY_ACK` 唯一允许的跨层路径：

```text
Frame(RASPI→STM32, DISPLAY_ACK)
  → ProtocolCodec.to_validated_message
  → DisplayAckContextValidator.to_domain_event(expected_display_content=...)
  → DisplayAckReceived
  → PureStateMachine.consume
  → FakeHal 动作记录 / 状态门变化
```

- 解码或上下文验证抛出协议错误时，不得构造或注入领域事件，状态机与 fake HAL 必须保持原状。
- 集成测试不得直接把 `crc_match=True` 当作合法确认的证据；合法路径必须由验证器产生该事件。
- 因完整 `ITEM_TASK` wire codec 未冻结，任务入口仅从已验证的逻辑 `ItemTaskReceived` 开始。测试名称和报告必须写明这是“逻辑任务入口集成”，不得声称完整串口端到端已通过。

### 4.2 掉电/重启锁定

- 新增明确领域事件 `NodeRestarted`，节点值只允许 `RASPI` 或 `STM32`；首次正常上电不是该事件。
- 运行上下文建立后，收到任一节点的 `NodeRestarted`，所有非 `FAULT_LOCK` 状态立即执行一次 `STOP_ALL`、`DISABLE_DRIVERS`、`INHIBIT_POWER`，进入 `FAULT_LOCK`，故障码为 `NODE_RESTARTED_CONTEXT_LOST`。
- 进入锁定后，旧任务、进度、结果和显示确认均不得恢复或推进状态；重复重启事件不得重复产生安全动作。
- 唯一退出路径是现有人工复位门：`round_closed`、`danger_area_clear`、`estop_released` 全为真。退出后轮次号变化，进入 `POWER_ON`，要求重新自检和回零；旧轮任务必须被拒绝，不能续跑。
- 本任务不实现持久化，不提供“恢复旧轮”接口。

### 4.3 固定容量去重策略

- 状态机的任务去重表与显示确认去重集必须各自使用调用者显式提供的正整数容量；`bool`、零、负数和缺失容量均拒绝构造。不得提供暗含产品结论的默认容量。
- 查重顺序必须先于容量检查：已有相同身份即按既有幂等语义重发缓存响应；相同身份异载荷仍故障；缓存已满也不能破坏已知身份的幂等性。
- 新身份写入前若对应缓存已满：不得 FIFO/LRU 淘汰、不得覆盖最旧记录、不得接受或运动；立即进入 `FAULT_LOCK`。任务表故障码 `TASK_DEDUP_CAPACITY_EXHAUSTED`，显示确认表故障码 `DISPLAY_ACK_DEDUP_CAPACITY_EXHAUSTED`。
- 有效人工新轮复位清空两类历史，但保持配置容量不变；无效复位、重连、超时、重传和重启均不得清空。
- `RoundSuccessCounter._recorded_results` 同样是运行期去重历史。本任务必须采用相同策略增加显式正整数 `result_dedup_capacity`：重复身份先处理；新结果身份在容量已满时抛出新的协议错误 `ResultDedupCapacityExhausted`，计数保持不变。该错误进入系统时由上层转为 `FAULT_LOCK`；本任务至少用跨层护栏测试证明错误不会产生运动或放行。
- 本设计只冻结行为，不冻结固件的数值容量；未来 STM32 C 实现前必须根据已确认的单轮最大件数、消息模型和 SRAM 预算另做容量裁决。

## 5. 新对话文件所有权

Codex 新对话开始前必须读取 `AGENTS.md` 指令、`CLAUDE.md`、`docs/requirements/analysis.md`、`docs/design/interface-contract.md`、TASK-003、TASK-004 和 REVIEW-009，并先运行当前基线测试。它不是仓库唯一编辑者。

### 5.1 唯一允许修改

| 责任 | 允许创建或修改 |
|---|---|
| 跨层集成测试 | `集成/tests/test_cross_layer_control_flow.py`，以及仅在导入需要时创建 `集成/tests/__init__.py` |
| 重启与固定容量状态机测试 | `电控/tests/state_machine/test_restart_and_bounded_dedup.py`、现有 `电控/tests/state_machine/test_state_machine_contract.py` 中仅为显式容量注入所需的机械性更新 |
| 状态机最小实现 | `电控/src/electrical_control/state_machine/core.py`、`电控/src/electrical_control/state_machine/__init__.py` |
| 结果去重容量测试 | `电控/tests/protocol/test_bounded_result_dedup.py`、现有协议测试中仅为显式容量注入所需的机械性更新 |
| 结果去重最小实现 | `电控/src/electrical_control/protocol/item_context.py`、`电控/src/electrical_control/protocol/errors.py`、`电控/src/electrical_control/protocol/__init__.py` |
| 证据回填 | 本文件的“执行证据”表，不得改写前述冻结设计 |

### 5.2 禁止修改

- 驱动目录、显示/UI目录、视觉目录、机械目录、正式方案文档、接口契约、TASK-003/004、REVIEW-009和其他协作者文件。
- 若测试暴露必须修改上述禁止范围的问题，停止 GREEN 实施，在本文件执行证据中记录精确阻塞，不扩大权限。
- 禁止撤销、覆盖、清理、批量格式化或提交他人的无关修改；禁止使用破坏性 Git 操作。

## 6. TDD 执行顺序与测试 ID

### 6.1 第一次 RED：合法与非法 `DISPLAY_ACK` 跨层路径

先只创建 `集成/tests/test_cross_layer_control_flow.py`，不得同步修改生产代码。测试共用 helper 必须把纯状态机推进到 `WAIT_DISPLAY_ACK`，并从当前 `ITEM_TASK`、结果码和明确的成功计数构造 `expected_display_content`。

| ID | 输入与断言 |
|---|---|
| `XL-ACK-001` | 合法方向、合法 6 字节载荷、匹配五字段 CRC；依次调用 codec、validator、state machine；断言进入 `PREPARE_BARRIER`、活动件清除、`START_MOTION` 总数仍为 1。 |
| `XL-ACK-002` | 篡改 CRC32；codec 可解析但 validator 抛 `PayloadError`；不得调用状态机；断言仍为 `WAIT_DISPLAY_ACK`、活动件保留、无新增 HAL 动作。 |
| `XL-ACK-003` | `target_seq` 与活动件不匹配；validator 拒绝；状态与 HAL 不变。 |
| `XL-ACK-004` | 将 `DISPLAY_ACK` 方向反转为 STM32→树莓派；codec 抛 `DirectionError`；状态与 HAL 不变。 |
| `XL-ACK-005` | 首个合法 ACK 由完整路径放行，再把同一个领域事件交给状态机；只产生缓存响应，不重复运动、不重复放行。 |
| `XL-ONCE-001` | 从逻辑 `ItemTaskReceived` 入口注入同身份同载荷任务两次并完成一次安全验证；断言 `START_MOTION == 1`。测试说明必须注明 `ITEM_TASK` wire codec 未冻结。 |
| `XL-GATE-001` | 首个有效 ACK 前注入下一件，必须拒绝且不运动；完整 ACK 路径后还需 `BarrierAvoidanceVerified` 才重新进入 `WAIT_TASK`。 |

运行并保存退出状态与失败摘要：

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest discover -s '集成/tests' -p 'test_*.py' -v
```

预期 RED：至少一个新测试因重启/容量接口尚不存在或既有跨层缺陷而失败。若 7 项全部直接通过，记录“跨层既有实现已 GREEN”，不得制造假失败；随后继续下一组真实 RED。

### 6.2 第二次 RED：重启不可续跑

先创建测试，不改生产实现。

| ID | 输入与断言 |
|---|---|
| `XL-RESTART-001` | `EXECUTING` 中收到 `NodeRestarted(RASPI)`；立即 `FAULT_LOCK`，三项安全动作各一次，禁止后续 `MotionDone`/结果/ACK 推进。 |
| `XL-RESTART-002` | `WAIT_DISPLAY_ACK` 中收到 `NodeRestarted(STM32)`；不得用旧 ACK 放行。 |
| `XL-RESTART-003` | 锁定后重复重启事件不重复发安全动作。 |
| `XL-RESTART-004` | 只有三条件人工复位可进入新轮 `POWER_ON`；旧轮 `ItemTaskReceived` 在完成新启动后也必须按轮次拒绝，不能启动运动。 |

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest '电控/tests/state_machine/test_restart_and_bounded_dedup.py' -v
```

预期 RED：导入 `NodeRestarted` 或相关行为断言失败，退出状态非 0。保存真实输出后，仅实现 4.2 的最小行为，再重跑至 GREEN。

### 6.3 第三次 RED：固定容量、无淘汰、耗尽锁定

| ID | 输入与断言 |
|---|---|
| `XL-CACHE-001` | 状态机缺失、零、负数或布尔容量拒绝构造。 |
| `XL-CACHE-002` | 任务缓存满时，已知同身份同载荷仍重发缓存响应，不故障、不运动。 |
| `XL-CACHE-003` | 任务缓存满时新身份导致 `TASK_DEDUP_CAPACITY_EXHAUSTED`，无淘汰、无新运动。 |
| `XL-CACHE-004` | ACK缓存满时新有效身份导致 `DISPLAY_ACK_DEDUP_CAPACITY_EXHAUSTED`，不得清活动件或放行。 |
| `XL-CACHE-005` | 无效人工复位、重启和普通通信事件不清缓存；有效人工新轮复位清空缓存但容量配置不变。 |
| `XL-COUNT-001` | `RoundSuccessCounter` 缺失、零、负数或布尔容量拒绝构造。 |
| `XL-COUNT-002` | 结果缓存满时重复已知身份仍保持幂等；新身份抛 `ResultDedupCapacityExhausted`，成功计数不变且不淘汰旧记录。 |
| `XL-COUNT-003` | 跨层 helper 捕获结果容量耗尽后使状态机故障锁定，且不产生第二次运动或显示放行。 |

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest '电控/tests/state_machine/test_restart_and_bounded_dedup.py' '电控/tests/protocol/test_bounded_result_dedup.py' -v
```

预期 RED：显式容量接口或容量耗尽行为不存在，退出状态非 0。保存真实输出后按 4.3 最小实现，不引入通用缓存框架或淘汰算法。

### 6.4 未冻结项拒绝回归

| ID | 输入与断言 |
|---|---|
| `XL-UNFROZEN-001` | `encode_item_task_payload()` 继续抛 `ContractNotFrozen`；不得因为集成测试新增临时 wire codec。 |
| `XL-UNFROZEN-002` | 源码和测试不得出现实际帧头、CRC16型号、波特率、重传次数、心跳周期、GPIO、定时器、速度、加速度、电流、电压、细分或步距默认值。CRC32 V0.4 已冻结向量不属于禁止项。 |

## 7. GREEN 与重构限制

1. 每组 RED 必须保存失败命令、退出状态和首个相关失败；未观察 RED 不得声称该组完成了测试先行。
2. 只实现令当前组通过的最小修改；不得趁机重命名 parse/decode、重构驱动、实现串口或增加 UI。
3. 每组 GREEN 后先跑该组测试，再跑协议、状态机、驱动和集成全套回归。
4. 允许消除测试 helper 重复，但不得把协议验证逻辑复制进测试替身；测试必须调用生产 codec 和 validator。
5. 不要求创建提交；若新对话选择提交，只能包含 5.1 的所有权文件，不得代替最终差异审查。

## 8. 最终验收命令

以下命令必须在工作区根目录逐项运行并记录实际通过数量；不得沿用 REVIEW-009 的旧数字：

```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest discover -s '集成/tests' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/protocol' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/state_machine' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/drivers' -p 'test_*.py' -v
python -m compileall '电控/src' '电控/tests' '集成/tests'
git diff --check
git status --short
git diff -- '.claude/tasks/TASK-20260812-005-cross-layer-integration.md' '集成/tests' '电控/src/electrical_control/protocol' '电控/src/electrical_control/state_machine' '电控/tests/protocol' '电控/tests/state_machine'
```

静态禁写扫描使用仓库文本搜索，检查以下词类是否被本任务新增为具体实现参数：`baud`、`CRC16`、`GPIO`、`TIM`、`A4988`、`microstep`、`steps_per_mm`、`acceleration`、`current_limit`、`voltage`、`heartbeat_interval`、`retry_count`。发现命中时必须逐项证明它只是“拒绝/未冻结”的说明或既有内容；否则验收失败。

## 9. 完成判据

只有同时满足以下条件，才可把本任务标为“主机侧通过”：

- `XL-ACK-001..005`、`XL-ONCE-001`、`XL-GATE-001` 全部通过，非法输入未进入状态机。
- `XL-RESTART-001..004` 全部通过，重启后旧轮不可恢复，人工新轮门有效。
- `XL-CACHE-001..005`、`XL-COUNT-001..003` 全部通过，无默认容量、无淘汰、耗尽安全失败。
- `XL-UNFROZEN-001/002` 通过，完整 `ITEM_TASK` wire codec 和其他未冻结参数继续被拒绝。
- 全套协议、状态机、驱动、集成回归与编译、差异检查均退出 0。
- 执行报告明确写“fake HAL 不代表真实电机、串口、显示器或 MCU 已验证”。
- Claude 只读审查尚未完成时，只能标“Codex 自检通过，审核弱独立性/待 Claude”；不得写“独立审核通过”。

## 10. 严格禁止动作

- 禁止接线、上电、烧录、投板、实机运动、购买或修改任何硬件。
- 禁止实现或猜写完整 `ITEM_TASK` 线格式、外层帧、CRC16、波特率、超时、重传、心跳和任何硬件参数。
- 禁止用覆盖/淘汰旧去重记录来维持运行；容量不足必须可见地故障锁定。
- 禁止实现掉电旧轮续跑、自动清零、自动回零、自动重抓、自动重放运动或自动跳过。
- 禁止把 `MOTION_DONE` 当成功、把收到结果当显示完成，或在实际渲染前生成 `DISPLAY_ACK`。
- 禁止修改所有权之外文件，禁止撤销或覆盖其他编辑者修改。

## 11. 执行证据（由 Codex 新对话追加）

| 阶段 | 命令与退出状态 | 实际结果 | 证据强度/限制 |
|---|---|---|---|
| 基线 | 尚未执行 | 尚未记录 | 执行前不得填写为通过 |
| RED-ACK | 尚未执行 | 尚未记录 | 若既有实现直接通过，如实记录 |
| GREEN-ACK | 尚未执行 | 尚未记录 | 主机侧跨层，不含 ITEM_TASK wire |
| RED-RESTART | 尚未执行 | 尚未记录 | 必须是相关失败 |
| GREEN-RESTART | 尚未执行 | 尚未记录 | fake 事件，不含真实断电 |
| RED-CACHE | 尚未执行 | 尚未记录 | 必须是相关失败 |
| GREEN-CACHE | 尚未执行 | 尚未记录 | 容量数值仅为测试注入 |
| 最终回归 | 尚未执行 | 尚未记录 | 不沿用旧 55 项数字 |
| Claude审核 | 尚未执行 | 尚未记录 | 未完成前标弱独立性 |

## 12. 新对话交付格式

最终报告必须按以下顺序：

1. 裁决：通过、条件通过或阻塞，以及只适用于主机侧的范围。
2. 变更文件：仅列 5.1 所有权内实际修改文件。
3. RED→GREEN：逐组给出真实失败与通过证据，未观察 RED 的组明确说明。
4. 测试汇总：集成、协议、状态机、驱动的最新通过数与退出状态。
5. 安全结论：重启锁定、旧轮拒绝、缓存耗尽行为和未冻结项拒绝。
6. 剩余阻塞：STM32 C跨语言向量、完整线协议、树莓派真实渲染、所有硬件门禁。
7. Claude交接：生成新的只读审查请求，但未经用户对具体外部写入确认，不替用户向外部系统发布。

