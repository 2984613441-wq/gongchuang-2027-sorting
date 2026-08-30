# 电控 + 视觉 多节点联合审查报告（2026-08-29）

> 节点：DeepSeek（DSH，召集/汇总/核验）· Claude Code（安全边界审查）· Codex CLI（视觉优化落地）
> · ChatGPT（提示词包，待用户投喂）· DSH 内部 subagent ×2（rpi 测试修复、视觉只读审查、C 逻辑复核）
> 范围：主机侧纯逻辑审查与优化；**不涉及**上电、烧录、串口、相机、实机运动。

---

## 0. 结论速览

| 子系统 | 测试状态（修复后） | 已修复 | 剩余待办 |
|---|---|---|---|
| 电控 Python | **135 passed + 41 subtests，0 failed** | gateway MOTION_DONE 分发 bug、SUCCESS_COUNT_OVERFLOW 未捕获、入站缓存无上限、`_completed_receipts` 全局列表无界、`_dispatch` 异常兜底、20 个陈旧测试 | 见 §3 剩余项 |
| 电控 C（stm32_logic） | **73/73 通过（MSVC /W4 /WX 零警告）** | DISPLAY_ACK 严格 6 字节、步进曲线溢出防护、新轮清零时机、round_id 上限 | P1-1 RESEND 语义（待确认） |
| 视觉 | **75 passed + 8 subtests**（full-access 下） | MMCQ 分两阶段目标数 bug、颜色链透明/空 ROI 裸异常、reacquire 无兜底、drop_table `True==1`、jsonl 无校验、坐标/缓冲校验 | P1 运行策略未冻结、ROI 取整规范、NMS 同分排序 |
| 跨节点分歧 | Claude 3 条 P0 结论经核验为**误报**（见 §5） | — | 分歧声明已记录，供用户裁决 |

> 视觉 8 个测试在 workspace-write 沙箱下因 **chmod 被沙箱拦截（WinError 5）** 失败；Codex 在 danger-full-access 下同批 **75 全过**，确认是环境限制而非代码缺陷。普通 shell 下应直接通过。

---

## 1. 电控：已修复的问题（本节点 DeepSeek）

### 1.1 PiProtocolGateway MOTION_DONE 分发 bug（真实，原必现挂死）
- **位置**：`电控/src/electrical_control/rpi/gateway.py:131-152`
- **问题**：原来 `accept_motion_done(round_id=frame.task_id, task_id=frame.task_id, frame_seq=frame.frame_seq)`：
  1. Scheduler 的 `round_id` 是**字符串**（如 `"round-new"`），`frame.task_id` 是整数 → 身份比对**永远失败**；
  2. `frame.frame_seq` 是 STM32 自己的发送计数器，与 Pi 侧任务 frame_seq 不同序列空间；
  3. `accept_motion_done` 抛出的 `SchedulerFault` **未被捕获**，会从 `feed_frame` 直接炸出。
- **修复**：改为按 active task 身份进入门禁——`current_task` 为空返回 `MOTION_DONE_IGNORED`；校验 `frame.task_id == task.task_id`；以 `task.round_id/task_id/frame_seq` 调用并捕获 `SchedulerFault` 返回 `FAULT`。
- **验证**：`test_barrier_ready_and_motion_done_are_dispatched`、`test_offline_main_chain.py` 自动转绿。

### 1.2 ControlFlowGuard SUCCESS_COUNT_OVERFLOW 未捕获（真实）
- **位置**：`电控/src/electrical_control/integration/control_flow.py:199-205`
- **问题**：255 成功后第 256 个成功结果，`RoundSuccessCounter.record_item_result` 抛 `SuccessCountOverflow`，guard 不捕获 → 异常逃出主机循环，而不是进 FAULT_LOCK。
- **修复**：捕获并 `_lock("SUCCESS_COUNT_OVERFLOW")`；新增集成测试 `test_xl_count_overflow_locks_on_256th_success`（255 完整轮 + 第 256 个在途成功）。

### 1.3 入站去重缓存无上限（已知问题 P2，顺手修）
- `gateway.py`：`_inbound_cache` 改为 `OrderedDict`，容量 `_INBOUND_CACHE_CAPACITY = 256`，超限淘汰最旧（FIFO）。

### 1.4 `_completed_receipts` 模块级全局列表无界增长（Claude P0-3 确认为真，但级别为 P2）
- `rpi/__init__.py`：改为 `deque(maxlen=512)`；每轮最多 255 件，跨轮不再无限增长，`_was_completed_by_pending` 的 O(n) 也被封顶。

