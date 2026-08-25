# REVIEW-20260825-009 电控只读审核（Codex · 帝国机制：求是 / 审核 / 谏议 / 文书）

审核方：Codex（OpenAI 节点，工程落地 / 可执行验证）
审核对象：电控/ 全量（Python 主机逻辑、STM32 纯逻辑、STM32F407 固件 App、测试）
审核等级：L3（高风险可控）；独立护栏为弱独立性
审核日期：2026-08-25
范围约束：主机侧纯逻辑与文档证据；不得把主机测试表述为固件、串口、屏幕、电机或实机通过

## 0. 调用说明（帝国机制）

本轮启用四项治理功能：求是（只据代码/测试/文档取证）、审核（按严重度出发现）、
谏议（对契约冲突与 fail-unsafe 风险点提出具体裁决与上机门禁）、文书/史官（落本记录）。
未启用 建制/协同/试行：本轮为只读审核，无跨节点并行、无制度变更、无试行授权。

独立性声明：本审核由单一模型完成，无法做到真正独立审核，标注为弱独立性。
裁决权保留给用户；以下“事实/推断/观点”分开标注。

## 1. 实际验证（真实命令与结果）

| 对象 | 命令/产物 | 结果 |
|---|---|---|
| STM32 纯逻辑 | 电控/stm32_logic/build/Release/ec_logic_tests.exe | 42/42 通过，exit 0 |
| 固件主机测试 | 电控/firmware/stm32f407_m144z/tests/build/Release/ec_firmware_host_tests.exe | 通过，exit 0 |
| 生产 axis driver | .../tests/build/Release/ec_axis_driver_tests.exe | 通过，exit 0 |
| 诊断关闭分支 | .../tests/build/Release/ec_diag_disabled_tests.exe | exit 0 |
| Python 测试 | python -m pytest 电控/tests | 未执行：PATH 上的 python 无 pytest 模块 |

证据时效：上述 exe 为 VS2022 已生成产物，时间戳（2026-08-25 18:49 至 18:58）晚于其全部相关源码
（最新源码 18:50）。本轮未重新编译：MinGW 对中文绝对路径产生乱码，MSBuild 构建挂起后已终止。
因此“测试通过”覆盖的是现有产物的行为，仍需在干净环境/目标平台复验后作为更高强度证据。

## 2. 审核发现（按严重度）

### HIGH-1 外层帧头 + CRC16 在 C 侧被“冻结”，权威契约仍标“待定/仍未知”，且无裁决记录

- 事实：电控/stm32_logic/include/ec_protocol.h:10-37 注释写 Frozen (user-adjudicated 2026-08-24)，
  并定义帧头 0xA5 0x5A、版本 0x01、帧级 CRC=CRC-16/MODBUS、task_id/frame_seq/data_len 大端。
- 事实：docs/design/interface-contract.md:51,60,251-252 仍为“待定”；
  docs/requirements/analysis.md:99 明确“仍未知：统一外层帧头、外层 CRC16”；
  电控/资料/硬件映射待确认表.md 把“完整生产通信帧、CRC16、超时和重传参数”列为仍待确认。
- 事实：docs/prompts/codex-handoff-20260824-next-conversation-prompt.md 与 REVIEW-007/008 均无
  0xA5/CRC-16/MODBUS 冻结裁决记录，analysis.md 决策表 D-001 至 D-009 也无对应条目。
- 推断：要么用户确已于 8-24/8-25 拍板但未写回权威文档，要么代码“猜写”了明令禁止猜写的
  未冻结外层帧/CRC16。二者都属于治理漂移。
- 谏议：请用户裁决是否确已冻结；若已冻结，把裁决写回 interface-contract.md（升版本）、
  analysis.md 决策表并补交接记录；若未冻结，应从 C 协议头回退该 Frozen 声明并保持与 Python 一致。

### HIGH-2 Python 与 C 对“什么已冻结”口径相反

- 事实：Python electrical_control/protocol/codec.py 对非 DISPLAY_ACK 命令抛 ContractNotFrozen，
  明确不实现外层帧；而 C ec_protocol.c 已完整实现外层帧编解码。
- 推断：两端对同一 V0.4 契约的理解相反，跨语言联调前必然冲突；这是 HIGH-1 的直接后果。

### MEDIUM-3 生产状态机与生产 axis driver 未接入固件主循环

- 事实：App/Src/ec_app.c:26-27 仅 ec_sm_init + ec_safety_apply 一次；
  全文件无 ec_sm_consume，也从不调用 ec_axis_driver_init/poll/start_pick_place。
  ec_app_poll（:54-59）只跑 ec_step/servo/group/barrier_test_poll 与 ec_diag_poll/tick。
