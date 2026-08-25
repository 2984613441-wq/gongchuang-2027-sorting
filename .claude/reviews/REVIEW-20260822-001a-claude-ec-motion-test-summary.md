# REVIEW-20260822-001a · 电控运动测试固件只读审核（Claude 结论摘要归档）

> 审核方：Claude（独立只读；结论由用户于 2026-08-22 转交归档）
> 审核对象：电控运动测试固件（`ec_board_stm32.c`、`ec_step_test.c`、
> `ec_servo_test.c`、`ec_group_test.c`、`ec_barrier_test.c`、`ec_diag.c`、
> `main.c`、`stm32f4xx_it.c`、`stm32f4xx_hal_msp.c`、`tests/CMakeLists.txt`）
> 关联核验：`REVIEW-20260822-002-codex-ec-motion-test-reconciliation.md`
> 编号说明：本文件为早期结论摘要归档，编号调整为 001a；完整审核见
> `REVIEW-20260822-001-claude-ec-motion-test-firmware.md`。

---

## 0. 总体裁决

| 维度 | 裁决 |
|---|---|
| **电控运动测试固件** | **有条件通过** |
| **实机运动门禁** | **不允许**（需整改 P0/P1 并另行授权后才能实机） |

**一句话**：命令协议、安全门禁（arm 一次性窗口 / 单轴互斥 / 超时停 / 输入抑制停 /
上电禁能）整体实现正确，但发现 **1 个 P0 功能缺陷 + 1 个 P1 一致性缺陷**，需整改后
才能实机运动。

---

## 1. 发现项（按严重性）

### P0　计数运动（`MOVE ... STEPS`）的步数递减中断从未使能，永远"超时"而非"完成"

- **事实**：`ec_board_stm32.c:162` 用 `HAL_TIM_PWM_Start_IT(timer, TIM_CHANNEL_1)`
  启动计数运动。该 API 对 channel 1 只使能 `TIM_IT_CC1`（HAL 源码
  `stm32f4xx_hal_tim.c:1565` 明确 `__HAL_TIM_ENABLE_IT(htim, TIM_IT_CC1)`），
  **不使能 `TIM_IT_UPDATE`**。
- **矛盾点**：步数递减逻辑在 `ec_step_port_on_timer_period`，由 `main.c:706` 的
  `HAL_TIM_PeriodElapsedCallback` 调用，它依赖 **update 中断**。而全用户代码里
  `TIM_IT_UPDATE` 只出现在 `ec_board_stm32.c:77` 的
  `__HAL_TIM_DISABLE_IT(timer, TIM_IT_UPDATE)`（关闭一个从未打开的中断）。grep
  全仓无任何 `__HAL_TIM_ENABLE_IT(..., TIM_IT_UPDATE)`。
- **后果**：`counted_steps_remaining` 永不递减 → `ec_motion_test_on_counted_done`
  永不触发 → 计数运动只能靠 `ec_step_test.c` 里的 `counted_timeout_ms` 超时，
  `STEP_RESULT` 永远报 `TIMEOUT`。这是当前分支 `barrier/counted-step motion`
  （提交 `37b06182`）的核心功能。
- **为何主机测试没抓到**：`tests/CMakeLists.txt` 只编译 `App/Src/*` +
  `stm32_logic/*`，**不编译 `ec_board_stm32.c`**（板级层被 port stub 替代），所以
  这个 HAL/中断接线错误对主机 CMake 测试不可见。
- **整改建议**：`ec_step_port_start_counted` 里 `HAL_TIM_PWM_Start_IT` 之后补
  `__HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE)`（或改用 `HAL_TIM_PWM_Start` + 手动
  开 update 中断）。整改后需在真实定时器中断下复核 `MOVE X DIR0 STEPS 100 HZ 100`
  报 `STEP_RESULT=DONE`。

> 次要连带（不单独定级，一并提醒）：`HAL_TIM_PWM_Start_IT` 已使能 CC1 中断，而
> TIM8 的 CC 中断是独立 IRQ（`TIM8_CC_IRQHandler`），当前 `stm32f4xx_it.c` 只定义
> 了 `TIM8_UP_TIM13_IRQHandler`。若 TIM8 的 CC 中断 NVIC 被 CubeMX 使能，会落到
> 默认 handler。修 P0 时应一并核对 `.ioc` 的 TIM8 中断 NVIC 配置。

