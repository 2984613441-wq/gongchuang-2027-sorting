# 视觉 A 方案闭环核验 — 2026-08-23

> 只读复审。核验对象：`5812d6e0`（A 方案落实提交）是否真实、完整地闭环
> `REVIEW-005` 的 I-1 / M-1 / M-2，以及是否引入新问题。
> 本轮未修改任何文件（除本记录外）、未提交、未上电、未接串口、未碰真实相机/树莓派/MaixCAM/STM32/电机/整机。

## 结论摘要

| 发现项 | 状态 | 一句结论 |
|---|---|---|
| I-1（去抖责任方） | **闭环（近期处置）** | 决策稿已落盘"已裁决 A"，桥接层为唯一去抖方，视觉层 stream 抑制保留为诊断/离线；`rg` 确认未误接进桥接层。防呆为**文档级**而非代码级（见建议 S-1）。 |
| M-1（N=1 默认命名用例） | **闭环** | `test_loop_default_min_confirm_frames_emits_each_frame` 存在，断言 `[1,2,3]`，走默认 `min_confirm_frames=1` 路径，实测通过。 |
| M-2（输出格式对照文档） | **闭环** | README 新增"视觉输出格式与真实链路消费方"表 + 唯一去抖责任方说明，与实际代码一致。 |
| 新问题 | **未引入** | 生产代码零改动（唯一"代码"改动是新增一个测试）；无回归风险。 |

**总体**：`5812d6e0` 真实、完整地闭环了三项发现，未引入新问题。A 方案作为"文档化决策 + 未接线"是**可接受的风险留痕**（当前预集成阶段），但建议在视觉接入真实模型前补一条代码级/测试级护栏，把"sorting_vision 不生成 wire 帧"从文档断言升级为可验证断言（S-1）。

---

## 已确认事实（本会话亲自跑命令/读文件）

### 提交与分支
- `git rev-parse HEAD` → `5812d6e071b9712065ccc60f64876366d88da02e`。
- `git branch --show-current` → `codex/stm32-motion-test-v1`。
- `git log --oneline` 顶两条为 `5812d6e0` ← `5d80f922`，父提交正确。
- `git show --stat --oneline 5812d6e0` → 仅 3 个文件、114 行插入、0 删除：
  - `docs/design/2026-08-23-vision-dedup-responsibility-decision-draft.md`（新增，+91）
  - `视觉/README.md`（+12）
  - `视觉/tests/test_single_target.py`（+11）
- `git diff --check 5d80f922 5812d6e0 -- 视觉 docs/design` → 无输出、退出码 0（无 whitespace 错误）。

### I-1 证据
- `rg -n "sorting_vision|min_confirm_frames" 集成` → **无匹配**（视觉核心未误接进桥接层）。
- `集成/demo_bridge/action_bridge.py:22-34` 从 `bridge` 导入 `jsonl_events`、`DetectionStabilizer`；`main()` 于 `:466` 以 `jsonl_events(sys.stdin)` 作为事件源，不消费 `sorting_vision`。
- `视觉/src/jsonl_emitter.py:21-29` 只输出 4 字段 `frame_id/label/confidence/ts_ms`，docstring 明确"Extra fields are rejected by the bridge, so this module never emits bbox or diagnostic fields"。
- 决策稿 `docs/design/2026-08-23-vision-dedup-responsibility-decision-draft.md`：
  - `:5` 状态"已裁决 A；本文件只做决策记录，不修改代码，也不构成实机授权"。
  - `:38-48` 方案 A：桥接层 `DetectionStabilizer` 为唯一去抖方；`sorting_vision.min_confirm_frames` 保留但明确为"诊断/离线使用"，真实运动路径不使用其 stream 抑制。
  - `:68-72` 第 4 节推荐 A；`:82-86` 第 6 节最小验证（补 M-1/M-2、grep 确认、跑测试）与本提交内容一致。

### M-1 证据
- `视觉/tests/test_single_target.py:227-236`
  `test_loop_default_min_confirm_frames_emits_each_frame`：`SingleTargetLoopConfig(model_path="fake.pt", labels=("block",), max_frames=3)`（**未传** `min_confirm_frames`，走默认 `=1`），断言 `[1, 2, 3]`。
- 实测通过（见下"通过的检查"第 5 条）。

### M-2 证据
- `视觉/README.md:46-56` 新增"视觉输出格式与真实链路消费方"表，三行：
  - `src/sorting_vision/` → 诊断 text/JSON，当前不消费，离线/诊断单目标核心；
  - `src/jsonl_emitter.py` → 4 字段 JSONL，`集成/demo_bridge/action_bridge.py` 消费，真实 wire 输入；
  - `src/vision_loop_template.py` → 旧桌面诊断 text，不消费，历史模板待归档。
- 表格下方明确"真实运动链路以桥接层 `DetectionStabilizer` 为唯一去抖责任方……`sorting_vision.min_confirm_frames` 当前仅用于诊断/离线路径，不接入真实运动链路，避免双重去抖"。
- 三份输出路径实测均存在：`视觉/src/sorting_vision/`、`视觉/src/jsonl_emitter.py`、`视觉/src/vision_loop_template.py`。
- 消费方与实际代码一致：`集成/deployment/README.md:6,16-17,25-26,38` 均指向 `jsonl_emitter.py → action_bridge.py`。

