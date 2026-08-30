# 载板原理图接线施工单（自己画板用）

> 适用范围：M144Z-M4 Mini Board（STM32F407ZGT6）自制载板。
> 状态：候选，未冻结。排针方向按用户确认：JP_L 第1行 PB15/PF12 靠 TF 卡端、PB15 外列；JP_R 第1行 PC6/PC7 靠 TF 卡端、PC7 内列（用户确认），仍建议 1:1 打印核对。
> 网名规范：本表网名直接写到立创 EDA/KiCad 原理图里；全部为 3.3V 逻辑，5V 只出现在动力/舵机支路。
> 规则：A4988 与对应板外驱动接口二选一；急停只切危险动力，不断逻辑；WRIST_PWM 默认 DNP。

## 1 载板上要放的接口

| 位号 | 器件 | 说明 |
|---|---|---|
| JP_L_SOCKET | 双排 2×25 排母 | 插 M144Z-M4 左侧排针，针序照抄板子（PB15 靠外、靠 TF 端） |
| JP_R_SOCKET | 双排 2×25 排母 | 插 M144Z-M4 右侧排针，已确认（PC6 外列、PC7 内列、靠 TF 端），1:1 核对建议保留 |
| U_DRV_X_SOCKET | A4988 模块 16 针插座 | X 轴候选，默认 DNP，验证后装 |
| U_DRV_Y_SOCKET | A4988 模块 16 针插座 | Y 轴候选，默认 DNP，验证后装 |
| J_X_MOTOR | 4 针端子 | X 电机 1A/1B/2A/2B |
| J_Y_MOTOR | 4 针端子 | Y 电机 1A/1B/2A/2B |
| J_DRV_X_CTRL | 4-6 针排针（DNP） | X 备用板外驱动：STEP/DIR/ENABLE/GND_LOGIC + 可选反馈 |
| J_DRV_Y_CTRL | 4-6 针排针（DNP） | Y 备用板外驱动：STEP/DIR/ENABLE/GND_LOGIC + 可选反馈 |
| J_DRV_Z_CTRL | 4-6 针排针 | Z 板外驱动：STEP_Z/DIR_Z/ENABLE_Z/GND_LOGIC + 可选反馈 |
| J_BARRIER_CTRL_1..4 | 每路 2-3 针 | 挡板舵机：PWM + GND_LOGIC |
| J_GRIPPER_CTRL | 2-3 针 | 夹爪舵机：GRIP_PWM + GND_LOGIC |
| J_WRIST_CTRL | 2-3 针 | 腕部预留：WRIST_PWM + GND_LOGIC，默认不装 |
| J_LIGHT | 2 针 | 补光：LIGHT_EN + GND_LOGIC |
| J_X_HOME / J_X_END / J_Y_HOME / J_Y_END / J_Z_UP / J_Z_DOWN | 各 2-3 针 | 限位开关输入（常闭优先），需调理后进 GPIO |
| J_ESTOP_FB | 2 针 | 急停辅助触点反馈，只读信号 |
| J_START / J_MANUAL_RESET | 各 2 针 | 启动 / 人工复位输入 |
| J_UART_MAIN | 3-4 针 | 正式 USART2：PA2_TX/PA3_RX/GND_LOGIC |
| J_UART_BACKUP | 3-4 针 | 备用 USART3：PD8_TX/PD9_RX/GND_LOGIC；与主串口独立 |
| TP_* | 测试点 | 每路 STEP/DIR/ENABLE/PWM/LIGHT_EN、主备 UART 和关键逻辑电源留测试点 |

## 2 信号接线表（照抄）

