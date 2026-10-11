# App 状态可观测与 ITEM_TASK 无应答排查

日期：2026-09-18。任务：app-state-item-task-20260918。执行与审核：Codex 单 Agent 实施、内部源码及证据复核；未做独立模型审核。

## 交付状态

- 已实现：STATUS 末尾追加 `APP_STATE=<枚举名>`，调用真实 `ec_app_state()`；既有字段及顺序保持不变。
- 已完成：Keil 全量重编，实际 `0 Error(s), 0 Warning(s)`；下述主机检查通过。
- **烧录后 APP_STATE 实际值：【未取得】。现场无应答根因：【证据不足】。** 本轮没有烧录、连接串口、发运动命令或进行实机验证。
- **烧录暂停原因：用户要求先核对并决定是否保留的两项高危设置均存在。** ISR 的 `NVIC_SystemReset()` 与 IWDG Reload=500 均未由本任务修改。需要用户针对当前诊断固件作保留/处置决定。

沿用用户已实测的串口双向通信、STATUS 心跳、INPUTS 与已排除项，不重复现场测试。本次代码修改仅涉及诊断输出及其孤立主机测试的链接桩；未改 wire、CRC、命令字、波特率、GPIO、限位和安全掩码。

## 本轮修改及行号对照

路径均相对工作区 `C:/Users/29845/Desktop/工创赛`。旧行号为本任务开始时工作副本的行号，并非 Git HEAD；工作区原本已有大量未提交修改。下文源码行号对应本次审查时版本；共享目录后续修改会使行号漂移，应同时按函数名定位。

| 文件/位置 | 修改前 | 修改后 | 本轮修改 |
|---|---:|---:|---|
| `电控/firmware/stm32f407_m144z/App/Src/ec_diag.c` include | 无 | 2 | 引入 `ec_app.h` |
| 同文件，状态名函数 | 无 | 268–286 | `ec_app_state_name()`，覆盖全部 12 个状态；未知值为 UNKNOWN |
| 同文件，STATUS 尾字段 | 368 | 389 | `BARRIER_US=%u\r\n` → `BARRIER_US=%u APP_STATE=%s\r\n` |
| 同文件，BARRIER 开启分支参数 | 395 | 416–417 | 追加 `ec_app_state_name(ec_app_state())` |
| 同文件，BARRIER 关闭分支参数 | 397 | 419–420 | 追加同一个真实状态调用 |
| `电控/firmware/stm32f407_m144z/tests/test_diag_disabled.c` | 无 | 2、12–13 | 引入 App 类型，并给不链接生产 App 的隔离测试提供状态桩 |

测试桩返回 FAULT_LOCK，只用于 `ec_diag_disabled_tests`，不进入 Keil 固件。生产状态由 `App/Src/ec_app.c:642` 的 `ec_app_state()` 返回 `ec_gateway_state(&gateway)`。主动 STATUS 与周期心跳共用该输出函数。

枚举权威：`电控/stm32_logic/include/ec_state_machine.h:9`。

| 数值 | APP_STATE 文本 |
|---:|---|
| 0 | FAULT_LOCK |
| 1 | POWER_ON |
| 2 | POST |
| 3 | HOMING |
| 4 | READY |
| 5 | PREPARE_BARRIER |
| 6 | WAIT_TASK |
| 7 | VALIDATE_TASK |
| 8 | EXECUTING |
| 9 | WAIT_ITEM_RESULT |
| 10 | WAIT_DISPLAY_ACK |
| 11 | COMPLETE |

`LIGHT`、`GRIP`、`ec_board.h` include、GROUP 的 1100 参数，以及测试中对应的灯/夹爪桩均为本任务之前的工作区修改。不能把整个 `git diff` 归为本任务补丁。

## 实际构建与验证

工作目录：项目根。Keil 路径为 `D:/Keil/UV4/UV4.exe`。实际执行：

