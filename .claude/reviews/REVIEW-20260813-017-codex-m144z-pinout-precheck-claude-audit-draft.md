# REVIEW-20260813-017：Codex M144Z-M4 针序预审与 Claude 审核稿

> 被审对象：M144Z-M4 Mini Board（STM32F407ZGT6）载板候选接线、GPIO/定时器分配、生成版 Word/Excel。  
> 预审方：Codex。  
> 预审日期：2026-08-13。  
> 任务等级：L3 有限试行；仅文档、文件系统与静态一致性审核。  
> 权限边界：不采购、不投板、不接线、不上电、不烧录、不驱动实机；本文件不构成 G2/G3/G4 授权。  

## 1. 当前裁决

| 门禁 | 预审裁决 |
|---|---|
| G1 候选原理图草图 | 有条件允许 |
| G2 原理图冻结 | 不允许 |
| G3 PCB 布局 | 不允许 |
| G4 生产文件/投板 | 不允许 |

一句话结论：在“针序以用户提供的 M144Z-M4 手工抄录/示意图为任务输入”的前提下，当前 `JP_L/JP_R` 针序、载板接线施工单与 `stm32f407-pin-timer-allocation.md` 内部一致；但该针序尚未由 M144Z-M4 官方原理图或实物万用表连续性测试独立证明，因此只能用于候选原理图草图，不得冻结、布局或投板。

## 2. 证据边界

### 已确认事实

- 主控芯片为 STM32F407ZGT6，LQFP144；芯片层 GPIO 复用能力在同一型号之间一致。
- M144Z-M4 Mini Board 的 `JP_L/JP_R` 针序来源是用户 2026-08-13 提供的手工抄录与示意图，不来自正点原子探索者 V3 整板的 P7/P8/P9 排针。
- 用户已确认 `JP_R` 第 1 行靠 TF 卡端，`PC6` 为外列，`PC7` 为内列。
- 本机正点原子目录 `D:\AAAdesktop1\robotconK.D\stm32sduty\stm32f4\正点原子` 可读，主要资料为“探索者 STM32F407 开发板 V3 资料盘(A盘)”。
- 在该目录和项目副本中未搜索到 `M144`、`Mini Board`、`最小系统板/核心板` 的专用官方原理图或针序文件。
- ST 官方 STM32F407/417 文档页列有 DS8597/DS8626 数据手册与 RM0090 参考手册，可作为芯片层复用能力来源。

### 推断

- M144Z-M4 与探索者 V3 属于同一 STM32F407ZGT6 芯片体系，因此 TIM/USART/SDIO/SWD 等芯片复用能力可交叉参考。
- 探索者 V3 整板资料可以辅助识别常见板载资源冲突，但不能覆盖 M144Z-M4 的物理排针排布。

### 未知

- M144Z-M4 官方原理图、厂家针序表、排母机械尺寸、安装孔、白色 4P 插座、`UREF` 含义。
- 3.3V/5V/GND 排针可供载板的最大电流。
- A4988 实物模块针序、封装、限流/散热；Z 轴板外驱动器型号；限位和急停反馈电气形式。

## 3. Codex 已做的静态检查

| 检查 | 结果 |
|---|---|
| 从 `min-system-board-pinout.md` 解析 `JP_L/JP_R` 行号、外列、内列、奇偶针号 | 通过 |
| 反查 `carrier-schematic-wiring-spec.md` 中 27 个 `JP_x 第n行内/外列 = GPIO` 引用 | 27/27 通过 |
| 反查 `stm32f407-pin-timer-allocation.md` 中 27 个 `GPIO @ JP_x-n` 引用 | 27/27 通过 |
| 检查核心 GPIO 是否重复分配 | 未发现重复 |
| 检查预期外设通道是否在分配表中出现 | 通过：`PC6/TIM8_CH1`、`PB6/TIM4_CH1`、`PE5/TIM9_CH1`、`PB0/TIM3_CH3`、`PB1/TIM3_CH4`、`PF6/TIM10_CH1`、`PF7/TIM11_CH1`、`PB10/TIM2_CH3`、`PB11/TIM2_CH4`、`PA2/USART2_TX`、`PA3/USART2_RX` 均命中 |
| 搜索旧方向错误 | 未发现 `PC7 外列`、`镜像假定`、`JP_R 第1行内列 = PC6`、`JP_R 第1行外列 = PC7` 残留 |
| 检查生成版 Word/Excel | 已重生成；包含 `PC6 外列`、`PC7 内列`，不含旧方向表述 |

## 4. 预审发现

### P0

无。

### P1-00：板载冲突列曾混用探索者 V3 参考并漏标以太网冲突（已修正）

