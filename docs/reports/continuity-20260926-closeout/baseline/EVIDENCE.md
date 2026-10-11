# 证据：ai-kingdom-continuity

## Codex 证据入口 v0.1

- 本节点证据：`../../nodes/codex/responses/ACCEPTANCE-v0.1.md`，读取回执：`../../nodes/codex/receipts/RECEIPT-CODEX-001.md`。文件尚不可访问时为缺件，不能据此宣称通过。
- 基线及版本冲突：`../../nodes/codex/responses/BASELINE-AND-CONFLICTS-v0.1.md`。
- 本次受控测试包含完整输入、缺失必读文件、内容哈希漂移和合成保真样本；这些只验证读取机制，不能升级为真实新对话或压缩验收。
- 下方全部为原作者记录，Codex 未复现其运行过程；未来于实际读取时间的来源时间戳不作为本节点执行证据。

类型取值：`用户报告` / `节点观察` / `脚本实测` / `推断`。
**只有本节点实际执行的才算本节点实测**；其他节点未参与写 `NOT_CALLED`。

| ID | 结论 | 证据路径或出处 | 类型 | 执行节点与时间 | 尚未验证部分 |
| --- | --- | --- | --- | --- | --- |
| E1 | 本机时间为 2026-09-25 20:30:12 +08:00，距截止 22:00 约 90 分钟 | `Get-Date` 输出 | 脚本实测 | deepseek_harness, 2026-09-25T20:30 | 无 |
| E2 | 入口 `C:\Users\29845\.codex\ai-kingdom\system-root.yaml` **不存在** | `Test-Path` → `False` | 脚本实测 | deepseek_harness, 2026-09-25T20:31 | 该目录是否曾存在、是否被移动/删除 |
| E3 | 治理 Skill `C:\Users\29845\.codex\skills\ai-kingdom\SKILL.md` **不存在**；`C:\Users\29845\.codex\ai-kingdom` 目录 **不存在** | `Test-Path` → `False`（两项） | 脚本实测 | deepseek_harness, 2026-09-25T20:31 | 同上 |
| E4 | 实际共享治理根为 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`，自声明 `shared_governance_root`，portable_core_version v1.1 | `BINDING-MANIFEST.yaml`，SHA256=`FE5E2AD42F291146C07BCCF7506AEEA9D41182362DFE14AFAF1A9E41D90DC0A5`，3271 bytes | 脚本实测（哈希）+ 节点观察（内容） | deepseek_harness, 2026-09-25T20:52 | 该自声明是否获用户确认（`AUTHORITATIVE-SOURCES.yaml` 未列此域为已确认） |
| E5 | 既有权威索引把 `handoff`、`workflow`、`capability`、`empire`、`evidence`、`experience` 标为 `UNRESOLVED`；`execution_gate` 为 `SHARED_AUTHORITATIVE v0.2 ACTIVE`（**仅为索引记载值；文件自身实为 v0.4，索引滞后 → 见 E16 / R11 / Q9**） | `governance\AUTHORITATIVE-SOURCES.yaml` SHA256=`EAC3614C80A842A5F44BD18D82B5EC1668DF53A0A0E228867152B91B2D0131DB`，16221 bytes | 节点观察（实际读取全文 409 行） | deepseek_harness, 2026-09-25T20:52 | 该索引自 2026-09-12 后是否仍最新 |
| E6 | 本会话对 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\projects` 的写入**被拒绝** | 命令输出 `Access to the path 'projects' is denied.`；一次带 `danger-full-access` 的重试**被中断、结果未知**；随后只读核查确认 `projects` 不存在、无 `_writetest` 残留，现有顶层条目与 2026-09-12 时间戳一致 | 脚本实测 | deepseek_harness, 2026-09-25T20:52–20:58 | 更宽权限下能否成功；**本节点就此止步，未反复尝试** |
| E7 | DSH 节点既有 Adapter 声明 `adapter_status: ACTIVE` / `runtime.status: INSTALLED_RUNTIME_UNVERIFIED`，绑定 `EXECUTION-GATE-CONTRACT.md` 与 `TASK-LIFECYCLE-SCHEMA.yaml` | `adapters\deepseek\adapter.yaml` SHA256=`9C0A8C1980CED5FB5FCD6CD8B1E457BB6A8B32377E0764D79EA3FE446D861886`，429 bytes | 节点观察（实际读取） | deepseek_harness, 2026-09-25T20:52 | `INSTALLED_RUNTIME_UNVERIFIED` 是否有真实运行时演练证据 |
| E8 | DSH 节点执行活动根为 `E:\deepseek-harness\empire`，其 `system-root.yaml` 明写「no_consumer…禁止据此做路由/发现决策」，且声明 AI Kingdom 治理层 `C:\Users\29845\.codex\ai-kingdom` 为 `read_only: true` 的上游契约源 | `E:\deepseek-harness\empire\system-root.yaml` SHA256=`6C5FEC976FF9022169ADFFDF71C25611AD32DEA1170333E7E7FA433B9A80644F`，5945 bytes，mtime 2026-08-29 | 节点观察（实际读取全文） | deepseek_harness, 2026-09-25T20:58 | 该 system-root 与 PORTABLE-CORE 的权威关系未裁决 |
| E9 | 本节点本轮**未修改**任何既有文件；`AI-KINGDOM-PORTABLE-CORE` 顶层条目与修改时间与核查前一致 | 核查前后目录列表对比 | 脚本实测 | deepseek_harness, 2026-09-25T20:58 | 无（本次范围内已核） |
| E10 | **独立新上下文读取回执测试**（代理「新对话」演练）：由**无本会话上下文**的独立阅读者仅凭文件复述共同理解、用户纠正与带单位参数，并识别故意缺失的必读文件 | 见 `handoffs/RECEIPT-20260925-DSH-001.md` 与 `EVIDENCE-TEST-20260925.md` | 脚本实测（独立子会话） | deepseek_harness（阅读者为独立上下文子会话；**时点未测量**，原写占位符 "T21:1x" 已更正 → R3-10） | 真实**压缩恢复**未演练（无法触发）→ 只能判 `PARTIAL` |
| E11 | v0.1 **原始 zip** 共 16 个文件，全部哈希已留档，可复算 | `CONTRACT-v0.1/MANIFEST-SHA256.txt` | 脚本实测 | deepseek_harness | 与用户原始 zip 的一致性（已由解包工具保证，未逐字节比对 zip CRC）。**⚠ 更正**：`CONTRACT-v0.1/` **目录现状为 18 个文件**，因本节点另建 `AUTHORITY-STATUS.md` 并生成了子清单自身；原文"共 16 个文件"仅对原始 zip 成立，**对目录现状不成立**（独立阅读者 2026-09-25 复测发现） |
| E12 | Claude 的 `~/.claude/state/handoff.md` 被既有权威索引记为 STALE（2026-09-06，objective/next_action 为空） | `AUTHORITATIVE-SOURCES.yaml` → `domains.handoff.freshness_observations` | 引用既有记录（**非**本节点实测） | deepseek_harness 仅转录；原作者 grok/claude 阶段 0.5 | 该文件当前是否仍 STALE；**本节点未读取该文件** |
| E13 | Grok 的 `kingdom_handoff: MISSING`，连续性判 `FAIL` | 同上 | 引用既有记录（**非**本节点实测） | 同上 | 当前状态；**本节点未核查** |
| E14 | **共享根落盘成功**：`projects/ai-kingdom-continuity/**` 与 `nodes/deepseek/**`（4 文件）已写入 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`；**既有权威文件 mtime 未变**（`BINDING-MANIFEST.yaml` 2026-09-12 23:53:28、`AUTHORITATIVE-SOURCES.yaml` 2026-09-12 23:54:18、`adapters/deepseek/adapter.yaml` 2026-09-12 23:53:28、`EXECUTION-GATE-CONTRACT.md` 2026-09-13 00:25:15） | 部署命令输出 `DEPLOY_OK`；部署后目录列举与抽查哈希；原顶层 12 项全部保留 | 脚本实测 | deepseek_harness | 长期写权限未获用户裁决（B2）。**⚠ 计数声明已废止（R3-6 · 结构性修正）**：本文件**不再在正文中断言任何文件数量**。
理由（实测）：本轮该数字已漂移四次（27 → 30 → 31 → 32），每次落盘后立即过期——
**写死的计数必然过期，这本身就是缺陷**。**唯一权威是 `MANIFEST-SHA256.txt`**
（每次落盘后从共享根自洽重生成）；需要计数时从清单行数推导，**不要引用本文件正文**。 |
| E15 | 独立阅读者发现受测产物 **6 条缺陷**（R4 Q7 同号不同义／R5 适配器版本混用／R8 must_read 漏列 WORKING-NOTES／R9 证据文件悬空／R10 哈希清单不覆盖项目文件／R6 执行门版本未核），作者已逐条确认并修复或关闭 | `EVIDENCE-TEST-20260925.md` §3；`nodes/deepseek/receipts/RECEIPT-H-20260925-DSH-001.md` §6 | 脚本实测（独立子会话）+ 作者确认 | deepseek_harness, 2026-09-25T21:00–21:35 | **修复后未再由独立阅读者复测**（N5） |
| E16 | `EXECUTION-GATE-CONTRACT.md` 文件自身为 **v0.4 / ACTIVE / SHARED_GOVERNANCE_ASSET**（7930 bytes，SHA256 `15EF8AB6287D15928C6C84E69438FD5CE5F9AC252BFAAE80E590EC07FE3A0D44`），而 `AUTHORITATIVE-SOURCES.yaml` 记该域为 **v0.2** → **索引滞后于文件（R11/Q9）**；同时确认 `~/.dsh/AGENTS.md` 内嵌 v0.4 摘要与正文**同版**（R6 关闭） | 本节点 `read` 该文件全文（100 行）；哈希复算 | 节点观察（全文实际读取）+ 脚本实测 | deepseek_harness | 索引是否应更新、由谁更新：**待用户/索引维护者裁决** |
| **E17** | **🔴 本节点自身缺陷（R12）：本文件与其他产物正文中的时间戳，多为"估计值"而非"实测值"。** 本节点全程只在 3 个时点真正执行过 `Get-Date`：`20:30:12`、`20:58:26`、`21:15:36`（+08:00）。此后写入的 `21:03 / 21:05 / 21:07 / 21:08 / 21:15 / 21:22 / 21:25 / 21:30 / 21:33 / 21:35 / 21:37 / 21:40 / 21:42 / 21:46 / 22:00 / 22:05 / 22:07 / 22:12` 等**均为推断估计，未经测量**。结果：正文声明时间（如 `STATE.md` 原写 `21:37`）**晚于**文件系统 mtime（`21:02:43`）与真实时钟（`21:15:36`） | 独立阅读者 2026-09-25T21:13:59 复测报告「本轮新发现」第 3 条；本节点随后实测 `Get-Date` = `2026-09-25T21:15:36.581+08:00` 确认 | 脚本实测（独立阅读者）+ 本节点实测确认 | 独立阅读者（发现）+ deepseek_harness（确认并登记） | **权威时间一律以文件系统 mtime 为准**；正文时间戳仅作先后顺序参考。已在本项目各文件顶部加入「时间戳口径」声明。**此缺陷说明：作者自报的时间与状态不经独立核对不可信** |
| **E18** | **共享根复测（第二轮）结果**：独立无上下文阅读者**仅从共享权威根** `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE` 读取 13 个指定文件 + 2 个补充文件，**无一缺失**；`must_read` 两份清单 17 个唯一路径 **全部 EXISTS（0 MISSING）**；`MANIFEST-SHA256.txt` A+B 节 **15/15 MATCH**（**当时口径**：清单为 A=11/B=4；现清单已重生成且条目更多，第三轮审计据现清单复算为 **27/27 MATCH**，见 R3-6）、C 节 8/8 **MATCH**、字节数 **23/23**（**当时口径**）；用户纠正 **恰好 5 条 C1–C5** 且两文件一致；`Q1–Q9` 编号**跨文件一致**（R4 已消除） | 阅读者回执（子会话 `afffaea2-adfa-4f53-966e-e6199791c7f8`），`read_at` = `2026-09-25T21:13:59+08:00`；归档见 `EVIDENCE-TEST-20260925-RETEST.md` | 脚本实测（独立子会话） | 独立阅读者 | 阅读者同时报告 **9 项文件中未登记的新不一致**（state_revision 冲突、handoff 内容滞后、时间戳错位、P3/D-010 双状态、R8 残留在 START.md、AUTHORITY-STATUS.md 无哈希覆盖等）→ 见 `EVIDENCE-TEST-20260925-RETEST.md` §4 |

## 其他节点参与情况

| 节点 | 本节点是否调用 | 说明 |
| --- | --- | --- |
| Claude Code | `NOT_CALLED` | 本节点未调用、未读取其运行状态 |
| Codex CLI/Desktop | `NOT_CALLED` | 同上 |
| Zcode | `NOT_CALLED` | 同上 |
| Grok | `NOT_CALLED` | 同上 |
| DeepSeek Harness 内部独立子会话（阅读者） | `ACTUALLY_CALLED` | 仅用于 E10 的独立读取回执测试；**不是**另一个 AI 节点，不得计入五节点 |

## 未验证/未知清单

- U-A：项目根最终位置（Q1）
- U-B：DSH 写共享根的授权（Q2）
- U-C：压缩前自动写盘钩子是否存在（Q4）
- U-D：真实压缩恢复能否通过（Q5）
- U-E：其余四节点实际接入状态（Q6，`NOT_CALLED`）
- U-F：既有 `handoff`/`workflow` 域的 `UNRESOLVED` 状态是否已被用户裁决更新