```powershell
$wd = (Resolve-Path '电控/firmware/stm32f407_m144z/MDK-ARM').Path
$p = Start-Process -FilePath 'D:\Keil\UV4\UV4.exe' `
  -ArgumentList @('-r','diankongv1.0.uvprojx','-o','app_state_build.log') `
  -WorkingDirectory $wd -Wait -PassThru
"KeilExitCode=$($p.ExitCode)"
Get-Content -LiteralPath (Join-Path $wd 'app_state_build.log')
```

最终全量重编实际输出末尾：

```text
KeilExitCode=0
linking...
Program Size: Code=26740 RO-data=1704 RW-data=208 ZI-data=3920
FromELF: creating hex file...
"diankongv1.0\diankongv1.0" - 0 Error(s), 0 Warning(s).
Build Time Elapsed:  00:00:05
SourceManifestStable=True
```

编译器：ARMCC V5.06 update 7 (build 960)。日志：`电控/firmware/stm32f407_m144z/MDK-ARM/app_state_build.log`。

HEX：`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1.0/diankongv1.hex`。

为避免其他任务重编覆盖，已另存交付候选：`docs/reports/app-state-20260918/diagnostic.hex`，对应日志 `docs/reports/app-state-20260918/keil-rebuild.log`；另存后核对 SHA256 与下值相同。

SHA256：`3A4D1E93A0E72EA5124AFF4D81A98745D79E9E369DC6AD0170209199F254BD12`。

首次重编也为 0/0，其后发现本任务外的并发修改更新了 `ec_step_test.h`、`ec_axis_driver.c`、`ec_board_stm32.c`，因此进行了上述第二次全量重编。首次日志保留为 `MDK-ARM/app_state_build_initial.log`，其 HEX 哈希已被最终构建替代。最终构建前后对 App/Core 与 stm32_logic 的 C/H 源文件做 SHA256 比较，结果相同；清单见 `docs/reports/2026-09-18-app-state-build-sources.json`。这不代表对其他任务修改作了安全审核。最终 HEX 含当前工作区已有/并发修改，不是基于干净 Git HEAD 只叠加本轮补丁。

**交付时新鲜度限制：** 报告写完后的哈希复核又发现 `App/Inc/ec_axis_driver.h`、`App/Src/ec_axis_driver.c`、`App/Src/ec_app.c` 被其他工作更新。上述 0/0 与 HEX 只属于清单记录的构建版本，不能认作这些后续修改已通过 Keil。未回滚他人修改，未持续追赶并发工作。恢复烧录前应按清单核对来源，或在修改稳定后重编并更新产物记录。

当前 Keil 宏保持原值：`EC_DIAGNOSTIC_BUILD=1, EC_MOTION_TEST_BUILD=1, EC_SERVO_TEST_BUILD=1, EC_GROUP_TEST_BUILD=0, EC_BARRIER_TEST_BUILD=0, EC_APP_PROGRESS_SOURCE_ENABLED=1`。Keil 引用 `电控/stm32_logic/src/` 协议及状态机源码。

本轮实际检查：

```powershell
git diff --check -- 电控/firmware/stm32f407_m144z/App/Src/ec_diag.c 电控/firmware/stm32f407_m144z/tests/test_diag_disabled.c
cmake --build 电控/stm32_logic/build-make --config Debug
ctest --test-dir 电控/stm32_logic/build-make --output-on-failure
cmake --build 电控/firmware/stm32f407_m144z/tests/build-make --target ec_diag_disabled_tests ec_firmware_host_tests ec_progress_source_disabled_tests
ctest --test-dir 电控/firmware/stm32f407_m144z/tests/build-make -R '^(ec_diag_disabled_tests|ec_firmware_host_tests|ec_progress_source_disabled_tests)$' --output-on-failure
$env:PYTHONPATH=(Resolve-Path '电控/src').Path
py -3 -m pytest 电控/tests/protocol 电控/tests/rpi/test_outbound.py 电控/tests/rpi/test_gateway.py -q
```