### 2.1 X 轴

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| STEP_X | JP_R 第1行外列 = PC6 | U_DRV_X_SOCKET.STEP；并联 J_DRV_X_CTRL.STEP（DNP） |
| DIR_X | JP_L 第19行内列 = PA7 | U_DRV_X_SOCKET.DIR；并联 J_DRV_X_CTRL.DIR |
| ENABLE_X | JP_L 第20行外列 = PA5 | U_DRV_X_SOCKET.EN（低有效）；并联 J_DRV_X_CTRL.ENABLE |
| X_MOTOR_1A/1B/2A/2B | — | U_DRV_X_SOCKET.1A/1B/2A/2B → J_X_MOTOR（线序以电机资料为准） |

### 2.2 Y 轴

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| STEP_Y | JP_R 第10行外列 = PB6 | U_DRV_Y_SOCKET.STEP；并联 J_DRV_Y_CTRL.STEP（DNP） |
| DIR_Y | JP_R 第1行内列 = PC7 | U_DRV_Y_SOCKET.DIR；并联 J_DRV_Y_CTRL.DIR |
| ENABLE_Y | JP_R 第2行内列 = PD7 | U_DRV_Y_SOCKET.EN（低有效）；并联 J_DRV_Y_CTRL.ENABLE |
| Y_MOTOR_1A/1B/2A/2B | — | U_DRV_Y_SOCKET.1A/1B/2A/2B → J_Y_MOTOR |

### 2.3 Z 轴（板外驱动）

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| STEP_Z | JP_R 第19行内列 = PE5 | J_DRV_Z_CTRL.STEP |
| DIR_Z | JP_R 第19行外列 = PE6 | J_DRV_Z_CTRL.DIR |
| ENABLE_Z | JP_R 第3行外列 = PG15 | J_DRV_Z_CTRL.ENABLE |
| GND_LOGIC | 公共地 | J_DRV_Z_CTRL.GND |

### 2.4 舵机 PWM / 补光

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| BARRIER_PWM_1 | JP_L 第18行外列 = PB0 | J_BARRIER_CTRL_1.PWM |
| BARRIER_PWM_2 | JP_L 第17行内列 = PB1 | J_BARRIER_CTRL_2.PWM |
| BARRIER_PWM_3 | JP_L 第15行外列 = PF6 | J_BARRIER_CTRL_3.PWM |
| BARRIER_PWM_4 | JP_L 第15行内列 = PF7 | J_BARRIER_CTRL_4.PWM |
| GRIP_PWM | JP_R 第12行外列 = PB10 | J_GRIPPER_CTRL.PWM |
| WRIST_PWM | JP_R 第11行内列 = PB11 | J_WRIST_CTRL.PWM（DNP） |
| LIGHT_EN | JP_R 第18行内列 = PC0 | J_LIGHT |

### 2.5 输入

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| X_HOME | JP_R 第7行内列 = PG7 | J_X_HOME（经上拉+RC+保护） |
| X_END | JP_R 第7行外列 = PG6 | J_X_END |
| Y_HOME | JP_R 第15行内列 = PG9 | J_Y_HOME |
| Y_END | JP_R 第15行外列 = PD5 | J_Y_END |
| Z_UP | JP_L 第16行内列 = PF11 | J_Z_UP |
| Z_DOWN | JP_R 第22行内列 = PG14 | J_Z_DOWN |
| ESTOP_FB | JP_R 第22行外列 = PG13 | J_ESTOP_FB |
| START_SIG | JP_L 第20行内列 = PA4 | J_START |
| MANUAL_RESET_SIG | JP_L 第16行外列 = PF8 | J_MANUAL_RESET |

### 2.6 通信

| EDA 网名 | 来自 Mini Board | 接到 |
|---|---|---|
| UART_MAIN_TX | JP_L 第22行内列 = PA2（USART2_TX） | J_UART_MAIN.TX（接树莓派 RX） |
| UART_MAIN_RX | JP_L 第21行外列 = PA3（USART2_RX） | J_UART_MAIN.RX（接树莓派 TX） |
| UART_BACKUP_TX | JP_L 第5行内列 = PD8（USART3_TX） | J_UART_BACKUP.TX（接对端 RX） |
| UART_BACKUP_RX | JP_L 第5行外列 = PD9（USART3_RX） | J_UART_BACKUP.RX（接对端 TX） |
| GND_LOGIC | 公共地 | 两个 UART 接口分别带 GND；主备 TX/RX 不并接 |

