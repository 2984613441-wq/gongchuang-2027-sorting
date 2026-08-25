# Claude 只读复审提示词 · 视觉 A 方案闭环核验（2026-08-23）

你是本项目的外部独立只读审查方。本轮**不修改任何文件、不提交、不上电、不接
串口、不碰真实相机/树莓派/MaixCAM/STM32/电机/整机**。你的产出只是把结论写进
指定记录文件，供用户带回工作区逐项核验。

## 背景

- 上一轮 `REVIEW-20260822-005-claude-vision-min-confirm-merge.md` 给出“有条件通过”，
  并留下 3 项发现：I-1（视觉 stream 去抖 vs 桥接 latch 去抖语义冲突且互不接线）、
  M-1（`min_confirm_frames=1` 默认路径缺命名用例）、M-2（三套视觉输出格式无单一权威文档）。
- 用户已裁决 I-1 选 **A 方案**：桥接层 `DetectionStabilizer` 作为真实运动链路
  **唯一**去抖责任方；视觉层 `min_confirm_frames` 保留为诊断/离线能力，不接入真实运动链路。
- 落实 A 的提交为 `5812d6e0`（当前 `HEAD`），叠在 `5d80f922` 之上。

## 你的任务

独立核验 `5812d6e0` 是否**真实、完整地**闭环了 I-1 / M-1 / M-2，并指出是否引入新问题。
重点是：不要把“文档里写了”当成“代码里已保证”，要区分“决策已记录”与“行为已改变”。

## 需要逐项核验的事实

1. `HEAD` 与分支：
   `git rev-parse HEAD` 应为 `5812d6e0`，`git branch --show-current` 应为
   `codex/stm32-motion-test-v1`；`git log --oneline -3` 的父提交为 `5d80f922`。

2. 提交范围只含 3 个文件：
   `git show --stat --oneline 5812d6e0` 应只有
   `docs/design/2026-08-23-vision-dedup-responsibility-decision-draft.md`（新增）、
   `视觉/README.md`、`视觉/tests/test_single_target.py`。

3. 决策稿状态与结论：
   通读 `docs/design/2026-08-23-vision-dedup-responsibility-decision-draft.md`，
   确认状态为“已裁决 A”，且 A 方案描述与第 4 节推荐、第 6 节最小验证一致。

4. I-1 是否真正闭环：
   - `rg -n "sorting_vision|min_confirm_frames" 集成` 应**无匹配**（确认视觉核心未误接进桥接层）。
   - `视觉/README.md` 新增“视觉输出格式与真实链路消费方”表是否与实际代码一致：
     三份输出路径 `视觉/src/sorting_vision/`、`视觉/src/jsonl_emitter.py`、
     `视觉/src/vision_loop_template.py` 是否都存在；表中所写消费方
     （`集成/demo_bridge/action_bridge.py` 消费 `jsonl_emitter.py`）是否与
     `action_bridge.py` 真实 import / 事件源一致。
   - 明确指出：A 方案是“文档化决策 + 未接线”，并未在代码里加任何防呆约束；
     请评估这是否属于可接受的风险留痕，还是需要补一层代码级护栏。

5. M-1 是否闭环：
   检查 `视觉/tests/test_single_target.py` 的
   `test_loop_default_min_confirm_frames_emits_each_frame` 是否存在、断言是否为
   `[1, 2, 3]`，以及是否真正走了默认 `min_confirm_frames=1` 路径。

6. M-2 是否闭环：
   检查 README 对照表是否说清“谁生成 wire 帧、谁只做诊断、真实链路吃哪一份”。

## 需要实际运行的主机命令（只读，禁止联网/硬件）

```bash
git rev-parse HEAD
git show --stat --oneline 5812d6e0
git diff --check 5d80f922 5812d6e0 -- 视觉 docs/design
rg -n "sorting_vision|min_confirm_frames" 集成
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s 视觉/tests -v
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s 集成/demo_bridge -v
```

预期：`视觉/tests` 39 项 OK，`集成/demo_bridge` 24 项 OK，`rg` 无匹配。

## 输出格式

严格按以下四段写，禁止把未执行项写成“通过”：

- **已确认事实**：只写你亲自跑命令/读文件得到的结果，附命令与证据。
- **推断**：标明是推断，附依据。
- **建议**：可执行的整改建议。
- **未知 / 不能得出的结论**：主机测试、Keil 构建、实机通过三者必须分开表述；
  本轮不得声称任何实机、串口、屏幕、电机结论。

另附“通过的检查 / 未执行的检查 / 不能得出的结论”三小节。

## 输出文件

写到这里（目录不存在则创建）：

`.claude/reviews/REVIEW-20260823-006-claude-vision-a-plan-closure.md`

编号 `006` 是既有 001..005 之后的下一个全局号，不要重号覆盖。
