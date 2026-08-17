# 探索者 STM32F407 V3 官方资料核对记录

> 状态：候选基线，未冻结。本文件为 GPIO/定时器分配与立创 EDA 载板原理图提供证据基线，不构成接线、上电、投板或采购授权。
> 核对日期：2026-08-13。
> 资料来源：用户本机官方 A 盘（探索者 STM32F407 开发板 V3 资料盘 A 盘），关键文件已复制到 `docs/design/explorer-f407-reference/`。
> 证据等级：A=厂商官方资料盘内资料；B=从官方 PDF/库文件提取并经坐标与文本交叉核对的结果；C=待用户/实物确认。

## 1 资料清单

| 资料 | 来源 | 版本/日期 | 本机副本 | 提取的证据 | 等级 |
|---|---|---|---|---|---|
| EXPLORER_V3.4.pdf | 官方 A 盘 `3，原理图.zip` | V3.4（工程日期 2023/6/7） | `docs/design/explorer-f407-reference/3，原理图/EXPLORER_V3.4.pdf` | 核心页：MCU 引脚、P7/P8/P9 排针、JTAG、电源、OLED/摄像头页 | A |
| EXPLORER_V3.5.pdf | 官方 A 盘 `3，原理图.zip` | V3.5 | `docs/design/explorer-f407-reference/3，原理图/EXPLORER_V3.5.pdf` | 与 V3.4 一致的排针/电源主体；P2 等选择口存在版本差异 | A |
| 探索者V3 IO引脚分配表.xlsx | 官方 A 盘 `3，原理图.zip` | V3 | `docs/design/explorer-f407-reference/3，原理图/探索者V3 IO引脚分配表.xlsx` | 每个 STM32F407ZGT6 引脚的板载连接资源、独立性和使用提示 | A |
| 探索者V3 硬件参考手册_V1.0.pdf | 官方 A 盘 | V1.0，2022/11/01 | `docs/design/explorer-f407-reference/探索者V3 硬件参考手册_V1.0.pdf` | 板卡参数、资源分布、VOUT1/VOUT2、电源拓扑 | A |
| EXPLORER_V3.4_PCB.lib | 官方 A 盘封装库 | V3.4 | `docs/design/explorer-f407-reference/EXPLORER_V3.4_PCB.lib` | AD/99SE 封装库，可作封装参考；导入立创/KiCad 需转换并 1:1 核对 | B |
| EXPLORER_V3_SCH.lib | 官方 A 盘封装库 | V3.4 | `docs/design/explorer-f407-reference/EXPLORER_V3_SCH.lib` | 官方原理图符号库 | B |

官方在线渠道（www.alientek.com、docs 站）本次未在线访问，本文件证据以本机 A 盘文件为准。

## 2 工作区盘点

执行 `rg --files | rg -i "(easyeda|jlceda|\.kicad_sch$|\.kicad_pcb$|\.epro$|gerber|\.gbr$|\.json$)"`：仅命中本仓库的计划/提示词 Markdown 文件，未发现任何现存 EDA 工程、原理图、PCB、Gerber 或 BOM。结论：载板原理图属于新建。

## 3 板卡身份与关键参数

### 3.1 板卡身份

- 产品型号：ATK-DNF407 V3.2（手册 1.1.2）；原理图版本 V3.4/V3.5。
- 核心：STM32F407ZGT6，LQFP144。
- 引出 IO：112 个；除 RTC 晶振占用的 PC14/PC15 外，110 个可用。
- 外形尺寸：121 mm × 160 mm（手册 1.1.2.1）。
- 工作电压：5 V（USB）或 DC 6~15 V（DC005）；整板电流约 75~120 mA。

已确认（用户 2026-08-13）：实物为 M144Z-M4 最小系统板（核心板），外形约 82.8 mm × 51.2 mm，上下各一组双排长排针 JP1/JP2，不是探索者 V3 整板。因此本文件第 4 节的 P7/P8/P9 排针表只作为整板参考证据，最小系统板 JP1/JP2 针序必须依据其官方原理图/卖家资料另建，本 A 盘没有该资料。

### 3.2 电源拓扑

依据手册 2.1.29/2.1.30 与原理图 POWER 页：

- DC_IN（DC005）：DC 6~15 V 输入。
- U10（RY9125）DC-DC 转 5 V；VD1（SS34）防反接；K1 总开关；F1 自恢复保险丝（1 A，USB 路径）。
- U11/U12（AMS1117-3.3）两路 LDO：3.3 V 数字与 3.3 V 模拟分开供电。
- VOUT1（2×3 排针）= 3.3 V 输入/输出；VOUT2（2×3 排针）= 5 V 输入/输出；外部供电最大约 1000 mA，USB 供电约 500 mA；带 TVS。

