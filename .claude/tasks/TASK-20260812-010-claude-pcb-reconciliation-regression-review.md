# TASK-20260812-010：Claude PCB 对账后全面复审

> 状态：待 Claude 复审。  
> 创建日期：2026-08-12。  
> 任务等级：L3 有限试行；只允许文档静态审核，不授权采购、投板、接线、上电、烧录或实机运动。

## 1. 目标

在方案 A 和 Claude 上轮 P2 意见均已对账后，对当前 PCB 文档进行一次独立、全面的回归审核。目标是确认已关闭问题没有引入新冲突，明确是否仅可进入 KiCad 候选原理图草图，并找出任何仍会阻止原理图冻结的缺口。

## 2. 审核对象与当前裁决

| 类别 | 文件 | 作用 |
|---|---|---|
| 当前方案 | `docs/design/pcb方案-17HS4401版.md` | 被审对象 |
| PCB 基线 | `docs/design/modular-pcb-design.md` | 接口、网络、DNP、KiCad 分页与门禁基线 |
| 硬件基线 | `docs/design/electrical-control-practical-hardware.md` | 参数卡、单电源、急停与台架门禁 |
| 需求汇总 | `电控/资料/要求汇总.md` | 已确认型号、系统及安全约束 |
| 任务分析 | `docs/requirements/analysis.md` | 架构、决策、阻塞项 |
| 协作约定 | `docs/design/claude-codex-collaboration.md` | 文件所有权、独立性与审查规则 |
| 首轮 Claude 审核 | `.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md` | 回归检查来源；不得修改 |
| Codex 预审 | `.claude/reviews/REVIEW-20260812-011-codex-pcb-pre-review.md` | 对账历史；不得修改 |
| 当前对账 | `.claude/reviews/REVIEW-20260812-012-codex-claude-pcb-reconciliation.md` | 已接受修正与剩余边界 |

用户已裁决：采用方案 A。X/Y 各预留默认 DNP 的 `J_DRV_X_CTRL`、`J_DRV_Y_CTRL`，包含 `STEP/DIR/ENABLE/GND_LOGIC` 及可选反馈；A4988 与板外驱动器二选一，不得共同驱动同一电机。

## 3. 权限、输出和不可修改项

Claude 只读审核所有输入，只允许新建：

`.claude/reviews/REVIEW-20260812-013-claude-pcb-reconciliation-regression-review.md`

不得修改方案、PCB 基线、硬件基线、任务、计划、代码、测试或任何既有审查记录。不得采购、投板、接线、上电、烧录、运行固件或实机运动。

## 4. 完成标准

新审查记录必须包含总体裁决、P0/P1/P2 发现项、精确文件位置、事实/推断/建议/未知区分、对每项的接受/拒绝/待外部输入建议、实际读取文件与检查方法、允许继续范围、仍禁止动作和独立性声明。

## 可复制给 Claude 的提示词

