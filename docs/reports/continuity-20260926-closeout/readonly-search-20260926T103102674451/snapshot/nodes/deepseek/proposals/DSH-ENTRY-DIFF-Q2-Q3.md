# 提案：`~/.dsh/AGENTS.md` 入口与只读条款的差异与影响（Q2 / Q3）

- proposal_id: `DSH-ENTRY-DIFF-Q2-Q3`
- author: `deepseek_harness`
- created_at: `2026-09-25T22:05:00+08:00`
- status: **`PROPOSED` —— 未应用。本文件不构成对 `~/.dsh/AGENTS.md` 的任何修改。**
- target_file: `C:\Users\29845\.dsh\AGENTS.md`
- target_sha256: `C78D21A6FF8778A79E503691D980BAACFF2CB7DFE67CE35622640D8F3D2950E3`
- target_bytes: `11942`（135 行，mtime 2026-09-13 13:52:26）
- 依据: 用户 2026-09-25 指令「Q2、Q3 涉及你本节点规则和入口修改，先给出具体差异及影响」
- 授权状态: **需用户对该具体动作逐项确认后方可执行；本节点未做任何改动**

---

## 0. 先说结论

- **Q3（入口路径）**：不是"改个路径"那么简单。§三 声明的**两个路径都不存在**，
  而且 §三 整节描述的**目录树在本机也不存在**。事实性修正风险低、价值高，建议做；
  但其中的"活动发现区/历史区"**不能由本节点擅自选一个替代根**——按
  `CONTINUITY-CONTRACT.md` §1「若权威索引说 UNRESOLVED，停止猜测，记录 UNRESOLVED 并问用户」。
- **Q2（只读→可写例外）**：这是一条**常设规则变更**，不是事实修正。
  它会削弱核心纪律 #3「任何外部写入必须先取得用户对该具体动作的确认」。
  本节点**不建议**现在做常设例外，给出三个选项供裁决（§3）。

---

## 1. 已实测的事实基础

