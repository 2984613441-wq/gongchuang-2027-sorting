# 第二批电控代码 Codex 实施与验证记录

> 日期：2026-08-12  
> 状态：Codex 主机侧自检及弱独立审查整改通过，待 Claude 只读审核  
> 治理：L3 八项功能有限试行；不代表治理体系、固件或硬件已经正式验证或激活

## 1. 范围与裁决

本轮完成三条互斥目录泳道：跨层集成补偿护栏、STM32 C 纯逻辑骨架、树莓派离线调度与非触摸显示骨架。裁决仅为“主机侧/纯逻辑代码可进入只读审核”。

继续禁止采购、投板、接线、上电、烧录、实机运动，以及对真实串口、显示屏、急停、限位、重力轴防坠和 A4988 适配作通过结论。

## 2. 目录所有权与变更

- 泳道 A：`电控/src/electrical_control/integration/`、`电控/tests/integration/`。
- 泳道 B：`电控/stm32_logic/`。
- 泳道 C：`电控/src/electrical_control/rpi/`、`电控/tests/rpi/`。
- 主 Codex：本报告；未修改三泳道既有 protocol、state_machine、drivers 生产文件。

## 3. RED 到 GREEN 证据

| 泳道/组 | 真实 RED | GREEN |
|---|---|---|
| A 跨层 | 缺少 `electrical_control.integration`，退出 1 | 集成 13 项，退出 0 |
| B CRC32 | 缺少 `ec_crc32_iso_hdlc`，链接退出 2 | 2 个 ID 通过 |
| B 固定容量去重 | 缺少 `ec_dedup_init`，链接退出 2 | 累计 8 个 ID 通过 |
| B 启动锁定 | 缺少 `ec_sm_init`，链接退出 2 | 累计 14 个 ID 通过 |
| B 主链/安全 | 行为断言失败，退出 1 | 最终 28/28 ID 通过 |
| C fake/恢复 | 缺少 `electrical_control.rpi`，退出 1 | 3/3 通过 |
| C 调度/渲染 | 缺少 `FakeRenderer`，退出 1 | 12/12 通过 |
| C 边界 | 愿望接口缺失，退出 1 | 5/5 通过 |

原始摘要分别保存在 `电控/tests/integration/LANE_A_EVIDENCE.md`、`电控/stm32_logic/evidence/` 和 `电控/tests/rpi/TDD-EVIDENCE.md`。

## 4. 主 Codex 新鲜验证

| 验证项 | 实际结果 | 退出状态 |
|---|---:|---:|
| 跨层集成 Python | 13/13 | 0 |
| 树莓派离线 Python | 20/20 | 0 |
| 既有协议 Python | 24/24 | 0 |
| 既有状态机 Python | 19/19 | 0 |
| 既有驱动 Python | 12/12 | 0 |
| Python 合计 | 90/90 | 全部 0 |
| Python `compileall` | 无语法错误 | 0 |
| CMake 配置/严格 GCC 构建 | 映射同一授权目录为 `S:` 后成功 | 0/0 |
| CTest | 1/1 可执行测试 | 0 |
| C 领域测试 | 32/32 显式 ID | 0 |
| Python/C CRC32 | `470B99F4` | 0 |
| 新增生产目录禁项扫描 | 0 命中 | 0 |
| `git diff --check` | 无空白错误 | 0 |

MinGW Make 对仓库中文绝对路径报告 `Illegal byte sequence`；使用 `subst S:` 映射同一 `电控/stm32_logic/` 目录后完成干净构建。删除不存在的旧映射时出现一次 `Invalid parameter - S:` 环境噪声，随后配置、构建和测试均退出 0。该噪声不作为业务 RED。

## 5. 安全结论与限制

- 合法 `DISPLAY_ACK` 只有经过方向、载荷和活动件上下文校验后才放行；CRC、目标、方向错误不进入状态机，重复 ACK 幂等。
- A 泳道对重启和容量耗尽采用补偿性 `ControlFlowGuard`：通过现有公开 `EmergencyStop` 触发一次停止、禁驱和动力抑制；精确故障码由门面保留。`PureStateMachine` 内部仍显示 `ESTOP_ACTIVE`，故“重启/容量故障不是核心原生事件”仍是待审限制。
- C 纯逻辑每次初始化均以 `RESTART_CONTEXT_UNPROVEN` 锁定；固定容量缓存不使用动态内存、不淘汰，耗尽锁定。
- 树莓派进程默认 `RECOVERY_LOCK`；旧快照仅诊断。只有明确渲染完成凭据才生成唯一可复用的 `DISPLAY_ACK` 意图；渲染开始、失败、取消或旧凭据均不确认。
- 完整 `ITEM_TASK` 线格式、外层帧、CRC16、波特率、超时、重传、心跳、GPIO、定时器、电机、限位和 A4988 参数仍未冻结、未实现。

## 5.1 弱独立审查发现与整改对账

`requesting-code-review` 的只读审查由参与过 A 泳道实现的执行者完成，因此独立性为弱。审查最初发现 3 个 Critical 和 1 个 Important，均先复现真实 RED 后整改：

| 发现 | 决议 | RED | 整改与 GREEN |
|---|---|---|---|
| A 可由调用方同时伪造 ACK 与期望内容自证放行 | 采纳 | 14 项中新增反例单独失败，退出 1 | Guard 内部从锁定任务、结果与计数派生期望，ACK API 移除调用方 `expected`；14/14 |
| B 旧轮/错件事件可推进或启动运动 | 采纳 | 32 个 ID 中 9 个断言失败，退出 1 | 任务、验证、运动完成和结果均绑定当前轮次/身份/验证标志；32/32 |
| C 可直接构造字段正确的 `RenderReceipt` 提前 ACK | 采纳 | 13 项中伪造凭据反例失败，退出 1 | 只接受具体 `PendingRender.complete()` 登记的凭据对象；RPI 21/21 |
| B 非 `WAIT_TASK` 新任务污染去重缓存 | 采纳 | 与 B 组同一 RED | 先检查状态/当前身份，再决定幂等重发；非法新身份不写缓存 |

整改后主 Codex 再次运行 Python 90/90、C 32/32、编译、跨语言 CRC、禁项扫描和差异检查。当前允许进入真正 Claude 只读审核，但不能把弱独立审查写成 Claude 或第三方审核。

## 6. 八项治理证据

- 文书：三泳道各保存 RED/GREEN，本报告汇总最新验证。
- 求是：区分旧基线、主机结果、环境噪声和未验证硬件。
- 建制：协议、集成、C 纯逻辑和树莓派目录保持单向职责边界。
- 协同：三泳道目录互斥，共享工作区未撤销他人变更。
- 谏议：拒绝 TASK-005 旧范围对现有核心文件的越权修改，改用补偿门面并保留原生缺口。
- 试行：只运行 fake、主机 Python 和主机 C；无外设动作。
- 审核：主 Codex 重新运行全部测试、编译、扫描和差异检查；当前独立性为弱独立性。
- 史官：不覆盖 REVIEW-009；Claude 后续只能新建 REVIEW-010。

## 7. Claude 交接

真实 Claude 只读审核尚未执行。使用 `.claude/tasks/TASK-20260812-008-claude-second-batch-readonly-review.md` 中的提示词，且只允许新建：

` .claude/reviews/REVIEW-20260812-010-claude-second-batch-code-review.md `

Claude 返回后，须逐项按采纳、驳回或待确认对账；不得仅凭本报告声称独立审核通过。