```text
请对工创赛智能分拣装置的 PCB 方案进行“对账后全面回归复审”。这是独立只读审核，不是重新设计 PCB。

工作区：
C:\Users\29845\Desktop\工创赛

目标：
确认用户裁决的方案 A 及 Claude 上轮审核发现已被正确、无副作用地对账；全面检查当前文档是否仅可进入 KiCad 候选原理图草图。重点找出 P0/P1/P2 问题，尤其是安全边界、跨文档接口漂移、候选/DNP 误用和任何会阻止原理图冻结的遗漏。

任务等级：L3 有限试行。开始前调用并遵守：
1. using-superpowers
2. code-review
3. verification-before-completion

若 Skill 缺失，记录真实缺失并采用最接近的安全流程；不得声称已经调用未提供的 Skill。

完整读取：
- 当前 `AGENTS.md` 与 `CLAUDE.md`
- `docs/requirements/analysis.md`
- `docs/design/claude-codex-collaboration.md`
- `docs/design/pcb方案-17HS4401版.md`
- `docs/design/modular-pcb-design.md`
- `docs/design/electrical-control-practical-hardware.md`
- `电控/资料/要求汇总.md`
- `.claude/tasks/TASK-20260812-010-claude-pcb-reconciliation-regression-review.md`
- `.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md`
- `.claude/reviews/REVIEW-20260812-011-codex-pcb-pre-review.md`
- `.claude/reviews/REVIEW-20260812-012-codex-claude-pcb-reconciliation.md`

不可改变的事实和边界：
- X/Y 电机：`17HS4401`，NEMA17、1.8°、1.7A/相、40N·cm。夹爪：`DS3120MG`，PWM 开合，旋转默认关闭。
- A4988 仍是候选 DNP 模块，未经过实际负载、限流、温升、干扰和急停验证前绝不可定型、采购或装配。
- 方案 A 已裁决：`J_DRV_X_CTRL`、`J_DRV_Y_CTRL` 默认 DNP，包含 `STEP/DIR/ENABLE/GND_LOGIC` 及可选反馈。A4988 与板外驱动器必须二选一，不能共享电机或同时驱动。
- 单一内置电源；逻辑与危险动力分路。急停独立硬件仅切危险动力正极，不切公共参考地；逻辑保电；解除急停不得自动恢复危险动力或旧任务。
- Z 轴执行器/防坠、挡板舵机、限位、供电峰值、保护器件、线束、连接器、GPIO/排针、铜厚和线宽均未冻结。
- `BARRIER_READY` 不能由“已发送 PWM”产生；最终判据可为独立传感器或经验证时序，当前仅预留 `J_BARRIER_READY_IN` / `J_AUX_IN_n` 输入路径。

只允许新建：
`.claude/reviews/REVIEW-20260812-013-claude-pcb-reconciliation-regression-review.md`

不得修改任何已有文件，也不得执行任何硬件或外部写入动作。

必须逐条回归检查上轮已处理事项：
1. `J_DRV_X_CTRL` / `J_DRV_Y_CTRL` 是否在两份 PCB 文档中定义一致，是否是默认 DNP，是否明确低能量控制边界，以及 A4988 与板外驱动器的二选一互锁；
2. Z 轴拓扑、接口表和 KiCad 页面是否统一为 `STEP/DIR/ENABLE` 及可选反馈；
3. `J_ESTOP_FB` 在两份 PCB 文档中是否一致为 `ESTOP_FB`、`GND_LOGIC`、可选反馈回路参考电源，且参考电源绝不替代急停主回路；
4. `J_BARRIER_READY_IN` / `J_AUX_IN_n` 是否已提供到位/就绪输入预留，且没有将未验证时序或 PWM 命令伪装成 `BARRIER_READY`；
5. 两份 PCB 文档的网络名、连接器方向、动力/逻辑边界、DNP 文案、KiCad 页码与 BOM 状态是否互相一致。

还必须全面检查：
6. 已确认型号和参数是否准确，是否把供应商资料或台架前未知项伪装成事实；
7. X/Y/Z 控制、反馈、动力和电机网络是否隔离；板外驱动器动力、电机输出和保护是否明确在载板外；
8. 急停、限位、启动/复位、驱动反馈、舵机/夹爪、补光、通信和测试点是否具有明确且不越权的接口边界；
9. `DS3120MG` 和挡板是否仅经 PWM/低能量接口控制，动力是否在急停边界内且不经过载板功率路径；
10. 是否存在 GPIO、排针、模块针序、电压、保险、端子额定、线宽、铜厚、Z 轴功率驱动或防坠方案被未经证据写死；
11. 高能量测试点是否禁止普通可触及探针焊盘；逻辑与动力回流、屏蔽和地参考是否没有自相矛盾；
12. KiCad 候选草图页是否覆盖所需边界，但没有把候选草图错误升级为原理图冻结、投板或接线授权；
13. 冻结门禁是否完整覆盖参数卡、计算、连接器/针序、ERC/网络、封装 1:1、台架和独立急停回路审查。

输出格式：
- 先给总体裁决：通过 / 有条件通过 / 驳回；必须区分“允许候选草图”与“允许原理图冻结/投板”。
- 再列 P0、P1、P2，附路径、标题或行号、事实依据、风险、最小修正建议、对账状态。
- 单独列“回归检查矩阵”，逐项说明 1-5 是否真正关闭、有条件关闭或回归失败。
- 清晰区分事实、推断、建议、未知；对发现项标记接受/拒绝/待机械或供应商输入建议。
- 记录实际读取文件和静态检查方法；声明 Claude 未参与 Codex 起草。若不能实现真正独立，标注弱独立性。
- 明确仍禁止采购、投板、正式接线、上电、烧录及实机运动。

完成后只新建上述 REVIEW-013 文件。不要在聊天中代替审查记录，不要修改任何已有文件。
```
