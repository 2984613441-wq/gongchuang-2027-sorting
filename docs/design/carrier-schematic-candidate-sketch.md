# 载板候选原理图草图（G1）

> 状态：G1 候选原理图草图，未冻结。
> 
> 本文件是原理图绘制前的可审查网络/分页草图，不是真实 EDA 工程，不替代 ERC、DRC、Gerber、BOM、坐标文件或实机验证。
> 
> 主控：M144Z-M4 Mini Board（STM32F407ZGT6）。`JP_L/JP_R` 针序采用用户 2026-08-13 手工抄录；`JP_R` 第 1 行为 `PC6` 外列、`PC7` 内列。该来源仍未由官方资料或万用表连续性独立验证。

## 1. 任务边界

### 已知输入

- `docs/design/carrier-schematic-wiring-spec.md`：候选网名、接口和互斥规则。
- `docs/design/stm32f407-pin-timer-allocation.md`：候选 GPIO/定时器分配。
- `docs/design/min-system-board-pinout.md`：用户提供的 M144Z-M4 排针记录。
- `docs/design/m144z-m4-tested-pin-pcb-map.md`：实测 GPIO、排针候选位置、双 UART 与 PCB 接口总图。
- `docs/design/modular-pcb-design.md`、`docs/design/pcb方案-17HS4401版.md`：模块边界和安全边界。

### 统一规则

1. 所有 GPIO 信号按 3.3 V 逻辑记录；5 V 仅保留在外部动力/舵机接口边界。
2. `U_DRV_X_SOCKET` 与 `J_DRV_X_CTRL` 二选一；`U_DRV_Y_SOCKET` 与 `J_DRV_Y_CTRL` 二选一。
3. `J_DRV_Z_CTRL` 仅承载低能量 `STEP_Z/DIR_Z/ENABLE_Z/GND_LOGIC` 控制边界，Z 轴动力不在载板上。
4. 急停主回路不经过载板；`J_ESTOP_FB` 只读辅助触点反馈。
5. `WRIST_PWM` 默认 DNP；六个储物箱无电控网络。
6. 所有 M144Z-M4 板载冲突统一记录为 `M144Z-M4 待验`。探索者 V3 仅作为芯片/整板参考，不能覆盖 M144Z-M4 排针针序。

### 本阶段未知

- M144Z-M4 官方针序、板载路由、`UREF` 和白色 4P 插座定义。
- 排母/连接器机械尺寸、A4988 模块实物针序和封装。
- 电源额定、保护器件定值、线宽、板框、安装孔和负载参数。

## 2. 分页草图目录

| 页码 | 页面名 | 草图内容 | 状态 |
|---|---|---|---|
| 00 | `TOP_HIERARCHY` | 层级关系、网名规则、DNP/待验图例 | 候选 |
| 01 | `MCU_CARRIER` | `JP_L_SOCKET`、`JP_R_SOCKET`、MCU 网名与排针映射 | 候选 |
| 02 | `LOGIC_POWER` | `VIN_RAW`、`VLOGIC_5V`、`VLOGIC_3V3`、地边界和测试点 | 候选 |
| 03 | `DRV_X_A4988_CANDIDATE` | X 轴 A4988 候选插座、控制网和电机端子 | 候选/DNP |
| 04 | `DRV_Y_A4988_CANDIDATE` | Y 轴 A4988 候选插座、控制网和电机端子 | 候选/DNP |
| 05 | `EXTERNAL_DRIVER_CTRL` | X/Y 板外备用接口和 Z 板外驱动控制接口 | 候选，X/Y 默认 DNP |
| 06 | `SERVO_GRIPPER_LIGHT` | 四路挡板 PWM、夹爪、腕部预留、补光控制 | 候选，腕部 DNP |
| 07 | `SAFETY_AND_INPUTS` | 限位、启动、人工复位、急停反馈接口与调理预留 | 候选 |
| 08 | `COMM_DEBUG_TEST` | 正式 USART2、备用 USART3、SWD 保留、测试点和维护接口 | 候选 |
| 09 | `CONNECTOR_SCHEDULE` | 板外连接器台账、方向、对端和未知字段 | 候选 |

## 3. 页面 00：层级与图例

### 3.1 图例

| 标记 | 含义 |
|---|---|
| `CANDIDATE` | 候选器件/网络，不能视为定型 |
| `DNP` | 默认不装；仅保留接口或候选位置 |
| `TBD` | 参数或实物资料待补 |
| `M144Z-M4 待验` | 板上针序/路由尚无官方或实测证据 |
| `EXPLORER_REF` | 探索者 V3 参考，不代表 M144Z-M4 已验证 |

