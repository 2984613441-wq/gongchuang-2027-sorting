# 尚待固化的讨论：ai-kingdom-continuity

## Codex 增量 v0.1

- 用户与 Codex 在本任务确认“共同理解优先、实际读盘、带版本回执”。在正式共享规范未升级的意义上，状态为 `AGREED_PENDING_FORMALIZATION`；任务内授权已生效。
- 修复跨文件版本漂移、升级共享规范是 `PROPOSED`，不是已确认的实施范围。
- 下方 W4 的提议不会因为使用了 AGREED_PENDING_FORMALIZATION 字样就成为共识。下方平台限制属于原作者，不外推到 Codex。
- 真实用户纠正及本次授权的唯一事实位置在 SHARED-UNDERSTANDING 顶部和 DECISIONS 的 C-D001 至 C-D004；本文件仅引用。

- state_revision: 3

> **⚠ 时间戳口径（R12 / E17）**：本文件时间戳为**估计值，未经测量**；权威时间以文件系统 mtime 为准。

记录**已经达成共识但尚未进入正式文件**的内容、用户纠正与关键讨论出处。
提议与共识分开记录；迁移到正式决定后保留引用。

---

## W1（2026-09-25T20:30）本轮用户指令 = 四条纠正 + 一个优先级重排

出处：用户本轮消息原文。

> "交接必须首先保留用户与 AI 对问题的共同理解、用户纠正及尚未确定的理解，
> 再保留已定决定、待固化共识、精确参数、证据和下一步。"
> "启动或恢复时实际读取文件并提交带版本的回执。"
> "只报告你所在节点真实完成的工作；不要替其他 AI 报完成。"
> "先核查本机 Active Root 和现有规则"

**共识状态**：以下四条已由用户直接指令确立，但**尚未写入正式规范**（包内 `core/HANDOFF-CONTRACT.md`
是草案，且该契约本身在 `AUTHORITATIVE-SOURCES.yaml` 中仍为候选/UNRESOLVED）。

- W1-a 共同理解优先于决定与进度（→ DECISIONS D-001）
- W1-b 实际读取 + 带版本回执（→ D-003）
- W1-c 只报本节点真实完成（→ D-002）
- W1-d 只读核查优先、不覆盖既有权威（→ D-004）

状态：`AGREED_PENDING_FORMALIZATION`。待写入的正式文件：本包 `core/HANDOFF-CONTRACT.md`
经维护者与用户批准后的下一版，或 `AUTHORITATIVE-SOURCES.yaml` 的 `handoff` 域。

---

## W2（2026-09-25T21:00）"先读包再实施"的顺序被用户明确要求倒过来

用户要求的顺序是：**先只读核查本机现实 → 再读包 → 再实施**。
这对 AI 是反直觉的：默认行为往往是"拿到包就照做"。
本轮据此实际发现了两处声明与现实的冲突（R1、R2），说明该顺序**有实际收益**，不是形式要求。

状态：`AGREED_PENDING_FORMALIZATION`（建议升为契约第 1 步的强制前置）。

---

## W3（2026-09-25T20:31）发现的冲突（非用户口头纠正，属证据性发现）

### R1 — Active Root 声明与实际不一致
- `~/.dsh/AGENTS.md` §三声明入口为 `C:\Users\29845\.codex\ai-kingdom\system-root.yaml` → **实测不存在**。
- 实际自声明的共享治理根为 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`（`BINDING-MANIFEST.yaml`）。
- 另有 `E:\deepseek-harness\empire\system-root.yaml`（DSH 执行活动根，非共享权威），
  它又把 `.codex\ai-kingdom` 描述为 `read_only: true` 的上游契约源。
- **三个来源指向三处，本节点不擅自选一个覆盖其余**（D-008 只作提议）。

### R2 — 声明 Skill 路径与实际不符
- 声明：`C:\Users\29845\.codex\skills\ai-kingdom\SKILL.md` → **不存在**。
- 实际存在：`C:\Users\29845\.agents\skills\ai-kingdom\SKILL.md`（3546 bytes，mtime 2026-09-13 10:00:51，
  同目录有 `SKILL.md.before-apply-20260913-113741.bak`）。
- 本节点**未读取**该 SKILL.md 正文（时间预算优先用于本任务；不作为本轮依据）。

### R3 — 只读条款与本轮写入指令冲突
- `~/.dsh/AGENTS.md` §三：「所有 AI Kingdom 文件只读」。
- 本轮用户指令要求「创建缺失的项目文件」。
- 本节点处置：按用户指令准备产物，但**实际写入被沙箱拒绝**，故不构成对既有文件的修改；
  授权问题上报 Q2 由用户裁决。

---

## W4（时点未测量；原稿误写占位符 "T20:4x"，已更正 → R3-10）本包与既有体系的权威关系（本节点提议）

- 包 `core/*` = CANDIDATE；不得成为第二套权威规则（包 README 明文）。
- 既有 `workflow/CONTINUITY-CONTRACT.md`（v1, CANDIDATE）与本包 `core/RUNTIME-RULES.md`（v0.1）
  在**同一问题上并存**，构成新的候选冲突（与既有 `U-HANDOFF-SCHEMA` 同类）。
- 本节点**不建议**本节点自行宣布哪一份胜出；建议由用户在两份候选间做一次裁决，
  或明确二者是"同一契约的两个抽象层级"。
- 状态：`PROPOSED`（**提议**，明确不使用 `AGREED_PENDING_FORMALIZATION`）。
  ← 原稿写作"`AGREED_PENDING_FORMALIZATION`（提议级）"，**一句话里并存两套状态词**，
  正是本项目 D3/D4 明令禁止的混用；已由第三轮审计发现并更正（R3-10）。**W4 是提议，不是共识。**

---

## W5（2026-09-25T20:58）能力边界自陈

- 本节点能：读任意可读路径、写工作区内路径、独立子会话（可用于独立读取回执测试）。
- 本节点**不能**：在无放宽权限时写 `C:\Users\29845\**`；不能触发平台级上下文压缩；
  不能代表其他节点提交回执；不能确认平台是否有压缩前钩子。
- 这些限制写入 `nodes/deepseek/ADAPTER.md`，供其他节点判断"能期待 DSH 做什么"。
