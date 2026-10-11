# T2：B2/B3 链路成因与 host 证据

**B2 是有意的启动安全状态。B3 的“首帧用于建轮次、不执行该件”成立；“5秒没ACK、重传两次才通”不能由现有日志成立。当前主机即使已经收到ACK，仍会在等待约12.9秒动作完成时于5秒、10秒重发。UART层实际丢帧尚无证据。**

本轮仅源码分析、host复现与文档；未改任何生产代码/参数或原测试，未执行git，未打开串口、上电或烧录。下文 `App/`、`tests/` 位于 `电控/firmware/stm32f407_m144z/`；`logic/` 指 `电控/stm32_logic/`。

收尾并发说明：其他写入已将WAIT2000/settle200改为WAIT200/settle600，并同步motion测试；本执行方没有回退。T1报告§0另列最新预算。本报告约12.9秒仅指任务提供的历史轮次；B2/B3的状态与ACK因果链不依赖这两个等待常量。为避免混淆，`run-host.ps1`现在使用保留的旧基线头文件/测试副本复现本报告输出；最新motion/axis验证见 `current-host-output.txt`。

## 1. B2：复位后立即 FAULT_LOCK

| 顺序 | file:line | 实际行为 |
|---|---|---|
| 1 | `Core/Src/main.c:128` | 调 `ec_app_init()` |
| 2 | `App/Src/ec_app.c:571-576` | 板级安全态→初始化gateway→SAFE_LOCK；失活watchdog为false |
| 3 | `logic/src/ec_protocol_gateway.c:273-280` | 初始化去重、状态机、响应缓存 |
| 4 | `logic/src/ec_state_machine.c:38-52` | 明确赋 `state=FAULT_LOCK`、`fault_reason=RESTART_CONTEXT_UNPROVEN`、`actions=SAFE_LOCK`、轮次0、无当前件 |
| 5 | `App/Src/ec_startup_sequence.c:68-73` | POST/HOMING/BARRIER均为IDLE，并未自动开始 |
| 6 | `App/Src/ec_app.c:602-626` | 空转只轮询输入、启动序列和运动；不凭时间自动解锁 |
| 7 | `App/Src/ec_diag.c:274,422,425` | 把 `ec_app_state()` 真枚举值映射为文本；不是常量字符串伪造 |

所以第一个启动事件之前，过9.263秒、25.637秒乃至更久仍在FAULT_LOCK都符合设计。此时15秒运动失活窗尚未开启，不能解释为“空闲15秒超时”。9.263/25.637是复位后采样时刻，不能单凭它们证明曾在别的状态失败。

退出链：`ec_app_poll()` 在 `:619-622` 根据真实输入给网关推进安全值；网关 `ec_protocol_gateway.c:148-158` 将其带入ITEM_TASK事件。`ec_state_machine.c:95-103` 在FAULT_LOCK收到该事件且危险区/急停条件允许时，学习task_id、清去重、转POWER_ON、BEGIN_POST。另一条是START产生人工新轮次事件（`ec_app.c:333-370`，状态机`:106-115`）。当前无需假设有实体START按键。

BEGIN_POST在 `ec_app.c:225-228` 重置并启动启动序列；POST检查急停/电源并等≥50ms（`ec_startup_sequence.c:108-148`）；HOMING等≥500ms且检查安全（`:152-190`）；BARRIER现为直接放行（`:195-218`）。App在`:373-419`把通过事件送回状态机，后者`:137-148`推进到WAIT_TASK并发BARRIER_READY。HOMING当前不做寻零运动；该文件关于“人工摆中心”的旧注释已过时，本轮不据此改变已裁决的负向HOME。

**判定：初始化FAULT_LOCK本身不是缺陷，不建议修改。** 若“已有合法首帧+安全条件成立+启动序列通过后仍锁住”，那是另一命题，需要事件轨迹；只读APP_STATE不能区分初始锁、后续急停锁或失活锁。可在后续获准的调试观测中读取 `gateway.sm.fault_reason`，在 `ec_sm_init` 与 `lock_machine` 设置跟踪点记录调用栈和事件，而非猜原因。

## 2. B3：三个机制必须分开

### 2.1 首发确实被用来建轮次，不是UART没收到

在FAULT_LOCK，`ec_state_machine.c:95-103` 只返回BEGIN_POST；不执行WAIT_TASK下`:165-185`的接件、去重和ACK路径。网关 `ec_protocol_gateway.c:66-110` 没有为BEGIN_POST生成ACK；`:165-176,182-193`也不会把它当已接收的运动任务保留。因此首帧驱动的是启动序列，并没有成为执行中的件。

约50+500ms启动检查完成后，状态机`:143-148`先进入WAIT_TASK，再发BARRIER_READY。**BARRIER_READY不是执行“吞帧”的动作；它是首帧已被用于建轮次的结果。** `电控/deploy/run_chain.py:902-925,1219-1240`在WAIT_MOTION_DONE且有在飞任务时立即原样重发；相关host测试验证不递增发送序号。

