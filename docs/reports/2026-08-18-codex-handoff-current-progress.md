# 2026-08-18 主控与视觉当前进度 · Codex 续接交接单

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

> 用途：后续只使用 Codex 时，从本文件继续，不依赖已消失的对话。  
> 当前结论：主控单执行器已产生实机动作；三执行器 GROUP 代码、主机测试和 Keil 构建通过，但尚未烧录或进行实体组合测试。视觉在另一对话处理，本文件只记录已知接口边界。

## 1. 一句话状态

STM32 已完成 X/Y 步进、PB10 舵机和 X/Y+舵机组合动作测试固件；最新 GROUP HEX 已生成并审核，但由于未授权运动的 P0 硬件门禁尚未形成完整实测闭环，现在不能把“构建通过”写成“三轴同步实机通过”。

## 2. 证据分类

### 用户现场已观察

- X 轴电机能够转动。
- Y 轴电机能够转动。
- PB10 舵机能够动作。
- 舵机 `1000 us` 是目前最大且合适的开口。
- 舵机 `1900 us` 是闭合位置。
- PWM 输出停止后，夹爪能保持位置。
- 九路输入曾得到 `RAW=01FF STABLE=01FF ACTIVE=0000`，并观察过输入位变化。

### 代码与构建已验证

- X/Y 单轴测试、舵机测试、GROUP 组合状态机均已接入 STM32 工程。
- 最新严格主机测试输出：`ALL FIRMWARE HOST TESTS PASSED`。
- GROUP 禁用构建测试退出码：`0`。
- Keil ARMCC：`0 Error(s), 0 Warning(s)`。
- GROUP 源文件和 `EC_GROUP_TEST_BUILD=1` 在 Keil 工程中各接入一次。

### 尚未验证

- GROUP 固件烧录后的串口命令链。
- X/Y/PB10 真实组合运动。
- X/Y 的 DIR0/DIR1 最终机械方向。
- 三执行器同时启动的电源压降、峰值电流、机械干涉和真实启动时间差。
- MCU 上电、复位、下载期间驱动侧 ENABLE/STEP 的硬件失效安全。
- 视觉到主控的真实串口闭环。

## 3. 当前最高风险 P0

必须同时关闭两个独立问题：

1. **公共信号地**：STM32 GND、X/Y 驱动逻辑 GND、舵机信号参考地必须可靠共地。动力电源可以分开，但控制信号必须有共同参考。
2. **复位高阻窗口**：MCU 复位、上电和下载时 GPIO 可能为高阻；驱动侧必须验证 ENABLE 默认禁能、STEP 默认不活动，并根据实际驱动板确认 SLEEP/RESET 默认态。

P0 未关闭前：禁止三执行器同时上电、禁止视觉自动触发、禁止无人值守运行。`STOP ALL` 只是软件停止，不是物理急停或动力断电。

## 4. 引脚冻结

| 对象 | 功能 | STM32引脚/外设 | 备注 |
|---|---|---|---|
| X轴 | STEP | PC6 / TIM8_CH1 | 10 Hz测试脉冲 |
| X轴 | DIR | PA7 | DIR0/1真实方向待记录 |
| X轴 | ENABLE | PA5 | 低有效 |
| Y轴 | STEP | PB6 / TIM4_CH1 | 10 Hz测试脉冲 |
| Y轴 | DIR | PC7 | DIR0/1真实方向待记录 |
| Y轴 | ENABLE | PD7 | 低有效 |
| 夹爪舵机 | PWM | PB10 / TIM2_CH3 | 50 Hz；OPEN=1000 us，CLOSE=1900 us |
| 串口3 | TX/RX | PD8 / PD9 | 115200、8N1 |

旧 Z 步进通道仍是 PE5/TIM9_CH1、PE6 DIR、PG15 ENABLE；当前 GROUP 中的“Z”指 PB10 舵机夹爪，不使用旧 Z 步进。

## 5. 九路安全输入

全部为低有效，外部 10 kΩ 上拉到 3.3 V；正常未触发目标为 `ACTIVE=0000`。

| 位 | 引脚 | 名称 |
|---:|---|---|
| 0001 | PG7 | X_HOME |
| 0002 | PG6 | X_END |
| 0004 | PG9 | Y_HOME |
| 0008 | PD5 | Y_END |
| 0010 | PF11 | Z_UP |
| 0020 | PG14 | Z_DOWN |
| 0040 | PG13 | ESTOP_FB |
| 0080 | PA4 | START_SIG |
| 0100 | PF8 | MANUAL_RESET_SIG |

GROUP 使用更严格规则：九路中任一路 `ACTIVE != 0`，授权、启动或运行都会被拒绝/停止。

## 6. 最新固件与工程位置

- STM32工程：`电控/firmware/stm32f407_m144z/`
- Keil工程：`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1.0.uvprojx`
- 最新GROUP HEX：`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1-group-motion-v1.hex`
- SHA-256：`FBE38714286EDB37CAD7DECF06C54EA176F3B7DA73208C27338899389C091A3C`
- Keil日志：`电控/firmware/stm32f407_m144z/MDK-ARM/group-motion-build.log`
- GROUP核心：`App/Inc/ec_group_test.h`、`App/Src/ec_group_test.c`
- 实现报告：`docs/reports/2026-08-18-stm32-group-motion-implementation.md`
- 任务分析：`.claude/tasks/TASK-20260818-001-xy-servo-group-motion.md`