| 检查 | 实际结果 |
|---|---|
| diff --check | 通过；仅 LF/CRLF 提示 |
| stm32_logic 构建/测试 | 构建退出 0；1/1 ec_logic_tests 通过 |
| 三个 firmware host targets | 构建退出 0；最终重编后再次测试，3/3 通过，耗时 0.07 s |
| Python 协议/网关 | 91 passed, 28 subtests passed, 1 warning；warning 为 pytest cache 的 WinError 183 |

测试环境处理记录：默认 `python` 指向不含 pytest 的 FishSim Python；改用 `py -3` 后先遇到模块路径缺失，设置上述 PYTHONPATH 后成功。孤立 `ec_diag_disabled_tests` 初次链接缺少新增依赖 `ec_app_state`，补上限定于测试的桩后成功。现有 CMake 的 S: 路径已确认映射到本工作区 `电控`。主机测试只证明主机逻辑与链接检查，不证明串口、电机或实机通过。

## 烧录前两项高危发现

风险等级：**高危；安全行为变更须单独说明、审核并取得用户决定，本轮未改动。**

1. **ISR 自复位仍在。** 当前 `App/Src/ec_board_stm32.c:452` 存在实际 `NVIC_SystemReset();`，不是只有注释；用户所述旧位置约 433，因其他任务修改现移至 452。`:438` 的 `last_main_loop_tick` 初值 0，`:445` 判断与当前 HAL tick 的差是否大于 1000 ms，`:454` 只在这个 ISR 回调里更新它。它实际测量的是两次 ISR 回调的间隔，并未测主循环活性。首次回调发生在上电超过 1 s，或两次回调相隔超过 1 s，均满足复位条件；该判断还位于 counted_active/有效 timer 检查之前。持续 ISR 执行反而不能凭此识别主循环饥饿。若 HAL tick 冻结，这个比较也不能解决冻结问题。代码层面的误判条件已经证实，现场是否触发尚无证据。
2. **IWDG Reload 确为 500。** `Core/Src/main.c:207–208` 为 Prescaler32、Reload500；在 `:126` 初始化，`:137` 于 `ec_app_poll()` 返回后喂狗。按 LSI 32 kHz 计算约 `(500+1)*32/32000 = 0.501 s`，实际受 LSI 偏差影响。主循环阻塞超过该窗口会复位。尚无现场最长主循环时长或复位标志证据，不能宣称该值导致本次无应答，也不能凭空给出替代 Reload 值。

建议：先处理 ISR 间隔被误当主循环活性的明确缺陷；看门狗窗口按可验证的执行时长与停机需求另行核定。不要以扩大超时或取消保护来直接掩盖无应答。当前 HEX 仅作为已构建的诊断候选，未获本次高危保留/处置决定，未烧录。

## 源码可确认的无应答分支

### 状态与 POST

- 上电初值为 `FAULT_LOCK`、fault_reason=`RESTART_CONTEXT_UNPROVEN`、round_id=0（`ec_state_machine.c:38–52`）。
- `FAULT_LOCK` 只处理满足各确认条件的 `MANUAL_NEW_ROUND_CONFIRMED`，其它事件直接返回快照；合法 ITEM_TASK 在这里也没有 NACK（`:67–79`）。
- 当前状态机的实际启动路径是 `POWER_ON → HOMING → PREPARE_BARRIER → WAIT_TASK`（`:74–76,99–110`）。**POST 阶段实际显示 POWER_ON**；虽然枚举中有 POST、READY，当前状态机未赋值进入这两态。STM32 没有 IDLE 或 RECOVERY_LOCK 枚举；RECOVERY_LOCK 属于 Python 调度器。
- `ec_startup_sequence_poll_post()` 的实际失败输入检查确实只有 ESTOP 与 POWER_PERMISSION（`App/Src/ec_startup_sequence.c:124,130`）。两者均未触发时，经过至少 50 ms 返回 PASSED（`:138`）。随后 2000 ms 超时分支位于该返回之后，在当前逻辑里不可达。没有限位检查。
- `ec_app_poll_startup_sequence()` 将失败转换为 EMERGENCY_STOP（`ec_app.c:377–428`）。一次正常 INPUTS 快照不能证明此前每次启动过程均正常。
- FAULT_LOCK 的其他来源包括急停、电源许可丢失、deadline、去重冲突/满；App 还会把轴故障及运动/显示 watchdog 超时转换为故障事件（状态机 `:81–95,126–130`；App `:450–561`）。`ec_app_handle_transition()` 执行动作与安全锁；接收成功路径会在递归任务校验前先发 ACK（App `:271`）。本轮不改任何进入条件。

