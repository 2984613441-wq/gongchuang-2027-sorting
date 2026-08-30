# STM32F407 载板 GPIO 与定时器分配（M144Z-M4 Mini Board 版）

> 状态：候选分配，未冻结。主控板为 M144Z-M4 Mini Board（STM32F407ZGT6），排针针序来自用户手工抄录（`docs/design/min-system-board-pinout.md`）；JP_L/JP_R 方向已按用户确认，冻结前仍需独立审核与 1:1 打印核对。
> 本文件对应实施计划 Task 2；排针编号约定：JP_L=左侧排针（2×25），JP_R=右侧排针（2×25），编号从靠近 TF 卡端开始，外列为奇数针号、内列为偶数针号。
> 约定：所有信号为 3.3 V 逻辑；板外输入经过载板调理/限流后接入；上电默认所有运动输出为安全态。
> “板载冲突”列仅为探索者 V3 官方资料的参考冲突，用于提示同芯片体系常见板载外设占用；M144Z-M4 真实板载路由仍待其官方资料或实物连续性测试确认，不得把“无”或“可复用”当作冻结事实。

## 1 资源覆盖清单

- STEP_X/Y/Z（3）
- DIR_X/Y/Z（3）
- ENABLE_X/Y/Z（3）
- BARRIER_PWM_1..4（4）
- GRIP_PWM（1）
- WRIST_PWM（1，默认 DNP）
- LIGHT_EN（1）
- X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN（6）
- ESTOP_FB、START_SIG、MANUAL_RESET_SIG（3）
- UART_MAIN_TX/UART_MAIN_RX（2，USART2）
- UART_BACKUP_TX/UART_BACKUP_RX（2，USART3）
- 驱动反馈 X/Y/Z READY/FAULT（预留，见第 3 节）

## 2 候选映射表

### 2.1 步进轴输出（9 路）

| 功能 | 定时器/外设 | GPIO | 排针 | 上电默认 | 探索者 V3 参考冲突 / M144Z-M4 待验 | EDA 网名 |
|---|---|---|---|---|---|---|
| STEP_X | TIM8_CH1 | PC6 | JP_R-1 | 停止 | OLED/CAMERA D0（不插摄像头） | STEP_X |
| DIR_X | GPIO 输出 | PA7 | JP_L-38 | 低 | 以太网 YT8512C（探索者 V3 参考；M144Z-M4 待验） | DIR_X |
| ENABLE_X | GPIO 输出 | PA5 | JP_L-39 | 禁能（安全态） | 无（不插 OLED/摄像头） | ENABLE_X |
| STEP_Y | TIM4_CH1 | PB6 | JP_R-19 | 停止 | 无 | STEP_Y |
| DIR_Y | GPIO 输出 | PC7 | JP_R-2 | 低 | OLED/CAMERA D1（不插） | DIR_Y |
| ENABLE_Y | GPIO 输出 | PD7 | JP_R-4 | 禁能（安全态） | OLED/CAMERA SCL（不插） | ENABLE_Y |
| STEP_Z | TIM9_CH1 | PE5 | JP_R-38 | 停止 | OLED/CAMERA D6（不插） | STEP_Z |
| DIR_Z | GPIO 输出 | PE6 | JP_R-37 | 低 | OLED/CAMERA D7（不插） | DIR_Z |
| ENABLE_Z | GPIO 输出 | PG15 | JP_R-5 | 禁能（安全态） | OLED/CAMERA RESET（不插） | ENABLE_Z |

选择依据：三轴 STEP 使用互不相同的硬件定时器 TIM8/TIM4/TIM9；DIR/ENABLE 全部取自主排针上可用的普通 GPIO，并避开 USB/TF/SWD/按键占用脚。

### 2.2 六路 PWM（4 挡板 + 夹爪 + 腕部预留）

