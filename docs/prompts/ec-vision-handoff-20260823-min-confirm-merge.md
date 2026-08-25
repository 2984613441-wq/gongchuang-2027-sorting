# 电控 → 视觉 交接：V0.1 合并审核补充

> 日期：2026-08-23
> 来源：电控侧（Claude，独立只读抽查）
> 用途：视觉侧按更新后的审核词出完整审核记录前，需知悉电控侧已实测核出的跨层接口问题
> 关联审核词：`docs/prompts/claude-review-20260822-vision-min-confirm-merge-readonly-review-prompt.md`

## 一、审核词已就位

视觉 Claude 按更新后的审核词出完整审核记录，编号 `REVIEW-20260822-005-claude-vision-min-confirm-merge.md`。

## 二、电控侧实测核出的跨层接口问题（请重点确认）

- 视觉 `min_confirm_frames` 默认值 = **1**（`视觉/src/sorting_vision/single_target.py:63`，单帧即报）
- 桥接端 `StabilityConfig` 默认值 = **consecutive_frames=5 / release_after_ms=1000**（`集成/demo_bridge/bridge.py:69-70`）

问题有两层：

1. **两个重叠的稳定性过滤层，默认值不一致（1 vs 5）**：视觉默认不预过滤，稳定性全部甩给桥接。若有人单独把视觉调到 N，会与桥接的 5 帧叠加，延迟没人预料到。
2. **释放语义单位不同**：视觉是 "release frames"（帧数，`jsonl_emitter.py`），桥接是毫秒（`release_after_ms`）。帧数 vs 毫秒，本来就不直接可比。

**需视觉侧裁定**：稳定性/释放过滤到底在哪一层做？部署前统一，避免双重过滤叠加延迟、或单层失效。

## 三、记账（不阻塞）

主仓库 "25 文件" vs 来源 dc2b7f7b "28 文件"，差 3 个 `.gitkeep`（主仓库已有），内容一致，不影响合并结论。

## 四、一句话

视觉按更新后的审核词出 REVIEW-005，重点回答第二节"过滤在哪一层做"。