### task_id 到底由谁锁存

1. STM32 上的生产调用来自本地 `ec_app_poll_start_button()`（`App/Src/ec_app.c:332–370`）：仅在 FAULT_LOCK 且 START 输入有效时，递增 `local_round_id`，注入 `MANUAL_NEW_ROUND_CONFIRMED`。初始化计数为 0；满足确认条件后，状态机把该轮次写入 round_id。失败尝试也先递增，故不能把板上实际轮次直接认作 1。
2. 网关的入站命令分派只有 ITEM_TASK 和 DISPLAY_ACK（`stm32_logic/src/ec_protocol_gateway.c:253–262`）；没有可以由树莓派发送来锁存新轮次的命令。
3. **用户已给出的 ACTIVE=0x00A8 包含 START=0x0080，且不含 MANUAL_RESET=0x0100。不能据此下“没按 START”的结论。** 若同一运行版本、同一时段持续读取这些输入，源码应尝试推进启动；实际状态及历史仍需 STATUS 证明。
4. 非锁定状态下，合法任务触发轮次拒绝动作时会发 NACK WRONG_ROUND（0x14），不是因 task_id 不相等直接静默丢弃（网关 `:103–109`、状态机 `:117–119`）。因此“task_id=1 不匹配”本身不能解释从未收到 NACK。

### 帧校验与应答对照

| 条件 | 当前代码行为 | 位置 |
|---|---|---|
| 外层头/version/总长度/CRC 错误 | 解码失败，静默返回 | `ec_protocol.c:62–93`；gateway `:245–246` |
| data_len 使总长超过 64 B | 清接收长度并静默丢弃 | gateway `:409–416` |
| data_len 在容量内，但实际字节不足 | 等待剩余字节；本函数没有帧超时 | gateway `:400–427` |
| receiver 不是 STM32=3、sender 不是 Pi=2 | 静默返回 | gateway `:249–250,128–129` |
| ITEM_TASK payload 非 12 B，或内容不合法 | payload 解码失败，静默返回；旧 8 B payload 不接受 | `ec_protocol.c:182–223`；gateway `:122–123` |
| 已在 FAULT_LOCK，收到合法 ITEM_TASK | 直接返回，不发 ACK/NACK | state machine `:67–79` |
| WAIT_TASK、轮次错误 | NACK WRONG_ROUND | state machine `:117–119`；gateway `:103–109` |
| 首次见到的陈旧 frame_seq（last 非零且 seq ≤ last） | 首次 NACK SINGLE_TASK_ONLY；该身份已入去重表 | state machine `:121–139` |
| 上一行同一任务再次重传 | 命中去重但响应缓存无记录，可静默；现有测试覆盖首次 NACK/后续静默 | gateway `:93–102`；`tests/test_protocol_gateway.c:607–645` |
| 同一身份的内容冲突/去重表满 | 进入 FAULT_LOCK，未设置应答动作 | state machine `:126–130` |
| 合法新任务，处于 WAIT_TASK、轮次一致、通过顺序门禁 | ACK ITEM_ACCEPTED，进入 VALIDATE_TASK | state machine `:140–146`；gateway `:80–86` |