### 1.5 20 个陈旧 rpi 测试（契约漂移，subagent A 完成）
- SAFETY_FIXES v3 加了 `WAIT_MOTION_DONE` 门禁但测试未同步（v3 文档自注"部分测试需更新"）。subagent A 更新 3 个测试文件（19 处），补 `accept_motion_done` 门禁步骤与 MOTION_DONE 帧，断言意图全部保留，**零修改 src 生产逻辑**。

### 1.6 C 侧 P1/P2 修复（自主续作，独立提交 `6d67258a`）
| 项 | 位置 | 修复 |
|---|---|---|
| P2-1 步进曲线溢出 | `ec_step_profile.c` 三角分支 | 峰值公式三项（2·a·d·total / d·start² / a·end²）逐一溢出防护，极端速率（≥1e9 Hz/s）fail-closed 返回 false 且不写结构体 |
| P2-2 新轮清零时机 | `ec_protocol_gateway.c` inject | 计数/上下文清零移到状态机提交之后，仅 `transition.state == POWER_ON`（即 round_id 变化 + 三标志全满足）才清零；被拒确认不再清计数 |
| P2-4 round_id 截断 | `ec_protocol_gateway.c` inject | `round_id > UINT16_MAX` 直接拒绝（否则出帧 task_id 截断、DISPLAY_ACK 轮次门禁永不满足 → 死锁） |
| DISPLAY_ACK 长度不对称 | `ec_protocol.c` | 载荷严格 `== 6` 字节，与 Python 对齐（Claude P0-4 采纳项） |

### 1.7 Python 网关异常兜底
- `gateway.py:_dispatch` 最外层 `except SchedulerFault → FAULT`、`except Exception → CRASH`，意外异常不再炸穿 `feed_frame`/`feed_byte`（Claude P2-4 采纳项）。新增 CRASH 用例。

**验证**：C 测试 **69 → 73 全过**（新增 C-STEP-012 溢出防护、C-GW-ROUND-002~004 新轮守卫、P-DACK 长载荷拒绝）；Python **134 → 135 + 41 subtests 全绿**。

### 1.8 P2-3 去重键跨实现核对结论（无需改码）
- Python `_item_task` 按 `(task_id, frame_seq)` 身份去重，C `ec_dedup` 按 `(task_id, frame_seq, fingerprint)` 去重——**两侧语义一致**：同身份重传 = DUPLICATE；改 frame_seq 的重传 = 新身份，在 WAIT_TASK 且轮次匹配时都会被接受并执行。冻结契约中"重传"= 同身份，故 P2-3 是语义澄清项而非缺陷。

---

## 2. 视觉：已修复的问题（Codex 节点落地，subagent B 定位）

| 文件 | 修复 | 对应 subagent B 问题 |
|---|---|---|
| `color_quant.py:283` | MMCQ 第二阶段目标数改为**绝对总数**（原 `color_count - pq2.size()` 因 `_split_boxes` 用绝对目标而**必然空转**）；全透明/空 ROI 显式失败；移除未用直方图全桶扫描 | P1-1 颜色链崩点 |
| `pipeline.py:38,80` | `infer_batch` 区分 `UNEXPECTED_BACKEND_FAILURE`/`INTERNAL_CORE_ERROR`；`reacquire` 补未知异常兜底 | P1-4 reacquire 不对称 |
| `coordinates.py:36` | 仿射矩阵先验形状再展开；边界/有限值/元数据校验统一 `ConfigurationError`（防裸 TypeError/IndexError） | P2 加固 |
| `sort_plan.py:138` | RGBA 缓冲长度与图像尺寸严格匹配（防短缓冲静默切片）；ROI 改逐行切片 | P1-1 关联 |
| `drop_table.py:57` | `point_for` 拒绝 bool 与越界箱号（修 `True == 1` 误命中 1 号箱） | P2-10 |
| `jsonl_emitter.py:22` | 输出前校验 frame/label/confidence/时间戳，拒绝 NaN/∞/越界置信度 | P2-11 |
| 新增回归测试 | `test_color_quant.py` 等 5 处测试文件 | P1 盲区 |

**Codex 测试证据**：修改前基线 62 passed → 新回归测试在旧实现上 16 failed（复现目标问题）→ 修改后 **75 passed + 8 subtests**。`git diff --check` 通过。

---

## 3. 电控剩余问题（本轮未改，建议下轮处理）

