# M144Z-M4 可导入针位符号包交付记录

## 原始需求

用户要求得到可以直接导入立创 EDA、并且能在原理图中直接看到 M144Z-M4 排针物理针号与 GPIO 对应关系的文件，而不是只有逻辑 GPIO 的绘制清单。

## 问题本质

旧版 `G1候选原理图绘制清单.xlsx` 只覆盖已使用信号，未提供完整 2×25 `JP_L/JP_R` 的 EDA 符号，也没有把针号作为符号 pin number。它适合人工抄表，不适合直接放入 EDA 画图。

## 本次产出

- `docs/design/M144Z-M4_CARRIER.lib`
- `docs/design/M144Z-M4_CARRIER.sch`（针对嘉立创 EDA 标准版“导入 → KiCad...”入口的完整 Legacy 原理图）
- `docs/design/M144Z-M4_CARRIER-cache.lib`（上述 `.sch` 的配套缓存库）
- `docs/design/M144Z-M4_CARRIER.kicad_sym`
- `docs/design/M144Z-M4_CARRIER_pinmap.csv`
- `docs/design/M144Z-M4_CARRIER_pinmap.svg`
- `docs/design/M144Z-M4_CARRIER_IMPORT_README.md`
- `docs/design/G1候选原理图绘制清单-含完整针位.xlsx`

两个符号分别对应 `JP_L` 和 `JP_R`，每个符号 50 个 pin，奇数为外列、偶数为内列。完整 CSV 共 100 行且物理针位唯一。

## 验收结果

- `JP_R-1=PC6`、`JP_R-2=PC7`：通过生成后反查。
- `JP_L-9=PD9`、`JP_L-10=PD8`：通过生成后反查。
- CSV：100 行，100 个唯一（排针、物理针号）组合。
- Excel：包含原有页、`完整物理针位`（100 行数据）和 `导入文件` 页。
- 立创 EDA 原生 GUI 导入：本环境未执行，证据状态为“未验证”；不得表述为已实开。

## 证据边界

GPIO/定时器功能是用户实测记录；排针物理位置是用户手工抄录与确认记录。M144Z-M4 官方针序及排针到 MCU 的连续性仍待官方资料或万用表验证。该包只解除“没有可视/可导入针位符号”的文档缺口，不改变 G1 候选阶段边界。

## 供电字段修订

后续审核发现旧版完整针位表把 `POWER_OR_BOARD` 和 `UNASSIGNED` 放进了可能被误当作网络标签的字段。已生成供电更新版：

- 普通未分配 GPIO 的“设计网名”留空，状态写明“不用则放不连接标记；备用则使用独立网名”。
- `GND` 使用 `GND_LOGIC`。
- `5V` 使用 `VLOGIC_5V`，作为外部 DC/DC 5V 主供电候选。
- `3.3V` 使用 `VLOGIC_3V3_BACKUP`，仅作为备选，必须与 5V/USB 互斥。
- `UREF/RST/VBAT` 不贴通用网络名，分别按 TBD/NC/`MCU_NRST` 条件处理。
- 新文件为 `G1候选原理图绘制清单-供电更新版.xlsx`，增加 `供电选择` 页。
