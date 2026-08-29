# 给 ChatGPT 的独立审查提示词包（2026-08-29）

> 用途：让 ChatGPT 作为第三方节点，对工创赛智能分拣装置的**电控**与**视觉**代码做独立审查，与
> Claude（安全边界）、Codex（视觉优化落地）、DeepSeek（汇总）三节点互补，重点提供**不同视角**。
> 使用方法：把下文「=== 从这里开始复制 ===」到「=== 复制到这里结束 ===」之间的全部内容粘贴给 ChatGPT。

---

=== 从这里开始复制 ===

你是一名资深嵌入式+机器视觉代码审查专家。请对一个"智能分拣装置"竞赛项目的**电控子系统（树莓派 Python + STM32 C）**与**视觉子系统（Python）**做独立代码审查。你拿不到文件，我会在下面给你关键代码片段与说明；请基于这些信息做审查，并在缺少信息时明确指出"此处需结合真实代码确认"，不要编造。

## 项目背景
- 树莓派 4B：任务队列、视觉数据接收、显示 ACK 回路、集中日志；STM32F407：单件运动控制、回零、急停、15 秒监控。
- 三设备（MaixCAM 视觉 / 树莓派 / STM32）用统一二进制外层帧通信。
- 冻结契约（已评审冻结，不要质疑）：外层帧 = 0xA5 0x5A + version 0x01 + sender/receiver + task_id(2B大端) + frame_seq(2B大端) + command + data_len(2B大端) + payload + CRC-16/MODBUS(0x8005, init 0xFFFF, 无反射无异或, 2B大端)。ITEM_TASK 载荷 8 字节 = target_seq + class_id + image_id + X/Y(int16 大端, 0.1mm, ±1450) + grip_angle(0xFF)。DISPLAY_ACK 载荷 6 字节 = target_seq + render_result(0x00=RENDERED) + display_crc32(CRC-32/ISO-HDLC of target_seq,class_id,image_id,success_count,result_code)。
- 状态机：POWER_ON→HOMING→PREPARE_BARRIER→WAIT_TASK→VALIDATE_TASK→EXECUTING→WAIT_ITEM_RESULT→WAIT_DISPLAY_ACK→PREPARE_BARRIER；FAULT_LOCK 后需人工确认新轮次（round_id 变化 + 三安全标志）才恢复。树莓派侧还有 MOTION_DONE 门禁：next_task→WAIT_MOTION_DONE→accept_motion_done→WAIT_ITEM_RESULT→accept_item_result→WAIT_RENDER→accept_render_receipt→READY。

## 电控 Python 侧关键实现（节选）
1. `rpi/gateway.py`：PiProtocolGateway.feed_byte 做字节级重同步（0xA5 0x5A 头），帧完成时 decode_outer_frame 校验头/版本/CRC，失败返回 FRAME_REJECTED 并丢弃整帧；_dispatch 用 (task_id, frame_seq) 入站去重缓存（OrderedDict，容量 256，超限淘汰最旧）；MOTION_DONE 处理：payload 必须为空，校验 frame.task_id==current_task.task_id，然后 scheduler.accept_motion_done(round_id=current_task.round_id, task_id=current_task.task_id, frame_seq=current_task.frame_seq)，SchedulerFault 捕获返回 FAULT。注意：Scheduler 的 round_id 是字符串（如 "round-new"），而协议 task_id 是整数。
2. `rpi/__init__.py`：Scheduler 类，_seen_tasks 字典记录 (round_id, task_id, frame_seq) → payload，同身份不同载荷即 _fault；模块级全局列表 `_completed_receipts` 保存完成渲染凭据，accept_render_receipt 要求凭据必须来自 PendingRender.complete()（防伪造），否则拒绝。
3. `state_machine/core.py`：PureStateMachine 纯逻辑状态机，事件驱动（ItemTaskReceived/MotionDone/ItemResultReceived/DisplayAckReceived/BarrierAvoidanceVerified/EmergencyStop/PowerPermissionLost/ManualReset/TimeObserved 等）；ROUND_TIMED_STATES 下 now-last_observable_at>=15s 触发 ROUND_TIME_EXHAUSTED 故障；故障时依次请求 STOP_ALL/DISABLE_DRIVERS/INHIBIT_POWER。
4. `integration/control_flow.py`：ControlFlowGuard 补偿层，带容量上限的三套去重（task/display_ack/result），容量耗尽即锁；成功计数 RoundSuccessCounter（1字节 0..255，达 255 后新的成功结果触发 SUCCESS_COUNT_OVERFLOW 并锁故障）。
5. `protocol/`：direction.py 方向白名单（BARRIER_READY/MOTION_DONE/ITEM_RESULT 只允许 STM32→RASPI，DISPLAY_ACK 只允许 RASPI→STM32）；display_ack.py 校验 render_result==0x00、target_seq 与当前件匹配、display_crc32 与期望内容匹配。