在WAIT_TASK收到重发时，状态机设置当前身份和ACK_ITEM_ACCEPTED；网关`:81-86`发ACK并缓存；App `ec_app.c:252-272`在验证重入前先flush这条ACK，避免旧的tx_len清空缺陷。现有回归 `tests/test_app.c:466-525`分别验证首次ACK恰好一次、噪声不重复发送、重传ACK序号不增加。

### 2.2 “5秒无应答”日志实际是完成等待超时，不是ACK等待超时

| file:line | 事实 |
|---|---|
| `电控/deploy/run_chain.py:1074-1076` | 5秒计时用于没有MOTION_DONE/ITEM_RESULT的情况 |
| `run_chain.py:1134-1142` | 只看在飞上下文和距上次发送时间；满足就重发并打印“无应答” |
| `run_chain.py:1166-1169` | MOTION_DONE才重置该计时 |
| `run_chain.py:1180-1183` | ITEM_RESULT才清在飞上下文 |
| `run_chain.py:1248-1260` | DUPLICATE/其它事件只记录；ACK_ACCEPTED没有停止或重置计时的分支 |
| `电控/src/electrical_control/rpi/gateway.py:198-228` | ACK实际被解析为ACK_ACCEPTED，并返回无outbound的事件 |

注意主循环`:1251-1254`的“ACK未建模/IGNORED”注释已落后于gateway实现；当前ACK_ACCEPTED会走末尾日志分支，而非该IGNORED分支，但两者均不更新超时。不能用旧注释当当前行为。

据此，在ACK正常、动作耗时12.9秒时，同样会经历 **ACK已收到→5秒重发→10秒再发→12.9秒DONE**。因此“重发两次才通”可能只是动作尚未结束，并非两次重发修好了丢帧。现有信息足以反证把这条日志当作ACK丢失证据，**不足以排除历史那轮还伴随真实传输异常**。

### 2.3 DUPLICATE不是“首ACK没到”的证据

STM32：`ec_state_machine.c:150-154`在执行期间看到同一当前身份，仅要求RESEND；网关`:93-103`拷贝缓存ACK，不递增tx_seq、不重启运动。

Pi：`gateway.py:116-134`对**入站STM32帧**按 `(task_id,frame_seq)` 查缓存。命中就返回DUPLICATE和缓存outbound；ACK本身没有outbound，所以该值是None。主循环`:1248-1249`虽然打印“已用缓存应答”，并不表示真的再发了应答。对于同一ACK身份出现DUPLICATE，通常意味着Pi之前已经见过该身份，而不是证明首ACK没有收到。

另有可区分的候选：Pi进程不断、STM32复位导致发送序号复用，同task_id/seq可能撞Pi旧入站缓存。该缓存键不含command/payload，缓存初始化在 `gateway.py:48-55`、命中在`:120-124`；STM32序号在 `ec_protocol_gateway.c:292`归零。**本轮没有证据说历史那次就是缓存碰撞**，但观测时需记录完整身份和command，不能只看DUPLICATE文本。

## 3. host 复现与实际输出

证据目录：`docs/reports/evidence/T1-T2-Codex-20260919/`。从仓库根目录运行：

```powershell
& docs/reports/evidence/T1-T2-Codex-20260919/run-host.ps1
& docs/reports/evidence/T1-T2-Codex-20260919/run-extra.ps1
```

均exit=0。`run-host.ps1`解析现有CMake目标的源文件清单、用gcc C11/O2/Wall/Wextra/Werror/pedantic直接构建；`app_probe.c`复用现有 `test_app.c` 的HAL/board/axis桩，实际链接生产app、startup、gateway和状态机。状态编号来自 `logic/include/ec_state_machine.h:9-22`：0=FAULT_LOCK、1=POWER_ON、6=WAIT_TASK、8=EXECUTING。

```
reset state=0 tx=0 ACK=0 barrier=0 moving=0 watchdog=0
idle9263 state=0 tx=0 ACK=0 barrier=0 moving=0 watchdog=0
idle25637 state=0 tx=0 ACK=0 barrier=0 moving=0 watchdog=0
first_ITEM state=1 tx=0 ACK=0 barrier=0 moving=0 watchdog=0
startup_done state=6 tx=1 ACK=0 barrier=1 moving=0 watchdog=0
resend_after_barrier state=8 tx=2 ACK=1 barrier=1 moving=1 watchdog=1
retry_5s state=8 tx=3 ACK=2 barrier=1 moving=1 watchdog=1
retry_10s state=8 tx=4 ACK=3 barrier=1 moving=1 watchdog=1
APP_PROBE PASS; board/axis are host doubles
```