### 3.1 C 侧（subagent C 复核，P0=0）
| 级别 | 位置 | 问题 | 建议 |
|---|---|---|---|
| P1-1 | `ec_state_machine.c:110-114` | `RESEND_CACHED_RESPONSE` 在 VALIDATE_TASK/EXECUTING/WAIT_ITEM_RESULT 被发出——**已核实为死动作**：网关 `consume_and_emit` 只物化 EMIT_BARRIER_READY/EMIT_MOTION_DONE/EMIT_ITEM_RESULT 三帧，`ec_app.c` 只处理 SAFE_LOCK/BEGIN_POST/BEGIN_HOMING/PREPARE_BARRIER/START_MOTION，RESEND 无任何执行者，重复任务到来时静默丢弃 | 需应用层作者定义"响应缓存"语义（缓存哪一帧、何时可重发），再在网关/App 层实现；本轮不猜写 |
| P2-3 | `ec_dedup.c` + gateway:86-92 | 去重键含 frame_seq——**已核对：Python/C 两侧语义一致（同身份=重传），属语义澄清项，无需改码**（见 §1.8） | — |
| P3×8 | 详见 subagent C 报告 | int16 大端转换 implementation-defined；255 拒绝静默无 NACK；`ack_consumed` 只写不读；枚举死状态；fallback 虚报峰值；魔法下标；Y 复用 X 限位宏；CRC32 碰撞未注释 | — |

> 已修复并移出：P2-1（步进溢出防护）、P2-2（新轮清零时机）、P2-4（round_id 上限）、DISPLAY_ACK 长度（§1.6）。

### 3.2 Python 侧（Claude 核验后保留项）
- **DISPLAY_ACK 长度不对称**（C `>=6` vs Python `==6`）：C 改严格 `!=6` 拒绝（P2，非 P0——真实流 Pi 恒发 6 字节）。
- **round_id 跨语言映射未定义**（Python str vs C uint32）：需冻结 `round_id = Pi 轮次标识` 的映射规则（P1/P2，当前无硬件在环）。
- **C 侧 CRC 失败无字节级重同步**（`ec_proto_decode` 失败即丢整帧，Python 逐字节 pop）：建议 C 增加 header 级重同步（P2）。
- `accept_motion_done(**kwargs)` 类型不安全 → 改显式参数（P3）；`_dispatch` 最外层补 `except Exception → CRASH`（P2-4）；C 零 identity 防御（P2-5）；`fake_serial` 加环境变量守卫（P1-5→P3）。
- frame_seq 单调性：`state_machine/core.py:266-270` 已有 `last_accepted_frame_seq`，网关层不重复强制（Claude P1-1 部分误报，见 §5）。

---

## 4. 视觉剩余问题（未修，subagent B + Codex 共识）

- **P1**：`run_vision_loop` 的 `capture()`/`on_result()` 异常策略（停止 vs 重试）未冻结——需先冻结语义再改。
- **P1**：JSONL `stdin` 透传模式无严格校验——需先明确 stdin 是否可信边界。
- **P2**：浮点框 `int()` 截断 ROI 的取整规范（floor/ceil/round）未冻结；同置信度 NMS 依赖后端顺序、`target_seq` 稳定性需与下游共同冻结。
- **P3**：`vision_loop_template.py` 与 `single_target.py` 双份分叉（模板 `_pick_best` 是被取代的反模式）→ 建议压缩为文档；`InferenceConfig.backend` 死字段；`FakeInfoDecoder.enable_*` 死配置；`benchmark.py` tracemalloc 只测 Python 侧内存。
- **历史脚本**（`开源参考/视觉/mydetect*.py` 等）：硬编码 `yolov5s.pt`+4 类标签（IndexError 风险）、`iou_thres=1.0` 禁用 NMS、`COM5/COM6` 串口、绝对路径、7 个"副本"文件无版本管理 → 建议清理归档。
- **测试缺口**：`color_quant` 已补（Codex 新增 test_color_quant.py）；仍缺 benchmark 空样本/单样本 p95、`format_diagnostic_text` 空 issues、后端一致性注入测试。

---

## 5. 跨节点分歧声明（Claude 结论核验）

按跨节点协作规则，Claude 节点报告与代码事实冲突处，双方各留声明，提交用户裁决：