## 电控 C 侧关键实现（节选）
- `stm32_logic/src/ec_protocol.c`：帧编解码同上述冻结契约；ITEM_TASK 解码用显式字节运算还原 int16 大端符号值（避免 ARM 小端直接解引用）；DISPLAY_ACK 解码允许 payload_len>=6（Python 侧要求 ==6，存在不对称）。
- `ec_protocol_gateway.c`：ec_gateway_feed_byte 字节级重同步；handle_item_task 校验发送方==PI、success_count==255 时拒绝新任务；handle_display_ack 校验发送方==PI + target_seq/render_result/display_crc32/task_id 全匹配；成功计数只在状态机真正提交 WAIT_ITEM_RESULT→WAIT_DISPLAY_ACK 且 result==SUCCESS 时 +1（防重放重复计数），达 255 不再增加。
- `ec_dedup.c`：线性扫描去重表（task_id+frame_seq+payload_fingerprint(CRC32)），DUPLICATE/CONFLICT/FULL 三态。
- `ec_state_machine.c`：FAULT_LOCK 后仅 MANUAL_NEW_ROUND_CONFIRMED（round_id 变化+round_closed+danger_area_clear+estop_released）恢复并清空去重；EMERGENCY_STOP/POWER_PERMISSION_LOST/DEADLINE_EXPIRED/DEDUP_CAPACITY_EXHAUSTED 均直接锁死。
- `ec_step_profile.c`：整数平方根 + f²=v₀²+2as 梯形/三角形加减速曲线规划，全 uint64 中间量，频率/重装载值均为整数运算。

## 视觉子系统关键实现（节选）
- `sorting_vision/pipeline.py`：VisionPipeline.infer_batch 任务 id 校验→后端推理→postprocess→坐标变换→DetectionResult（target_seq 按枚举顺序 1..n）；任何 VisionError/未知异常都转 FAILED 结果（fail-closed）。
- `postprocess.py`：bbox 校验（有限数、0<=x1<x2<=宽）、confidence>=阈值过滤、类感知 NMS（同 class 且 IoU>阈值才抑制）、suppressed 且 reject_duplicates 时抛 DuplicateDetectionError、数量>max_detections 也抛 DuplicateDetectionError（错误码语义存疑）。
- `sort_plan.py`：按 (color_id, shape_id) 分组映射箱号 1..6；颜色来自 MMCQ 主色量化 + HSL 分桶（红/橙/黄/绿/青/蓝/紫/粉/黑/白/灰）；无 box_assignment 时用字典序默认（明确标注仅诊断用，非冻结物理映射）。
- `color_quant.py`：MMCQ（中值切分）从 node-vibrant 移植，5bit/通道直方图 32768 桶；纯 stdlib。
- `single_target.py`：单目标确认循环（min_confirm_frames 连续同 class 才输出）；backend.capture/infer/release 注入式。
- `backends/`：fake（确定性测试）、onnx_runtime（需注入 input_builder/output_decoder）、ultralytics（YOLO，PC/树莓派）、maixcam（MaixPy v4，MaixCAM 目标硬件，YOLO11）。
- `jsonl_emitter.py`：按帧输出 {"frame_id","label","confidence","ts_ms"} JSONL，供演示桥消费。

## 你的任务
1. 挑出你认为的 **P0/P1 级问题**（安全/逻辑/数据一致性），重点怀疑：Python 与 C 两侧行为不对称、重放/伪造路径、计数边界、状态机可达性、失败路径是否真的 fail-closed。
2. 指出**测试最可能没覆盖的边界**。
3. 给出 3-5 条你认为最值得改的优化（按性价比）。
4. 对每条结论给出"证据链"：基于哪段代码/哪个契约，以及"如果信息不足"的明确标注。

输出为 Markdown，分级清单（P0/P1/P2/P3）+ 测试缺口 + 优化建议。不要泛泛而谈，不要重复我说过的"冻结契约"，聚焦你独立发现的点。

=== 复制到这里结束 ===

---

## 投喂说明
- 把以上内容整段粘贴给 ChatGPT（任意版本），它会基于节选代码做独立审查。
- 如果 ChatGPT 需要看具体文件，可以补充粘贴以下任意文件内容：`电控/src/electrical_control/`（全部）、`电控/stm32_logic/src/`（全部）、`视觉/src/sorting_vision/`（全部）。
- 建议让 ChatGPT 用"审查者"身份输出，之后再和 Claude/Codex/DeepSeek 三份结论做交叉比对，分歧点提交用户裁决（按跨节点协作规则）。