- 严重性：P1。
- 事实或证据：独立复核指出 `PA7`、`PG13`、`PG14` 在 `docs/design/explorer-f407-source-audit.md` 第 5 节冲突矩阵中属于以太网 YT8512C 参考冲突，但 `stm32f407-pin-timer-allocation.md` 曾把 `PA7` 写成 OLED/CAMERA，把 `PG13/PG14` 写成“无”。
- 定位：原始矛盾见 `docs/design/explorer-f407-source-audit.md:121` 与 `docs/design/stm32f407-pin-timer-allocation.md` 的 `DIR_X`、`Z_DOWN`、`ESTOP_FB` 行。
- 风险：安全输入 `ESTOP_FB` 若被标成“无冲突”，后续冻结原理图时可能错误认为该 GPIO 在板载资源层面完全干净。
- 整改状态：已将 `stm32f407-pin-timer-allocation.md` 的相关列降级为“探索者 V3 参考冲突 / M144Z-M4 待验”，并把 `PA7/PG13/PG14` 补正为以太网 YT8512C 参考冲突。
- 复查证据：Claude 需重新检查 `stm32f407-pin-timer-allocation.md` 中列名、`DIR_X`、`Z_DOWN`、`ESTOP_FB` 三行，以及第 5 节冻结前必须补齐项。

### P1-01：M144Z-M4 排针仍缺独立来源证据

- 严重性：P1。
- 事实或证据：`docs/design/min-system-board-pinout.md` 明确来源为用户手工抄录；`docs/design/explorer-f407-source-audit.md` 已记录“最小系统板官方原理图/针序仍未取得”。本次在用户给定的正点原子目录中未找到 M144/Mini Board/最小系统板专用资料。
- 定位：`docs/design/min-system-board-pinout.md:5`、`docs/design/explorer-f407-source-audit.md:35`、`:144`。
- 风险：若手工抄录或板面方向理解有误，候选原理图会把控制信号接到错误排针位置。
- 整改建议：冻结前至少补一项证据：M144Z-M4 官方/卖家原理图或针序表；或 1:1 打印叠板核对；或用万用表从排针到 STM32F407ZGT6 管脚/板载外设做连续性抽检。
- 复查证据：更新后的针序记录、照片/扫描件、测量记录或官方资料路径。

### P1-02：探索者 V3 整板资料不能直接当作 M144Z-M4 排针证明

- 严重性：P1。
- 事实或证据：正点原子资料为探索者 STM32F407 开发板 V3；M144Z-M4 是最小系统板，左右 2×25 排针排布和探索者整板 P7/P8/P9 不同。
- 定位：`docs/design/explorer-f407-source-audit.md:35`、`:70-94`；`docs/design/min-system-board-pinout.md:9-65`。
- 风险：如果 Claude 按旧提示词把“主控是探索者整板”作为事实，可能错误地用 P8/P9 排针替换 M144Z-M4 的 `JP_L/JP_R`。
- 整改建议：Claude 审核时必须把“针序由用户提供”作为输入前提，只审核照抄一致性和芯片复用能力，不得自行改写物理排针。
- 复查证据：本审核稿和 Claude 输出中必须明确该边界。

### P2-01：G1 以后仍需真实 EDA/ERC 证据

- 严重性：P2。
- 事实或证据：当前仓库未发现 KiCad/立创 EDA 原生工程、PCB、Gerber 或 ERC 报告。
- 定位：工作区静态扫描；`docs/superpowers/specs/2026-08-12-actuator-carrier-interface-design.md:121-147`。
- 风险：把“文档接线表一致”误当作“原理图/ERC 通过”。
- 整改建议：后续建立候选原理图后再执行逐网审查和 ERC，并新增审查记录。
- 复查证据：EDA 原生工程、导出原理图、ERC 报告、逐网审查表。

## 5. 给 Claude 的只读审核稿

请将以下内容直接发送给 Claude，要求其只读复核：