frame_seq 没有独立的“必须非零否则静默丢弃”检查；不要虚构该门禁。CRC 运算为 MODBUS（初值 FFFF、反射多项式 A001），**本项目外层封装以高字节在前写 CRC**，不能因标准 Modbus RTU 的惯例自行换序。payload 校验含 grip_angle=FF，以及 pick/drop 坐标各在 ±1450 范围；以当前解码器为准，未修改。

当前主源码及 staging Python 编码实现与当前 C 解码器都为 12 B payload，CRC 算法/封装一致。这个静态事实不证明树莓派实际 import 的文件或板上固件就是当前版本；需要现场原始帧核对。

## 树莓派侧：已定位文件，尚不能归因现场

按冲突台账 §9 E-26，当前入口为 `电控/deploy/run_chain.py`，不是已废弃的 `deployment/`。

- `run_chain.py:1011–1015` 的 `--start-round` 调用 `scheduler.start_verified_new_round(VerifiedNewRound(round_id, True, True, True))`。
- `电控/src/electrical_control/rpi/__init__.py:335–349` 的实现只清理本地调度器、设 round_id 和 READY，**没有串口发送**，不证明 STM32 已经 WAIT_TASK。
- `电控/src/electrical_control/rpi/outbound.py:74–94` 用配置的 round_task_id 编码任务，wire frame_seq 从 1 递增；`:96` 后重传原字节。`run_chain.py:1049` 发送 ITEM_TASK。
- staging 副本 `工具/pi_staging/ec-chain/deploy/run_chain.py:860–865` 也采用本地确认逻辑；不能仅凭仓库入口判定现场启动的就是哪份副本。

**确认的集成缺口：树莓派把本地轮次确认当作就绪条件，却没有由此建立 STM32 轮次/就绪的可验证同步。当前没有“漏发的某条现有新轮次 wire 命令”可补发。** 本轮不发明命令、不更改协议，也不把该缺口直接写成本次现场根因。

## 尚缺的最小现场证据

1. 用户决定上述两项高危设置如何处理后，确认实际烧录的产物身份；采集 ITEM_TASK 首发与重试前后**未经二进制解析器过滤**的 STATUS，保留 APP_STATE、时间及是否复位的上下文。
2. 同时保留首发/重发的完整 ITEM_TASK 十六进制和未经筛选的 RX 字节，确认现场 Python 入口及实际 import 路径/版本。仅“没有 inbound 日志”不足以判定没有 RX。
3. 若 APP_STATE=FAULT_LOCK，只能先确认静默的状态分支；还需 fault_reason/轮次/启动经过或复位原因，才能解释为什么锁定。若为 WAIT_TASK，则用实际帧逐项检查长度、CRC、收发设备、payload、task_id 和 frame_seq，并与板上轮次比较。若为 POWER_ON，则沿实际 POST 轮询和启动经过调查，不能等待打印一个当前不会进入的 POST 枚举。

目前结论停在源码机制与诊断能力已确认；没有捏造 APP_STATE 实测值，也没有宣称问题已修复。

## 内部审查记录

【核心角色】诊断读真实 App 状态、状态名覆盖完整；末尾追加字段，既有顺序不变；测试孤立链接桩不进入生产固件。

【监察角色】两项高危复位设置明确存在，未顺手修改；未进行烧录/运动；台账冲突按较新 deploy 权威结论处理；主机通过不等于现场通过。

【调度协议】本轮为 L2 可逆诊断改动与只读审查；状态 REVIEW_REQUIRED / WAITING_EXTERNAL。代码与构建已交付，现场根因调查等待用户的高危处置决定及随后现场证据。任务进度见 `.claude/tasks/task-20260918-app-state-item-task.md`。
