# M144Z-M4 载板符号导入包

状态：G1 候选原理图输入包；不是 M144Z-M4 官方原生库，也不是已冻结 PCB。

## 直接使用的文件

### 0. 立创 EDA 标准版直接导入（你截图中的入口）

在 `文件 → 导入 → KiCad...` 中选择：

- `M144Z-M4_CARRIER.sch`

这个文件已经是一个完整的 KiCad Legacy 原理图，内部放置了 `JP_L` 和 `JP_R` 两个符号；同目录的 `M144Z-M4_CARRIER-cache.lib` 是它的配套符号缓存库。导入后应能直接看到两组 2×25 排针和 GPIO 名称。

如果导入窗口只接受新版 KiCad 工程，再使用下面的 `.kicad_sym` 符号库方式。

### 1. 立创 EDA / KiCad 兼容符号库

- `M144Z-M4_CARRIER.lib`：Legacy KiCad/Eeschema 库，优先尝试导入这个文件。
- `M144Z-M4_CARRIER.kicad_sym`：KiCad 新版符号库，若当前立创 EDA 版本支持 KiCad 新库则使用这个文件。
- `M144Z-M4_CARRIER.sch`：完整 Legacy KiCad 原理图，适合立创 EDA 标准版的“导入 → KiCad...”入口。
- `M144Z-M4_CARRIER-cache.lib`：上面 `.sch` 文件配套的缓存库，不要单独放置。

库中有两个应放入原理图的符号：

- `M144Z_M4_JP_L`：左侧 2×25 排针，奇数针为外列，偶数针为内列。
- `M144Z_M4_JP_R`：右侧 2×25 排针，奇数针为外列，偶数针为内列。

放置符号后，针号就是排针实物针号，针脚旁的文字就是 GPIO/板载脚名。例如：

```text
M144Z_M4_JP_R 的 1 脚 = PC6 = STEP_X
M144Z_M4_JP_R 的 2 脚 = PC7 = DIR_Y
M144Z_M4_JP_L 的 41 脚 = PA3 = UART_MAIN_RX
M144Z_M4_JP_L 的 44 脚 = PA2 = UART_MAIN_TX
```

在立创 EDA 中按“导入外部库 / KiCad Legacy Library（`.lib`）”选择 `M144Z-M4_CARRIER.lib`，然后搜索上面两个符号名。不同版本菜单名称可能不同；如果标准版不接受 `.lib`，改用 `M144Z-M4_CARRIER.kicad_sym` 或先用 KiCad 转换。

## 2. 完整核对资料

- `M144Z-M4_CARRIER_pinmap.csv`：100 个物理针位逐针表。
- `M144Z-M4_CARRIER_pinmap.svg`：左右两组 2×25 的可视针位图。
- `G1候选原理图绘制清单-供电更新版.xlsx`：原清单 + `完整物理针位` + `导入文件` + `供电选择` 工作表。

## 3. 当前能确认到什么程度

- 已确认：STM32 GPIO/定时器功能来自用户实测记录；例如 `PC6=TIM8_CH1`、`PB6=TIM4_CH1`、`PE5=TIM9_CH1`、USART3/USART2。
- 供电候选：外部 DC/DC 输出 5V 作为 `VLOGIC_5V` 主方案；外部稳定 3.3V 作为 `VLOGIC_3V3_BACKUP` 备选，必须与 5V/USB 互斥。
- 候选针位：`JP_L/JP_R` 物理位置来自用户手工抄录，`JP_R-1=PC6 外列`、`JP_R-2=PC7 内列`按用户确认记录。
- 未确认：M144Z-M4 官方针序、排针到 MCU 的连续性、连接器机械尺寸，以及立创 EDA GUI 对这两个库文件的实际导入结果。

因此，这个包可以开始画 G1 候选原理图，但不能据此宣称原理图冻结、PCB 布局、投板或硬件验证通过。冻结前必须用 1:1 打印和万用表连续性把 `JP_L/JP_R` 全部核对一遍。