### 3.2 层级关系

```text
TOP_HIERARCHY
├── MCU_CARRIER
├── LOGIC_POWER
├── DRV_X_A4988_CANDIDATE
├── DRV_Y_A4988_CANDIDATE
├── EXTERNAL_DRIVER_CTRL
├── SERVO_GRIPPER_LIGHT
├── SAFETY_AND_INPUTS
├── COMM_DEBUG_TEST
└── CONNECTOR_SCHEDULE
```

## 4. 页面 01：MCU_CARRIER

### 4.1 连接器与针序边界

| 位号 | 器件 | 针数 | 针序来源 | 证据状态 |
|---|---|---:|---|---|
| `JP_L_SOCKET` | M144Z-M4 左侧双排排母 | 2×25 | `min-system-board-pinout.md` JP_L | 用户手工抄录，待验 |
| `JP_R_SOCKET` | M144Z-M4 右侧双排排母 | 2×25 | `min-system-board-pinout.md` JP_R | 用户手工抄录，待验 |

约定：排针编号从靠近 TF 卡端开始；奇数为外列，偶数为内列。`JP_R-1=PC6`、`JP_R-2=PC7`，不采用镜像假定。

### 4.2 候选 MCU 网名映射

| 网名 | STM32 GPIO | 排针 | 复用/用途 | 上电默认 | 冲突记录 |
|---|---|---|---|---|---|
| `STEP_X` | PC6 | JP_R-1 | TIM8_CH1 | 停止 | EXPLORER_REF OLED/CAMERA D0；M144Z-M4 待验 |
| `DIR_X` | PA7 | JP_L-38 | GPIO | 低 | EXPLORER_REF 以太网 YT8512C；M144Z-M4 待验 |
| `ENABLE_X` | PA5 | JP_L-39 | GPIO，低有效 | 禁能 | EXPLORER_REF 未见冲突；M144Z-M4 待验 |
| `STEP_Y` | PB6 | JP_R-19 | TIM4_CH1 | 停止 | EXPLORER_REF 未见冲突；M144Z-M4 待验 |
| `DIR_Y` | PC7 | JP_R-2 | GPIO | 低 | EXPLORER_REF OLED/CAMERA D1；M144Z-M4 待验 |
| `ENABLE_Y` | PD7 | JP_R-4 | GPIO，低有效 | 禁能 | EXPLORER_REF OLED/CAMERA SCL；M144Z-M4 待验 |
| `STEP_Z` | PE5 | JP_R-38 | TIM9_CH1 | 停止 | EXPLORER_REF OLED/CAMERA D6；M144Z-M4 待验 |
| `DIR_Z` | PE6 | JP_R-37 | GPIO | 低 | EXPLORER_REF OLED/CAMERA D7；M144Z-M4 待验 |
| `ENABLE_Z` | PG15 | JP_R-5 | GPIO，低有效 | 禁能 | EXPLORER_REF OLED/CAMERA RESET；M144Z-M4 待验 |
| `BARRIER_PWM_1` | PB0 | JP_L-35 | TIM3_CH3 | 停 PWM | EXPLORER_REF TFTLCD 触摸 SCK；M144Z-M4 待验 |
| `BARRIER_PWM_2` | PB1 | JP_L-34 | TIM3_CH4 | 停 PWM | EXPLORER_REF TFTLCD 触摸 PEN；M144Z-M4 待验 |
| `BARRIER_PWM_3` | PF6 | JP_L-29 | TIM10_CH1 | 停 PWM | EXPLORER_REF 未见冲突；M144Z-M4 待验 |
| `BARRIER_PWM_4` | PF7 | JP_L-30 | TIM11_CH1 | 停 PWM | EXPLORER_REF 光敏传感器；M144Z-M4 待验 |
| `GRIP_PWM` | PB10 | JP_R-23 | TIM2_CH3 | 停 PWM | EXPLORER_REF USART3_TX；M144Z-M4 待验 |
| `WRIST_PWM` | PB11 | JP_R-22 | TIM2_CH4 | DNP | EXPLORER_REF USART3_RX；M144Z-M4 待验 |
| `LIGHT_EN` | PC0 | JP_R-36 | GPIO | 关 | EXPLORER_REF 未见冲突；M144Z-M4 待验 |
| `X_HOME` | PG7 | JP_R-14 | 输入 | 安全态 | EXPLORER_REF 无线接口；M144Z-M4 待验 |
| `X_END` | PG6 | JP_R-13 | 输入 | 安全态 | EXPLORER_REF 无线接口；M144Z-M4 待验 |
| `Y_HOME` | PG9 | JP_R-30 | 输入 | 安全态 | EXPLORER_REF 单总线；M144Z-M4 待验 |
| `Y_END` | PD5 | JP_R-29 | 输入 | 安全态 | EXPLORER_REF 未见冲突；M144Z-M4 待验 |
| `Z_UP` | PF11 | JP_L-32 | 输入 | 安全态 | EXPLORER_REF TFTLCD 触摸 MOSI；M144Z-M4 待验 |
| `Z_DOWN` | PG14 | JP_R-44 | 输入 | 安全态 | EXPLORER_REF 以太网 YT8512C；M144Z-M4 待验 |
| `ESTOP_FB` | PG13 | JP_R-43 | 输入，仅反馈 | 安全态 | EXPLORER_REF 以太网 YT8512C；M144Z-M4 待验 |
| `START_SIG` | PA4 | JP_L-40 | 输入 | 未触发 | EXPLORER_REF OLED/CAMERA HREF；M144Z-M4 待验 |
| `MANUAL_RESET_SIG` | PF8 | JP_L-31 | 输入 | 未触发 | EXPLORER_REF 蜂鸣器；M144Z-M4 待验 |
| `UART_MAIN_TX` | PA2 | JP_L-44 | USART2_TX | 空闲 | 实测 115200 8N1；M144Z-M4 排针位置待验 |
| `UART_MAIN_RX` | PA3 | JP_L-41 | USART2_RX | 空闲 | 实测 115200 8N1 回显；M144Z-M4 排针位置待验 |
| `UART_BACKUP_TX` | PD8 | JP_L-10 | USART3_TX | 空闲 | 实测 115200 8N1；M144Z-M4 排针位置待验 |
| `UART_BACKUP_RX` | PD9 | JP_L-9 | USART3_RX | 空闲 | 实测 115200 8N1 回显；M144Z-M4 排针位置待验 |