当前改动尚未形成 Git 提交；工作树中还有用户的视觉、文档、旧舵机和集成桥接等其他改动，提交时必须精确选择本任务文件，不得一把提交整个工作树。

## 7. GROUP 行为

状态机：

```text
IDLE -> ARMED(10秒) -> SETTLING(20ms) -> RUNNING(最多2秒) -> IDLE
```

启动顺序：

1. 精确校验方向和 OPEN/CLOSE。
2. 消费一次授权。
3. 设置 X/Y 方向。
4. 禁用全部步进驱动，然后在同一函数内依次启用 X/Y。
5. 等待20 ms。
6. 在同一次主循环轮询中依次启动 X STEP、Y STEP、PB10 PWM。
7. 任一步失败立即停止 X/Y STEP、停止舵机 PWM、禁用驱动，不自动重试。

这是软件近同时，不是三个定时器的硬件同边沿同步。

## 8. 串口命令

### 查询与停止

```text
INPUTS
STATUS
GROUP STOP
STOP ALL
```

### 组合动作

```text
GROUP ARM
GROUP START XDIR0 YDIR0 OPEN
```

- 每次 START 前必须重新 `GROUP ARM`。
- 授权有效10秒且一次性消费。
- `OPEN=1000 us`，`CLOSE=1900 us`。
- X/Y方向可分别换成 `DIR1`，共8个精确组合命令。

常用HEX：

```text
GROUP ARM
47 52 4F 55 50 20 41 52 4D 0D 0A

GROUP START XDIR0 YDIR0 OPEN
47 52 4F 55 50 20 53 54 41 52 54 20 58 44 49 52 30 20 59 44 49 52 30 20 4F 50 45 4E 0D 0A

GROUP START XDIR0 YDIR0 CLOSE
47 52 4F 55 50 20 53 54 41 52 54 20 58 44 49 52 30 20 59 44 49 52 30 20 43 4C 4F 53 45 0D 0A

STOP ALL
53 54 4F 50 20 41 4C 4C 0D 0A
```

## 9. 后续严格顺序

### 阶段A：P0硬件验收

1. 断电检查所有公共地。
2. 核对真实驱动板型号、VDD、ENABLE/STEP/SLEEP/RESET接法。
3. 验证上电、复位、下载、串口断开、`STOP ALL`、动力扰动时 X/Y 都不会自行运动。
4. 记录是否出现重复 `BOOT SAFE`、乱码或复位。

### 阶段B：单轴方向冻结

1. 只给一轴动力。
2. 分别测试 DIR0、DIR1，记录真实机械方向。
3. Y轴同样执行。
4. 不用猜测的方向进入 GROUP 命令。

### 阶段C：分级组合验证

1. 先 X+Y，不接舵机动力。
2. 再单独舵机1000↔1900三轮，不接X/Y动力。
3. 最后才允许 X+Y+舵机组合；保留物理断电手段。
4. 每次先查 `INPUTS`，必须看到 `ACTIVE=0000`；再授权、启动。
5. 任一抖动、异响、掉压、复位、乱码、异常发热或机械干涉立即物理断电。

### 阶段D：视觉联动

只有A到C通过后，视觉程序才允许通过电脑桥接触发固定动作；视觉只输出稳定类别，不直接输出PWM或自由运动参数，不自动重试运动。

## 10. 视觉线已知状态

- 视觉工作由独立对话负责，本对话不得覆盖其文件。
- 旧 YOLO 工程曾位于 `D:/AAAdesktop1/shijue/ultralytics-8.3.163`。
- 可用解释器曾确认为 `D:/Anaconda/envs/yolo/python.exe`，RTX 5070 Ti CUDA可用。
- 真正比赛数据集的路径、YOLO格式和类别顺序仍需视觉对话确认；COCO128和旧 `atri` 数据不能当作比赛模型。
- 主控联动边界：视觉输出稳定类别；电脑桥接把类别映射为固定主控动作；STM32仍是唯一底层运动与安全控制器。

## 11. 临时文件与提交注意

- `tests/build-group*` 和 `tests/build-strict` 是本轮产生的可再生临时构建目录，尚未删除。
- 删除这些目录需要用户对具体删除动作明确授权。
- 不要删除原有 `tests/build`。
- Git提交前先只读检查差异，只暂存本任务明确文件；不要误提交数据集、ZIP、DOCX或其他对话正在修改的内容。

## 12. 给下一个Codex对话的直接提示词

```text
读取 docs/reports/2026-08-18-codex-handoff-current-progress.md、
.claude/tasks/TASK-20260818-001-xy-servo-group-motion.md、
docs/reports/2026-08-18-stm32-group-motion-implementation.md 和 CLAUDE.md。
先只读核对当前Git差异和P0门禁，不要假定三执行器实机已经通过。
当前最新HEX是 diankongv1-group-motion-v1.hex，SHA256为
FBE38714286EDB37CAD7DECF06C54EA176F3B7DA73208C27338899389C091A3C。
下一步先协助完成P0硬件验收和X/Y方向冻结；没有我的明确授权不要执行烧录、上电、删除或Git提交。
```
