# 视觉→运动去抖责任方与输出契约决策草稿

> 日期：2026-08-23
> 来源：`REVIEW-20260822-005-claude-vision-min-confirm-merge.md` 的 I-1 发现
> 状态：已裁决 A；本文件只做决策记录，不修改代码，也不构成实机授权。

## 1. 问题

视觉侧 `sorting_vision.run_vision_loop` 的 `min_confirm_frames` 是
**stream**（达到 N 后逐帧持续上报，靠下游去重）；运动桥接层
`DetectionStabilizer` 是 **latch-once**（连续 N 帧后只返回一次，直到无目标
释放窗口才解锁）。两者语义相反、默认值不同，且当前真实运动链路不消费
`sorting_vision`，所以问题尚未触发，但属于联调前必须收敛的契约缺口。

## 2. 已核验事实

- `视觉/src/sorting_vision/single_target.py:274-287`
  `emit = confirm_streak >= config.min_confirm_frames`，达到 N 后持续 emit；
  `min_confirm_frames` 默认 1，见同文件 `:63`；docstring 见 `:248-251`。
- `集成/demo_bridge/bridge.py:66-70`
  `StabilityConfig(min_confidence=0.70, consecutive_frames=5,
  release_after_ms=1000)`。
- `集成/demo_bridge/bridge.py:178-226`
  `DetectionStabilizer.offer` 在连续 N 帧同 label 后 `_latched=True` 并只
  返回一次；锁存期间同 label 帧返回 `None`。
- `集成/demo_bridge/action_bridge.py:22-34` 从 `bridge` 导入
  `jsonl_events`、`DetectionStabilizer`；`:466` 以
  `jsonl_events(sys.stdin)` 作为事件源。
- `视觉/src/jsonl_emitter.py` 只输出 4 字段 JSONL
  `frame_id/label/confidence/ts_ms`，自身无去抖。
- `集成/deployment/README.md` 链路为 `视觉 JSONL -> action_bridge ->
  STM32`，指向 `jsonl_emitter.py`，未指向 `sorting_vision`。
- 当前 `sorting_vision` 的输出（诊断 text/JSON）与 `Detection.from_json_line`
  的 4 字段契约不兼容，因此未接入真实运动路径。

## 3. 可选方案

### A. 桥接层作为唯一去抖方（近期推荐）

- 保持真实路径：视觉侧输出原始逐帧 JSONL（`jsonl_emitter` 或未来等价适配器），
  由 `action_bridge` 的 `DetectionStabilizer` 做 latch 去抖。
- `sorting_vision.min_confirm_frames` 保留，但明确为“诊断/离线使用”，真实
  运动路径不使用其 stream 抑制。
- 补一个 `min_confirm_frames=1` 的命名测试（M-1），补一份输出格式与消费方
  对照表（M-2）。

优点：改动最小，不重写桥接层；安全门禁保持现状。
风险：需文档化防止后续把 `sorting_vision` stream 误接入桥接层造成双重去抖。

### B. 视觉层作为唯一去抖方

- 把 `sorting_vision` 的确认结果作为权威输出接入 `action_bridge`，桥接层
  关闭或旁路 `DetectionStabilizer`（`consecutive_frames=1` 且不锁存，或移除）。
- 淘汰/归档 `jsonl_emitter.py` 与 `vision_loop_template.py`。

优点：视觉核心真正进入真实链路，单一责任方。
风险：需为 `sorting_vision` 输出做桥接层输入适配；桥接层失去自身 latch 安全
语义，需重新验证故障路径。

### C. 收敛为单一权威契约（最终目标）

- 定义唯一的“视觉→桥接”wire 格式与唯一去抖责任方，统一真实路径，归档被
  取代的模板/发射器，并保留一套诊断输出。

优点：长期最干净。
风险：跨 `视觉/`、`集成/` 契约变更，范围较大；它是视觉接入真实模型前的门禁，
需在实机联调前完成，不能无限期延后。

## 4. 推荐

近期选 **A**：先保住现有真实运动路径，明确桥接层 `DetectionStabilizer` 为
唯一去抖责任方；同时落实 M-1、M-2 文档与测试。视觉接入真实模型之前，必须先
完成单一权威 wire 契约收敛（C 方案）并归档被取代的模板/发射器，作为实机联调
前的门禁。

## 5. 待用户裁决

1. 选 A / B / C。
2. 若选 A：是否保留 `min_confirm_frames` 作为诊断能力，还是暂时隐藏；是否
   把真实路径文档明确写为“不使用视觉层 stream 抑制”。
3. 若选 B/C：是否授权修改桥接层输入契约、移除旧 `jsonl_emitter` /
   `vision_loop_template`，并新增端到端适配测试。

## 6. 最小验证

- A：补 M-1 命名测试、M-2 文档表；`grep` 确认没有把 `sorting_vision` 误接进
  `action_bridge`；跑 `视觉/tests` 与 `集成/demo_bridge` 测试。
- B/C：新增适配测试与端到端 dry-run 用例，保持故障锁存语义不变。

## 7. 边界

本文件仅为决策草稿。真实模型、相机、串口、STM32、电机和实机动作均未授权，
后续每个具体动作仍需用户确认。
