# G1 候选 PCB 与 STM32 固件交接记录

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

> 交接编号：HANDOFF-20260816-001  
> 关联任务：TASK-20260816-001、TASK-20260814-004  
> 日期：2026-08-16  
> 子系统：电控 / 候选 PCB / STM32 固件  
> 状态：可作为**固件代码基线**；不是 PCB 冻结、投板或实机系统放行证明。

## 1. 当前结论

下一段对话可以按本文 GPIO 与外设映射编写 STM32F407 的 CubeMX/HAL 安全启动和接口自检代码。该映射来自已记录的 GPIO 功能测试与静态施工表；M144Z-M4 排针物理位置、真实 EDA 网络和 PCB 制造状态仍须保留为候选/待验。

## 2. 固件固定基线

### 2.1 三轴步进驱动

| 网络 | GPIO | CubeMX 外设 | 安全默认态 | 说明 |
|---|---|---|---|---|
| `STEP_X` | PC6 | TIM8_CH1 | 停止脉冲 | X 轴 STEP |
| `DIR_X` | PA7 | GPIO 输出 | 低 | X 轴方向 |
| `ENABLE_X` | PA5 | GPIO 输出 | 高（禁能） | A4988 类接口低有效 |
| `STEP_Y` | PB6 | TIM4_CH1 | 停止脉冲 | Y 轴 STEP |
| `DIR_Y` | PC7 | GPIO 输出 | 低 | Y 轴方向 |
| `ENABLE_Y` | PD7 | GPIO 输出 | 高（禁能） | A4988 类接口低有效 |
| `STEP_Z` | PE5 | TIM9_CH1 | 停止脉冲 | Z 轴 STEP |
| `DIR_Z` | PE6 | GPIO 输出 | 低 | Z 轴方向 |
| `ENABLE_Z` | PG15 | GPIO 输出 | 高（禁能） | A4988 类接口低有效 |

约束：上电后必须先停止三个 STEP 定时器，再将三个 `ENABLE_*` 输出高电平；只有完成自检、输入状态确认和明确使能命令后才能输出脉冲。

### 2.2 PWM 与灯控

| 网络 | GPIO | CubeMX 外设 | 默认态 |
|---|---|---|---|
| `BARRIER_PWM_1` | PB0 | TIM3_CH3 | 停 PWM |
| `BARRIER_PWM_2` | PB1 | TIM3_CH4 | 停 PWM |
| `BARRIER_PWM_3` | PF6 | TIM10_CH1 | 停 PWM |
| `BARRIER_PWM_4` | PF7 | TIM11_CH1 | 停 PWM |
| `GRIP_PWM` | PB10 | TIM2_CH3 | 停 PWM |
| `WRIST_PWM` | PB11 | TIM2_CH4 | 默认禁用（DNP） |
| `LIGHT_EN` | PC0 | GPIO 输出 | 低（关） |

PWM 的候选控制帧率为 50 Hz。脉宽范围、执行器型号和跨定时器同步要求尚未冻结，代码不得写成已验证的具体舵机参数。

### 2.3 3.3V 逻辑输入

| 网络 | GPIO | 正常电平 | 触发电平 |
|---|---|---:|---:|
| `X_HOME` | PG7 | 1 | 0 |
| `X_END` | PG6 | 1 | 0 |
| `Y_HOME` | PG9 | 1 | 0 |
| `Y_END` | PD5 | 1 | 0 |
| `Z_UP` | PF11 | 1 | 0 |
| `Z_DOWN` | PG14 | 1 | 0 |
| `ESTOP_FB` | PG13 | 1 | 0 |
| `START_SIG` | PA4 | 1 | 0 |
| `MANUAL_RESET_SIG` | PF8 | 1 | 0 |

候选载板电路为：外部接口经 1 kΩ 串联、ESD、100 nF 滤波后进入 GPIO，并由 10 kΩ 上拉到 `VLOGIC_3V3_BACKUP`。代码基线使用 GPIO 输入、`NOPULL`；外部上拉决定默认逻辑。所有这些输入只能接干接点或 3.3V 兼容信号，禁止将 5V 直接输入 GPIO。

`ESTOP_FB` 仅用于读取辅助急停反馈，不可替代板外急停主动力切断回路。

### 2.4 串口

| 角色 | UART | TX | RX | 配置 |
|---|---|---|---|---|
| 主 UART（树莓派） | USART3 | PD8 = `UART_MAIN_TX` | PD9 = `UART_MAIN_RX` | 115200, 8N1 |
| 备 UART | USART2 | PA2 = `UART_BACKUP_TX` | PA3 = `UART_BACKUP_RX` | 115200, 8N1 |