| 声明项（§三 行号） | 声明值 | 实测 |
| --- | --- | --- |
| 入口文件（L62） | `C:\Users\29845\.codex\ai-kingdom\system-root.yaml` | **不存在**（`Test-Path` = False） |
| 治理 Skill（L63） | `C:\Users\29845\.codex\skills\ai-kingdom\SKILL.md` | **不存在**；实际存在于 `C:\Users\29845\.agents\skills\ai-kingdom\SKILL.md`（3546 bytes，`references/` 并存） |
| 其父目录 | `C:\Users\29845\.codex\ai-kingdom` | **整个目录不存在** |
| 活动发现区（L60） | `registry/`、`experience/`、`records/`、`task-orchestrator/`、`scripts/` | 在 `.codex` 下无根可挂（父目录不存在）。在 `E:\deepseek-harness\empire\` 下存在 `registry`、`experience`、`records`、`scripts`（**无** `task-orchestrator`）；在 `C:\Users\29845\Desktop\ai-kingdom\ai-kingdom\` 下存在 `experience`、`records`、`registry`、`scripts`、`snapshots`（**无** `task-orchestrator`、**无** `sediment`） |
| 历史区（L61） | `sediment/`、`snapshots/` | 上述两个候选根中**均未找到 `sediment`**；`snapshots` 仅在 Desktop 树存在 |
| 共享治理根（§三未提，实际存在） | — | `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`（`BINDING-MANIFEST.yaml` v1.1 自声明 `shared_governance_root`，SHA256 `FE5E2AD4…C0A5`） |

**结论**：§三 的**入口与 Skill 两句是错的**（指向不存在的路径）；
其**目录树描述无法在本机唯一确认**，且与两个候选根都不完全吻合。

---

## 2. Q3：入口路径修正（具体差异）

### 差异 1 — L62 入口文件

```diff
- - **入口文件**：`C:\Users\29845\.codex\ai-kingdom\system-root.yaml`
+ - **共享治理根**：`C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`（`BINDING-MANIFEST.yaml` v1.1，
+   SHA256 `FE5E2AD42F291146C07BCCF7506AEEA9D41182362DFE14AFAF1A9E41D90DC0A5`）
+ - **入口文件**：`C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\00-ENTRY\README.md`
```

**影响**：
- 正向：下次启动不再尝试打开一个不存在的文件而静默按记忆行事（这正是本轮 R1 的成因）。
- 风险：**低**。纯事实修正，不改变任何权限、不新增权限。
- 副作用：把"入口"从 `.codex` 域挪到 `AI-KINGDOM-PORTABLE-CORE` 域，等于**本节点单方面**把
  共享治理根认作入口。若其他节点/用户认为应以别的根为准，会造成不一致 →
  故此项建议**与 Q1 的裁决一起生效**（Q1 已由用户按现有共享根对齐，故本项与之一致）。

### 差异 2 — L63 治理 Skill

```diff
- - **治理 Skill**：`C:\Users\29845\.codex\skills\ai-kingdom\SKILL.md`（及 references/）
+ - **治理 Skill**：`C:\Users\29845\.agents\skills\ai-kingdom\SKILL.md`（及 references/）
```

**影响**：
- 正向：指向真实文件。该 SKILL.md 实际存在，正文自述为 **AI Kingdom v1.1 limited-trial**、
  `constitution_version: 1.2.1-limited-trial`，与本节点 `constitution_version` 一致。
- 风险：**低**。
- **注意**：本节点**尚未加载该 Skill 正文**（本轮只读了前 25 行用于核对事实）。
  修正路径**不等于**该 Skill 已被调用或生效；不得据此宣称 Skill 接线完成。

### 差异 3 — L60/L61 活动发现区 / 历史区

**建议写法（不猜、标 UNRESOLVED）**：

```diff
- - **活动发现区**（可作依据）：`registry/`、`experience/`、`records/`、`task-orchestrator/`、`scripts/`
- - **历史区**（只作参考，不作为现行政策）：`sediment/`、`snapshots/`
+ - **活动发现区 / 历史区**：`UNRESOLVED` —— 原声明树（`C:\Users\29845\.codex\ai-kingdom\`）在本机**不存在**；
+   候选根（`E:\deepseek-harness\empire\`、`C:\Users\29845\Desktop\ai-kingdom\ai-kingdom\`）与本声明**均不完全吻合**
+   （两者都缺 `task-orchestrator`，均无 `sediment`）。
+   `AUTHORITATIVE-SOURCES.yaml` 的 `empire` 域已记为 `UNRESOLVED`。
+   **按 `CONTINUITY-CONTRACT.md` §1：记录 UNRESOLVED 并问用户，不由本节点选一个替代根。**
+   → 待用户裁决前，本节点不把任一候选根当作"活动发现区"依据。
```

**影响**：
- 正向：消除"自以为有依据、其实依据不存在"的隐患。
- 风险：**低**（只是把错误声明降级为显式未知，不删信息、不新增权限）。
- 代价：在用户裁决前，本节点**失去**"活动发现区"这一依据来源。这是**诚实换取的代价**，可接受。

---

## 3. Q2：只读条款 → 可写例外（三个选项，附影响）

### 现状（L64）

```
- 所有 AI Kingdom 文件**只读**；DSH 的产出想沉淀进经验，写入候选区，不直接晋升。
```
另 L76：`❌ 不修改任何源体系文件（.codex、.claude 下的治理文件一律只读）`

### 冲突事实

本轮用户指令要求"创建缺失的项目文件"，而 L64 要求"所有 AI Kingdom 文件只读"。
本轮实际执行方式：写入被沙箱拒绝 → 经**用户批准的放宽权限**完成 →
只**新增**文件、**既有权威文件 mtime 全部未变**（证据 E9/E14）。

即：**本轮写入是靠"逐次用户批准"完成的，不是靠 L64 的措辞授权。**

### 选项 A — 加"窄范围常设例外"

