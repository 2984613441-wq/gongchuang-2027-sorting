# 项目入口：ai-kingdom-continuity

## 当前接入索引 v0.1 / Codex 增量（用户已确认项目根）

- 唯一项目根：`C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\projects\ai-kingdom-continuity`，来源为用户对 Q-C01 的批准与补充约束；下方候选根说明为历史。
- Codex 入口：`../../nodes/codex/START.md`；适配器：`../../nodes/codex/ADAPTER.md`。
- Codex 当前任务：`tasks/codex-access/REQUEST.md`；最新 Codex 交接：`handoffs/H-20260925-CODEX-001/REQUEST.md`。
- Codex 恢复必读版本集：`handoffs/H-20260925-CODEX-001/READSET.json`。按 START 的顺序实际读取，逐项比对 SHA256；不从旧摘要补值。
- `MANIFEST-SHA256.txt` 保留为 DSH 历史快照；本次修改后的文件使用上述带时间的 READSET，不把旧清单当当前版本。哈希不一致时停止受影响操作并重新核对，不静默刷新基线。
- 下方 `latest_handoff` 和节点自报均保留为 DSH 历史索引；不会自动成为 Codex 最新交接或验收结论。

- project_id: `ai-kingdom-continuity`
- authoritative_root: `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\projects\ai-kingdom-continuity`
  （✅ **用户已裁决**，2026-09-25「Q1按现有共享根对齐」；见 `DECISIONS.md` D-008）
- core_version: `continuity-v0.1`（候选契约，**非**共享权威源；`CONTRACT-v0.1/`）
- state_revision: **3**（统一口径：本项目所有文件、handoff、RECEIPT、哈希清单一致记 3）
- latest_handoff: `handoffs/H-20260925-DSH-001.md`
- latest_retest: `EVIDENCE-TEST-20260925-RETEST.md`（第二轮，从共享权威根）
- current_task: `ai-kingdom-continuity-access`（各节点接入 + 真实验收，截止 2026-09-25T22:00+08:00）
- deadline: 2026-09-25T22:00:00+08:00

> **⚠ 时间戳口径（R12 / E17）**：本文件正文中的时间戳**多为估计值，未经测量**。
> 本节点全程只在 `20:30:12`、`20:58:26`、`21:15:36`(+08:00) 三次真正执行过 `Get-Date`。
> **权威时间一律以文件系统 mtime 为准**，正文时间戳仅表示先后顺序。

## 启动阅读顺序（每个节点每次启动/恢复都执行）

1. `INDEX.md`（本文件）
2. `SHARED-UNDERSTANDING.md` ← **共同理解优先，必须先读**
3. `STATE.md`
4. `DECISIONS.md`
5. `WORKING-NOTES.md`
6. `PARAMETERS.yaml`
7. `EVIDENCE.md`
8. 最新 `handoffs/<id>.md` 及其 `must_read`
9. `nodes/<本节点>/ADAPTER.md` 与 `nodes/<本节点>/START.md`

读完必须提交回执（`handoffs/RECEIPT-*.md` 同构），写明实际读取的路径+版本/哈希+时间+缺失项。

## must_read（附版本/哈希）

**本项目文件的权威哈希清单：`MANIFEST-SHA256.txt`（项目根，rev 2 起有效）。**
下表的"版本"栏仅为可读标签；**核验一律以 `MANIFEST-SHA256.txt` 中的 SHA256 为准**。

| # | 路径 | 版本/哈希 | 状态 |
| --- | --- | --- | --- |
| 1 | `SHARED-UNDERSTANDING.md` | rev 1（哈希见 `MANIFEST-SHA256.txt`） | 本项目权威 |
| 2 | `STATE.md` | **rev 3** | 本项目权威 |
| 3 | `DECISIONS.md` | rev 1 | 本项目权威 |
| 4 | `WORKING-NOTES.md` | rev 1 ← **原稿遗漏，已补** | 本项目权威 |
| 5 | `PARAMETERS.yaml` | rev 1 | 本项目权威 |
| 6 | `EVIDENCE.md` | rev 1 | 本项目权威 |
| 7 | `EVIDENCE-TEST-20260925.md` | rev 1 | 测试证据（第一轮·镜像） |
| 8 | `EVIDENCE-TEST-20260925-RETEST.md` | rev 1 ← **原稿遗漏，已补（第三轮审计 U12）** | 测试证据（第二轮·共享根） |
| 9 | `EVIDENCE-TEST-20260925-AUDIT3.md` | rev 1 | **第三轮独立审计（判定 + 未承认缺陷）** |
| 10 | `handoffs/H-20260925-DSH-001.md` | rev 2 | 交接快照 |
| 11 | `handoffs/RECEIPT-20260925-DSH-001.md` | rev 1 | 恢复回执 |
| 12 | `nodes/deepseek/START.md` | 0.1.0 ← **原稿遗漏，已补；START 才是启动第一入口** | 本节点入口 |
| 13 | `MANIFEST-SHA256.txt` | rev 3 | **哈希权威** |