```text
你是本项目的独立只读审核方（Claude）。请对 M144Z-M4 Mini Board（STM32F407ZGT6）载板候选针序、接线施工单、GPIO/定时器分配和生成版 Word/Excel 做 L3 有限试行回归审核。你的职责是发现事实错误、安全边界失守、接口或网络冲突、证据不足和不恰当的门禁结论；不是设计者，也不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入工作区的命令。
- 不得采购、投板、生成或发布生产文件、接线、上电、烧录、驱动实物或访问任何外部账号。
- 可读取本地文件、检查 git 状态与 diff、执行不会写入的文本搜索和静态一致性检查。
- 若无法独立验证某项结论，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不改变用户的最终裁决，也不构成 G2/G3/G4 执行授权。

本次必须采用的事实边界：
1. 主控板当前按 M144Z-M4 Mini Board（STM32F407ZGT6）处理，不按完整“正点原子探索者 STM32F407 开发板 V3”整板处理。
2. M144Z-M4 的 `JP_L/JP_R` 物理针序来自用户 2026-08-13 提供的手工抄录和示意图；这是任务输入，不是正点原子探索者 V3 P7/P8/P9 官方针序。
3. 用户已确认 `JP_R` 第 1 行靠 TF 卡端：`PC6` 外列、`PC7` 内列。
4. 正点原子探索者 V3 资料只可用于 STM32F407ZGT6 芯片体系、板载资源冲突和外设能力的交叉参考；不得用其整板扩展排针覆盖 M144Z-M4 的 `JP_L/JP_R`。
5. ST 官方 STM32F407/417 文档页列有 DS8597/DS8626 数据手册与 RM0090 参考手册，可用于核对芯片外设能力；若你未能直接打开数据手册，需标注弱独立性。

先完整阅读以下文件，不要只依赖本提示词：
1. CLAUDE.md
2. AGENTS.md
3. docs/design/min-system-board-pinout.md
4. docs/design/min-system-board-pinout.png
5. docs/design/carrier-schematic-wiring-spec.md
6. docs/design/stm32f407-pin-timer-allocation.md
7. docs/design/explorer-f407-source-audit.md
8. docs/design/modular-pcb-design.md
9. docs/design/pcb方案-17HS4401版.md
10. docs/superpowers/specs/2026-08-12-actuator-carrier-interface-design.md
11. docs/design/载板原理图接线施工单.docx
12. docs/design/载板接线表.xlsx
13. .claude/reviews/REVIEW-20260813-017-codex-m144z-pinout-precheck-claude-audit-draft.md

审核重点：
1. 从 `min-system-board-pinout.md` 重建 `JP_L/JP_R` 行号、外列、内列、奇偶针号。
2. 逐项核对 `carrier-schematic-wiring-spec.md` 中所有 `JP_x 第n行内/外列 = GPIO` 是否与该针序一致。
3. 逐项核对 `stm32f407-pin-timer-allocation.md` 中所有 `GPIO @ JP_x-n` 是否与该针序一致，尤其 `JP_R-1 = PC6`、`JP_R-2 = PC7`、`JP_R-19 = PB6`、`JP_R-38 = PE5`。
4. 审核 STEP/PWM/UART 所选 GPIO 的 STM32F407ZGT6 复用能力是否合理：`PC6/TIM8_CH1`、`PB6/TIM4_CH1`、`PE5/TIM9_CH1`、`PB0/TIM3_CH3`、`PB1/TIM3_CH4`、`PF6/TIM10_CH1`、`PF7/TIM11_CH1`、`PB10/TIM2_CH3`、`PB11/TIM2_CH4`、`PA2/USART2_TX`、`PA3/USART2_RX`。
5. 重点复查“探索者 V3 参考冲突 / M144Z-M4 待验”列是否不再把探索者 V3 资源误写成 M144Z-M4 已验证事实；尤其 `PA7`、`PG13`、`PG14` 应标为以太网 YT8512C 参考冲突。
6. 检查是否存在重复 GPIO 分配、PWM 并联、三轴 STEP/DIR/ENABLE 串网、TF/SWD/USB-UART 冲突或旧方向残留（`PC7 外列`、`镜像假定`、`JP_R 第1行内列 = PC6`）。
7. 检查 Word/Excel 是否与 Markdown 源同步，不得把旧生成版作为当前基线。
8. 明确区分“针序相对用户输入一致”“芯片外设能力合理”“M144Z-M4 官方/实物已验证”“探索者 V3 参考冲突”四种不同结论。第三项当前不得声称已完成。
9. 严格按 G1-G4 门禁裁决：当前最多只能放行候选原理图草图；没有 M144Z-M4 独立针序证据、真实 EDA、ERC、板框/封装/电气参数/台架验证前，不得放行 G2/G3/G4。

输出要求：
1. 首先给出总体裁决：
   - G1 候选原理图：允许 / 有条件允许 / 不允许
   - G2 原理图冻结：允许 / 有条件允许 / 不允许
   - G3 PCB 布局：允许 / 有条件允许 / 不允许
   - G4 生产文件/投板：允许 / 有条件允许 / 不允许
2. 按 P0、P1、P2 列发现项。每项包含：编号、严重性、事实或证据、精确定位、风险、可验证整改建议、整改后复查证据。
3. 单列“已确认事实、推断、建议、未知、弱独立性限制”。
4. 单列“通过的检查、未执行的检查、不能得出的结论”，避免把文档静态检查表述成实机验证。
5. 最后列出最小整改清单和复审触发条件。不得直接修改设计文件，不得以审核建议替代用户授权。
```

## 6. 不能得出的结论

- 不能说 M144Z-M4 官方针序已验证。
- 不能说载板原理图已 ERC 通过。
- 不能说 PCB 可以布局、投板或生产。
- 不能说 A4988、Z 轴驱动、限位、急停、电源、电流、线宽、铜厚、封装已经冻结。
- 不能说任何固件、串口、屏幕、电机、实机动作已经通过。