探针断言三个ACK的外层序号相同。它主动注入5秒/10秒重复帧来验证板侧回应，不是假称运行了完整Pi主循环的端到端定时测试；主机计时原因由上节源码链确定。

`pi_probe.py`调用真实Pi网关、复用现有离线调度fixture，输出：

```
first_ACK event=ACK_ACCEPTED outbound=None state=WAIT_MOTION_DONE
replayed_ACK event=DUPLICATE outbound=None state=WAIT_MOTION_DONE
second_replay event=DUPLICATE outbound=None state=WAIT_MOTION_DONE
PI_PROBE PASS: DUPLICATE is inbound identity dedup, not proof of a lost first ACK
```

既有测试实际结果：`test_gateway.py` **19/19**、`test_barrier_ready_resend.py` **3/3**、`test_serial_link_serial.py` **11/11**；协议/状态机 **77/77**；app及禁用进展源测试通过。完整原始输出见 `host-output.txt`、`extra-output.txt`。可单独运行：

```powershell
$env:PYTHONPATH='电控/src'
$env:PYTHONDONTWRITEBYTECODE='1'
py -3.14 -m unittest discover -s 电控/tests/rpi -p test_gateway.py -v
py -3.14 -m unittest discover -s 电控/tests/rpi -p test_barrier_ready_resend.py -v
py -3.14 -m unittest discover -s 电控/tests/rpi -p test_serial_link_serial.py -v
py -3.14 docs/reports/evidence/T1-T2-Codex-20260919/pi_probe.py
```

验证限制：原app host目标缺少新增 `ec_axis_driver_diag()` 的double，原样链接报undefined reference。本轮仅在证据目录加零快照double后运行，未改原测试；这不验证真实诊断数据。board/UART/axis为桩，host通过不能排除实机UART层异常，也不能证明轴实际运动。

## 4. 下一次如何可证伪地定位真正的丢失环节

以下是观测设计，**本轮没有执行硬件采集或修改观测代码**。保留同一轮的有方向原始字节、单调时间、task_id、frame_seq、command、ACK reason/target_seq，且记录板子是否复位。只拿“无应答/DUPLICATE”两句中文无法完成归因。

| 候选 | 必须观察到的链 | 如何证伪 |
|---|---|---|
| 首发被用于启动 | 首ITEM完整到达解析器→FAULT_LOCK变POWER_ON→没有ACK/运动→BARRIER_READY→同帧重发才ACK/运动 | 若首发前已WAIT_TASK，或首发已产生ACK/EXECUTING，则不适用该解释 |
| 完成计时导致正常重传 | 首个执行帧已有ACK_ACCEPTED；运动尚未DONE，距发送约5/10秒重发，重复ACK身份相同，运动只启动一次 | 若首次执行帧确实没有ACK到达Pi，不能仅用此机制解释ACK缺失；需继续分层查 |
| Pi缓存碰撞 | Pi原始RX存在完整新帧；解码身份命中旧缓存，command/内容或启动代际不同，事件却DUPLICATE | 无缓存命中或新Pi进程空缓存时同样复现，可否定该候选 |
| UART RX丢字节/解析失败 | 主机TX写入数足够、线端字节完整；板RX计数/环形缓冲数据不完整或CRC/解码失败；配合ORE/FE/NE/PE、重装接收及溢出计数 | 板已成功解析该帧并进入对应状态，则不是这次帧的接收丢失 |
| UART TX/主机接收侧丢ACK | App的flush已有ACK；HAL发送结果/线上字节、Pi raw RX、PySerial解码各层逐一比对 | 完整合法ACK已进Pi网关，则不能再归咎于UART把该ACK丢掉 |

需要补观测的位置明确如下：

- 板接收：`App/Src/ec_board_stm32.c:901-932`接收启用/回调/重装；`:918-923`环满会丢最旧字节；`:975-981`错误回调清ORE并重装。主循环取字节见 `ec_app.c:636-643,656-663`。
- 板发送：`ec_app.c:66-71` flush；`ec_board_stm32.c:935-945`目前丢弃HAL_UART_Transmit返回值，**调用过transmit不等于发送成功**。后续观测应记录返回值而非只计调用次数。
- Pi传输：`serial_link_serial.py:71`发送未核对write返回字节数；`:84-87,100-130`收字节并解码，坏帧会被丢弃继续扫描。捕获原始读写与解码前后结果才能区分线路与解析器。
- Pi分发：`gateway.py:116-134`记录缓存命中身份和旧值对应的command/内容；`run_chain.py:1134-1142,1164-1260`记录计时基准、当前事件和调度状态。

若要现场采集，应在已获准的运行入口内单点记录，避免额外进程争抢同一UART。分析本轮已有材料的结果是：**B2可解释；启动首发行为可复现；两次重传无需假设ACK丢失也可解释；历史那次是否还有UART异常仍为证据不足。当前不建议据此盲改UART、去重缓存或状态机。**
