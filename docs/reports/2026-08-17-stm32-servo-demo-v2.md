# STM32F407 PB10 数字舵机观察版 v2 验证记录

> 日期：2026-08-17
> 结论范围：主机纯逻辑测试、静态接入检查和 Keil 目标构建；不代表舵机供电、方向、机械行程、堵转电流或实机动作通过。

## 实现摘要

- 保留现有 X/Y/Z STEP、运动授权和安全输入行为。
- 新增 `EC_SERVO_TEST_BUILD=1` 和 PB10/TIM2_CH3 受控测试模块。
- 新增 10 秒单次授权、1300/1500/1700 us 白名单、2 秒自动停止、限位/急停中止和 STEP/舵机互斥。
- 新增 `SERVO STOP` 与 `STOP ALL`；串口溢出或超长命令会停止全部测试输出。
- 启动安全路径继续停止 TIM2_CH3，未增加自动 PWM 启动。

## 实际验证

### 主机测试

- 工具：WinLibs GCC，`-std=c11 -Wall -Wextra -Werror -pedantic`。
- 结果：`ALL FIRMWARE HOST TESTS PASSED`。
- 覆盖：未授权拒绝、安全输入拒绝、STEP忙拒绝、10秒过期、非法脉宽、三项白名单、2 秒超时、运行中限位、显式停止、串口命令映射与互斥。
- 诊断关闭构建也单独编译并运行成功。
- 为避免仓库内旧测试产物混淆，本轮测试由 GCC 直接重建到工作区外的临时验证目录后执行；仓库内旧 `tests/build` 不作为 v2 证据。

### Keil目标构建

- 工具：Keil ARMCC V5.06 update 7 build 960。
- 结果：`0 Error(s), 0 Warning(s)`。
- Program Size：Code=13556，RO-data=768，RW-data=68，ZI-data=2580。
- HEX：`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1-servo-demo-v2.hex`。
- SHA-256：`1D72C0069CE068DD930A251C61F5592A994DAA3FFA44F5DD169A5FD84D1AE8B0`。
- 旧的 `diankongv1-servo-demo.hex` 保留为 1400/1500/1600 us、500 ms 版本，便于回退；本轮实机测试只能选择带 `-v2` 的文件。

## 未验证与下一门禁

- 舵机角度版本、脉宽真实效果、供电峰值、堵转电流和机械安全端点仍未知。
- 用户描述的“升降并联动夹爪”尚未转换为自动动作；必须先无负载记录 1300/1500/1700 us 的实物效果。
- 12 V 不得直供舵机；实机首测需要独立 4.8--7.4 V 合适电源、公共地和可立即切断的动力开关。
