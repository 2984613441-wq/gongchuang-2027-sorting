# REVIEW-20260822-004 · Claude 回归审核：电控 P0/P2 整改（通过，静态层面）

> 审核方：Claude（独立只读；结论由用户于 2026-08-22 转交归档）
> 审核对象：2026-08-22 电控 P0/P2 整改批次
> 依据审核词：`docs/prompts/claude-review-20260822-ec-p0-p2-fixes-readonly-review-prompt.md`
> 关联实施记录：`REVIEW-20260822-003-codex-p0-p2-ec-fixes.md`

## 0. 总体裁决

- 电控固件 P0/P2 整改：**通过（静态层面）**
- 实机动作门禁：**不允许**（运行时正确性尚未经真实定时器中断验证；
  `STEP_RESULT=DONE` 实机复核未授权）

## 1. 发现项

### P0（无代码缺陷；整改正确）

- 事实/证据：`ec_board_stm32.c` 启动路径改为 `HAL_TIM_PWM_Start`（不带中断）
  + 启动前 `__HAL_TIM_CLEAR_FLAG(TIM_FLAG_UPDATE)` + 启动后
  `__HAL_TIM_ENABLE_IT(TIM_IT_UPDATE)`；停止路径补
  `__HAL_TIM_DISABLE_IT(TIM_IT_CC1)` + `DISABLE_IT(TIM_IT_UPDATE)`。
- 精确定位：启动约 `ec_board_stm32.c:157/164/171`，停止约 `:77/78`。
- 风险：无新增。步数递减现挂在 update 中断上且中断确实被使能；TIM8_CC
  连带风险消解（不再使用 `Start_IT` 的 CC 中断；NVIC 中 `TIM4_IRQn`、
  `TIM8_UP_TIM13_IRQn`、`TIM1_BRK_TIM9_IRQn` 三条 update 路径全通，
  `TIM8_CC_IRQn` 未使能正确）。
- 时序判断：clear→Start→ENABLE_IT 在微秒级间隙内计数器不可能回绕，无伪中断。
- 可验证整改：无。
- 复查证据：真实定时器中断下 `MOVE X DIR0 STEPS 100 HZ 100` 应报
  `STEP_RESULT=DONE`、`STEP_REMAIN=0`（未授权，未执行）。

### P1（无代码缺陷；文档澄清正确）

- 事实/证据：指令清单第 3 节改为“按动作类别检查抑制掩码”，明确单轴运动/舵机
  7 路、组合动作 9 路，并如实记录 START/MANUAL_RESET 语义缺口。
- 精确定位：`docs/design/2026-08-20-motion-command-list-v1.md` 第 3 节。
- 风险：无；保留 7/9 但消除措辞歧义，裁决合理。

### P2（无代码缺陷；文档整改正确）

- P2-1：`EC_STEP_MAX_STEPS` 在函数层（`ec_step_test.c:126`）与解析层
  （`ec_diag.c:193-195`）同时生效，无硬编码残留。
- P2-3/P2-4/P2-2：BARRIER 四模式同行为、TIM9 注释、极端参数约 27.8 h
  超时兜底，三处措辞准确。
- 测试有效性：新增用例覆盖 1,000,001 拒绝（函数层 + 解析层各一）与
  1,000,000 接受（`last_counted_steps == 1000000U`），非空转测试。

### P2（过程/测试缺口，非代码缺陷）

- 事实/证据：`tests/CMakeLists.txt` 仍不编译 `ec_board_stm32.c`，主机测试
  2/2 不验证 P0 中断接线本身；P0 正确性目前靠静态分析 + Keil 编译兜底。
- 精确定位：`电控/firmware/stm32f407_m144z/tests/CMakeLists.txt`。
- 风险：真实中断运行时行为未经验证；审核词一.5 已正确点出，无遗漏。
- 可验证整改：实机授权后复核 `STEP_RESULT=DONE`；或把板级接线纳入可测试层。
- 复查证据：上述任一路径完成后复审 P0。

## 2. 证据核对

- Keil 构建日志 `MDK-ARM/ec-p0-fix-20260822-build.log`：`0 Error(s), 0 Warning(s)`，
  且确实编译了 `ec_board_stm32.c`。
- 新 HEX SHA256：`1a565e56b11b2d564798d96d15295ad204820ea58a439af3833a4e83fa8d8196`，
  与审核词一致。

## 3. 已确认事实 / 推断 / 建议 / 未知 / 弱独立性限制

- 已确认事实：代码、文档、测试、Keil 日志与 SHA256 与审核词一致。
- 推断：P0 在真实定时器中断下应产生 `STEP_RESULT=DONE`（静态推断，非实机观测）。
- 建议：实机授权后先复核 `MOVE X DIR0 STEPS 100 HZ 100`；择机评估板级接线
  可测试性。
- 未知：真实中断时序、串口回显与 `STATUS` 时序。
- 弱独立性限制：主机测试未由 Claude 独立重跑，仅静态确认用例有效与证据文件
  存在；Keil/SHA256 已实测核对。

## 4. 通过的检查 / 未执行的检查 / 不能得出的结论

- 通过的检查：P0 修复接线、P2-1 一致性、P1 文档与代码一致性、P2-3/P2-4/P2-2
  文档、测试有效性、Keil 与 SHA256 证据。
- 未执行的检查：Claude 侧主机测试独立重跑、实机/串口/烧录/运动、真实定时器
  中断下的 `STEP_RESULT` 行为。
- 不能得出的结论：不能据此宣称固件已通过实机运动测试或计数运动功能已在硬件可用。

## 5. 最小整改清单与复审触发条件

- 最小整改清单：001 撞号已处理为 001a + 001（完整版）；本记录落 004。
- 复审触发条件：实机授权并复核 `STEP_RESULT=DONE` 后复审 P0；若主机测试增加
  板级接线覆盖，复审测试有效性；若掩码或文档基线变更，复审 P1。
