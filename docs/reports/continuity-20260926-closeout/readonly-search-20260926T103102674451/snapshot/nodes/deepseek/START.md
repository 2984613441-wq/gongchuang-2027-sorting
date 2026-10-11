# 节点入口：deepseek_harness（DSH）

- node: `deepseek_harness`
- display_name: DeepSeek Harness
- project_id: `ai-kingdom-continuity`
- project_root: `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\projects\ai-kingdom-continuity`
  （✅ **用户已裁决** 2026-09-25「Q1按现有共享根对齐」；见 `DECISIONS.md` D-008）
- local_mirror: `E:\deepseek-harness\_staging\deploy\projects\ai-kingdom-continuity`
- adapter_status: `IMPLEMENTED_UNVERIFIED`
- adapter_version: `0.1.0`

## 每次启动或恢复，按此顺序读取

1. `projects/ai-kingdom-continuity/INDEX.md`
2. `projects/ai-kingdom-continuity/SHARED-UNDERSTANDING.md` ← **必须最先读的共同理解**
3. `projects/ai-kingdom-continuity/STATE.md`
4. `projects/ai-kingdom-continuity/DECISIONS.md`
5. `projects/ai-kingdom-continuity/WORKING-NOTES.md` ← **原稿遗漏，已补（R8 残留修复）**
6. `projects/ai-kingdom-continuity/PARAMETERS.yaml`
7. `projects/ai-kingdom-continuity/EVIDENCE.md`
8. `projects/ai-kingdom-continuity/MANIFEST-SHA256.txt` ← 核验版本的**哈希权威**
9. 最新 `handoffs/<id>.md` 及其 `must_read`（逐项核对版本/哈希）
10. `projects/ai-kingdom-continuity/EVIDENCE-TEST-20260925-RETEST.md`（最新独立复测结果）
11. `projects/ai-kingdom-continuity/handoffs/RECEIPT-20260925-DSH-001.md`
12. 本节点 `ADAPTER.md`

**⚠ 时间戳口径（R12/E17）**：项目文件正文时间戳多为**估计值**，权威时间以文件系统 **mtime** 为准。

读完**必须**在 `nodes/deepseek/receipts/` 写回执，包含：
`project_id`、`handoff_id`、实际读取的文件路径+版本/哈希、读取时间、缺失项、
以及对"共同理解 / 用户纠正 / 未定 / 已定 / 精确参数 / 下一步"的短复述。

**缺失项要列出；不以旧聊天摘要替代实际读取。**

## 硬性边界

- 只声明本节点**实际执行**的工作；其他节点一律 `NOT_CALLED`。
- 不把提议写成决定；未写入规范的共识写 `AGREED_PENDING_FORMALIZATION`。
- 压缩前交接：DSH **无已证实自动钩子** → 标 `MANUAL_REQUIRED`，由用户主动触发，不得报自动化。
- 不修改既有权威源文件；不复制凭据。

## 权威层级（本节点遵守）

```
用户明确指令 > 安全/权限/现实边界 > 防昏君追问 > 19条国本(C:\Users\29845\.claude\constitution.md v0.6)
> 当前任务规则 > 共享治理契约(EXECUTION-GATE-CONTRACT **v0.4**，文件自身版本；索引记 v0.2 属滞后 → R11/Q9)
> 本连续性候选契约(continuity-v0.1, CANDIDATE) > 节点 Adapter > 历史经验
```