主 UART 接树莓派时采用交叉连接：`PD8 TX → Pi RX`、`PD9 RX ← Pi TX`，且必须共用 `GND_LOGIC`。主/备 UART 的 TX/RX 不得互并。

### 2.5 不占用引脚

| 引脚/资源 | 保留原因 |
|---|---|
| PA13 / PA14 | SWDIO / SWCLK，烧录与调试 |
| PC8–PC12、PD2 | 板载 TF/SDIO |
| PA9 / PA10 | 板载 USB-UART，不作为本载板第三串口 |

## 3. 下一段固件的第一轮实现边界

第一轮仅实现：

1. 所有输出的安全初始化；
2. USART3 周期性启动/状态文本；
3. 九路输入的低有效读取与状态上报；
4. 三个 STEP 定时器的“停止/使能/单轴低频测试”软件接口；
5. 不接入真实电机功率、舵机动力或急停主回路。

定时器 PSC/ARR/CCR 必须按下一段对话实际 CubeMX 时钟树计算，不能从旧示例直接照抄。候选目标是单轴连续 STEP 不超过 20 kHz；该目标不构成实物运动验收。

## 4. PCB / EDA 当前边界

| 项目 | 当前状态 | 证据与限制 |
|---|---|---|
| 原理图与 PCB | 用户已在嘉立创 EDA 进行候选绘制与布线 | 不等于正式原理图冻结。 |
| 测试点 | 已规划 22 个：电源 2、STEP/DIR/ENABLE 9、主/备 UART 4、PWM/灯控 7 | 需在最终 PCB 中逐网连通。 |
| 输入调理 | 九路候选输入采用 1 kΩ + 10 kΩ + 100 nF + H3V3LD3U | 元件选型/最终 EDA 网络仍须复核。 |
| 最新已观察 DRC | 曾显示“原理图网表与 PCB 网表不一致”，需执行“导入更新”后重新检查 | 当前没有“DRC 全通过”证据。 |
| 2026-08-16 Gerber ZIP | 仅含 Gerber、钻孔和飞针测试 JSON；不含可编辑工程 | JSON 中保留旧位号/显示名，不能作为最终生产文件。 |
| 供电 | CN5=`VLOGIC_5V`，CN6=`VLOGIC_3V3_BACKUP`，两者不可相连 | 3.3V 外供能力及供电策略未冻结。 |

板外边界：DC/DC、电池、树莓派、A4988 功率输入 `VMOT`、步进电机四相线、舵机动力、急停主回路和相机均不属于本载板 PCB。

## 5. 测试状态

| 测试项 | 状态 | 证据 |
|---|---|---|
| STEP/DIR/ENABLE GPIO 与定时器功能 | 已记录通过 | `TASK-20260814-004`、`m144z-m4-tested-pin-pcb-map.md` |
| 输入低有效读取与联动 | 已记录通过 | `TASK-20260814-004`、输入测试会话记录 |
| USART3 / USART2 115200 8N1 | 已记录通过 | `TASK-20260814-004` |
| M144Z-M4 排针连续性 | 未验证 | 缺官方针序或万用表连续性测试 |
| 最终 EDA ERC / DRC | 未验证 | 当前仅观察到同步前网表不一致及局部连通性修正过程 |
| Gerber / BOM / CPL 可生产性 | 未验证 | 现有 Gerber ZIP 为同步前候选输出 |

## 6. 下一段对话启动提示词

```text
继续工创赛 STM32F407 固件候选开发。

先阅读并遵守：
1. AGENTS.md、CLAUDE.md
2. docs/reports/2026-08-16-g1-pcb-code-handoff.md
3. docs/design/stm32f407-pin-timer-allocation.md
4. .claude/tasks/TASK-20260816-001-g1-pcb-code-handoff.md

严格使用交接记录中的 GPIO 映射，不擅自重分配引脚。先实现 HAL/CubeMX 安全初始化：三个 ENABLE 高电平禁能、三个 STEP 定时器停止、LIGHT_EN 低、WRIST_PWM 禁用；输入均按外部 3.3V 上拉、低有效读取；主 UART 使用 USART3 的 PD8/PD9，115200 8N1。

第一轮只写并验证主机侧/固件代码结构、串口状态上报、输入读取和无功率单轴脉冲接口。不得把候选 PCB 状态表述为已投板、已完成 DRC 或实机系统验证；不得执行未经明确授权的接线、上电、烧录和实机运动。
```

## 7. 来源

- `.claude/tasks/TASK-20260814-004-tested-pin-pcb-map.md`
- `docs/design/stm32f407-pin-timer-allocation.md`
- `docs/design/m144z-m4-tested-pin-pcb-map.md`
- `docs/reports/REVIEW-20260814-tested-pin-pcb-map.md`
- 当前会话中的嘉立创 EDA 截图与 2026-08-16 Gerber ZIP 只读检查。
