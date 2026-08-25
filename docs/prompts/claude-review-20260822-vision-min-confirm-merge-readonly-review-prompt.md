# 给 Claude 的 2026-08-22 视觉 V0.1 合并批次只读审核词

## 用途

委托 Claude 对已合入主仓库的视觉 V0.1 三个提交（推理核心、诊断加固、
`min_confirm_frames`）做一次独立、只读回归审核，并给出桌面仓库与 worktree
视觉侧分叉的处置建议。

该审核只评价当前工作区代码、测试和文档；不授权修改文件、创建提交、push、
接线、上电、烧录、实机运动、访问真实串口或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“2026-08-22 视觉 V0.1 合并批次”
做回归审核。你只负责发现事实错误、协议/契约不一致、语义未锁定、测试盲区、
文档与证据表述问题；你不是设计者，也不修改任何文件。

工作区：
- 主仓库：C:\Users\29845\Desktop\工创赛（分支 codex/stm32-motion-test-v1，
  HEAD=5d80f922）
- 对照 worktree：C:\Users\29845\.codex\worktrees\0f5a\工创赛
  （与主仓库共享同一 .git 对象库，detached HEAD=db8c6d35）

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得创建提交或 push；
  不得运行会写入工作区的命令。
- 不得接线、上电、烧录、驱动实物、访问真实串口或外部账号。
- 可读取本地文件，可执行 git status/diff/log 等只读检查；可运行不写工作区的
  测试（如 PYTHONDONTWRITEBYTECODE=1 python -m unittest ...）。
- 若无法独立验证，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不改变用户最终裁决，也不构成实机或外部执行授权。