| 功能 | 定时器/外设 | GPIO | 排针 | 上电默认 | 探索者 V3 参考冲突 / M144Z-M4 待验 | EDA 网名 |
|---|---|---|---|---|---|---|
| BARRIER_PWM_1 | TIM3_CH3 | PB0 | JP_L-35 | 停 PWM（安全态） | TFTLCD 触摸 SCK（不插 LCD） | BARRIER_PWM_1 |
| BARRIER_PWM_2 | TIM3_CH4 | PB1 | JP_L-34 | 停 PWM（安全态） | TFTLCD 触摸 PEN（不插 LCD） | BARRIER_PWM_2 |
| BARRIER_PWM_3 | TIM10_CH1 | PF6 | JP_L-29 | 停 PWM（安全态） | 无 | BARRIER_PWM_3 |
| BARRIER_PWM_4 | TIM11_CH1 | PF7 | JP_L-30 | 停 PWM（安全态） | 光敏传感器（不使用） | BARRIER_PWM_4 |
| GRIP_PWM | TIM2_CH3 | PB10 | JP_R-23 | 停 PWM（安全态） | USART3_TX（改用 USART2） | GRIP_PWM |
| WRIST_PWM | TIM2_CH4 | PB11 | JP_R-22 | DNP/固件禁用 | USART3_RX（改用 USART2） | WRIST_PWM |
| LIGHT_EN | GPIO 输出 | PC0 | JP_R-36 | 关 | 无 | LIGHT_EN |

### 2.3 输入（9 路）

| 功能 | 外设 | GPIO | 排针 | 探索者 V3 参考冲突 / M144Z-M4 待验 | EDA 网名 |
|---|---|---|---|---|---|
| X_HOME | 输入 | PG7 | JP_R-14 | 无线接口（不使用） | X_HOME |
| X_END | 输入 | PG6 | JP_R-13 | 无线接口（不使用） | X_END |
| Y_HOME | 输入 | PG9 | JP_R-30 | 单总线（不使用） | Y_HOME |
| Y_END | 输入 | PD5 | JP_R-29 | 无 | Y_END |
| Z_UP | 输入 | PF11 | JP_L-32 | TFTLCD 触摸 MOSI（不插 LCD） | Z_UP |
| Z_DOWN | 输入 | PG14 | JP_R-44 | 以太网 YT8512C（探索者 V3 参考；M144Z-M4 待验） | Z_DOWN |
| ESTOP_FB | 输入 | PG13 | JP_R-43 | 以太网 YT8512C（探索者 V3 参考；M144Z-M4 待验） | ESTOP_FB |
| START_SIG | 输入 | PA4 | JP_L-40 | OLED/CAMERA HREF（不插） | START_SIG |
| MANUAL_RESET_SIG | 输入 | PF8 | JP_L-31 | 蜂鸣器（不装蜂鸣器时可用；若板载蜂鸣器存在需裁决） | MANUAL_RESET_SIG |

### 2.4 通信与调试

| 功能 | 外设 | GPIO | 排针 | 说明 / 探索者 V3 参考冲突 | EDA 网名 |
|---|---|---|---|---|---|
| UART_MAIN_TX | USART2_TX | PA2 | JP_L-44 | 正式树莓派通信；115200 8N1 实测通过 | UART_MAIN_TX |
| UART_MAIN_RX | USART2_RX | PA3 | JP_L-41 | 正式树莓派通信；115200 8N1 回显通过 | UART_MAIN_RX |
| UART_BACKUP_TX | USART3_TX | PD8 | JP_L-10 | 备用接口；115200 8N1 实测通过 | UART_BACKUP_TX |
| UART_BACKUP_RX | USART3_RX | PD9 | JP_L-9 | 备用接口；115200 8N1 回显通过 | UART_BACKUP_RX |
| SWD | SWDIO/SWCLK | PA13/PA14 | SWD 排针 | 仅用于烧录调试，载板不占用 | 保留 |
| TF/SDIO | SDIO | PC8(JP_R-11)、PC9(JP_R-12)、PC10(JP_R-6)、PC11(JP_R-7)、PC12(JP_R-9)、PD2(JP_R-8) | 见左列 | 板载 TF 卡，使用 TF 时不可占用 | 保留 |

