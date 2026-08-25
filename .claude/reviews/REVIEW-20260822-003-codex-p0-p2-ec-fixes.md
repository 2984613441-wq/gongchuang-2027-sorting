# REVIEW-20260822-003 · Codex 实施记录：P0 计数中断修复与 P2 整改

> 记录方：Codex（实施与验证记录，非独立审核）
> 日期：2026-08-22
> 依据：`REVIEW-20260822-001-claude-ec-motion-test-firmware.md`、
> `REVIEW-20260822-002-codex-ec-motion-test-reconciliation.md`
> 用户裁决：P0 按修法 A；P1 保留 7/9；P2-1/P2-3/P2-4 同批实施，P2-2 记录边界

## 1. 变更

- `App/Src/ec_board_stm32.c`：
  - `ec_step_port_start_counted` 改用 `HAL_TIM_PWM_Start` + 手动
    `__HAL_TIM_ENABLE_IT(TIM_IT_UPDATE)`；启动前清除 `TIM_FLAG_UPDATE`，
    防止残留更新事件在使能中断后立即触发。
  - `stop_counted_timer` 补 `__HAL_TIM_DISABLE_IT(TIM_IT_CC1)`，避免历史
    `PWM_Start_IT` 残留的 CC1 中断在后续非 IT PWM 启动时产生多余中断。
  - 注释补 TIM9（P2-4）。
- `App/Inc/ec_step_test.h`：新增 `EC_STEP_MAX_STEPS = 1,000,000`。
- `App/Src/ec_step_test.c`：`ec_motion_test_start_steps` 增加 steps 上限校验（P2-1）。
- `App/Src/ec_diag.c`：诊断解析层复用 `EC_STEP_MAX_STEPS`。
- `tests/test_step_test.c`、`tests/test_diag.c`：新增 1,000,001 拒绝与
  1,000,000 接受用例。
- `docs/design/2026-08-20-motion-command-list-v1.md`：
  - 第 3 节按动作类别限定抑制掩码措辞，注明 START/MANUAL_RESET 当前仅参与
    组合动作抑制（P1 澄清）。
  - 第 5 节注明 BARRIER ALL/COLLECT/AVOID 当前固件行为相同（P2-3）。
  - 第 7 节记录极端参数超时边界约 27.8 h（P2-2）。

## 2. 验证

- 主机测试：在 `%TEMP%` 纯英文目录全新 MinGW 构建，`ec_firmware_host_tests`
  与 `ec_diag_disabled_tests` 2/2 通过。
- Keil：`D:\Keil\UV4\UV4.exe -b diankongv1.0.uvprojx -j0 -o
  ec-p0-fix-20260822-build.log`；`0 Error(s), 0 Warning(s)`；日志见
  `电控/firmware/stm32f407_m144z/MDK-ARM/ec-p0-fix-20260822-build.log`。
- 新 HEX：`MDK-ARM/diankongv1.0/diankongv1.hex`，SHA256
  `1A565E56B11B2D564798D96D15295AD204820EA58A439AF3833A4E83FA8D8196`。
- 未执行：实机、串口、烧录、运动。`STEP_RESULT=DONE` 实机复核仍需用户逐项授权。

## 3. 剩余问题

- P0 的功能性结论仍需真实定时器中断下复核：`MOVE X DIR0 STEPS 100 HZ 100`
  应报 `STEP_RESULT=DONE`、`STEP_REMAIN=0`。
- P1 已按裁决保留 7/9，未改掩码；START/MANUAL_RESET 生产语义待定义。
- 仓库卫生（3.42 GiB pack、3 个 tmp 垃圾对象约 224 MB）、`fd369a28` 夹带
  修正、push 均未执行，需用户授权。
- 桥接代码与提交/仓库卫生两份 Claude 审核结论尚未归档。