- 推断：当前烧录进板子的固件是“诊断/测试固件”，不是方案 B 的自动运行主链。
  ec_state_machine.c 与 ec_axis_driver.c 在本固件中是未接线代码。
- 谏议：不要把“固件主机测试通过”表述为“状态机/抓放闭环已实现”；上机前必须明确主链接线计划。

### MEDIUM-4 STM32 侧缺少 D-007 的 success_count 状态实现

- 事实：success_count 在 C 侧只作为 ec_proto_display_content_crc32 的参数
  （ec_protocol.h:103-108），全仓 C 代码无计数器、无 255 溢出处理、无按件身份去重、无轮次复位。
  对应冻结规则目前只落在 Python RoundSuccessCounter。
- 推断：STM32 无法独立重建本件 DISPLAY_ACK 期望 CRC32，违背接口契约 6.1 节的双端一致性要求。

### MEDIUM-5 生产运动参数仍是占位值，且处于未调用状态

- 事实：App/Inc/ec_axis_driver.h:29-36 标注 PLACEHOLDERS（100 step/mm、500 Hz、
  夹爪 1000/1900 us、settle 200 ms）；ec_axis_driver.c 未被任何生产路径调用。
- 观点：作为骨架可接受，但必须与“已冻结参数”隔离，发布构建不得把占位值当标定值。

### MEDIUM-6 失败结果码被坍缩为单一值，可能破坏 DISPLAY_ACK 内容一致性

- 事实：electrical_control/integration/control_flow.py:200 用 result_code = 0 if event.success else 1，
  而契约 ITEM_RESULT 定义 0x02=GRIP_FAILED 等多个失败码；DISPLAY_ACK 内容 CRC32 依赖 result_code。
- 推断：非 SUCCESS 失败时，树莓派与 STM32 对规范字节序列可能取不同 result_code，CRC 不一致。

### LOW-7 STM32 侧接件前未做 255 溢出门禁，溢出会抛未捕获异常

- 事实：control_flow.py:146 _consume_task 的 eligible 不含 can_accept_new_item；
  只有 rpi/__init__.py 的 Scheduler 做该检查。item_context.py:78-79 在计数为 255 时抛
  SuccessCountOverflow，而 _consume_result 未捕获，会向上传播为未处理异常而非转入 FAULT_LOCK。
- 观点：比赛件数（至少 12）远达不到 255，实际触发概率极低，但属契约 6.1 的合规缺口。

### LOW-8 C 纯逻辑状态机跳过了 POST / READY / COMPLETE 三个态

- 事实：ec_state_machine.h 声明 POST/READY/COMPLETE，但 ec_sm_consume 的转移为
  POWER_ON 到 HOMING 到 PREPARE_BARRIER，无“待机一键启动授权”与“完成”态可达。
- 推断：该 C 逻辑只覆盖自动运行子状态机的片段，未建模顶层“上电到自检到回零到待机到完成”生命周期。

### 上机前强制门禁（非代码缺陷，但属 fail-unsafe 风险）

- 安全输入极性按“任意安全引脚 LOW=抑制”实现（ec_step_test.c ec_motion_inhibit_from_raw、
  ec_axis_driver.c EC_AXIS_SAFETY_MASK）。极性依赖未验证接线，上机前必须万用表核对，否则可能倒置为
  “触发限位/急停不停止”。
- ESTOP_FB 仅辅助反馈，不替代硬件切动力；重力轴（Z=舵机）防坠未定前禁止带载。

## 3. 已确认正确/稳健的点（求是）

- CRC-16/MODBUS 与 CRC-32/ISO-HDLC 的黄金向量均通过（123456789 到 0x4B37、01 02 03 04 05 到 0x470B99F4），
  编码/解码往返与坏头/坏版本/坏 CRC/短帧拒绝均有测试覆盖。
- ec_proto_decode_item_task 只解冻结的 3 字节身份前缀，X/Y/角度保持 opaque，未猜写未冻结编码。
- 诊断测试命令的 arm/settle/超时/抑制/单次授权消耗逻辑完整，STEP X/Y/Z 已补 ec_motion_test_is_armed 门禁。
- 计数 DONE 与 TIMEOUT 竞争已按 DONE 优先处理（ec_step_test.c 写 TIMEOUT 前检查 result==NONE）。

## 4. 遗留问题

1. HIGH-1 的冻结裁决需用户拍板并回写权威文档。
2. 需要干净环境重编译 + 目标平台复验（本轮未重编译，Python 测试未跑）。
3. 生产主链（状态机 + axis driver + 协议调度）的接线计划与逐阶段验证清单缺失。
