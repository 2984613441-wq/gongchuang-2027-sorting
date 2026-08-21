# 2026-08-21 视觉→STM32 完整指令桥接实施记录

> 状态：主机侧代码完成，实机串口未验证
> 关联：`docs/design/2026-08-20-motion-command-list-v1.md`

## 目标

把视觉/树莓派端到 STM32 的链路代码写好，后续实机只需标定参数并启用动作，
不再补协议代码。

## 变更

- 新增 `集成/demo_bridge/action_bridge.py`：通用 JSONL→ASCII 指令事务层，
  覆盖 `MOVE`、`MOVE STEPS`、`SERVO`、`GROUP`、`BARRIER`。
- 新增 `集成/demo_bridge/config.full.example.json`：全动作默认 `enabled=false`。
- 新增 `视觉/src/jsonl_emitter.py`：输出桥接要求的四字段 JSONL；带 fake
  source，主机可无摄像头/模型干跑。
- 新增 `集成/deployment/run_pipeline.py` 与 README：树莓派部署入口与命令。

## 安全模型

- 默认 `--dry-run`；真实串口运动必须 `--allow-motion` 且配置显式启用。
- 每次动作事务：`STOP ALL → STATUS 空闲 → INPUTS ACTIVE=0000 → ARM →
  单条运动命令 → 运行态确认 → 空闲确认`。
- `ERR`、`BOOT SAFE`、安全输入、超时均锁存故障，最多三次 `STOP ALL`，
  不自动重发运动命令；无法确认停止时关闭串口并要求物理断电。

## 验证

- `集成/demo_bridge`：24/24 通过（原 13 + 新增 11）。
- `视觉/src`：4/4 通过。
- 端到端干跑：fake 视觉 → `action_bridge --dry-run`，稳定触发后按示例配置
  输出 `IGNORED disabled`，符合安全默认。
- 未验证：真实串口、STM32 实机、树莓派摄像头推理。

## 后续

1. 视觉端把真实检测器接到 `jsonl_emitter.py` 的 fake source 位置。
2. 实机标定后把动作配置改为 `enabled=true` 并逐类验证。
3. 仍不是正式二进制协议；`docs/design/interface-contract.md` 冻结后另行对齐。
