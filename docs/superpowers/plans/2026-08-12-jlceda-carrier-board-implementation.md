# 嘉立创 EDA 载板实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于已确认的三步进轴、四挡板舵机、三指夹爪和安全边界，完成探索者 STM32F407ZGT6 的真实 GPIO/定时器分配及可打开、可审查的嘉立创 EDA 载板原理图。

**Architecture:** 探索者开发板通过排母安装到载板；载板承担低能量控制、输入调理、默认安全态和测试接口。X/Y A4988 仅为候选并各自保留板外驱动后备，Z 驱动、舵机动力、DC/DC 和急停主回路全部板外。

**Tech Stack:** 正点原子探索者 STM32F407ZGT6 官方资料、STM32F407 定时器/GPIO 复用、嘉立创 EDA（标准版或专业版，以本机环境/现有工程识别结果为准）、Markdown 设计记录、EDA ERC/网络检查。

---

## 文件结构

- Create: `docs/design/explorer-f407-source-audit.md`，记录官方资料、版本、URL、板载资源和证据强度。
- Create: `docs/design/stm32f407-pin-timer-allocation.md`，保存功能到 GPIO、定时器、排针和 EDA 网名的最终映射。
- Modify: `docs/requirements/analysis.md`，只同步经用户裁决的新事实与仍未知项。
- Modify: `docs/design/modular-pcb-design.md`，同步 Z 步进轴、六路 PWM、六路限位和腕部 DNP。
- Modify: `docs/design/pcb方案-17HS4401版.md`，同步主方案接口与门槛。
- Modify: `docs/design/electrical-control-practical-hardware.md`，更新执行器参数卡状态。
- Modify: `电控/资料/要求汇总.md`，修正旧的 Z 轴未知描述和夹爪策略。
- Create: `电控/pcb/jlceda-carrier/` 下的嘉立创 EDA 原理图工程，具体扩展名由识别出的 EDA 版本决定。
- Create: `docs/reports/jlceda-schematic-review.md`，记录 ERC、逐网检查和 G1-G4 门槛。

### Task 1: 核对探索者开发板官方资料

**Files:**
- Create: `docs/design/explorer-f407-source-audit.md`

- [ ] **Step 1: 盘点本地工程和 EDA 文件**

Run:

```powershell
rg --files | rg "(?i)(easyeda|jlceda|\.json$|\.kicad_sch$|\.kicad_pcb$|\.epro$|gerber|\.gbr$)"
```

Expected: 列出真实存在的 EDA/生产文件；零输出时在审计文件中明确“工作区未发现现有 EDA 工程”，不得推断已有 PCB。

- [ ] **Step 2: 获取并记录官方资料**

在 `docs/design/explorer-f407-source-audit.md` 中逐项记录：资料名称、官方 URL、版本/发布日期、访问日期、与本项目相关的页码或表格、证据等级。至少覆盖官方原理图、扩展排针、尺寸/安装信息和板载资源。

- [ ] **Step 3: 建立板载冲突矩阵**

在同一文件中列出 TF 卡、SWD、板载 USB 串口、晶振、外部存储及其他实际启用资源对应的 STM32 引脚，并标记“必须保留 / 可禁用但需用户裁决 / 当前不用”。

- [ ] **Step 4: 验证审计文件无无来源结论**

Run:

```powershell
rg -n "官方|URL|版本|访问日期|TF|SWD|USB|排针" docs/design/explorer-f407-source-audit.md
```

Expected: 每类证据均有命中；所有第三方资料明确标注为交叉验证。

- [ ] **Step 5: 提交单一主题变更**

```powershell
git add docs/design/explorer-f407-source-audit.md
git commit -m "docs: audit explorer f407 board resources"
```

### Task 2: 完成 GPIO 与定时器分配

**Files:**
- Create: `docs/design/stm32f407-pin-timer-allocation.md`
- Read: `docs/design/explorer-f407-source-audit.md`