| Claude 结论 | 核验结果（DeepSeek，证据） | 判定 |
|---|---|---|
| **P0-1** Python 缺 ITEM_TASK 方向校验，伪造帧可绕过 | `codec.py:13` 对每帧先 `validate_direction`；`gateway.py:110-111` 拒绝一切非 STM32→RASPI 帧；ITEM_TASK 是 Pi→STM32 出站命令（`encode_item_task_frame` 硬编码方向），Pi 侧从不解码入站 ITEM_TASK | **误报**（白名单存在，ITEM_TASK 不在其中是有意为之） |
| **P0-2** C 侧无 sender/receiver 校验 | `ec_protocol_gateway.c:81`（handle_item_task）、`:127`（handle_display_ack）拒绝 `sender != PI`；`:168` 拒绝 `receiver != STM32`。`ec_sm_consume` 纯状态机不带 wire 字段是分层设计 | **误报**（Claude 只看了纯状态机层，漏了网关层） |
| **P1-3** MOTION_DONE 门禁可被 WAIT_RENDER 分支绕过 | `accept_item_result` 仅接受 WAIT_ITEM_RESULT/WAIT_RENDER；WAIT_RENDER 只能经 WAIT_ITEM_RESULT 到达（后者必经 accept_motion_done）；WAIT_RENDER 分支是幂等重发 | **误报**（无直达路径） |
| P0-3 全局 receipts 列表无界 | 属实，已修复（§1.4）；级别应为 P2（每轮 ≤255 条，非"数小时 OOM"） | 采纳（已修） |
| P0-4 DISPLAY_ACK 长度 != vs < | 属实不对称；级别 P2（Pi 恒发 6 字节，无实际分歧路径） | 部分采纳（建议 C 改 `!=6`） |
| P0-5 round_id str vs uint32 | 跨语言映射确实未冻结；级别 P1/P2（当前无硬件在环，演示链在 Python 内自洽） | 采纳（建议冻结映射规则） |
| P1-2 C 侧 255 无检查 | 部分误报：`handle_item_task` 有 255 拒绝、`ec_gateway_inject` 有防回绕增量，Claude 漏看 | 部分采纳 |
| P1-1 缺 frame_seq 单调性 | 部分误报：`state_machine/core.py:266-270` 已有检查 | 部分采纳 |

**裁决请求**：请用户对上述"误报 vs 采纳"判定做最终裁决；若认可，Claude 结论中的 P0 三项不作为阻断项。

---

## 6. 测试证据汇总

```
电控 Python（PYTHONPATH=电控/src，.venv-test）:
  pytest 电控\tests -q -p no:cacheprovider
  => 135 passed, 41 subtests passed in 0.25s

电控 C（MSVC /W4 /WX）:
  cmake -S . -B build-fix && cmake --build build-fix
  .\build-fix\Debug\ec_logic_tests.exe
  => ALL 73 STM32 LOGIC TESTS PASSED

视觉（PYTHONPATH=视觉/src，.venv-test）:
  pytest 视觉\tests -q -p no:cacheprovider
  => full-access 下 75 passed, 8 subtests passed in 0.39s
  （workspace-write 沙箱下 8 项因 chmod 被拦失败，环境限制）
```

---

## 7. 修改文件清单（本轮）

**电控（src）**
- `电控/src/electrical_control/rpi/gateway.py` — MOTION_DONE 分发修复 + 有界入站缓存 + `_dispatch` 异常兜底
- `电控/src/electrical_control/integration/control_flow.py` — SUCCESS_COUNT_OVERFLOW 捕获进 FAULT_LOCK
- `电控/src/electrical_control/rpi/__init__.py` — `_completed_receipts` 改 `deque(maxlen=512)`
- `电控/stm32_logic/src/ec_protocol.c` — DISPLAY_ACK 严格 6 字节
- `电控/stm32_logic/src/ec_step_profile.c` — 峰值公式溢出防护
- `电控/stm32_logic/src/ec_protocol_gateway.c` — 新轮清零时机 + round_id 上限

**电控（tests）**
- `电控/tests/rpi/test_scheduler_rendering.py`、`test_gateway.py`、`test_boundaries_and_public_api.py` — 补 v3 门禁步骤（subagent A）+ CRASH 用例
- `电控/tests/integration/test_control_flow_guard.py` — 新增 SUCCESS_COUNT_OVERFLOW 用例
- `电控/stm32_logic/tests/test_{protocol,step_profile,protocol_gateway}.c` — 新增溢出/长载荷/新轮守卫用例

**视觉（Codex）**
- `视觉/src/sorting_vision/{pipeline,coordinates,sort_plan,color_quant,drop_table}.py`、`视觉/src/jsonl_emitter.py`
- `视觉/tests/test_{pipeline,sort_plan,color_quant,drop_table,jsonl_emitter}.py`、`视觉/analysis.md`

**文档**
- `docs/prompts/chatgpt-independent-review-20260829.md`（ChatGPT 提示词包，待投喂）
- `.gitignore`（`.venv-test/`、`.uv-cache/`、`电控/stm32_logic/build-*/`）

---

## 8. 下一步建议（按优先级）

