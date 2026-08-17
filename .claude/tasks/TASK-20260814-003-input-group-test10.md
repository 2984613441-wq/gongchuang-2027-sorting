# TASK-20260814-003: test10 剩余安全输入分组测试

## 范围

- 输入：`PG6/X_END`、`PD5/Y_END`、`PG13/ESTOP_FB`、`PA4/START_SIG`、`PF8/MANUAL_RESET_SIG`。
- 通信观察：`PD8/PD9 = USART3`，115200 8N1。
- 不修改已确认的 STEP、DIR、ENABLE 分配，不涉及电机、驱动器或 PCB 结论。

## 实施

`test10/Core/Src/main.c` 每 500 ms 读取五路上拉输入并输出一行状态。输入悬空应为 `1`，接 STM32 GND 应为 `0`。

## 状态

代码已写入并完成静态复核；待烧录和用户实测。