- [ ] **Step 1: 先写资源覆盖清单**

在分配文件中列出以下功能且每项只出现一次：`STEP_X/Y/Z`、`DIR_X/Y/Z`、`ENABLE_X/Y/Z`、`BARRIER_PWM_1..4`、`GRIP_PWM`、`WRIST_PWM`、`X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN`、`ESTOP_FB`、`START_SIG`、`MANUAL_RESET_SIG`、补光、正式通信、备用 UART 和驱动反馈。

- [ ] **Step 2: 建立完整映射表**

表头固定为：

```markdown
| 功能 | 外设/定时器通道 | STM32 GPIO | 探索者排针 | 上电默认态 | 5V 容忍 | 板载冲突 | 嘉立创 EDA 网名 | 选择依据 |
```

每个分配都必须能回溯到官方资料；不确定项标为“未分配”，不得用猜测填满表格。

- [ ] **Step 3: 证明定时器方案可用**

记录三轴 STEP 的最大目标步频、所用定时器时钟、分频/周期范围和最坏中断负载；记录四挡板、夹爪、腕部六路 PWM 的帧周期策略及同步更新方法。若采用 GPIO 软件步进，必须给出最坏抖动预算和三轴协调依据。

- [ ] **Step 4: 运行静态覆盖检查**

Run:

```powershell
rg -n "STEP_X|STEP_Y|STEP_Z|BARRIER_PWM_1|BARRIER_PWM_4|GRIP_PWM|WRIST_PWM|X_HOME|Z_DOWN|ESTOP_FB|SWD|TF" docs/design/stm32f407-pin-timer-allocation.md
```

Expected: 所有关键功能和保留资源均有映射或明确未分配原因；不存在重复 GPIO 或未解释的复用冲突。

- [ ] **Step 5: 提交单一主题变更**

```powershell
git add docs/design/stm32f407-pin-timer-allocation.md
git commit -m "docs: allocate stm32f407 carrier pins and timers"
```

### Task 3: 同步现行设计基线

**Files:**
- Modify: `docs/requirements/analysis.md`
- Modify: `docs/design/modular-pcb-design.md`
- Modify: `docs/design/pcb方案-17HS4401版.md`
- Modify: `docs/design/electrical-control-practical-hardware.md`
- Modify: `电控/资料/要求汇总.md`

- [ ] **Step 1: 修正执行器事实**

将旧的“Z 轴执行器未知”改为“Z 轴确定为步进电机，具体型号/驱动/防坠仍未知”；把挡板固定为四路独立 PWM 同步更新；把夹爪固定为 DS3120MG 驱动三指开合；加入默认 DNP 的 `WRIST_PWM`；明确六个储物盒无电控接口。

- [ ] **Step 2: 同步连接器和网名**

统一使用 `STEP_Z/DIR_Z/ENABLE_Z`、`BARRIER_PWM_1..4`、`GRIP_PWM`、`WRIST_PWM`、`X_HOME/X_END/Y_HOME/Y_END/Z_UP/Z_DOWN`。不得同时保留语义相同的 `STEP_3` 与 `STEP_Z` 作为两个网络；历史说明可写“原 STEP_3 现命名为 STEP_Z”。

- [ ] **Step 3: 保留未知与安全边界**

确认文档仍明确：Z 电机/驱动型号、挡板舵机参数、限位实物、电源额定、A4988 针序、连接器和铜宽未冻结；舵机动力、DC/DC、急停主回路和 Z 驱动均在载板外。

- [ ] **Step 4: 运行跨文档一致性检查**

Run:

```powershell
rg -n "Z 轴.*未知|STEP_3|旋转默认关闭|4路独立PWM|固定储物盒|WRIST_PWM" docs/requirements/analysis.md docs/design/modular-pcb-design.md docs/design/pcb方案-17HS4401版.md docs/design/electrical-control-practical-hardware.md 电控/资料/要求汇总.md
```

