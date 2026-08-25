# REVIEW-20260822-001 — 电控运动测试固件只读审核

> 审核方：Claude（电控主官视角，只读）
> 日期：2026-08-22
> 分支：codex/stm32-motion-test-v1
> 范围：电控子系统（运动测试固件 + 板级层 + 命令协议 + 安全门禁）；**视觉侧不在本次范围内**

## 被审对象

- `电控/firmware/stm32f407_m144z/App/Src/ec_diag.c`（诊断命令协议）
- `…/App/Src/ec_step_test.c`、`ec_servo_test.c`、`ec_group_test.c`、`ec_barrier_test.c`（四个运动测试模块）
- `…/App/Src/ec_inputs.c`、`ec_safety_adapter.c`、`ec_app.c`
- `…/App/Src/ec_board_stm32.c`（板级层：GPIO / 定时器 / UART）
- `…/Core/Src/main.c`、`stm32f4xx_it.c`（CubeMX 接入 + 中断向量）
- `电控/stm32_logic/src/ec_state_machine.c`（生产状态机，交叉参考）

## 总体裁决

- **电控运动测试固件：有条件通过**
- **实机动作门禁：不允许** —— P0 未修复并复核前，禁止实机执行 `MOVE … STEPS` 计数运动；P1 掩码裁决未落地前，禁止把 START/MANUAL_RESET 当作可依赖的运动抑制信号。

---

## 发现项

### P0-1 计数运动（`MOVE … STEPS`）的步数递减中断从未使能，永远“超时”而非“完成”

- **严重性**：P0（阻断当前分支核心功能）
- **事实/证据**：
  - `ec_board_stm32.c:162` 用 `HAL_TIM_PWM_Start_IT(timer, TIM_CHANNEL_1)` 启动计数运动。该 HAL API 对 channel 1 只使能 `TIM_IT_CC1`（HAL 源码 `stm32f4xx_hal_tim.c:1565` 明确 `__HAL_TIM_ENABLE_IT(htim, TIM_IT_CC1)`），**不使能 `TIM_IT_UPDATE`**。
  - 步数递减逻辑在 `ec_step_port_on_timer_period`，由 `main.c:706` 的 `HAL_TIM_PeriodElapsedCallback` 调用，依赖 **update 中断**。
  - 全用户代码中 `TIM_IT_UPDATE` 只出现在 `ec_board_stm32.c:77` 的 `__HAL_TIM_DISABLE_IT(timer, TIM_IT_UPDATE)`（关闭一个从未打开的中断）；grep 全仓无任何 `__HAL_TIM_ENABLE_IT(…, TIM_IT_UPDATE)`。
- **精确定位**：`ec_board_stm32.c:162`（启动方式）、`main.c:706-709`（回调入口）、`ec_board_stm32.c:77`（错误地关闭未开启的 update 中断）。
- **风险**：`counted_steps_remaining` 永不递减 → `ec_motion_test_on_counted_done` 永不触发 → 计数运动只能靠 `ec_step_test.c` 的 `counted_timeout_ms` 超时，`STEP_RESULT` 永远报 `TIMEOUT`。当前分支 `barrier/counted-step motion`（提交 37b06182）的核心功能在实机上不可用。
- **可验证的整改建议**：`ec_step_port_start_counted` 中，在 `HAL_TIM_PWM_Start_IT` 之后补 `__HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE)`（或改用 `HAL_TIM_PWM_Start` + 手动开 update 中断）。同时核对 `.ioc` 的 TIM8 CC/UP 中断 NVIC 配置（见下方连带提醒）。
- **整改后需要复查的证据**：真实定时器中断下发送 `MOVE X DIR0 STEPS 100 HZ 100`，`STATUS` 报 `STEP_RESULT=DONE` 且 `STEP_REMAIN=0`；`MOVE X DIR0 STEPS 5 HZ 10` 在合理时间内完成而非超时。

> 连带提醒（不单独定级）：`HAL_TIM_PWM_Start_IT` 已使能 CC1 中断，而 TIM8 的 CC 中断是独立 IRQ（`TIM8_CC_IRQHandler`），当前 `stm32f4xx_it.c` 只定义了 `TIM8_UP_TIM13_IRQHandler`。若 TIM8 的 CC 中断 NVIC 被 CubeMX 使能，会落到默认 handler。修 P0 时应一并核对 TIM8 中断 NVIC。

### P1-1 四个运动测试模块的安全抑制掩码不一致，与冻结基线“任一输入触发立即停止”不符

- **严重性**：P1（潜伏一致性缺陷，生产逻辑接入后暴露）
- **事实/证据**：
  - `ec_step_test.c:12-14` 的 `EC_MOTION_SAFETY_MASK` 与 `ec_servo_test.c:7-9` 的 `EC_SERVO_SAFETY_MASK` 均为 **7 路**（X/Y/Z 六限位 + ESTOP_FB）。
  - `ec_group_test.c:31-34` 与 `ec_barrier_test.c:15-18` 的 `has_inhibit` 用 `EC_INPUT_ALL_MASK`（**9 路**，含 `START_SIG`、`MANUAL_RESET_SIG`）。
- **精确定位**：`ec_step_test.c:12`、`ec_servo_test.c:7`、`ec_group_test.c:31`、`ec_barrier_test.c:15`。
- **风险**：`START_SIG` / `MANUAL_RESET_SIG` 触发时，step/servo 运动不停、group/barrier 会停。与审计词“九路输入…运行中任一输入触发立即停止”不一致。当前诊断固件未消费这两路输入，属潜伏；生产逻辑（一键启动、人工复位）接入后会不一致。
- **可验证的整改建议**：裁决 START_SIG / MANUAL_RESET_SIG 是否属于运动抑制输入，然后统一四模块掩码（要么都 7 路，要么都 9 路），并同步更新文档冻结基线表述。
- **整改后需要复查的证据**：四模块对同一位输入（如 MANUAL_RESET 接地）的停止行为一致，且有对应主机测试断言。

