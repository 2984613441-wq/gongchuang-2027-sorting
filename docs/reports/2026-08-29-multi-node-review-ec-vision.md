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

回退方式：`git checkout codex/stm32-motion-test-v1`（回到本轮前），或 `git reset --hard 8416a638`（回到检查点）。原分支 `codex/stm32-motion-test-v1` 未被改动。

---

*主机侧纯逻辑结论；不构成固件、串口、相机、实机通过的证据。*