1. **用户裁决** §5 分歧声明；裁决后把 Claude 报告中"采纳"项排期（C 侧重同步、255 NACK、零 identity 防御、`accept_motion_done` 显式参数）。
2. **C 侧 P1-1**：RESEND 语义确认（需与 ec_app.c 作者确认）→ 限定到 ITEM_RESULT 已发出后的状态。
3. **视觉冻结项**：采集/推理异常停止-重试策略、ROI 取整规范、NMS 同分排序 + `target_seq` 稳定规则（需与下游共同冻结）。
4. **清理**：`开源参考/视觉` 历史脚本归档（硬编码路径/串口/7 个副本）；`vision_loop_template.py` 压缩为文档；`视觉/src/test_jsonl_emitter.py` 旧副本与 `tests/` 新副本去重；视觉测试迁移到普通 shell/CI。
5. **ChatGPT 第三方视角**：投喂 `docs/prompts/chatgpt-independent-review-20260829.md`，与三节点结论交叉比对。

## 9. 可回退性（git 检查点）

本报告所有改动位于独立分支 **`20260829-multinode-review`**，检查点与修复提交：
- `8416a638` — 审查检查点（电控 bug 修复 + 视觉优化 + 报告；含 SAFETY_FIXES v3 未提交的门禁代码）
- `6d67258a` — C 侧 P1/P2 修复 + Python 网关异常兜底
- `073456d8` — 报告更新（C 侧修复记录、P1-1 RESEND 死动作核实、P2-3 核对结论、可回退说明）

回退方式：`git checkout codex/stm32-motion-test-v1`（回到本轮前），或 `git reset --hard 8416a638`（回到检查点）。原分支 `codex/stm32-motion-test-v1` 未被改动。

## 10. 赛题对齐核验（问题二 · 智能分拣，27年工创.pdf 第 9~13 页）

赛题原文已逐条提取并与实现对照（2026-08-29 补读），结论：**项目文档 `要求汇总.md` 的 R-F01~R-R05 与赛题原文逐条一致，可作为决策依据；本轮全部修复直接服务于赛题硬性规则，无需要推翻的决定。**

| 赛题硬性规则 | 对应实现 | 状态 |
|---|---|---|
| 显示本件信息完成后才能分拣下一件（P12） | `DISPLAY_ACK` 闭环 + `WAIT_MOTION_DONE` 门禁（含本轮 gateway 修复） | ✅ |
| 超 15 秒无动作或无显示 → 本轮结束（P12） | STM32 唯一监控端（要求汇总 §6.1）；显示边界=首次 DISPLAY_ACK；心跳/重传/重复刷新不重置 | ✅（Python Scheduler 不加超时，与赛题"STM32 统一监控"一致） |
| 形状+颜色完全一致同一储物盒（P11/12） | 视觉 `sort_plan` 按 `(color_id, shape_id)` 分组 → 箱号 1..6 | ✅ |
| 六个独立储物盒（P10） | `drop_table` `MAX_BOX_ID=6` | ✅ |
| 显示序号/货物名称/图片/分拣成功总数量（P12） | `DisplayContent` 5 字段（target_seq/class_id/image_id/success_count/result_code）+ 树莓派本地图片库 | ✅ |
| 每盒容纳 ≤4 件（P10） | 储物盒容量属机械要求，非软件限制；初赛 ≥12 件/≥6 类不触发 | ✅ 无需软件改动 |
| 货物 ≤40mm、托盘 ≥160×160mm、整机 ≤350×350×450mm、占地 ≤500×500mm | 机械/布局事项，软件不涉及 | — |
| 单一内置电源、比赛过程不更换（P10） | 采购/供电设计事项 | — |
| 识别文字/图像/二维码（P10） | `info_decode.py` 占位（QR/OCR 待决赛）；初赛分拣规则只用形状+颜色 | ⚠️ 决赛命题发布后需落地 |
| 一键启动（P12） | `start_verified_new_round` 人工确认 + STM32 物理按钮 | ✅ |

> 待办提醒：决赛环节的"模拟污渍/缺陷图形、文字、二维码"识别与"信息完全一致同一盒"是目前唯一未实现的功能点（`info_decode` 占位），等决赛命题发布再落地。

## 11. 主机侧闭环开发（2026-08-29 追加，多 agent 并行）

赛题巡检后补建的生产链缺口：树莓派→STM32 出站发送器、显示渲染模块、端到端闭环测试。接口契约见 `docs/design/2026-08-29-host-side-chain-interfaces.md`，三个模块由并行 subagent 按冻结契约实现（`65ffed0d`）：

