# REVIEW-20260820-001 · 四路挡板 + XY 目标步数 + 校赛指令清单 V1 只读回归审核

> 审核方：Claude（本会话，只读）
> 审核对象：`ec_barrier_test.*`、`ec_step_test.*`、`ec_board_stm32.c`、`ec_diag.c`、`ec_app.c`、`main.c`、`stm32f4xx_it.c`、`stm32f4xx_hal_msp.c`、`main.h`、`MDK-ARM/diankongv1.0.uvprojx`、`tests/*`
> 基线：`电控/资料/硬件映射待确认表.md`、`docs/design/2026-08-20-motion-command-list-v1.md`、两份验证记录、Keil 构建日志
> 日期：2026-08-20

---

## 0. 总体裁决

| 维度 | 裁决 |
|---|---|
| **主机侧代码与测试** | **有条件允许** |
| **实机动作门禁** | **不允许**（本审核只读，不构成任何实机授权） |

**一句话**：代码结构清晰、状态机与安全门禁逻辑正确、中断接线/时钟/引脚映射全部一致、测试与构建证据自洽。存在 **1 个 P1**（60s 计数超时静默截断）需在依赖长距离/低速运动前整改，若干 P2/P3 一致性项。**实机仍被门禁**：共地、复位窗口上拉/下拉、四路挡板脉宽、XY 每毫米步数与正方向、最大安全频率均未标定，本审核不授权上电。

---

## 1. 发现项（按严重性）

### P0（无）

未发现阻断级缺陷：无引脚/定时器复用冲突，无 IRQ 名称错误，无时钟/PSC 计算错误，无 STATUS 格式串参数不匹配，无命令解析越界。

---

### P1-1　60s 计数超时静默截断，成功与超时不可区分

- **证据**：`ec_step_test.c:11` `EC_MOTION_COUNTED_TIMEOUT_MS = 60000`；`ec_step_test.c:190-193` 超时即 `stop_active_test()`；解析器 `ec_diag.c:193-196` 允许步数 1～1,000,000、频率 10～10,000 Hz。
- **风险**：60s 内可完成步数 = 频率×60。10 Hz 时仅 600 步；即便 1,000,000 步 @ 10,000 Hz 也需 100s，超 60s。故合法的低速/长距离运动会被 60s 静默截断。截断后 `stop_active_test()` 置 `mode=IDLE`、`counted_steps=0`（`ec_step_test.c:34-42`），`STEP_TARGET`/`STEP_REMAIN` 均回 0，与"正常发完"完全无法区分（`ec_step_test.c:216-225`）。上位机按 STATUS 轮询会误判为"已完成"。
- **整改建议**：① 超时改为 `steps/frequency_hz*1000 + 安全余量`（或直接按参数推导上限）；② 或新增状态位区分 `DONE`/`TIMEOUT`/`INHIBIT`；③ 或收窄允许参数范围并写入指令清单。至少先在清单标注"低频率×大步数会被 60s 看门狗截断"。
- **复查证据**：超时后 STATUS 出现可区分的完成/超时标记；或大参数组合实测不再被静默截断。

---

### P2-1　计数模式结束后泄漏 `TIM_IT_CC1` 中断使能

- **证据**：`HAL_TIM_PWM_Start_IT` 同时使能 `TIM_IT_CC1` 与 `TIM_IT_UPDATE`；`stop_counted_timer()`（`ec_board_stm32.c:69-82`）只 `__HAL_TIM_DISABLE_IT(timer, TIM_IT_UPDATE)`，未关 `TIM_IT_CC1`。此后 `ec_step_port_start()`（非 IT 的 `HAL_TIM_PWM_Start`）复用同一 TIM 时，CC1IE 仍置位，每个周期产生一次多余的捕获比较中断，进入空的弱 `HAL_TIM_PWM_PulseFinishedCallback`。
- **风险**：当前无功能危害（回调为空），但每周期多一次无效 ISR，且是后续若实现 `HAL_TIM_PWM_PulseFinishedCallback` 时的隐患。
- **整改建议**：`stop_counted_timer()` 中同步 `__HAL_TIM_DISABLE_IT(timer, TIM_IT_CC1)`；或改用 `HAL_TIM_PWM_Stop_IT`。
- **复查证据**：计数结束后读 `htim->Instance->DIER`，CC1IE 已清零。

---

### P2-2　挡板通道脉宽校验统一引用 `htim3.Init.Period`

- **证据**：`ec_board_stm32.c:205` `barrier_start_channel()` 对传入的 `timer`（含 TIM10/TIM11）一律用 `pulse_us > htim3.Init.Period` 校验，而非 `timer->Init.Period`。
- **风险**：当前 TIM3/TIM10/TIM11 的 `Period` 均为 19999，校验等价、无害；属潜在不一致，若某通道周期改动即出错。
- **整改建议**：改为 `pulse_us > timer->Init.Period`。
- **复查证据**：代码评审确认；或单测覆盖 TIM10/TIM11 通道周期不同于 TIM3 的用例。

---

### P2-3　指令清单遗漏 `STEP X|Y|Z` 与 `STEP STOP`