## 3 电源网络（5V 主供电，3.3V 备选，互斥）

| 网名 | 用途 | 说明 |
|---|---|---|
| VIN_RAW | 外部总电源输入 | 载板只放入口端子/保险位，不集成适配器 |
| VMOT_ESTOP | X/Y A4988 动力 | 外部经急停/保护后接入；U_DRV_X/Y_SOCKET.VMOT |
| V_SERVO_5V | 挡板/夹爪舵机动力 | 直接到舵机，不经载板；载板只出 PWM+GND |
| VLOGIC_5V | 逻辑 5V 主供电候选 | 外部 DC/DC 降压模块输出；通过供电选择跳线接 M144Z-M4 5V 排针；与 USB/3.3V 备选互斥 |
| VLOGIC_3V3_BACKUP | 逻辑 3.3V 备选供电/参考 | 仅在确认 3.3V 排针允许直接输入后使用；与 5V/USB 互斥，不给电机/舵机供电 |
| GND_LOGIC | 逻辑地 | 公共参考地 |
| GND_POWER | 动力地 | 与 GND_LOGIC 在入口侧单点汇接，待最终确认 |

A4988 的 VDD 逻辑电源按模块资料接 3.3V 或 5V（待模块实物确认）。

### 3.1 M144Z-M4 排针电源脚候选处理

```text
JP_L-48 / JP_L-50（3.3V） -> VLOGIC_3V3_BACKUP（备选，方向待验）
JP_L-49、JP_R-47、JP_R-49（GND） -> GND_LOGIC
JP_R-48 / JP_R-50（5V） -> VLOGIC_5V（主供电候选）
JP_L-46（UREF） -> 暂不连接，不能贴 POWER_OR_BOARD
JP_L-47（RST） -> 当前不接硬件复位则 NC；使用时命名 MCU_NRST
JP_R-46（VBAT） -> 不使用 RTC 备用电源则 NC，不能接 5V
```

`VLOGIC_5V`、`VLOGIC_3V3_BACKUP`、USB 供电三者不得在没有电源选择/防倒灌设计时同时接入。C-Link/ST-Link 的 3.3V 仅作为低功耗台架测试来源，不作为最终载板供电结论。

## 4 A4988 配置与互斥

- MS1/MS2/MS3：第一版用跳线/电阻固定，不接 MCU。
- RST/SLP：按模块资料做硬件默认使能态（RST 上拉、SLP 接高），不先占 MCU。
- EN：接 ENABLE_X/Y，低有效，上电默认禁能。
- U_DRV_X_SOCKET 与 J_DRV_X_CTRL 二选一装配，Y 同理；禁止同时驱动同一电机。

## 5 输入调理

- 限位、启动、复位、急停反馈：常闭开关优先，载板做上拉（软件可配下拉）、RC 滤波和瞬态保护后再进 GPIO。
- 未确认电平的传感器输出不得直连 STM32 GPIO。
- ESTOP_FB 只读取急停辅助触点状态，绝不串入急停主回路。

## 6 画完检查清单

- 每个 GPIO 只连一次（对照本表）。
- STEP/DIR/ENABLE 三轴各三路，共 9 路，没有与 PWM/输入串网。
- 四路挡板 PWM、夹爪、腕部各自独立，未并联。
- WRIST_PWM 默认不装。
- X/Y A4988 与备用驱动接口有互斥标注。
- 六个储物箱没有电控网络。
- 全部 3.3V 逻辑；动力/舵机 5V 网络与逻辑网络分开。
- J_UART_MAIN 与 J_UART_BACKUP 各自独立，TX/RX 未并网，两个接口都有 GND_LOGIC。
- SWD（PA13/PA14）不占用。