### 生产代码改动范围
- 本提交对 `视觉/src/**` 与 `集成/**` 的**生产代码零改动**；唯一触及 `.py` 的改动是新增一个测试方法。

---

## 推断（标明依据）

- **T-1**：A 方案本质是"文档化决策 + 未接线"，代码里没有为"禁止把 sorting_vision 误接进桥接层"增加任何刻意防呆。
  依据：`git show --stat` 仅文档+测试三文件；决策稿 `:5` 自称"只做决策记录，不修改代码"。
- **T-2**：当前存在一条**隐性**格式护栏，但它属"偶发"而非"刻意"：`bridge.py:43-47` 的 `Detection.from_json_line` 要求字段集**恰好等于** `{frame_id,label,confidence,ts_ms}`，而 `sorting_vision` 的诊断 JSON（`schema_version/diagnostic_only/...` 多字段）与诊断 text（`3:block:...` 非 JSON）都会被该检查拒绝，无法被静默消费。
  依据：`bridge.py:42-47` 严格字段集校验；`jsonl_emitter.py:1-9` docstring 说明桥接拒绝额外字段。
- **T-3**：新 M-1 用例与既有 `test_loop_honors_max_frames_and_releases_backend`（`:309-321`，同样用默认 `min_confirm_frames=1` 断言 `[1,2,3]`）在"N=1 逐帧上报"的断言上**部分重叠**；但新用例把"逐帧上报"与"max_frames 截断"两个关注点拆开（backend `frames=3` == `max_frames=3`，不触发截断），命名更贴切，属可接受的针对性闭环。
  依据：两用例均断言 `[1,2,3]`，但 `frames` 参数不同（4 vs 3）。

---

## 建议

- **S-1（主要）**：在视觉接入真实模型**之前**，补一条负向集成测试，把 T-2 的"偶发格式护栏"固化为"刻意、可验证"的不变量——例如在 `集成/demo_bridge` 测试中，把 `sorting_vision` 的诊断 JSON 与诊断 text 分别喂给 `Detection.from_json_line`，断言均抛出 `BridgeError`。此举零生产代码改动，直接把"决策已记录"升级为"行为已保证"，是填补"文档级防呆"与"代码级防呆"差距的最低成本动作。
- **S-2**：若短期不补 S-1，至少把"C 方案（单一权威契约）"显式写为"视觉接入真实模型前的门禁"（决策稿第 4 节已隐含"跑通一次闭环后评估 C"，建议把触发点写死为门禁而非软性评估）。
- **S-3（可选清理）**：决策稿 `:26` 引 `action_bridge.py:25-30`，实际 import 块为 `:22-34`；`:31` 引 `:465-466`，实际 `jsonl_events(sys.stdin)` 在 `:466`。行号略有偏移，指向的代码均正确，不构成结论错误，可在下次修订时校准。

---

## 未知 / 不能得出的结论

- **主机测试通过**（`视觉/tests` 39 项、`集成/demo_bridge` 24 项）**不等于** Keil 构建通过，也**不等于**实机通过。
- 本轮**未执行**任何：真实模型、相机、树莓派/MaixCAM 推理、串口、屏幕、STM32、电机、整机闭环。
- **不能得出**"真实模型下 `min_confirm_frames` 或 `consecutive_frames` 取值合理"的结论。
- **不能得出**"视觉→运动去抖语义在实机上无冲突"的结论（主机侧已文档化收敛，实机侧未验证）。

---

## 通过的检查 / 未执行的检查 / 不能得出的结论

### 通过的检查（静态核对或主机测试）
1. HEAD=5812d6e0、分支 codex/stm32-motion-test-v1、父提交 5d80f922 均吻合。
2. 提交范围仅 3 文件（决策稿 + README + 测试），114 插入 0 删除，无越界。
3. `git diff --check` 干净。
4. `rg "sorting_vision|min_confirm_frames" 集成` 无匹配。
5. `视觉/tests` → **Ran 39 tests, OK**（含 M-1 新用例）。
6. `集成/demo_bridge` → **Ran 24 tests, OK**。
7. 三份输出路径均存在；README 对照表与实际代码、deployment README 指向一致。

### 未执行的检查
- 真实模型、相机、树莓派/MaixCAM 运行。
- Keil/STM32 固件构建。
- 串口、屏幕、STM32、电机、整机闭环。
- 负向集成测试（S-1 建议项，本轮仅建议、未授权执行）。

### 不能得出的结论
- 不能得出"实机/串口/屏幕/电机已通过"的任何结论。
- 不能得出"防呆已在代码级保证"的结论（当前为文档级，见 T-1/T-2）。
- 不能得出"真实模型下参数取值合理"的结论。

---

## 独立性限制（如实声明）

本次复审的**全部事实**均在本会话内通过重新执行只读命令（git / rg / unittest / 读文件）直接获得，不依赖 `REVIEW-005` 的结论；闭环判定目标（I-1/M-1/M-2）也由本审核词背景段独立重述。但本会话是产出 `REVIEW-005` 的同一会话的延续，`REVIEW-005` 全文已在本会话上下文中，故"闭环判定"并非模型分离的真独立，对"是否闭环"的判断存在先验一致性风险。缓解措施：所有可检查事实均已重新推导，未沿用旧结论。
