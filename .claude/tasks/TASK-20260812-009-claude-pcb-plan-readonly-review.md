# TASK-20260812-009：Claude PCB 方案只读审核

> 状态：Claude 审核完成，意见已对账。  
> 创建日期：2026-08-12。  
> 任务等级：L3 有限试行；仅文档静态审核，不授权采购、投板、接线、上电、烧录或实机运动。

## 1. 目标

对 `docs/design/pcb方案-17HS4401版.md` 进行独立只读审核，确认它是否准确继承已确认执行器型号和既有安全/接口边界，并找出会阻止进入 KiCad 候选原理图阶段的问题。

## 2. 审核对象与事实基线

| 类别 | 文件 | 用途 |
|---|---|---|
| 被审方案 | `docs/design/pcb方案-17HS4401版.md` | 本次唯一被审方案稿 |
| PCB 基线 | `docs/design/modular-pcb-design.md` | 载板边界、功能接口和 DNP 门禁 |
| 硬件基线 | `docs/design/electrical-control-practical-hardware.md` | 参数卡、单电源与急停边界 |
| 需求汇总 | `电控/资料/要求汇总.md` | 已确认型号和系统约束 |
| 协作规则 | `docs/design/claude-codex-collaboration.md` | 交接、独立性和文档所有权 |
| 任务分析 | `docs/requirements/analysis.md` | 当前架构、决策与约束 |

已确认事实：X/Y 为 `17HS4401`（NEMA17、1.8°、1.7A/相、40N·cm）；夹爪为 `DS3120MG` 数字舵机，PWM 开合、旋转默认关闭。A4988 仍是 X/Y 的候选 DNP 模块位，不是最终驱动。

## 3. 权限与输出

| 角色 | 权限/职责 |
|---|---|
| Claude | 只读审核所有输入；仅新建本次审查记录。 |
| Codex | 已完成方案起草；后续仅根据被接受的意见对账。 |
| 用户 | 对采购、投板、接线、上电和任何硬件变更作最终裁决。 |

Claude 只允许新建：

`.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md`

不得修改 `docs/design/pcb方案-17HS4401版.md`、任何生产代码、任务文件、计划文件或历史审查记录。

## 4. 验收条件

审核记录必须给出：总体裁决、按 P0/P1/P2 排序的发现项、精确文件定位、事实/推断/建议/未知区分、采纳/驳回/待外部输入分类、允许继续的范围、仍禁止的硬件动作及独立性声明。

## 5. 审核结果与对账状态

- Claude 独立审核记录：`.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md`
- Codex 预审与对账记录：`.claude/reviews/REVIEW-20260812-011-codex-pcb-pre-review.md`
- P1-01：用户裁决采用方案 A；`J_DRV_X_CTRL`、`J_DRV_Y_CTRL` 已进入两份 PCB 方案文档，默认 DNP，A4988 与板外驱动器二选一。
- P2-01：拓扑统一为 `STEP/DIR/ENABLE` 及可选反馈。
- P2-02：`J_ESTOP_FB` 统一为 `ESTOP_FB`、`GND_LOGIC`、可选反馈回路参考电源。
- P2-03：预留 `J_BARRIER_READY_IN` / `J_AUX_IN_n`；最终判据仍待机械/电控确认，仅 PWM 不得产生 `BARRIER_READY`。
- 当前阶段：允许进入 KiCad 候选原理图草图；仍禁止采购、投板、正式接线、上电、烧录和实机运动。

## 可复制给 Claude 的提示词

