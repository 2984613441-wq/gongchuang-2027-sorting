# 视觉 V0.1 合并批次只读回归审核 — 2026-08-22

## 总体裁决

- **视觉 V0.1 合并批次：有条件通过**
- **桌面/worktree 分叉处置：有条件允许**

合并本身（cherry-pick）忠实、无越界、无 whitespace 错误、38/38 主机测试通过；
`min_confirm_frames` 逻辑正确且三处（代码/docstring/README）一致，前序 4 项闭环证据
齐备。**不通过项**不在本次提交内容里，而在合并后浮出的架构问题：`min_confirm_frames`
去抖与运动桥接层 `DetectionStabilizer` 去抖语义重复且方向相反，且两者当前互不接线，
需在真实视觉↔运动联调前收敛（见 I-1）。

---

## 已确认事实 / 推断 / 建议 / 未知 / 弱独立性限制

### 已确认事实（直接对照主仓库实测/静态核对）
- `HEAD=5d80f922`，三提交 `6ed4d9db`(25 文件) / `5e83399c` / `5d80f922` 依次叠在 `fd369a28` 上。
- 三提交合计改动 25 个文件，**全部位于 `视觉/` 下**，未混入电控/集成/文档无关改动。
- `git diff --check fd369a28 5d80f922 -- 视觉` 无 whitespace 错误。
- `git diff db8c6d35 5d80f922 -- 视觉` 只剩主仓库独有的 3 个分叉文件：
  `jsonl_emitter.py`、`test_jsonl_emitter.py`、`vision_loop_template.py`（+355 行），
  即 `sorting_vision/` 与 README 等共享文件与 worktree 逐字一致，cherry-pick 无差异。
- 主机测试 `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s 视觉/tests` → **Ran 38 tests, OK**。
- `min_confirm_frames` 语义三处一致：
  - 代码 `视觉/src/sorting_vision/single_target.py:274-287`（streak 计数 + `emit`）
  - docstring `single_target.py:248-251`（"after that, every subsequent same-class frame is emitted"）
  - `视觉/README.md:37-40`（"达到 N 后，后续同类帧继续逐帧上报，由下游按需去重"）
- 前序 4 项发现均已在 `5d80f922` 内闭环（证据见下"通过的检查"）。
- README "参考环境核验"所述产物真实存在且被 gitignore 忽略：
  - `开源参考/`（目录）、`智能分类垃圾桶全套文件.zip`（565MB）在桌面仓库根目录；
  - `.gitignore:141-142` 明确忽略两者；
  - `开源参考/视觉/requirements.txt` 实测存在。
- 桥接层存在独立的去抖实现 `集成/demo_bridge/bridge.py:66-70`（`StabilityConfig`：
  `min_confidence=0.70`、`consecutive_frames=5`、`release_after_ms=1000`），
  及 `DetectionStabilizer`（`bridge.py:178-226`，**latch-once** 语义）。

### 推断
- `sorting_vision` 的 `min_confirm_frames` 当前是"孤岛"：实现+测试齐全，但真实运动链路
  （`集成/demo_bridge/action_bridge.py`）消费的是 `jsonl_emitter.py` 的 4 字段 JSONL，
  而非 `sorting_vision` 输出；`jsonl_emitter` 本身无任何去抖。故该特性尚未进入真实路径。
  此推断依据：`action_bridge.py:15-32` 从 `bridge.py` import `jsonl_events`/`DetectionStabilizer`，
  `main()` 以 `jsonl_events(sys.stdin)` 作为事件源。

### 建议
- 联调前明确"谁负责去抖"：桥接层 `DetectionStabilizer`（latch + release 窗口）或视觉层
  `min_confirm_frames`（stream）二选一，避免双重去抖与语义冲突（见 I-1）。
- 收敛三套视觉输出格式（`sorting_vision` 诊断 / `jsonl_emitter` wire / `vision_loop_template` 模板）。

### 未知
- 真实模型/相机/树莓派或 MaixCAM 上的行为、延迟、精度未验证。
- 串口、屏幕、STM32、电机、整机闭环未执行。

### 弱独立性限制
- 本次审核由**参与前序视觉审查的同一会话**执行，模型未分离。对"前序闭环"的判断存在
  先验一致性风险；但合并一致性、语义一致性、分叉风险三项是本轮**直接对照主仓库实测**，
  与先验无关。

---

## 发现项

### Important

**I-1 · `min_confirm_frames`（stream）与桥接层 `DetectionStabilizer`（latch）语义重复且方向相反，且当前互不接线**

- **事实/证据**：
  - 视觉层 `single_target.py:281` `emit = confirm_streak >= config.min_confirm_frames`，达到 N 后
    **持续逐帧上报**（arm-then-stream），docstring（`:248-251`）与 README（`:37-40`）均明确"由下游去重"。
  - 桥接层 `bridge.py:178-226` `DetectionStabilizer` 在连续 `consecutive_frames` 帧同 label 后
    **锁存并只返回一次**（`:222-225`），随后静默直到无目标持续 `release_after_ms` 才解锁
    （latch-once / 边沿触发）。
  - 二者语义在"达到阈值之后"完全相反：一个持续流式，一个锁存单次。
  - 真实运动链路 `action_bridge.py` 消费 `jsonl_emitter.py`（4 字段 JSONL，无去抖），不消费
    `sorting_vision`；去抖由桥接层自己的 `DetectionStabilizer` 承担。
  - 默认值也不同：视觉 `min_confirm_frames=1`，桥接 `consecutive_frames=5`。