### P2-1 `ec_motion_test_start_steps` 自身不校验 steps 上限

- `ec_step_test.c:126` 只查 `steps != 0`；1,000,000 上限只在诊断解析层 `parse_move_steps_command` 校验。函数契约不完整，属防御性缺口。建议在 `ec_motion_test_start_steps` 内补 `steps <= 1000000` 校验。

### P2-2 计数超时在极端参数下近 28 小时

- `ec_step_test.c:140`：`counted_timeout_ms = steps*1000/hz + 1000`。steps=1e6 / hz=10 → ≈ 1e8 + 1000 ms ≈ 27.8 h。一旦计数中断失效（即 P0），低频率下要等极久才超时停止。修 P0 后建议增加对“超时上限”或“极长时长”的显式保护/告警。

### P2-3 BARRIER 的 COLLECT / AVOID / ALL 在固件中行为相同

- `ec_diag.c:499-553`：`BARRIER P`、`BARRIER ALL P`、`BARRIER COLLECT P`、`BARRIER AVOID P` 四者最终都调用 `ec_barrier_test_start(0x0F, pulse)`，仅 OK 响应串不同。挡板“归集 vs 避让”的真实位置逻辑未实现，差异完全靠操作员传入的 P 值。需在文档明示，避免误以为固件存在模式区分。

### P2-4 注释遗漏 TIM9

- `ec_board_stm32.c:126` 注释只写 “TIM4/TIM8 use a 100 kHz timer clock (PSC=159)”，未提 TIM9。已核实 `main.c` 中 TIM9 也是 PSC=159，三轴同为 100 kHz（HSI 16 MHz / 160），故**非 bug**，仅注释不完整。

---

## 已确认事实（通过项）

- 命令集与响应串与冻结基线一致：`MOTION ARM`→`OK MOTION ARMED 10S`、`MOVE X|Y|Z DIR0|DIR1`→`OK MOTION STARTING`、`MOVE … STEPS … HZ …`→`OK MOTION STARTING`、`SERVO ARM/PB10 P<us>`、`GROUP ARM/START XDIR YDIR OPEN|CLOSE`、`BARRIER ARM/P|ALL P|1..4 P|COLLECT P|AVOID P` 等，含 `GROUP START` 的 XDIR/YDIR 前缀。
- 参数校验齐全：步数 1~1,000,000、频率 10~10,000 Hz、舵机/挡板脉宽范围、通道 1~4、方向 0/1。
- 安全门禁正确：arm 一次性 10 s 窗口（消费即失效 + 超时失效）；单轴互斥；限位/急停抑制；上电 `ec_board_enter_safe_state` 先停 PWM / 禁能 / 灯灭；`ENABLE` 低有效、上电保持高。
- 生产状态机 `ec_sm_consume` 在诊断固件中不被驱动（`ec_safety_apply` 仅 init 调用一次，`SAFE_LOCK=1` 为静态标志），符合“诊断固件 ≠ 生产固件”定位。

## 推断

- P0 的“永远 TIMEOUT”是基于代码路径的静态推断，非实机观测。
- P1 判定“潜伏”依据：诊断固件中 START/MANUAL_RESET 未被任何逻辑消费（`ec_app.c`、`ec_diag.c` 均未引用）。

## 建议

1. 优先修 P0（补 `TIM_IT_UPDATE` 使能），这是当前分支核心功能。
2. 裁决并统一 P1 的抑制掩码。
3. P2 可择机处理，不阻塞。

## 未知 / 弱独立性限制

- 中断/NVIC 最终行为依赖 `.ioc` 与 Keil 实际 NVIC 配置；本审核据源码 + HAL 库静态判定。
- 未执行实机 / 上电 / 烧录；未访问真实串口。

## 通过的检查

- 命令解析与冻结基线一致性。
- arm 门禁、单轴互斥、超时停、输入抑制停、上电安全默认。
- 三个步进定时器 PSC=159 / ARR=9999（HSI 16 MHz → 100 kHz），`period = 100000/freq - 1` 对三轴均正确。

## 未执行的检查

- 实机定时器中断下的计数运动行为。
- 真实串口回显与 `STATUS` 时序。
- Keil 无警告构建后的板级复核。

## 不能得出的结论

- 不能据此宣称“固件已通过实机运动测试”或“计数运动功能可用”。
- 不能宣称 START/MANUAL_RESET 的抑制语义已定。

---

## 最小整改清单

| 优先级 | 动作 | 复查证据 |
|---|---|---|
| P0 | `ec_step_port_start_counted` 补 `__HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE)`；核对 TIM8 中断 NVIC | `MOVE X DIR0 STEPS 100 HZ 100` → `STEP_RESULT=DONE`、`STEP_REMAIN=0` |
| P1 | 裁决并统一四模块抑制掩码 + 更新文档基线 | 四模块对同一位输入停止行为一致 + 主机测试断言 |
| P2 | 补 steps 上限校验、超时上限告警、COLLECT/AVOID 语义文档化、注释补 TIM9 | 各自对应的主机测试/文档复核 |

## 复审触发条件

- P0 整改完成并实机复核后，需复审本文件 P0 项并更新为“已修复”。
- 任一模块掩码或文档基线变更后，复审 P1。
- 本审核只读，不构成任何接线、上电、烧录或实机运动授权。
