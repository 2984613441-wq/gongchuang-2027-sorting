# 泳道 A 集成护栏证据

> 范围：主机侧 Python、真实协议 codec/上下文 validator、纯状态机与 fake HAL。  
> 边界：这是 `integration.ControlFlowGuard` 的补偿性集成护栏；现有 protocol/state_machine 核心仍未原生提供重启故障码或固定容量去重接口。护栏使用公开 `EmergencyStop` 保守锁定，因此核心内部故障码仍为 `ESTOP_ACTIVE`，门面另保留精确集成故障码。fake HAL 不代表真实电机、串口、显示器或 MCU 已验证。

## 基线

- 命令：`PYTHONPATH=电控/src` 后分别运行 protocol、state_machine、drivers 的 `unittest discover`。
- 退出码：`protocol=0 state=0 drivers=0`。
- 数量：协议 24、状态机 19、驱动 12，合计 55 项通过。

## RED

- 命令：`python -m unittest discover -s '电控/tests/integration' -p 'test_*.py' -v`
- 退出码：1。
- 数量：`Ran 1 test`，`FAILED (errors=1)`。
- 首个相关失败：`ModuleNotFoundError: No module named 'electrical_control.integration'`，发生于测试导入期；证明所需跨层护栏尚不存在。

## GREEN

- 初次命令：同 RED。
- 初次退出码：0。
- 初次数量：12 项通过。
- 测试质量收紧：将 ACK/结果容量耗尽测试从私有缓存注入改为只经公开事件自然填满，随后仍为 12 项通过、退出 0。
- 最终集成命令：同 RED。
- 最终集成退出码：0。
- 最终集成数量：13 项通过。
- 覆盖：合法 `DISPLAY_ACK` 唯一放行；CRC、目标序号、方向错误不进入状态机；重复 ACK 幂等；逻辑任务入口注明 ITEM_TASK wire 未冻结；下一件需 ACK 后再经挡板验证；旧轮、旧帧不运动；节点重启一次性安全锁定且人工新轮后旧轮仍拒绝；三类容量均显式正整数、无淘汰、耗尽先锁定并保留旧身份。

## 最终回归

- 命令：依次运行 integration、protocol、state_machine、drivers 的 `unittest discover`，再运行 `python -m compileall '电控/src' '电控/tests/integration'` 与本泳道路径 `git diff --check`。
- 退出码：`integration=0 protocol=0 state=0 drivers=0 compile=0 diffcheck=0`。
- 数量：集成 13、协议 24、状态机 19、驱动 12，共 68 项通过，0 失败、0 错误。

## 限制

- 没有实现或验证完整 `ITEM_TASK` wire codec、统一外层帧、真实 UART、真实渲染、STM32 C、真实电机或任何硬件参数。
- 重启/容量故障是门面补偿，不是 `PureStateMachine` 原生语义；若未来核心新增原生事件与固定容量，需迁移并重新观察 RED→GREEN。

## 只读审查 Critical 修复：ACK 上下文不可由调用方自证

- 问题：旧 API 同时接收 ACK 帧和调用方提供的 `expected_display_content`；调用方若把同一伪造内容同时用于造帧与 expected，validator 会自洽通过并错误放行。
- RED 命令：`python -m unittest '电控/tests/integration/test_control_flow_guard.py' -v`。
- RED 退出码：1；`Ran 14 tests`，仅新增 `test_review_ack_context_cannot_be_self_asserted_by_caller` 失败。
- 首个相关失败：期望保持 `WAIT_DISPLAY_ACK`，实际进入 `PREPARE_BARRIER`。
- GREEN：Guard 构造时接收已经验证的逻辑 `ItemTaskPayload` 上下文；接件时按活动 `(task_id, frame_seq)` 锁定该上下文，结果到达后用内部 `RoundSuccessCounter` 和结果码生成唯一 `DisplayContent`。`consume_display_ack()` 已移除调用方 expected 参数。
- 最终回归：集成 14、协议 24、状态机 19、驱动 12，共 69 项通过；`integration=0 protocol=0 state=0 drivers=0 compile=0 diffcheck=0`。
- 边界：这里的逻辑任务上下文仍从完整 ITEM_TASK wire codec 之后的已验证入口注入；本修复未猜写未冻结的线编码。
