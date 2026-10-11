# ToolOffset / HOME 门禁 / 拒识日志实施与审查 — 2026-09-19

## 结论

T1、T2、T3 已在主机侧代码落地并通过主机回归。系统仍不能自动证明滑台在 HOME，人工输入只是操作门禁；严禁把本报告表述为固件或实机验证。

## T1 证据

- 配置与迁移警告：`电控/calibration_config.ini:63-74`。
- 缺节/缺键默认 0：`电控/src/electrical_control/rpi/pixel_to_device.py:151-153,243-249`。
- 运动链在 `pixel_to_device` 结果后叠加：同文件 `:449-458`。
- 最终 PICK 再校验边界：同文件 `:460-476`。
- 固件直接把 PICK 当 waypoint：`电控/firmware/stm32f407_m144z/App/Src/ec_motion_plan.c:197-200`。

迁移护栏：当前仓库 `tx/ty` 仍是旧折入偏移的副本。只有人工新标定明确输出“相机像素 → 未加工具偏移的装置基准坐标”后，才能同步带非零 `[ToolOffset]` 的配置；否则会重复补偿。

## T2 证据与评估

- 无自动绝对位置：`ec_startup_sequence.c:8-14,159-167` 明确不查 X/Y HOME、不寻零，只认上电位置。
- HOME 不变量：`ec_motion_plan.h:163-183,193-194`。
- 人工门禁：`电控/deploy/run_chain.py:471-506`，在 `:1001` 调用；开轮在 `:1095`。
- 前台入口：`工具/pi_start_chain.sh:2-17`；systemd 不再自动开轮：`电控/deploy/ec-chain.service:12-13,38`。

“先回 HOME 再 PICK”不能自动纠偏：现规划按 waypoint 差发增量，未知起点误差不会消失；盲撞机械限位又没有到位反馈。当前程序已用 10 步、容量 11（`ec_motion_plan.c:191-200`；`ec_axis_driver.h:189-192`），串行增加 X/Y 两腿会达到 12 步而装不下。

今晚错位到 HOME 的附加距离：`59.5 + 30.3 = 89.8 mm = 7184 steps`。按现有 5000Hz 巡航，忽略加减速的绝对下界也是 1.4368s；同构步进曲线主机计算为 2.36816s。与现有主机预算 13.463s 相加约 15.831s，超过 `ec_app.c:553` 的 15s 线约 0.831s。该数是主机模型，不是实机计时。

## T3 证据

- 像素域 `[57,232]×[142,232]`：`pixel_to_device.py:47-48,331-338`。
- 件高缺项：同文件 `:345-356`。
- 最终 PICK 越界：同文件 `:460-476`。
- 队列 WARNING 含 box_id / pixel / reason：`vision_ingest.py:241-255`。

## 原始验证输出

```text
py -3.14 电控/tools/selftest_tool_offset_home_rejection.py
PASS: ToolOffset/三类拒识原因/HOME 门禁主机自检全部通过

py -3.14 -m pytest -q 电控/tests/rpi/test_pixel_to_device.py 电控/tests/rpi/test_vision_ingest.py
51 passed, 1 warning in 0.52s

py -3.14 -m pytest -q 电控/tests/rpi
204 passed, 1 warning, 29 subtests passed in 1.71s

PYTHONUTF8=1 py -3.14 电控/deploy/selftest_failclosed.py
全部通过：11 项 ✅
```

warning 是 pytest 无法写工作区外层 `.pytest_cache`，测试临时目录使用显式可写 `--basetemp` 后全部执行；不是断言失败。

## 审核量化

- 结论：主机侧通过；现场部署前仍需完成迁移顺序与操作员验证。
- 置信度：4/5。
- 证据缺失计数：2（Pi 上新标定四数尚未证实已去工具偏移；未做实机/HIL HOME 与时序复测）。
- 逻辑跳跃计数：0。
- 替代解释：未来若增加限位/编码器/绝对视觉定位，可替代人工 HOME 门禁；若相机移动改变旋转或有效像素域，不止四个对角仿射数需要复核。
- 建议动作：先完成人工 camera-only 标定，再同步代码和配置到 Pi；现场前台运行并按横幅确认 HOME；随后仅做授权范围内的实机验证。