- **证据**：`ec_diag.c:374-385` 实现并响应 `STEP X/Y/Z`、`STEP STOP`，`HELP` 串（`ec_diag.c:320-328`）也列出，但 `docs/design/2026-08-20-motion-command-list-v1.md` 第 4 节命令表未收录。
- **风险**：固件有、权威清单没有，上位机对照清单时无法得知此命令存在。审核项 一.3 明确要求此类一致性。
- **整改建议**：在命令表补 `STEP X|Y|Z`（10 Hz / 5s、仅信号不使能驱动）、`STEP STOP`。
- **复查证据**：清单命令表与固件 `ec_diag_process_line` 逐一比对无遗漏。

---

### P3-1　MOVE（旧版与 STEPS）未在 diag 层检查舵机 busy

- **证据**：`ec_diag.c:400`（MOVE STEPS）与 `ec_diag.c:420`（旧 MOVE）只查 `barrier_test_busy() || group_test_busy()`，未查 `ec_servo_test_blocks_step()`；而 `MOTION ARM`（`ec_diag.c:392`）与 `STEP X/Y/Z`（`ec_diag.c:375-382`）均查。
- **风险**：舵机运行中发 MOVE，返回 `ERR MOTION_NOT_ARMED_OR_INHIBITED` 而非 `ERR TEST_BUSY`。**非安全漏洞**——motion 的 ARM 门禁仍会阻止实际运动（`ec_step_test.c:125-130`），仅是错误码误导。反向（舵机侧查 `step_test_busy()`）是完整的。
- **整改建议**：MOVE 两处补 `ec_servo_test_blocks_step()`，使错误码语义一致。

---

### P3-2　验证记录对"端口启动失败"覆盖存在过报

- **证据**：`docs/reports/2026-08-20-xy-step-motion-v1-verification.md:24` 声称 step 测试覆盖"端口启动失败"，但 `tests/test_step_test.c:12-13` 的 `ec_step_port_start*` 桩恒返回 `true`，step 模块从未演练端口失败分支（挡板模块确有覆盖：`test_barrier_test.c:109`）。
- **风险**：证据表述偏乐观，弱化验证可信度。
- **整改建议**：修正记录措辞，或给 step 桩加"失败注入"用例。

---

### P3-3　HSI 16 MHz 时钟下的 UART 波特率精度（已知风险）

- **证据**：`main.c:153-169` 用 HSI（16 MHz，PLL 关），USART3 115200（`main.c:579-586`）。
- **风险**：HSI 标称 ±1%，BRR 量化误差约 0.08%，合计约 ±1% 波特率偏差。台架短距可用，正式生产时钟待确认（硬件映射表已列入"最终生产时钟"待确认项）。
- **整改建议**：正式版评估切换 HSE 晶振；当前台架阶段可接受。

---

## 2. 已确认事实 / 推断 / 建议 / 未知 / 弱独立性

### 已确认事实（逐条核对过源码）
1. 挡板四通道 = PB0/TIM3_CH3、PB1/TIM3_CH4、PF6/TIM10_CH1、PF7/TIM11_CH1，与硬件映射表一致；无与 STEP/舵机/补光/UART 的复用冲突。
2. X/Y/Z STEP = PC6/TIM8_CH1、PB6/TIM4_CH1、PE5/TIM9_CH1；DIR/ENABLE 引脚逐位对照 `main.h` 与硬件映射表，全部一致。
3. 九路输入位序（`ec_inputs.h:6-14`）与 `read_raw_inputs()`（`ec_board_stm32.c:45-53`）、硬件映射表一致。
4. 定时器时钟自洽：HSI 16 MHz → TIM2/3/10/11 PSC=15 → 1 MHz（1µs/计数，舵机/挡板 `compare=pulse_us` 直接成立）；TIM4/8/9 PSC=159 → 100 kHz（10µs/计数，`period=100000/f-1` 成立）。
5. TIM4/TIM8/TIM9 的 IRQ 名称正确：`TIM4_IRQHandler`、`TIM8_UP_TIM13_IRQHandler`、`TIM1_BRK_TIM9_IRQHandler`（STM32F407 经典共享 IRQ 坑，全部接对），NVIC 使能与优先级在 `stm32f4xx_hal_msp.c:118-150`。
6. 一次更新事件 = 一个完整 PWM 周期 = 一步脉冲（`HAL_TIM_PWM_Start_IT` 使能 UPDATE IT，`ec_step_port_on_timer_period` 按周期递减），计数语义正确。
7. 计数完成路径：停 PWM → 关 UPDATE IT → 禁能驱动 → 复位状态，无递归/重复停止。
8. ARM 一次性授权 + 10s 窗口 + poll 过期清除 + 九路门禁，逻辑正确；时间戳减法用 `(uint32_t)` 回绕，溢出安全。
9. 互斥双向成立（servo/group/barrier/motion 通过 `step_test_busy()` 含 `mode` 与 `motion_armed`）。
10. `BARRIER COLLECT/AVOID` 未写死角度，显式接收脉宽，符合"标定值由上层下发"的契约。
11. 挡板脉宽解析严格拒绝非数字/越界（逐位 `>MAX` 防溢出）/小于 MIN，允许前导零。
12. STATUS 格式串 21 个说明符 : 21 个实参，在 4 种 `EC_*_BUILD` 组合下均配平；`%lu` 显式强转 `unsigned long`，跨 32/64 位安全。
13. Keil `.uvprojx` 定义 `EC_DIAGNOSTIC_BUILD=1 ... EC_BARRIER_TEST_BUILD=1`（全开），挡板/XY 命令确实编入固件。
14. HEX 文件存在，SHA256 = `1277f247…d03d`，与验证记录一致。
15. `ec_servo_test_*` / `ec_group_test_*` 被 `ec_diag.c` 无条件调用的函数在对应 `.c` 中均非 `#if` 包裹，`EC_*_BUILD=0` 组合可链接。