| 模块 | 文件 | 说明 |
|---|---|---|
| 串口抽象 | `rpi/serial_link.py` | `SerialLink` 协议 + `FakeSerialLink`；波特率/端口由部署注入，**不写死** |
| 出站发送器 | `rpi/outbound.py` | `OutboundGateway`：发送冻结 ITEM_TASK/DISPLAY_ACK 帧；tx_seq 独立单调；task_id≠round/u16 越界/非法 payload fail-closed |
| 显示渲染 | `rpi/display.py` | `DisplayViewModel`（序号/名称/图片/成功总数）+ `build_display_view` + `FakeDisplayRenderer`；真实 HDMI 渲染由部署注入 |
| 闭环测试 | `tests/integration/test_host_side_chain.py` | 赛题"显示完成后才能分拣下一件"端到端验证（全 fake）：每件 1 条 ITEM_TASK、MOTION_DONE 门禁、显示完成前不派发下一件、显示总数==成功计数、sent=[ITEM_TASK,ACK,ITEM_TASK,ACK] |

**验证**：电控全量 **192 passed + 49 subtests**（新增 31+14+11 用例）；C 侧 **85/85**（MSVC+gcc 双零警告）。仍待开发：MaixCAM 入站（payload 未冻结）。

## 13. 应答帧实施 + 真实串口适配器（2026-08-29/30，E-1/E-2 拍板落地）

- **拍板**：用户确认 ACK/NACK 各 2 字节（原因+目标序号）、NACK 原因码 0x10~0x15 六枚（E-1/E-2）。
- **C 侧实施**（`2c34d189`，C 测试 73→85）：ACK/NACK 编解码；`last_accepted_frame_seq` 顺序门；响应缓存（与 dedup 同窗口、原样重放不递增 tx_seq、miss fail-closed）；重复 DISPLAY_ACK → RESEND；255 拒绝与 ACK 校验失败由静默改 NACK。
- **树莓派**：`PySerialLink`（pyserial 懒加载，USART2 115200 8N1 冻结默认——固件核对确认，端口部署注入；字节级帧解析复用 `decode_outer_frame`；512 字节防御上限；mock 测试 11 用例）。
- **契约冻结**：`interface-contract.md` §4.1 新增 ACK/NACK 2 字节载荷 + 6 枚 NACK 原因码 + 重发/15 秒/fail-closed 边界。
- 待办：E-6 重传上限 3 次待台架实测；Python 侧可选增强 D-1/D-2（resend_item_task、NACK 日志）。

## 14. 多 agent 三路交付（2026-08-30，`bcacad0f`）

| 路 | 内容 | 验证 |
|---|---|---|
| A1 Python 增强（D-1/D-2） | `protocol/ack_nack.py`（ACK/NACK 原因码+解析，与 C 侧逐值对齐）；`OutboundGateway.resend_item_task`（原样重放不递增 tx_seq + on_retransmit 钩子）；`PiProtocolGateway` ACK/NACK 入站解析 + STAGE 日志 | Python 192→**210 passed + 58 subtests** |
| A2 树莓派部署包 | `电控/deploy/`：`run_chain.py`（真实链路骨架：PySerialLink→Scheduler→Outbound→HdmiDisplayRenderer，视觉源/图片/字体全注入）+ `install.sh`（config.txt 备份后追加 1024×600）+ `ec-chain.service` + `requirements.txt` + `README.md` | `--fake-link` 2 件闭环 demo exit 0 |
| A3 固件测试修复 | `firmware/tests` 全绿（生产代码零改动）：axis_driver 单轴断言更新（P0-FIX 后单轴合法）；`host_stubs/` HAL 桩（HAL_GetTick）；test_app 启动链重写为真实 P0-FIX 行为（POST→HOMING→BARRIER 超时→FAULT_LOCK）；diag 掩码 01FF→03FF | 5 套件全绿（gcc -Werror） |

**当前总状态**：电控 Python **210+58**、C 逻辑 **85/85**、固件 host 测试 **5 套件全绿**、视觉 **75**（full-access）。烧录 hex 0 错 0 警已实机验证（用户确认）。

## 15. 外部独立审查复核（2026-08-30，只读审查结论核验与处理）

外部节点只读审查结论逐条核验：