## 3 预留与未分配项

- 驱动反馈（可选）：DRV_X/Y/Z_FAULT、DRV_X/Y/Z_READY 预留候选：PD3/PD4（JP_R-27/JP_R-28）、PG10（JP_R-31）、PE1/PE0（JP_R-34/JP_R-33）、PC1（JP_R-35）等；默认 DNP，不占核心信号。
- 正式通信采用 USART2（PA2/PA3），备用采用 USART3（PD8/PD9）；两套接口独立引出，不并接 TX/RX。
- USART1（PA9/PA10）保留给板载 USB_UART，不作为第三套载板串口。
- 六储蓄箱无电控网络；腕部旋转 WRIST_PWM 默认 DNP。

## 4 定时器与脉冲方案

### 4.1 三轴 STEP

- 使用 TIM8_CH1（PC6）、TIM4_CH1（PB6）、TIM9_CH1（PE5）输出脉冲；三轴使用不同定时器。
- 设计目标：单轴最大连续步进脉冲 20 kHz（余量高于当前运动工况预期）；TIM8/TIM4/TIM9 时钟按 STM32F407 时钟树核算（APB2 定时器 168 MHz 或 APB1 定时器 84 MHz，最终以 CubeMX 配置为准）。
- 计算示例（84 MHz）：PSC=0 时 20 kHz 对应 ARR=4199，CCR=ARR/2；频率变化通过更新 ARR/CCR 完成，无每脉冲中断。
- 若采用软件脉冲方案必须另行给出最大步频、抖动与三轴协调证明。

### 4.2 舵机类 PWM（四挡板/夹爪/腕部）

- 帧周期统一 50 Hz（20 ms）；脉冲宽度范围按最终舵机资料冻结（DS3120MG 标为候选范围，禁引用为已冻结值）。
- TIM2（GRIP/WRIST）、TIM3（BARRIER1/2）、TIM10/TIM11（BARRIER3/4）在同一控制节拍内更新 CCR；跨定时器同步精度按台架实测验收。
- 上电默认：所有 PWM 通道输出安全态，不允许驱动挡板/夹爪动作。

## 5 冻结前必须补齐

- 排针方向：JP_L 已确认（PB15 外列、靠近 TF 卡端）；JP_R 已按用户确认（PC6 外列、PC7 内列、靠近 TF 卡端），仍建议 1:1 打印核对一次。
- 板载冲突列仅按探索者 V3 资料作参考，M144Z-M4 的真实板载路由需官方资料或实物连续性测试确认；尤其 PA7、PG13、PG14 在探索者 V3 参考矩阵中连接以太网 YT8512C，不能标为“无冲突”。
- UREF、白色 4P 插座、KEY0/KEY-UP 对应 GPIO 确认。
- 3.3V/5V/GND 排针可供给载板的最大电流确认（板载 LDO 能力有限，逻辑大电流仍应由外部模块提供）。
- 板载 TF 卡使用决策：若保留 TF，PC8-PC12/PD2 不可占用（本表已避开）。
- 挡板舵机型号与 PWM 参数、DS3120MG 实测、限位开关型式、急停反馈电气形式。
- 载板板框与安装孔实测。

## 6 静态校验

执行：
- `rg -n "STEP_X|STEP_Y|STEP_Z|BARRIER_PWM_1|BARRIER_PWM_4|GRIP_PWM|WRIST_PWM|X_HOME|Z_DOWN|ESTOP_FB|SWD|TF" docs/design/stm32f407-pin-timer-allocation.md`
- `rg -n "JP_L|JP_R" docs/design/stm32f407-pin-timer-allocation.md`

要求：每个 GPIO 只分配一次；所有排针引用与 `min-system-board-pinout.md` 一致；未冻结项保持未确认。



