# REVIEW-20260822-002 · Codex 对 Claude 电控运动测试审核的核验与裁决记录

> 记录方：Codex（工程实施核验；本记录不构成独立审核）
> 依据：`REVIEW-20260822-001-claude-ec-motion-test-firmware.md`
> （早期结论摘要归档为 `REVIEW-20260822-001a-claude-ec-motion-test-summary.md`）
> 日期：2026-08-22
> 状态：核验完成；P0/P2 整改待用户确认后实施，P1 待用户裁决

## 0. 核验结论

| 发现项 | 核验结论 |
|---|---|
| P0 计数运动 update 中断未使能 | **采纳**；修法待用户确认后实施 |
| P1 四模块抑制掩码 7/9 不一致 | **驳回代码缺陷定性，降级为文档语义待澄清**；与冻结清单第 3 节一致 |
| P2-1 `start_steps` 不校验步数上限 | **采纳**（防御性缺口） |
| P2-2 极端参数下计数超时近 28 小时 | **接受**（P0 修复后影响大幅降低，仍记录边界） |
| P2-3 BARRIER COLLECT/AVOID/ALL 行为相同 | **采纳（文档）** |
| P2-4 TIM9 注释遗漏 | **采纳（注释）**；确认非 bug |

---

## 1. P0 核验

### 事实成立

- `ec_board_stm32.c:162` 仅用 `HAL_TIM_PWM_Start_IT`，HAL 源码
  `stm32f4xx_hal_tim.c:1565` 只使能 `TIM_IT_CC1`。
- 用户代码无任何 `__HAL_TIM_ENABLE_IT(..., TIM_IT_UPDATE)`；仅
  `ec_board_stm32.c:77` 在 `stop_counted_timer()` 里关闭 `TIM_IT_UPDATE`。
- `main.c:706-708` 的 `HAL_TIM_PeriodElapsedCallback` → `ec_step_port_on_timer_period`
  依赖 update 中断；`stm32f4xx_hal_tim.c:3954-3960` 只有 `TIM_IT_UPDATE` 使能时
  才调用 PeriodElapsedCallback。
- `tests/CMakeLists.txt` 确实不编译 `ec_board_stm32.c`，主机测试无法覆盖此接线。

### 对 Claude 弱独立性的补充核验（重要修正）

- **NVIC 已使能，不缺失**：`stm32f4xx_hal_msp.c:120-149` 已对 `TIM4_IRQn`、
  `TIM8_UP_TIM13_IRQn`、`TIM1_BRK_TIM9_IRQn` 执行 `HAL_NVIC_SetPriority` +
  `HAL_NVIC_EnableIRQ`；`stm32f4xx_it.c` 对三者均有对应 IRQHandler。因此只要在
  DIER 打开 `TIM_IT_UPDATE`，update 中断即可触发。
- **TIM8 CC 无默认 handler 落地风险**：`stm32f4xx_hal_msp.c` 只使能
  `TIM8_UP_TIM13_IRQn`，未使能 `TIM8_CC_IRQn`，因此 `HAL_TIM_PWM_Start_IT` 打开的
  CC1 中断不会进入默认 handler；Claude 提示的连带项在当前工程不成立。

### 建议修法

推荐修法 A（最小且避免多余 CC1 中断）：

```c
/* 计数运动只需 update 中断逐周期递减步数；PWM 用非 IT 启动，避免 CC1 干扰 */
if (HAL_TIM_PWM_Start(timer, TIM_CHANNEL_1) != HAL_OK) { ... }
__HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE);
```

备选修法 B（Claude 原文）：`HAL_TIM_PWM_Start_IT` 成功后补
`__HAL_TIM_ENABLE_IT(timer, TIM_IT_UPDATE)`；缺点是 CC1 中断仍使能（TIM4/TIM9 共享
IRQ 行，会多产生无效 compare 中断），但功能上可行。

整改后验证：Keil 命令行重建并保存日志；实机或等效真实中断环境复核
`MOVE X DIR0 STEPS 100 HZ 100` 的 `STEP_RESULT=DONE`。

---

## 2. P1 核验

### 事实成立，但与冻结基线原文一致