```text
请对工创赛智能分拣装置的 PCB 方案进行独立只读审核。

工作区：
C:\Users\29845\Desktop\工创赛

任务：
审核 `docs/design/pcb方案-17HS4401版.md` 是否能作为 KiCad 候选原理图输入。目标是发现事实冲突、安全边界遗漏、接口不闭合和过早冻结的参数；不是设计正式 PCB，更不是采购、投板或实机操作。

本任务为 L3 有限试行。开始前调用并遵守：
1. using-superpowers
2. code-review
3. verification-before-completion

若 Skill 缺失，记录真实缺失并使用最接近的安全流程；不得声称已调用未提供的 Skill。

完整读取：
- 当前 `AGENTS.md` 与 `CLAUDE.md`
- `docs/requirements/analysis.md`
- `docs/design/claude-codex-collaboration.md`
- `docs/design/pcb方案-17HS4401版.md`
- `docs/design/modular-pcb-design.md`
- `docs/design/electrical-control-practical-hardware.md`
- `电控/资料/要求汇总.md`
- `.claude/tasks/TASK-20260812-009-claude-pcb-plan-readonly-review.md`

必须以以下事实为基线：
- X/Y 电机已确认：`17HS4401`，NEMA17、1.8°、1.7A/相、40N·cm。
- 夹爪已确认：`DS3120MG` 数字舵机，PWM 开合，旋转默认关闭。
- A4988 只可作为 X/Y 的候选 DNP 模块位；1.7A/相是限流和散热边界，未完成实测不得定型。
- 用户已裁决采用方案 A：X/Y 各预留默认 DNP 的板外驱动低能量控制接口，包含 `STEP/DIR/ENABLE/GND_LOGIC` 及可选反馈；A4988 与板外驱动器必须二选一，不能同时连接或共同驱动同一电机。
- 整机只有一套内置电源；逻辑与危险动力分路。
- 急停主回路必须独立硬件切断危险动力正极，不得切公共参考地；逻辑保持供电，解除急停不得自动恢复旧任务或危险动力。
- Z 轴执行器、挡板舵机、限位、供电峰值、保护器件、线束、连接器、GPIO/排针、铜厚和线宽仍未冻结。

只允许新建：
`.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md`

不得修改被审方案、任意其他文档、代码、测试、计划、任务记录或历史审查文件。不得采购、投板、接线、上电、烧录、运行固件或执行实机运动。

重点检查：
1. 17HS4401 和 DS3120MG 是否准确写入，且没有把供应商资料或实测前的属性伪装成已确认事实；
2. A4988 是否始终是候选/DNP，是否包含限流、热、负载、干扰、急停门禁和失败后的替代路径；
3. X/Y/Z 通道的 STEP/DIR/ENABLE、动力、反馈与电机网络是否隔离，Z 轴是否被错误定型；
4. 单一电源、逻辑/危险动力分区、急停只切正极而不切公共参考地、逻辑保电和不自动恢复是否明确且无矛盾；
5. DS3120MG 与四路挡板的 PWM 控制和板外动力边界是否清楚，是否误把 PWM 发出当作到位或夹持成功；
6. 是否猜写 GPIO、排针、A4988 针序、电压、保险、端子额定、线宽、铜厚、Z 轴驱动或防坠方案；
7. KiCad 分页、连接器功能、DNP 标记、测试点和布局规则是否足以进入候选原理图草图；
8. 高能量测试点是否避免普通可触及探针焊盘，是否有额定和防护限制；
9. 是否存在与既有 PCB/硬件基线冲突、文档漂移或遗漏的冻结门禁。

输出要求：
- 先给总体裁决：通过 / 有条件通过 / 驳回；
- 再按 P0、P1、P2 列出发现项，每项包含文件定位、事实依据、风险和最小修正建议；
- 清晰区分事实、推断、建议和未知；
- 对每项标记接受 / 拒绝 / 待机械或供应商输入；
- 说明允许继续的范围和仍禁止的硬件动作；
- 记录实际读取的文件及检查方法；
- 写明独立性：Claude 仅做只读审核，未参与本次方案起草；若无法真正独立，标注“弱独立性”。

审查结束后只创建上述 REVIEW 文件。不要在聊天中代替审查记录，也不要直接修改方案。
```