---

### P1　四个运动测试模块的安全抑制掩码不一致，与冻结基线"任一输入触发立即停止"不符

- `ec_step_test.c:12` 和 `ec_servo_test.c:7` 用 **7 路**掩码（6 限位 +
  ESTOP_FB）。
- `ec_group_test.c:31` 和 `ec_barrier_test.c:15` 用 **9 路**
  （`EC_INPUT_ALL_MASK`，含 `START_SIG`、`MANUAL_RESET_SIG`）。
- 后果：`START_SIG`/`MANUAL_RESET_SIG` 触发时，step/servo 运动不停、group/barrier
  会停。与审计词#2 基线"九路输入…运行中任一输入触发立即停止"不一致。
- 定性：当前诊断固件里 START/MANUAL_RESET 未被消费，属**潜伏**问题；但生产逻辑
  接入（一键启动、人工复位）后会暴露。需用户裁决 START/MANUAL_RESET 到底算不算
  运动抑制输入，然后统一四模块掩码。

---

### P2（低优先级，可择机处理）

1. **`ec_motion_test_start_steps` 自身不校验 steps ≤ 1,000,000**
   （`ec_step_test.c:126` 只查 `steps != 0`）；上限只在诊断解析层
   `parse_move_steps_command` 校验。函数契约不完整，属防御性缺口。
2. **计数超时在极端参数下近 28 小时**：steps=1e6 / hz=10 →
   `counted_timeout_ms ≈ 1e8 + 1000 ms`。一旦计数中断失效（正是 P0），低频率下要
   等极久才超时停止。
3. **BARRIER 的 COLLECT/AVOID/ALL 在固件里行为完全相同**（`ec_diag.c` 三者都
   `ec_barrier_test_start(0x0F, pulse)`，仅 OK 响应串不同）。挡板"归集 vs 避让"的
   真实位置逻辑未实现，差异完全靠操作员传入的 P 值。需在文档里明示，避免误以为
   固件有模式区分。
4. **注释遗漏**：`ec_step_port_start` 注释只写 "TIM4/TIM8 use 100 kHz
   (PSC=159)"，未提 TIM9。已核实 `main.c` 里 TIM9 也是 PSC=159，三轴同为
   100 kHz（HSI 16 MHz / 160），故**非 bug**，仅注释不完整。

---

## 2. 已确认事实（通过项）

- 命令集与响应串与审计词#2 冻结基线一致（`MOTION ARM`→`OK MOTION ARMED 10S` 等，
  含 `GROUP START` 的 XDIR/YDIR 前缀、barrier 四种模式映射）。步数 1~1e6、频率
  10~10000 Hz、脉宽/通道取值校验齐全。
- 安全门禁正确：arm 一次性 10 s 窗口 + 消费即失效 + 超时失效；单轴互斥；限位/急停
  抑制；上电 `ec_board_enter_safe_state` 先停 PWM/禁能/灯灭；`ENABLE` 低有效、上电
  保持高。
- 生产状态机 `ec_sm_consume` 在诊断固件中**不被驱动**（`ec_safety_apply` 仅 init
  调用一次，`SAFE_LOCK=1` 为静态标志），符合"诊断固件 ≠ 生产固件"定位。

---

## 3. 弱独立性限制

- 中断/NVIC 的最终行为依赖 `.ioc` 与 Keil 实际 NVIC 配置，本审核只据源码与 HAL 库
  静态判定；P0 已由 HAL 源码 + 无 `ENABLE_IT(UPDATE)` 的 grep 双重坐实，但建议在
  真实定时器中断下实测复核一次再定案。
- 未执行实机/上电/烧录；"STEP_RESULT 永远 TIMEOUT"是基于代码路径的静态结论，非
  实机观测。

---

> 本文件为 Claude 结论的归档副本；Codex 已于 2026-08-22 逐项对照工作区核验，并补充
> NVIC 与冻结清单证据，见 REVIEW-20260822-002。
