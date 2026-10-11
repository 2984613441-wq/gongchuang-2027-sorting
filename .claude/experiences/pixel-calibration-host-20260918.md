# 标定接入主机链路

- 结论：标定回调必须在正式工厂注入；全零/退化矩阵须在加载时拒绝。ObjectHeights 的 box_id 不可替换成形状 class_id。补偿中心应使用图像中心仿射像；未知高度拒识。
- 来源：2026-09-18 用户任务与 `docs/reports/2026-09-18-pixel-calibration-host-review.md`；完整主机 pytest 341 passed, 59 subtests passed，新合成回归 40 项。
- 适用条件：当前树莓派纯逻辑链路，既有 BATCH_TARGETS/ITEM_TASK 格式；图像主点近似中心；不作为现场标定、固件或实机通过的证据。
- 最后验证时间：2026-09-18。
- 状态：受限（主机验证通过，真实参数与实机精度待现场验证）。
