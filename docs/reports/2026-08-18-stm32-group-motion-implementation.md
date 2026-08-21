# STM32 X/Y + PB10 舵机组合动作实现报告

> 任务：`TASK-20260818-001`  
> 日期：2026-08-18  
> 阶段：审核前实现与主机侧验证  
> 边界：未进行烧录、上电、接线、波形或实机运动测试

## 实现结果

- 新增独立 `IDLE -> ARMED -> SETTLING -> RUNNING` GROUP 状态机。
- 新增精确命令：`GROUP ARM`、`GROUP START XDIR0|1 YDIR0|1 OPEN|CLOSE`、`GROUP STOP`。
- `OPEN` 固定为 `1000 us`，`CLOSE` 固定为 `1900 us`；不接受组合命令中的任意 PWM 值。
- 授权有效期 `10000 ms`，闭区间边界，START 一次性消费；执行最长 `2000 ms`。
- 九路输入中任一 `ACTIVE != 0` 都拒绝授权/启动，或在执行中立即停止。
- 启动顺序为：设置 X/Y 方向，禁用全部驱动，在同一函数内依次使能 X/Y，等待 `20 ms`，然后在同一次 poll 中依次启动 X STEP、Y STEP 和 PB10 PWM。
- 任一部分启动失败，都调用统一停止端口：停 X/Y STEP、停 PB10 PWM、禁用步进驱动。
- GROUP 与既有 STEP/MOTION/SERVO 授权和运行命令双向互斥；`STOP ALL`、`LINE_TOO_LONG`、`RX_OVERFLOW` 同时停止 GROUP。
- `STATUS` 末尾追加 `GROUP_TEST`、`GROUP_ARMED`、`GROUP_ACTIVE`、`GROUP_XDIR`、`GROUP_YDIR`、`GROUP_SERVO_US`；`HELP` 已同步。
- 新增宏 `EC_GROUP_TEST_BUILD=1`，主机测试和 Keil 目标都已启用；禁用构建返回 `ERR GROUP_TEST_DISABLED`。

## 同步性边界

GROUP 是“同一轮询周期内的软件近同时启动”。X、Y 和 PB10 通过软件依次调用不同定时器，因此不是硬件相位同步，也不应宣称为同一边沿启动。

## 主机侧验证

为避免 MinGW 对中文路径的处理问题，使用临时驱动器映射运行同一工作区中的 CMake 测试。实际编译选项为：

```text
-std=c11 -Wall -Wextra -Werror -pedantic
```

结果：

```text
ec_firmware_host_tests   Passed
ec_diag_disabled_tests  Passed
100% tests passed, 0 tests failed out of 2
```

覆盖了授权成功、10000/10001 ms 边界与过期、一次性消费、八种精确 START 命令、四种 X/Y 方向、OPEN/CLOSE、1999/2000 ms 边界、完整九路安全输入、双向忙状态拒绝、部分启动失败的全停、GROUP STOP、STOP ALL、超长行、RX 队列溢出、禁用构建和既有回归。

`git diff --check` 通过。

## Keil 构建

- ARMCC：V5.06 update 7 build 960。
- 结果：`0 Error(s), 0 Warning(s)`。
- Program Size：`Code=14580, RO-data=1468, RW-data=84, ZI-data=2580`。
- GROUP 源文件和 `EC_GROUP_TEST_BUILD=1` 在 Keil 工程中都只出现一次。
- 日志：`MDK-ARM/group-motion-build.log`。
- HEX：`MDK-ARM/diankongv1-group-motion-v1.hex`。
- SHA-256：`FBE38714286EDB37CAD7DECF06C54EA176F3B7DA73208C27338899389C091A3C`。

## 剩余风险与后续门禁

1. 当前证据只能证明主机逻辑和 Keil 目标可构建，不能证明串口、定时器波形、驱动器、电机或舵机实机通过。
2. X/Y 真实机械方向尚未冻结，实机前必须由用户选定 XDIR/YDIR。
3. 未关闭两项 P0 前禁止多执行器同时上电：所有非隔离信号可靠共地；驱动侧 ENABLE 默认禁能、STEP 默认不活动的复位/烧录高阻窗口保护。
4. 同时启动的电源压降、峰值电流、机械干涉和真实启动时差仍属未验证。
5. `STOP ALL` 仅是软件停止，不是物理急停或断电手段。