结论：探索者整板仅作为逻辑低压源（毫安到约 1 A 级），不能承担步进或舵机动力供电；X/Y/Z 动力、舵机动力、DC/DC 与急停主回路均在载板外，与现有主方案一致。

## 4 扩展排针（载板对插面）

### 4.1 P7（1×16，FSMC_D0~D15）

| 针 | 信号 | 针 | 信号 |
|---|---|---|---|
| 1 | PD14 / FSMC_D0 | 9 | PE11 / FSMC_D8 |
| 2 | PD15 / FSMC_D1 | 10 | PE12 / FSMC_D9 |
| 3 | PD0 / FSMC_D2 | 11 | PE13 / FSMC_D10 |
| 4 | PD1 / FSMC_D3 | 12 | PE14 / FSMC_D11 |
| 5 | PE7 / FSMC_D4 | 13 | PE15 / FSMC_D12 |
| 6 | PE8 / FSMC_D5 | 14 | PD8 / FSMC_D13 |
| 7 | PE9 / FSMC_D6 | 15 | PD9 / FSMC_D14 |
| 8 | PE10 / FSMC_D7 | 16 | PD10 / FSMC_D15 |

手册文字曾把“1×16 FSMC 排针”写成 P3，但原理图明确该 1×16 排针为 P7，P3 是 OLED/摄像头接口，以原理图为准。

### 4.2 P8（2×22，44 针）

| 针 | GPIO | 针 | GPIO | 针 | GPIO | 针 | GPIO |
|---|---|---|---|---|---|---|---|
| 1 | PE1 | 12 | PF2 | 23 | PA1 | 34 | PB1 |
| 2 | PE0 | 13 | PF5 | 24 | PC3 | 35 | PF12 |
| 3 | PE3 | 14 | PF4 | 25 | PA4 | 36 | PF11 |
| 4 | PE2 | 15 | PF7 | 26 | PA0 | 37 | PF14 |
| 5 | PE5 | 16 | PF6 | 27 | PA6 | 38 | PF13 |
| 6 | PE4 | 17 | PF9 | 28 | PA5 | 39 | PG0 |
| 7 | PC13 | 18 | PF8 | 29 | PC4 | 40 | PF15 |
| 8 | PE6 | 19 | PC0 | 30 | PA7 | 41 | PB13 |
| 9 | PF1 | 20 | PF10 | 31 | PB0 | 42 | PG1 |
| 10 | PF0 | 21 | PC2 | 32 | PC5 | 43 | GND |
| 11 | PF3 | 22 | PC1 | 33 | PB2 | 44 | PB12 |

### 4.3 P9（2×22，44 针）

| 针 | GPIO | 针 | GPIO | 针 | GPIO | 针 | GPIO |
|---|---|---|---|---|---|---|---|
| 1 | PB9 | 12 | PG11 | 23 | PC10 | 34 | PG6 |
| 2 | PB8 | 13 | PG10 | 24 | PA15 | 35 | PG5 |
| 3 | PB7 | 14 | PG9 | 25 | PA14 | 36 | PG4 |
| 4 | PB6 | 15 | PD7 | 26 | PA13 | 37 | PG3 |
| 5 | PB5 | 16 | PD6 | 27 | PA8 | 38 | PG2 |
| 6 | PB4 | 17 | PD5 | 28 | PC9 | 39 | PD13 |
| 7 | PB3 | 18 | PD4 | 29 | PC8 | 40 | PD12 |
| 8 | PG15 | 19 | PD3 | 30 | PC7 | 41 | PD11 |
| 9 | PG14 | 20 | PD2 | 31 | PC6 | 42 | PB15 |
| 10 | PG13 | 21 | PC12 | 32 | PG8 | 43 | PB14 |
| 11 | PG12 | 22 | PC11 | 33 | PG7 | 44 | GND |

### 4.4 剩余 IO/选择口

| 接口 | 形式 | 引脚/信号 |
|---|---|---|
| P10 | 2×2 | 1=PA10/USART1_RX，2=TXD(CH340)，3=PA9/USART1_TX，4=RXD(CH340) |
| P2 | 2×3 | PB10/USART3_TX、PB11/USART3_RX 与 ATK 模块 GBC_RX/GBC_TX 选择（V3.5）；版本差异需对照实物 |
| P4 | 2×3 | PA2/USART2_TX、PA3/USART2_RX 与 RS485 RX/TX 选择 |
| P5 | 2×3 | PA11/USB_D-、PA12/USB_D+ 与 CAN_RX/CAN_TX 选择 |
| P3 | 1×18 | OLED/摄像头接口（PA4、PA6、PC6/7/8/9/11、PE5/6、PG9/15、PA8、PD6/7 等） |
| VOUT1 | 2×3 | 3.3 V 输入/输出；电压/GND 列向需实物万用表确认（C） |
| VOUT2 | 2×3 | 5 V 输入/输出；电压/GND 列向需实物万用表确认（C） |