先完整阅读下列基线，再核对本次变更：
1. AGENTS.md 与 CLAUDE.md
2. docs/prompts/codex-handoff-20260822-next-conversation-prompt.md
3. 视觉/README.md、视觉/TRAINING.md、视觉/src/sorting_vision/*、
   视觉/tests/*、视觉/examples/fake_demo.py
4. 主仓库提交：6ed4d9db、5e83399c、5d80f922 及父提交 fd369a28
5. 对照 worktree 提交：dc2b7f7b、91ae0991、db8c6d35
6. 上述提交的 git diff 与 git diff --check

已确认事实（Codex 已实测或静态核对）：
- 三个视觉提交已从 worktree 分支 cherry-pick 到主仓库，内容与来源提交一致：
  - 6ed4d9db ← dc2b7f7b（视觉推理核心与单目标循环，25 文件）
  - 5e83399c ← 91ae0991（诊断加固与错误边界，4 文件）
  - 5d80f922 ← db8c6d35（min_confirm_frames，3 文件）
- 文件数说明：“25 文件”为主仓库提交统计；来源 dc2b7f7b 原为 28 文件，
  差 3 个 .gitkeep（主仓库已存在），内容一致但文件数不同，不影响结论。
- git diff db8c6d35 5d80f922 -- 视觉 只剩主仓库独有的 3 个分叉文件
  （jsonl_emitter.py、test_jsonl_emitter.py、vision_loop_template.py），
  说明本次 cherry-pick 的视觉路径与 worktree 完全一致。
- 主机测试：PYTHONDONTWRITEBYTECODE=1 python -m unittest discover
  -s 视觉/tests -v → Ran 38 tests, OK。
- 前序 Claude 审查结论（用户提供，针对 91ae0991 快照，当前 HEAD 已前移）：
  2 个 Important + 2 个 Minor。Codex 核对当前提交后判定均已在 5d80f922 内解决：
  - min_confirm_frames 达到 N 后持续上报：README 与 docstring 已锁定
    “arm-then-stream”，并有 test_loop_keeps_emitting_after_confirmation
    断言 [2,3,4]。
  - README 参考环境核验：原文已注明产物在桌面仓库根目录、未纳入 worktree；
    桌面根目录实际存在 开源参考/ 与 智能分类垃圾桶全套文件.zip，且
    .gitignore 按设计忽略两者。
  - 失败帧重置：test_loop_failure_frame_resets_confirmation_and_is_emitted
    覆盖 OK,FAIL,OK×3 并断言 [2,5]。
  - max_frames 截断：README 已注明未凑满 N 的目标不上报。
- 已知分叉（待你确认处置建议）：主仓库 视觉/src 额外保留
  jsonl_emitter.py、test_jsonl_emitter.py、vision_loop_template.py；
  worktree 视觉分支没有这三个文件。两者尚未统一为单一视觉接口。
- 未执行：真实模型、相机、树莓派/MaixCAM、串口、屏幕、STM32、电机和整机。

请按下列顺序审核。

一、合并一致性
1. 核对 5d80f922 与 db8c6d35 的 视觉 路径内容是否一致，确认 cherry-pick
   未引入差异；diff 应只剩主仓库 3 个独有分叉文件。
2. 核对三个提交是否只触碰视觉相关文件，未混入电控/集成/文档无关改动。

二、min_confirm_frames 语义
1. 确认“连续 N 帧同类别才上报；达到 N 后持续逐帧上报”在代码、docstring、
   README 三处一致。
2. 检查失败帧重置、类别变化重置、max_frames 截断的行为和测试覆盖；
   指出仍缺的边界（例如 N=1 默认、连续失败、类别变化后 N 帧重算）。
3. 评估“持续上报 + 下游去重”对运动侧/桥接层（集成/demo_bridge）的
   真实风险，并给出是否需要边沿触发/锁存的建议。
4. 核对视觉 `min_confirm_frames` 默认值与桥接端 `StabilityConfig` 默认值是否
   匹配：视觉 `single_target.py` 为 `min_confirm_frames=1`（单帧即报），
   桥接端 `bridge.py` 为 `consecutive_frames=5`、`release_after_ms=1000`。
   注意两侧释放语义单位不同（视觉为“release frames”帧数、桥接为毫秒），
   评估部署时双重过滤叠加延迟或单层失效的风险。

三、前序审查闭环
1. 确认 4 个发现是否确实解决，文档/测试证据是否可追踪。
2. 检查是否出现新的行为或文档不一致。

四、README 与证据
1. 核对“参考环境核验”的位置表述、产物存在性、gitignore 设计是否一致；
   是否需要补充更精确路径或核验报告引用。
2. 核对 TRAINING.md、fake_demo 示例等新增内容是否有未实现承诺。

五、桌面/worktree 分叉
1. 评估 jsonl_emitter.py / vision_loop_template.py 与 sorting_vision 同时
   存在造成的契约混淆风险。
2. 给出处置建议（保留双轨 / 迁移合并 / 淘汰旧模板），并列出最小验证步骤；
   不得直接修改文件。

六、测试与证据
1. 核对 38/38 测试与新增 4 个循环用例的断言强度。
2. 检查是否存在只测实现细节而放过真实接入契约的空转测试。

七、结论边界
1. 明确区分“主机测试通过”“静态核对通过”“实机/真实模型已通过”。
2. 列出视觉接入真实模型和运动侧联调前的门禁。

输出要求：
1. 将审核记录创建为新的文件（不要覆盖旧审核）：
   .claude/reviews/REVIEW-20260822-005-claude-vision-min-confirm-merge.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确
   “审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：
   - 视觉 V0.1 合并批次：通过 / 有条件通过 / 不通过
   - 桌面/worktree 分叉处置：允许 / 有条件允许 / 不允许
3. 随后按 Important、Minor、其他排序列出发现项。每项必须包含：编号、
   严重性、事实或证据、精确定位、风险、可验证的整改建议、整改后需要复查
   的证据。没有发现也必须明确写“Important（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”，不得混写。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得修改生产代码、测试或历史审查
   文件，不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成新的采纳/驳回/待确认
记录。任何文件合并、删除旧模板、真实模型/相机验证、串口实测、push 或 git 改写
仍须用户对具体动作授权。