Expected: 旧网名只在迁移说明中出现；所有现行表述与本方案一致，没有把具体型号/额定值补成事实。

- [ ] **Step 5: 提交单一主题变更**

```powershell
git add docs/requirements/analysis.md docs/design/modular-pcb-design.md docs/design/pcb方案-17HS4401版.md docs/design/electrical-control-practical-hardware.md 电控/资料/要求汇总.md
git commit -m "docs: freeze actuator interface architecture"
```

### Task 4: 建立嘉立创 EDA 原理图工程

**Files:**
- Create: `电控/pcb/jlceda-carrier/` 下的原生工程文件
- Read: `docs/design/stm32f407-pin-timer-allocation.md`

- [ ] **Step 1: 识别 EDA 版本与原生格式**

从本机已安装软件或现有项目识别嘉立创 EDA 标准版/专业版。若二者都无法识别且文件格式会受影响，只向用户询问版本；不得生成伪原生文件。

- [ ] **Step 2: 建立层级页**

创建 `TOP`、`MCU_CARRIER`、`LOGIC_POWER`、`DRV_X_A4988_CANDIDATE`、`DRV_Y_A4988_CANDIDATE`、`EXTERNAL_DRIVER_CTRL`、`SERVO_GRIPPER_LIGHT`、`SAFETY_AND_INPUTS`、`COMM_DEBUG_TEST` 和 `CONNECTOR_SCHEDULE` 页面。

- [ ] **Step 3: 绘制低能量控制网络**

按分配表连接三轴控制、六路 PWM、六路限位、急停反馈、启动/人工复位、通信和测试点。所有运动输出具有硬件默认禁止状态；板外输入只使用已由最终电平支持的调理电路，未定器件保持 DNP/待参数标记。

- [ ] **Step 4: 绘制候选驱动边界**

X/Y A4988 页面标记 `CANDIDATE - DNP UNTIL VERIFIED`，不得虚构 `FAULT`；对应板外驱动接口与 A4988 有明确互斥装配说明。Z 页面仅出现低能量控制和可选反馈，不出现 Z 动力或电机相线。

- [ ] **Step 5: 检查工程真实可打开**

使用对应嘉立创 EDA 打开保存后的工程，确认页面、符号、网名和中文注释未丢失。若当前工具无法打开原生工程，停止声称完成工程，改为交付逐页实施表、完整网络表、连接器针脚表和封装核对表。

- [ ] **Step 6: 提交单一主题变更**

```powershell
git add 电控/pcb/jlceda-carrier
git commit -m "feat: add jlceda carrier schematic"
```

### Task 5: ERC、逐网审查和门槛结论

**Files:**
- Create: `docs/reports/jlceda-schematic-review.md`
- Read: `docs/superpowers/specs/2026-08-12-actuator-carrier-interface-design.md`

- [ ] **Step 1: 执行自动 ERC**

使用已识别的嘉立创 EDA ERC 功能并保存错误、警告和排除项。工具无法自动执行时，明确记录“未执行自动 ERC”，不得写“通过”。

- [ ] **Step 2: 完成逐网检查**

逐项确认：三轴互不短接；四挡板、夹爪和腕部六路 PWM 独立；储物盒零网络；逻辑和危险动力不误并；急停主回路不经过载板；TF、SWD、UART 无冲突；X/Y 两种驱动方式互斥。

- [ ] **Step 3: 判定 G1-G4**

按设计文件第 8 节逐项列出证据。没有板框、封装实物核对、电流/温升计算和台架安全测试时，最高只能给出相应较低门槛，不得以文档完整替代实物证据。

- [ ] **Step 4: 运行文本和工作区检查**

Run:

```powershell
git diff --check
git status --short
```

Expected: 本任务文本无空白错误；工作区中的其他用户改动保持原样，没有被回滚或混入本任务提交。

- [ ] **Step 5: 提交审查记录**

```powershell
git add docs/reports/jlceda-schematic-review.md
git commit -m "test: document carrier schematic review"
```