TF/SDIO、SWD、板载 USB_UART 和 USB_OTG 在本草图中只作为冲突审查标记，不接入载板功能网。

## 5. 页面 02：LOGIC_POWER

| 网名/接口 | 草图连接 | 当前状态 |
|---|---|---|
| `VIN_RAW` | 外部总电源入口端子/保险位预留 | 载板不集成适配器，参数 TBD |
| `VMOT_ESTOP` | 急停/保护后的 A4988 动力边界 | 外部输入，危险动力不经逻辑回路 |
| `VLOGIC_5V` | 逻辑 5V 输入边界 | 电压/额定 TBD |
| `VLOGIC_3V3` | 3.3V 逻辑参考 | 与 M144Z-M4 板载 LDO 关系待验 |
| `V_SERVO_5V` | 外部舵机供电边界 | 载板只出 PWM/GND_LOGIC |
| `GND_LOGIC` | 所有逻辑接口公共参考 | 不承载危险动力回流 |
| `GND_POWER` | 动力地入口侧单点汇接候选 | 位置/拓扑待安全审查 |

不在本页确定反接保护、保险丝、TVS、DC/DC、去耦或电阻电容数值；这些均为 `TBD` 器件位。

## 6. 页面 03：DRV_X_A4988_CANDIDATE

| 位号/网名 | 草图连接 | 状态 |
|---|---|---|
| `U_DRV_X_SOCKET` | `STEP_X`、`DIR_X`、`ENABLE_X`、逻辑地、`VMOT_ESTOP`、电机四相 | 候选，默认 DNP |
| `J_X_MOTOR` | `X_MOTOR_1A/1B/2A/2B` | 端子针序/额定 TBD |
| `J_DRV_X_CTRL` | `STEP_X/DIR_X/ENABLE_X/GND_LOGIC`，可选反馈位 | 候选，默认 DNP |
| `MS1/MS2/MS3` | 跳线/电阻固定候选 | 数值 TBD，不接 MCU |
| `RST/SLP` | 模块资料要求的默认使能态 | 针序/电平待实物确认 |

规则：`U_DRV_X_SOCKET` 与 `J_DRV_X_CTRL` 禁止同时装配并驱动同一电机。A4988 额定、电流、散热和电机线序均不在 G1 冻结。

## 7. 页面 04：DRV_Y_A4988_CANDIDATE

