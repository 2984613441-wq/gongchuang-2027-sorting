# REVIEW-20260812-012：Codex–Claude PCB 审核对账

> 对账对象：`REVIEW-20260812-010-claude-pcb-plan-review.md`、`REVIEW-20260812-011-codex-pcb-pre-review.md`  
> 对账日期：2026-08-12  
> 对账方：Codex；用户已裁决 P1-01 采用方案 A。  
> 独立性：弱独立性；Codex 参与方案起草，Claude 审核记录本身保持只读未改。

## 1. 对账结论

**总体裁决：有条件通过，允许进入 KiCad 候选原理图草图阶段；不允许冻结、投板或实机动作。**

Claude 与 Codex 独立确认的 P1-01 已由用户选择方案 A 关闭：X/Y 各预留默认 DNP 的 `J_DRV_X_CTRL`、`J_DRV_Y_CTRL`，包含 `STEP/DIR/ENABLE/GND_LOGIC` 及可选反馈。A4988 与板外驱动器必须二选一，不能同时连接或共同驱动同一电机。

## 2. 发现项对账

| 项目 | Claude 结论 | Codex 对账 | 状态 |
|---|---|---|---|
| P1-01 X/Y 板外驱动出口 | 缺少独立控制连接器 | 用户选 A，已同步两份 PCB 方案 | 已关闭 |
| P2-01 拓扑文字 | `STEP/DIR` 与接口表的 `ENABLE/反馈` 不一致 | 已统一为 `STEP/DIR/ENABLE` 及可选反馈 | 已关闭 |
| P2-02 `J_ESTOP_FB` | 可选反馈参考电源在两份 PCB 文档中描述不同 | 已统一为 `ESTOP_FB`、`GND_LOGIC`、可选反馈回路参考电源 | 已关闭 |
| P2-03 `BARRIER_READY` | PWM 输出外没有明确到位/就绪输入路径 | 已预留 `J_BARRIER_READY_IN` / `J_AUX_IN_n`；最终传感器或时序判据待确认 | 已关闭为接口预留；判据本身待外部输入 |

## 3. 修改文件

- `docs/design/pcb方案-17HS4401版.md`
- `docs/design/modular-pcb-design.md`
- `.claude/tasks/TASK-20260812-009-claude-pcb-plan-readonly-review.md`
- `.claude/reviews/REVIEW-20260812-011-codex-pcb-pre-review.md`

Claude 原始记录 `.claude/reviews/REVIEW-20260812-010-claude-pcb-plan-review.md` 未修改。

## 4. 当前允许与禁止

允许：建立 KiCad 候选原理图草图、补全网络命名、DNP 标识和接口预留；继续收集机械/供应商资料。

禁止：采购、投板、正式接线、上电、烧录、实机运动；不得把 A4988 升格为最终驱动，不得把 `BARRIER_READY` 以“已发 PWM”代替最终验证判据。

## 5. 验证记录

对账后需执行并记录：文档交叉检索、`git diff --check`、方案 A 接口存在性检查，以及后续 KiCad 草图的 ERC/网络检查。当前对账不等于硬件验证或 PCB 设计完成。