| # | 结论 | 核验 | 处理 |
|---|---|---|---|
| P0-1 | 运动参数必然撞 15 秒超时（80 steps/mm@500Hz、HOME(-145,-145)→取料(0,0)=11600 步≈23.2s>15s） | ✅ 属实（占位参数，`ec_axis_driver.h`/`ec_motion_plan.h` 标注占位） | 📋 记录为**标定阻塞项**：需机械组参数 + 台架实测后冻结速度/步进，非代码问题 |
| P0-2 | 主串口文档冲突：固件 USART2/PA2/PA3，但 `interface-contract.md` §2.1 仍写主链路 USART3/PD8/PD9 | ✅ 属实（固件核对同结论） | ⏸ **待用户拍板**：契约文档同步为 USART2 主（固件已事实切换，属文档同步非协议改动，但涉冻结接口不擅动） |
| P1-1 | 启动链安全阻断（POWER_PERMISSION 未接 GPIO、挡板无反馈 → FAULT_LOCK） | ✅ 属实（fail-closed 合理） | ⏸ 等硬件接线 + 挡板反馈引脚分配（I/O 映射红线） |
| P1-2 | POST 检查弱：限位全同态只等 100ms 放行；50ms 即 PASSED，2 秒超时分支不可达 | ✅ 属实（`ec_startup_sequence.c:122-146`） | ⏸ **待用户拍板**：修复方案 = POST 真正验证限位可读（含 2 秒超时路径），或明确接受"占位自检" |
| P2 | 文档漂移 ±135 vs ±145（`2026-08-25-item-task-codec-handoff.md`） | ✅ 属实 | ✅ **已修正**为 ±1450（与契约/代码对齐） |

结论一致：**软件骨架与协议门禁成形、主机测试可信；当前真正阻塞 = 运动参数时序（标定）、串口文档冻结（拍板）、硬件反馈接口（接线）**。不应把当前状态称为"完整闭环可运行"——此评价采纳。

## 16. 外部审查修正（2026-08-30，对 `00049fc3` 的复核纠错）

外部审查对上一轮交付的复核结论（全部采纳并修正）：

| # | 批评 | 核验 | 修正动作 |
|---|---|---|---|
| 1 | **运动预算算错**：PLACE→HOME 最坏是 23200 步（+145→-145 全行程 290mm），合计 **46400 步**而非 34800；3kHz=15.47s **不满足**，原"3kHz 最坏 11.6s ✅"错误 | ✅ 属实（ec_motion_plan.h HOME/PICK 坐标） | ✅ 预算表已修正（`2026-08-30-motion-time-budget.md` §2）；**3kHz 目标撤回**，改为"先冻结落点/HOME/PICK/路径 → 按实际路线算预算 → 台架测丢步" |
| 2 | **15 秒修复越界**：提的"MOTION_DONE 重起 15 秒"不符合现有契约（滚动 `lastObservableAt` + 有效进展令牌 + 显示用预算剩余，见伪代码 L110 / 契约 L242；Python core.py OBSERVABLE_WINDOW 是现成实现）；且"发出脉冲≠实际进展"（堵转时脉冲仍走） | ✅ 属实 | ✅ 方案撤回，改为**滚动失动监控**：可观察进展令牌（台架验证，非脉冲计数）+ 预算剩余 + MOTION_DONE 不重起（`2026-08-30-motion-time-budget.md` §3.3） |
| 3 | **USART2 只同步一份文档**：硬件映射表/实测引脚表/载板原理图/Excel/M144Z 引脚总图/PCB 清单仍全是 USART3；interface-contract.md 版本号未升；且 `analysis.md` D-011 是冻结记录 | ✅ 属实（全库 grep 25+ 处；SAFETY_FIXES_v2/v3 自述 08-28 就欠账） | ✅ 盘点成清单（`2026-08-30-hardware-truth-convergence.md` §1，A/B/C 三类）；**批量同步待用户确认 USART2 为最终事实后执行** |
| 4 | **引脚分配暂缓**：执行器口径冲突（要求汇总=XY 步进+Z 舵机+夹爪舵机两个独立舵机 vs 固件=单 Z 舵机联动 vs 旧图=三轴步进+独立夹爪+腕部）；真值表未收敛前不应选挡板/失电 GPIO | ✅ 属实 | ✅ 盘点冲突（`2026-08-30-hardware-truth-convergence.md` §2）；**引脚分配一律暂缓**，先收敛唯一硬件真值表 |

**待用户拍板**（收敛后才可施工/冻结）：① USART2 为最终物理事实（是/否）→ 批量同步；② 执行器口径（单 Z 舵机联动 or 双舵机独立）；③ 15 秒滚动失动监控重构（批准）；④ 运动标定顺序（先冻结路径再测步频）。

## 17. 二次复核修正（2026-08-30，对 `34d5c5d5`）

外部审查二次复核的两处修正 + 四项结论（全部采纳）：