结构与 X 轴相同但网名、位号和电机端子独立：`U_DRV_Y_SOCKET`、`J_Y_MOTOR`、`J_DRV_Y_CTRL`、`Y_MOTOR_1A/1B/2A/2B`。Y 轴控制网为 `STEP_Y/DIR_Y/ENABLE_Y`。

规则：`U_DRV_Y_SOCKET` 与 `J_DRV_Y_CTRL` 禁止同时装配并驱动同一电机；A4988 模块默认 DNP，参数 TBD。

## 8. 页面 05：EXTERNAL_DRIVER_CTRL

| 接口 | 针脚候选 | 对端/边界 | 状态 |
|---|---|---|---|
| `J_DRV_X_CTRL` | `STEP_X/DIR_X/ENABLE_X/GND_LOGIC` + 可选反馈 | X 板外驱动器 | DNP |
| `J_DRV_Y_CTRL` | `STEP_Y/DIR_Y/ENABLE_Y/GND_LOGIC` + 可选反馈 | Y 板外驱动器 | DNP |
| `J_DRV_Z_CTRL` | `STEP_Z/DIR_Z/ENABLE_Z/GND_LOGIC` + 可选反馈 | Z 板外驱动器 | 候选 |

本页不得出现 `STEP_3`、`DIR_3`、`ENABLE_3` 或 `J_DRV3_CTRL`；统一采用 Z 轴网名。板外驱动动力、电机相线和急停主回路不进入载板。

## 9. 页面 06：SERVO_GRIPPER_LIGHT

| 接口 | 信号 | 供电边界 | 状态 |
|---|---|---|---|
| `J_BARRIER_CTRL_1` | `BARRIER_PWM_1/GND_LOGIC` | 外部舵机供电 | 候选 |
| `J_BARRIER_CTRL_2` | `BARRIER_PWM_2/GND_LOGIC` | 外部舵机供电 | 候选 |
| `J_BARRIER_CTRL_3` | `BARRIER_PWM_3/GND_LOGIC` | 外部舵机供电 | 候选 |
| `J_BARRIER_CTRL_4` | `BARRIER_PWM_4/GND_LOGIC` | 外部舵机供电 | 候选 |
| `J_GRIPPER_CTRL` | `GRIP_PWM/GND_LOGIC` | 外部舵机供电 | 候选 |
| `J_WRIST_CTRL` | `WRIST_PWM/GND_LOGIC` | 外部舵机供电 | DNP |
| `J_LIGHT` | `LIGHT_EN/GND_LOGIC` | 外部补光模块供电 | 候选 |

不在 G1 固定 PWM 频率、脉宽、舵机电流、补光功率、连接器额定或保护器件值。

## 10. 页面 07：SAFETY_AND_INPUTS

| 接口 | 输入网 | 草图调理 | 约束 |
|---|---|---|---|
| `J_X_HOME` / `J_X_END` | `X_HOME` / `X_END` | 上拉、RC、瞬态保护预留 | 常闭优先，参数 TBD |
| `J_Y_HOME` / `J_Y_END` | `Y_HOME` / `Y_END` | 上拉、RC、瞬态保护预留 | 常闭优先，参数 TBD |
| `J_Z_UP` / `J_Z_DOWN` | `Z_UP` / `Z_DOWN` | 上拉、RC、瞬态保护预留 | Z 轴机械安全由机械组确认 |
| `J_ESTOP_FB` | `ESTOP_FB` | 只读反馈调理预留 | 不串入急停主回路 |
| `J_START` | `START_SIG` | 输入调理预留 | 不自动触发危险动作 |
| `J_MANUAL_RESET` | `MANUAL_RESET_SIG` | 输入调理预留 | 仅人工复位请求 |

急停主回路是板外独立硬件切断危险动力；本页只画反馈和低能量输入边界。

## 11. 页面 08：COMM_DEBUG_TEST

| 接口/测试点 | 信号 | 说明 |
|---|---|---|
| `J_UART_MAIN` | `UART_MAIN_TX/UART_MAIN_RX/GND_LOGIC` | 正式 USART2；TX/RX 对端交叉 |
| `J_UART_BACKUP` | `UART_BACKUP_TX/UART_BACKUP_RX/GND_LOGIC` | 备用 USART3；主备 TX/RX 不并接 |
| `SWD` | SWDIO/SWCLK/GND | 使用 M144Z-M4 下方 SWD 接口，载板不复刻 MCU |
| `TP_STEP_*` | 各轴 STEP | 仅测试点候选 |
| `TP_DIR_*` | 各轴 DIR | 仅测试点候选 |
| `TP_ENABLE_*` | 各轴 ENABLE | 仅测试点候选 |
| `TP_PWM_*` | PWM/`LIGHT_EN` | 仅测试点候选 |
| `TP_UART_*` | 主/备 UART TX、RX | 分别保留，不并接 |
| `TP_POWER_*` | 关键逻辑/动力边界 | 测试点位置和安全等级 TBD |