### 推断
- 60s 超时是"安全看门狗"，本意防中断不触发导致的卡死，但未按运动参数推导，副作用是静默截断（→ P1-1）。

### 建议
- 见各发现项的整改建议；优先 P1-1，其次 P2-1/P2-2/P2-3。

### 未知
- M144Z-M4 排针到 MCU 的物理连续性（硬件映射表自列"待确认"）。
- `ec_inputs.c` 去抖/active 判定细节（本次变更范围外，未逐行核，但其输出与测试断言一致）。
- 挡板到位判据、COLLECT/AVOID 标定角度、XY 每毫米步数与正方向、最大安全频率、机械干涉、电源/急停。

### 弱独立性限制
- 未在本环境重新执行 Keil 构建与 ctest；"0 Error 0 Warning" 与"2/2 通过"采信用户本机结果，佐证为构建日志文本与 CMake 配置（`-Wall -Wextra -Werror`）。
- 未读基线测试 `test_group_test.c`/`test_servo_test.c`/`test_inputs.c`/`test_safety_adapter.c`/`test_app.c`/`test_main.c`/`test_diag_disabled.c`（本次审核聚焦挡板/XY/diag 三个新增或核心测试）。

---

## 3. 通过的检查 / 未执行的检查 / 不能得出的结论

### 通过的检查
- 挡板引脚/定时器 vs 硬件映射，无冲突。
- IRQ 名称 + NVIC + `stm32f4xx_it.c` 处理函数 vs 启动文件。
- 定时器 PSC/ARR 与脉宽/步频单位换算。
- ARM 一次性/10s/过期清除/门禁。
- BARRIER RUNNING 期间输入触发、3s 保持、端口失败 → 停 PWM 回 IDLE。
- BARRIER↔STEP/SERVO/GROUP 互斥双向。
- STOP ALL / STEP STOP / RX_OVERFLOW / LINE_TOO_LONG → 停挡板。
- 上电安全态含四路挡板 PWM 停止（`ec_board_enter_safe_state` 调 `ec_barrier_port_stop`）。
- 命令解析前缀长度/脉宽指针偏移（`BARRIER P`/`ALL P`/`1..4 P`/`COLLECT P`/`AVOID P`/`MOVE … STEPS … HZ …`）逐条核对。
- STATUS 缓冲区/字段/格式串、HELP 覆盖新增命令。
- 计数完成回调复位、目标/剩余查询。
- `EC_BARRIER_TEST_BUILD=0` 路径可链接（`ec_diag_disabled_tests` + 函数无条件定义）。

### 未执行的检查
- 烧录、串口实测、挡板逐通道脉宽、XY 每毫米步数/正方向、最大安全频率、机械干涉、电源/急停（均为实机项）。
- 复位窗口上拉/下拉的硬件落实（属硬件层，非固件层）。

### 不能得出的结论
- "实机通过"——本次仅覆盖代码/测试/构建证据。
- 挡板到位判据与 COLLECT/AVOID 实际角度。
- DIR 正方向（`EC_DIRECTION_1` 对应物理正/负方向未标定）。

---

## 4. 最小整改清单与复审触发条件

### 最小整改（建议顺序）
1. **[P1-1]** 计数超时改为按 `steps/frequency_hz` 推导（或新增完成/超时状态位）。
2. **[P2-1]** `stop_counted_timer()` 补关 `TIM_IT_CC1`。
3. **[P2-2]** `barrier_start_channel()` 校验改用传入 `timer->Init.Period`。
4. **[P2-3]** 指令清单命令表补 `STEP X|Y|Z`、`STEP STOP`。
5. **[P3-1]** MOVE 两处补 `ec_servo_test_blocks_step()`。
6. **[P3-2]** 修正验证记录中"端口启动失败"覆盖措辞或补失败注入用例。

### 复审触发条件
- 任一条 P1/P2 整改落地后，重跑 ctest（2/2）与 Keil 重建（0/0），并复核对应证据。
- 实机前必须完成：共地确认、复位窗口上拉/下拉、四路挡板脉宽标定、XY 每毫米步数与正方向标定、最大安全频率、机械干涉、急停与电源验证。

---

**审核记录已写入工作区**：`.claude/reviews/REVIEW-20260820-001-claude-barrier-command-v1.md`（新文件，未覆盖旧记录）。