| # | 批评 | 修正 |
|---|---|---|
| 1 | 15 秒文档内部矛盾：§3.3 已改"MOTION_DONE 不重起"但结尾仍写"显示阶段独立 15 s 预算"；且"运动时长从 15s 预算扣除"不准确 | ✅ 措辞修正：显示阶段可用时间 = 距最后一次有效可观察进展的**剩余窗口**（最多接近 15s，不人为重起）；滚动窗口扣除的是**静默时间**非运动总时长；测试扩为 8 条（§3.4） |
| 2 | "固件代码是硬件事实权威"结论错误：Git 历史显示固件**自 8-17 就是 USART2**，8-25 冻结记录随后定 USART3 主，无批准切换记录——是**实现漂移**（固件没跟随后续冻结决定），非"固件后来切换" | ✅ 事实判定改口：**维持 USART3 主冻结基线**；`interface-contract.md` 已恢复 USART3 主并标注漂移；待实物接线确认后二选一（PD8/PD9→改固件回 USART3；PA2/PA3+明确变更→V0.7 全库同步） |
| 3 | Python OBSERVABLE_WINDOW 只是参考模型，固件无生产进展源；`ec_axis_driver_progress()` 是程序步骤计数，不能未经台架验证当实际进展 | ✅ 采纳：15 秒重构**有条件批准**——进展源默认不激活（保留适配器/开关，fail-closed） |
| 4 | 执行器口径：双舵机独立为设计基线，单舵机联动仅作待证明候选 | ✅ 采纳：基线 = Z 升降 DS3120MG + 夹爪另一只 DS3120MG；GPIO 机械确认前不冻结 |

**四项结论落档**（`2026-08-30-hardware-truth-convergence.md` §3）：USART 维持 USART3 主基线待实物确认；执行器双舵机独立基线；15 秒有条件批准（进展源 fail-closed）；运动标定顺序批准。

## 18. 15 秒滚动失动监控落地（2026-08-30，`700c508`）

按二次复核的"有条件批准"实施完成：

| 条件 | 落地 |
|---|---|
| 单调 `last_observable_ms` + `watchdog_active` | ✅ 替代固定 15s 单点计时（`ec_app.c`） |
| 令牌去重 | ✅ `ec_app_note_observable_progress`：单调 token，重复/过期不续时 |
| **进展源默认 fail-closed** | ✅ `EC_APP_PROGRESS_SOURCE_ENABLED=0`（生产 Keil 构建死代码消除）；测试目标宏 1 + 运行期开关（boot 默认 OFF） |
| MOTION_DONE 不重起 | ✅ 不触碰基准，显示阶段按剩余窗口 |
| 无效/重复 DISPLAY_ACK 不续时 | ✅ 仅 `ACK_DISPLAY_CONSUMED` 首个有效结案 |
| 回绕安全比较 | ✅ uint32 减法（含回绕测试） |
| 测试 ≥8 条 | ✅ 8 条全过（新令牌续时/重复去重/恰 15s/14.9s 重计/MOTION_DONE 不重起/无效 ACK/tick 回绕/堵转 fail-closed） |

验证：gcc + cmake/ctest 双通道全绿；宏 0/1 双配置 -Werror 通过；变异检查证明测试非空转。发现并修正：旧 READY 清除路径在当前状态机不可达（有效 ACK 转 PREPARE_BARRIER）→ 改用 `ACK_DISPLAY_CONSUMED` 作结案信号。

## 12. 屏幕到货与 HDMI 渲染器（2026-08-29 追加）

- **屏规格**：树莓派 7"/10" 系列 HDMI 屏，本项目 **1024×600**（说明书提取，`docs/design/2026-08-29-hdmi-screen-arrival-verification.md` 含接线、config.txt、上电验证清单 8 项、FAQ）。上电验证为 L4 授权操作，待用户安排。
- **真实渲染器**（`5923f82c`）：`rpi/display_hdmi.py` `HdmiDisplayRenderer`——Pillow 合成 1024×600 帧（序号/货物名称/图片/成功总数），`image_loader`/`frame_output`/`font_path` 全部注入（硬件参数不写死），fail-closed（图片加载失败不产半成品帧），`complete()` 对接 PendingRender→RenderReceipt→DISPLAY_ACK 闭环。14 用例，合成帧经视觉核验布局正确。
- **部署提醒**：树莓派端渲染需注入中文字体（如 `fonts-wqy-zenhei`）与真实 frame_output（pygame/framebuffer）；图片目录、字体路径、输出方式均为部署配置。

---

*主机侧纯逻辑结论；不构成固件、串口、相机、实机通过的证据。*