- **精确定位**：
  - `视觉/src/sorting_vision/single_target.py:274-287`（stream emit）
  - `集成/demo_bridge/bridge.py:178-226`（latch stabilizer）
  - `视觉/src/jsonl_emitter.py`（wire 4 字段，无去抖）
- **风险**：若未来把 `sorting_vision` 的 stream 输出接进桥接层，会与 `DetectionStabilizer` 的
  `consecutive_frames` 叠加成**双重去抖**；或按 `min_confirm_frames` 的"下游去重"假设去写桥接层，
  则与桥接层既有的 latch 模型冲突。当前不报错（真实模型/串口未接），但属联调前必须决策的契约缺口。
- **可验证的整改建议**（任一即可，需用户授权后执行）：
  1. 确立单一去抖责任方并写入 `docs/design/`；若桥接层为准，视觉层 `min_confirm_frames` 退化为
     "逐帧单目标检测 + 失败关闭"（或保留但标注"诊断专用，不经运动链路"）。
  2. 明确 `sorting_vision` 与 `jsonl_emitter` 的输出契约关系：谁生成 wire 帧、谁只做诊断，
     避免三套格式并存。
  3. 淘汰/归档 `vision_loop_template.py` 与 `jsonl_emitter.py` 中被取代者。
- **整改后需复查**：`grep -rn` 确认视觉↔桥接的输入源唯一；`集成/tests` 与 `视觉/tests` 各自
  对同一去抖语义的用例不互相矛盾；`docs/design/` 有单一契约文档。

### Minor

**M-1 · `min_confirm_frames=1` 默认路径无命名用例直接锁定**

- 现有覆盖：`test_loop_honors_max_frames_and_releases_backend` 用默认 `min_confirm_frames=1`
  断言 `[1,2,3]`，间接证明单帧即报；`test_loop_keeps_emitting_after_confirmation` 证明 N>1 的
  stream。但没有一个命名用例显式断言"N=1 时首帧即上报且无抑制"。
- 定位：`视觉/tests/test_single_target.py`。
- 建议：补一个 `test_loop_default_min_confirm_frames_emits_each_frame`（min=1，3 帧 → `[1,2,3]`），
  把默认语义钉死。

**M-2 · 三套视觉输出格式无单一"谁是权威"文档**

- `sorting_vision`（诊断 text/JSON）、`jsonl_emitter.py`（4 字段 wire JSONL）、
  `vision_loop_template.py`（模板诊断 text）三者并存，各自自述定位（"不是 wire codec" /
  "bridge-compatible" / "TEMPLATE"），但没有一份文档回答"视觉→运动桥接到底吃哪一份"。
- 定位：`视觉/README.md`（未指向桥接消费方）、`集成/deployment/README.md:16`（指向 `jsonl_emitter.py`）。
- 建议：在 README 或 `docs/design/` 补一段"输出格式与消费方对照"，把三条路径的权威性一次说清。
  此为 I-1 的文档侧配套，不阻塞本次提交。

---

## 通过的检查 / 未执行的检查 / 不能得出的结论

### 通过的检查（静态核对或主机测试）
1. cherry-pick 一致性：`git diff db8c6d35 5d80f922 -- 视觉` 仅 3 个分叉文件，共享文件逐字一致。
2. 改动范围：三提交 25 文件全在 `视觉/`，无电控/集成/文档越界。
3. whitespace：`git diff --check` 干净。
4. 主机测试：38/38 通过。
5. `min_confirm_frames` 语义：代码/docstring/README 三处一致；4 个循环用例
   （连续确认、类别变化重置、达到 N 后持续、失败帧重置）断言正确。
6. 前序 4 项闭环（逐项证据）：
   - 持续上报语义 → docstring `:248-251` + README `:37-40` + `test_loop_keeps_emitting_after_confirmation` `[2,3,4]`。
   - README 参考环境 → 产物存在 + `.gitignore:141-142`。
   - 失败帧重置 → `test_loop_failure_frame_resets_confirmation_and_is_emitted` `[2,5]`。
   - max_frames 截断 → README `:39-40`。
7. README 证据：`开源参考/`、zip、`开源参考/视觉/requirements.txt` 均实测存在。

### 未执行的检查
- 真实模型、相机、树莓派/MaixCAM 运行。
- 串口、屏幕、STM32、电机、整机闭环。
- 桥接层自身测试（`集成/demo_bridge/test_action_bridge.py` 等）未在本轮复跑——属电控/集成域，
  不在本次视觉合并范围，但 I-1 关联其去抖语义。

### 不能得出的结论
- 不能得出"视觉→运动链路去抖语义已统一"的结论（恰相反，见 I-1）。
- 不能得出"真实模型下 min_confirm_frames 参数取值合理"的结论。
- 不能得出"实机/串口已通过"的任何结论。

---

## 最小整改清单与复审触发条件

### 最小整改清单（均需用户对具体动作授权，本审核不代为执行）
1. **联调前决策去抖责任方**（I-1）：视觉层 stream vs 桥接层 latch 二选一，写入 `docs/design/`。
2. 补 `M-1` 的 `min_confirm_frames=1` 命名用例。
3. 补 `M-2` 的"输出格式与消费方对照"文档。
4. 淘汰/归档被取代的 `vision_loop_template.py` 或 `jsonl_emitter.py`（I-1 第三步，可选延后）。

### 复审触发条件
- 当视觉输出首次真实接入 `集成/demo_bridge` 时（无论哪一份输出），必须复审 I-1 是否已收敛；
- 当 `min_confirm_frames` 或 `DetectionStabilizer.consecutive_frames` 任一默认值被改动时；
- 当三套输出格式减少到一套或明确主从关系时。