- `ec_step_test.c:12`、`ec_servo_test.c:7`：7 路掩码（6 限位 + ESTOP_FB）。
- `ec_group_test.c:31`、`ec_barrier_test.c:15`：`EC_INPUT_ALL_MASK = 0x01FF`（9 路，
  含 `START_SIG` bit7、`MANUAL_RESET_SIG` bit8）。
- 冻结清单 `docs/design/2026-08-20-motion-command-list-v1.md` 第 3 节原文：
  "组合动作（GROUP、BARRIER）使用全部九路门禁；单轴运动使用限位/急停相关七路门禁。"
- 因此当前代码与冻结清单一致；Claude 引用的"九路输入…任一输入触发立即停止"是清单
  第 3 节前两句的概括，与后两句的分动作规定存在措辞歧义。

### 裁决建议（待用户最终裁决）

- 建议**保持 7/9 现状**：单轴/舵机运动只受限位与急停约束，组合动作受全部 9 路
  约束，符合冻结清单。
- 若用户裁决统一 9 路，则属修改冻结基线，需同步改代码与指令清单，并在实机前重新
  审核。
- 无论哪种裁决，都应在指令清单第 3 节明确写明 START/MANUAL_RESET 在诊断固件中的
  语义（当前未被消费，仅参与组合动作抑制），避免后续生产逻辑接入时暴露分歧。

---

## 3. P2 核验

### P2-1 成立

- `ec_step_test.c:126` 只检查 `steps == 0U`；上限 1,000,000 仅硬编码在
  `ec_diag.c:191` 的 `parse_move_steps_command`。
- 建议：在 `ec_step_test.h` 新增 `EC_STEP_MAX_STEPS`，`ec_motion_test_start_steps`
  同时校验上下限，诊断层复用该常量。

### P2-2 成立

- `ec_step_test.c:131-133`：`counted_timeout_ms = (steps*1000)/hz + 1000`；
  steps=1e6、hz=10 时约 100,000,000 ms（约 27.8 h）。
- P0 修复后正常完成路径由 update 中断驱动，超时仅作为异常兜底；仍建议在文档记录
  该边界，或在实现正式看门狗时对 timeout 设上限。

### P2-3 成立

- `ec_diag.c:506/531/545` 三条路径均调用 `ec_barrier_test_start(UINT8_C(0x0F),
  pulse, ...)`，仅成功响应串不同（`OK BARRIER SET ALL` / `COLLECT` / `AVOID`）。
- 建议：在 `docs/design/2026-08-20-motion-command-list-v1.md` 第 5 节明示
  COLLECT/AVOID 目前为语义命令，位置逻辑待实机标定后由上层脉冲值实现。

### P2-4 成立但非 bug

- `ec_board_stm32.c:150` 注释仅写 TIM4/TIM8；`diankongv1.0.ioc:283-286` 与
  `main.c` 的 TIM9 均为 PSC=159、Period=9999，三轴同 100 kHz。
- 建议：注释补 TIM9。

---

## 4. 测试盲区与验证要求

- `tests/CMakeLists.txt` 不编译 `ec_board_stm32.c`，板级中断接线对主机测试不可见；
  已核验 P0 正是因此漏检。
- P0/P2 整改后：主机测试必须保持 2/2（`ec_firmware_host_tests`、
  `ec_diag_disabled_tests`）；Keil 命令行重建必须退出码 0 并保存日志文本；实机
  `STEP_RESULT=DONE` 复核仍属实机门禁，需用户对具体动作授权。

---

## 5. 需要用户裁决

1. P0 修法：按推荐修法 A（`HAL_TIM_PWM_Start` + 手动使能 `TIM_IT_UPDATE`）实施，
   还是备选修法 B（`PWM_Start_IT` 后补 `ENABLE_IT`）？
2. P1 掩码：保持单轴 7 路 / 组合 9 路（推荐，与冻结清单一致），还是统一 9 路
   （需同步改冻结清单并重新审核）？
3. 是否同一批实施 P2-1/P2-3/P2-4 小整改（推荐，均为低风险文档/防御性修正）？

> 以上裁决后，Codex 完成整改、主机测试、Keil 重建与记录更新；实机动作另行逐项授权。