## 5 板载资源冲突矩阵

| 板载资源 | 占用引脚 | 对本项目的处置 |
|---|---|---|
| SWD（JTMS/JTCK） | PA13（P9-26）、PA14（P9-25） | 必须保留 |
| JTAG 附加脚 | PA15（P9-24）、PB3（P9-7）、PB4（P9-6） | 建议保留；若复用须禁用 JTAG 并保留 SWD |
| RTC 32.768 kHz 晶振 | PC14、PC15 | 不可用 |
| USB 转串口/一键下载 | PA9/PA10（P10） | 保留；UART1 可承担本项目通信（需调整 P10 跳线） |
| USB/CAN 选择 | PA11/PA12（P5） | 当前不用 CAN/USB HOST，可待用户裁决复用 |
| I2C1（24C02/磁力计/音频） | PB8/PB9 | 避免占用 |
| SPI FLASH 25Q128 | PB3/PB4/PB5/PB12 | 避免；PB12 为片选不建议复用 |
| TF/SDIO | PC8、PC9、PC10、PC11、PC12、PD2 | 若保留 TF 卡功能则不可占用 |
| 以太网 YT8512C | PA1、PA7、PC1、PC4、PC5、PG11、PG13、PG14、PD3 | 校赛不用以太网；复用前需停用/复位相关电路，待用户裁决 |
| 音频 ES8388 | PB12、PB13、PC2、PC3、PC6 | 可复用但需停用音频相关外设 |
| TFTLCD 触摸/背光 | PB0、PB1、PB2、PF11、PC13、PB15 | 不插 LCD 时可复用；PB15 亦为背光 |
| OLED/摄像头接口 | PA4、PA6、PC6/7/8/9/11、PE5/6、PG9、PG15、PA8、PD6/7 | 不插屏/摄像头时可复用 |
| 按键/WK_UP | PE2/3/4、PA0 | 可复用但按键会同时触发，需裁决 |
| LED/蜂鸣器/光敏 | PF9/PF10/PF8/PF7 | 可复用输出（LED 会被同时点亮） |
| 无线接口 NRF24L01 | PG6、PG7、PG8 | 不插无线模块时可复用 |
| 单总线/红外 | PG9、PA8 | 不插 DHT11/红外时可复用 |

## 6 与本项目信号面的对应

已确认方案的核心信号面约为：

- 输出 15 路：STEP_X/Y/Z、DIR_X/Y/Z、ENABLE_X/Y/Z、BARRIER_PWM_1..4、GRIP_PWM；
- 预留输出：WRIST_PWM（默认 DNP）、LIGHT_EN；
- 输入 10 路：X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN、ESTOP_FB、START_SIG、MANUAL_RESET_SIG；
- 通信：UART_TX/RX；
- 可选反馈：X/Y/Z 驱动 FAULT/READY、夹爪/补光反馈、AUX 等。

详细 GPIO/定时器分配属于下一阶段任务（`docs/design/stm32f407-pin-timer-allocation.md`），本文件只提供证据基线与冲突矩阵。

## 7 待确认项

1. 实物板卡身份：已确认是 M144Z-M4 最小系统板（82.8×51.2，JP1/JP2）。最小系统板官方原理图/针序仍未取得（C）。
2. 排针版本差异：V3.4 与 V3.5 的 P2 等选择口存在版本差异，对插面以实物丝印和万用表为准。
3. VOUT1/VOUT2 的电压/GND 列向（C）：以实物测量为准。
4. 安装孔与排母实测间距（C）：官方 A 盘没有 PCB 源工程，板框与安装孔尺寸需实物测量或官方 PCB 工程补充。
5. 板载以太网、音频、TF、OLED、触摸等未使用资源是否允许停用后复用其 GPIO，需用户最终裁决。

## 8 验证记录

- 使用 pdftotext 与 -bbox 坐标提取官方原理图文本，重建 P7/P8/P9/P2/P3/P4/P5/P10/VOUT 排针映射；P8/P9 表用 V3.4 与 V3.5 交叉核对一致。
- 解析官方 IO 引脚分配表 xlsx（Sheet1，116 行），得到每个 GPIO 的板载连接资源与独立性标志。
- 工作区 EDA 盘点输出为零个现存工程，已在第 2 节记录。

本文件不虚构 GPIO、排针号、器件值或额定值；所有待定项保持未确认状态。