## 12. 页面 09：CONNECTOR_SCHEDULE

| 位号 | 功能 | 信号方向 | 对端 | 针序/额定 | 版本状态 |
|---|---|---|---|---|---|
| `JP_L_SOCKET` | M144Z-M4 左排针 | 双向/电源 | M144Z-M4 JP_L | 手工抄录，待 1:1/连续性验证 | 候选 |
| `JP_R_SOCKET` | M144Z-M4 右排针 | 双向/电源 | M144Z-M4 JP_R | PC6 外列、PC7 内列；待验证 | 候选 |
| `U_DRV_X_SOCKET` | X A4988 | 控制/动力 | A4988 模块、X 电机 | 模块针序 TBD | 候选/DNP |
| `U_DRV_Y_SOCKET` | Y A4988 | 控制/动力 | A4988 模块、Y 电机 | 模块针序 TBD | 候选/DNP |
| `J_DRV_X_CTRL` | X 板外驱动备用 | 输出/反馈 | X 外部驱动器 | 针序/电平 TBD | 候选/DNP |
| `J_DRV_Y_CTRL` | Y 板外驱动备用 | 输出/反馈 | Y 外部驱动器 | 针序/电平 TBD | 候选/DNP |
| `J_DRV_Z_CTRL` | Z 板外驱动 | 输出/反馈 | Z 外部驱动器 | 针序/电平 TBD | 候选 |
| `J_X_MOTOR` / `J_Y_MOTOR` | 电机端子 | 输出动力 | X/Y 电机 | 线序/额定 TBD | 候选 |
| `J_BARRIER_CTRL_1..4` | 挡板舵机 | PWM 输出 | 外部舵机供电模块 | 针序/额定 TBD | 候选 |
| `J_GRIPPER_CTRL` | 夹爪舵机 | PWM 输出 | 外部舵机供电模块 | 针序/额定 TBD | 候选 |
| `J_WRIST_CTRL` | 腕部预留 | PWM 输出 | 外部舵机供电模块 | 默认不装 | DNP |
| `J_LIGHT` | 补光 | 控制输出 | 外部补光模块 | 针序/额定 TBD | 候选 |
| `J_X_HOME` / `J_X_END` | X 限位 | 输入 | 外部开关 | 类型/线长 TBD | 候选 |
| `J_Y_HOME` / `J_Y_END` | Y 限位 | 输入 | 外部开关 | 类型/线长 TBD | 候选 |
| `J_Z_UP` / `J_Z_DOWN` | Z 限位 | 输入 | 外部开关 | 类型/线长 TBD | 候选 |
| `J_ESTOP_FB` | 急停反馈 | 输入 | 急停辅助触点 | 只读，针序 TBD | 候选 |
| `J_START` / `J_MANUAL_RESET` | 人机输入 | 输入 | 外部按钮 | 类型/针序 TBD | 候选 |
| `J_UART_MAIN` | USART2 | 双向 | 树莓派 | TX/RX/GND，针序 TBD | 候选 |
| `J_UART_BACKUP` | USART3 | 双向 | 备用上位机/树莓派 | TX/RX/GND，针序 TBD；禁止与主接口并接 | 候选 |

## 13. G1 草图验收边界

### 本轮允许确认

- 分页、接口边界、候选网名、DNP 互斥和安全边界已形成可复核文字草图。
- `STEP_Z/DIR_Z/ENABLE_Z` 命名统一；无 `STEP_3` 等旧别名。
- `JP_R` 方向在文档中统一为 `PC6 外列 / PC7 内列`。

### 本轮不能确认

- M144Z-M4 官方针序或实物连续性。
- 任何器件封装、额定、电源保护定值、板框和布线规则。
- ERC、网络审查、DRC、Gerber、BOM、坐标文件、投板或实机动作。

### 下一门禁（G2）前置

1. 建立真实 EDA 工程并逐网录入本草图。
2. 补齐 M144Z-M4 独立针序证据和 A4988 实物针序/封装。
3. 完成 ERC、逐网审查、器件定值和参数卡。
4. 通过独立审核后，才讨论原理图冻结。