```diff
- - 所有 AI Kingdom 文件**只读**；DSH 的产出想沉淀进经验，写入候选区，不直接晋升。
+ - 所有 AI Kingdom **既有**文件**只读**；DSH 的产出想沉淀进经验，写入候选区，不直接晋升。
+ - **窄范围例外（常设）**：在共享治理根 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE` 下，
+   本节点可**新增**（不覆盖）`nodes/deepseek/**` 与 `projects/<project-id>/**` 下的文件；
+   **禁止**修改/覆盖任何既有文件；每次写入须复核"既有文件 mtime 未变"并登记新增清单与哈希。
+   **例外不含**：`.codex`/`.claude` 治理文件、`core/*` 契约、`governance/*`、任何既有权威源。
```

| | 影响 |
| --- | --- |
| 正向 | 本节点落盘不再逐次请示；交接产物能及时固化（本轮若无常设例外，需每次批准） |
| 风险 | **削弱核心纪律 #3**「任何外部写入必须先取得用户对**该具体动作**的确认」——例外正是把"具体动作"泛化为"一类动作" |
| 风险 | 措辞一旦被泛化解读（"AI Kingdom 文件可写"），可能被下一轮误用为可改既有权威源 |
| 可缓解 | 若采纳，必须同时加：范围白名单 + "只新增" + mtime 未变复核 + 每次登记哈希 + 显式排除清单 |
| 本节点建议 | **暂不采纳**（见选项 C） |

### 选项 B — 不改规则，维持逐次确认

```diff
  （L64 保持原文不变）
+ （在项目 `DECISIONS.md` 中记录：本节点每次写入共享根，均需用户对该具体动作批准；
+   批准与执行结果登记于 `events.jsonl`）
```

| | 影响 |
| --- | --- |
| 正向 | **零规则风险**；核心纪律 #3 完整保留；与 `EXECUTION-GATE-CONTRACT` §4 一致（状态变更操作按级需 `READY_FOR_EXECUTION`） |
| 代价 | 每次落盘需一次用户批准（本轮实测为 2 次批准即完成全部落盘，成本可接受） |
| 本节点建议 | **可采纳**；若用户嫌繁琐，建议先观察 2–3 个任务的批准频次再决定是否升级为选项 A |

### 选项 C — 只修事实、不动权限（本节点推荐）

```diff
  （L64 原文不动 —— 只读条款保留）
  （§三 的 L62/L63 按 §2 差异 1/2 修正；L60/L61 按差异 3 标 UNRESOLVED）
```

| | 影响 |
| --- | --- |
| 正向 | 修正**事实错误**（低风险高价值）＋ **不触碰权限**（零规则风险）；把 Q2 留给后续按需裁决 |
| 代价 | 落盘仍需逐次批准（等同选项 B 的成本） |
| 理由 | 事实错误会**持续**误导每次启动；而写入权限是**偶发**需求，逐次确认成本低。**先修会一直咬人的，后议偶尔疼的。** |

---

## 4. 需要用户裁决的事项（本节点不代决）

| 项 | 请裁决 | 本节点建议 |
| --- | --- | --- |
| Q3-a | 是否按差异 1 修正 L62 入口路径 | 建议修正 |
| Q3-b | 是否按差异 2 修正 L63 治理 Skill 路径 | 建议修正 |
| Q3-c | 是否按差异 3 把 L60/L61 标为 `UNRESOLVED`（而非选一个替代根） | 建议标 UNRESOLVED |
| Q2 | 选 A（常设窄例外）／B（不改，逐次确认）／C（只修事实、不动权限） | 建议 **C** |

**执行前置**：以上任一项若获批准，本节点将**先备份** `~/.dsh/AGENTS.md`（含 SHA256），
应用**逐条**最小差异，并输出变更前后哈希与逐行 diff 供核对。
**本节点不会一次改多项、也不会顺手改其他章节。**

---

## 5. 本提案的边界声明

- 本文件是**提议**，`PROPOSED`，**不是决定**，未对任何文件生效。
- 本节点**未修改** `C:\Users\29845\.dsh\AGENTS.md`（其 mtime 仍为 2026-09-13 13:52:26，
  哈希仍为 `C78D21A6…50E3`）。
- 差异 1 中"以 `AI-KINGDOM-PORTABLE-CORE` 为入口"与本轮 Q1 裁决一致，但仍**需 Q3-a 单独批准**方可写入。
- 本节点未读取 `C:\Users\29845\.agents\skills\ai-kingdom\SKILL.md` 的 `references/`，
  故不对该 Skill 的实际能力作任何断言。