## 编号命名空间登记（消除 ID 冲突 · 第三轮审计 R3-9/U9）

本节点在 3 轮中产生过**互相冲突的同号 ID**（`N3` 在同一句里两次不同义；`N4`/`N5` 跨文件不同义），
这与本项目明令禁止的 D3/D4 混用属同一类错误。**现登记如下唯一口径：**

| 前缀 | 含义 | 权威定义处 |
| --- | --- | --- |
| `D-0xx` | 决定账本条目 | **`DECISIONS.md`（唯一权威）** |
| `P1–P4` | 待固化共识 | `SHARED-UNDERSTANDING.md` §五 |
| `Q1–Q9` | 未决问题 | `SHARED-UNDERSTANDING.md` §六 + handoff A5 |
| `R1–R12` | 缺陷/冲突（第一、二轮） | `WORKING-NOTES.md` W3（R1–R3）、`EVIDENCE-TEST-20260925.md` §3（R4–R11）、`EVIDENCE.md` E17（R12） |
| **`R2-1–R2-9`** | **第二轮阅读者发现的缺陷（原 `N1–N9`，已重编）** | `EVIDENCE-TEST-20260925-RETEST.md` §4 |
| **`R3-1–R3-14`** | **第三轮审计的判定与未承认缺陷（原审计书的 `N*`/`U*`，已重编）** | `EVIDENCE-TEST-20260925-AUDIT3.md` |
| `N1–N5`（**仅限 `STATE.md`**） | 本节点"已实施未验证"清单 | `STATE.md` |

> **禁止**再使用裸 `N<数字>` 跨文件引用。引用须带来源文件或使用上表的 `R2-*` / `R3-*`。

## 既有共享权威源（**只读引用，本包不替代**）

| 域 | 路径 | 版本 | 权威类型 |
| --- | --- | --- | --- |
| 共享治理根 | `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\BINDING-MANIFEST.yaml` | v1.1 | `SHARED_AUTHORITATIVE` |
| 权威索引 | `...\governance\AUTHORITATIVE-SOURCES.yaml` | v1 (phase 0.5) | `SHARED_AUTHORITATIVE` |
| 连续性 I/O | `...\workflow\CONTINUITY-CONTRACT.md` | v1 | `CANDIDATE` |
| 执行门 | `...\workflow\EXECUTION-GATE-CONTRACT.md` | **v0.4**（文件自身头部）——**索引记载 v0.2 为滞后，见 R11/Q9** | `SHARED_AUTHORITATIVE (v0.2 索引记载 / ACTIVE)` |
| 19 条国本全文 | `C:\Users\29845\.claude\constitution.md` | v0.6 | `SHARED_AUTHORITATIVE` |
| DSH 节点入口 | `C:\Users\29845\.dsh\AGENTS.md` | constitution 1.2.1-limited-trial | `NODE_AUTHORITATIVE` |

## 为什么本包不是第二套权威规则

`00-SEND-TO-ALL-AI.md` 与包内 `core/*` 是**候选契约**（`authority_type: CANDIDATE`）。
`AUTHORITATIVE-SOURCES.yaml` 目前将 `handoff`、`workflow` 两个域标为 `UNRESOLVED`。
本包**不自行宣布胜出**：它只作为被引用的候选，写入 `CONTRACT-v0.1/AUTHORITY-STATUS.md` 并保留哈希。
任何跨节点采纳、合并或重大规则变化**必须经用户裁决**。

## 所有权

| 路径 | 写入者 |
| --- | --- |
| `SHARED-UNDERSTANDING.md` / `STATE.md` / `DECISIONS.md` / `PARAMETERS.yaml` / `EVIDENCE.md` | 当前记录员提交提议，**重要裁决由用户确认** |
| `nodes/<node>/**` | 仅对应节点 |
| `events.jsonl` | 所有节点可**追加**，不得改写历史 |
