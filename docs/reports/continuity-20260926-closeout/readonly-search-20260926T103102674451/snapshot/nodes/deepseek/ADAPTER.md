# Provider Adapter：deepseek_harness

- node: `deepseek_harness`
- adapter_version: `0.1.0`
- adapter_status: `IMPLEMENTED_UNVERIFIED`
- contract: `core/HANDOFF-CONTRACT.md` + `core/RUNTIME-RULES.md`（候选契约 continuity-v0.1）
- updated_at: `2026-09-25T21:08:00+08:00`
- 既有注册位: `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\adapters\deepseek\adapter.yaml`（v0.2.0，status `ACTIVE`，
  `runtime.status: INSTALLED_RUNTIME_UNVERIFIED`）——**本文件不覆盖它**，只补充连续性交接适配。

> **两个版本号不得混用（R5）**：
> - `adapter_version 0.1.0` = **本文件**（连续性交接适配器，`nodes/deepseek/ADAPTER.md`），状态 `IMPLEMENTED_UNVERIFIED`。
> - `adapter.yaml v0.2.0` = **既有注册位**（Portable Core `adapters/deepseek/adapter.yaml`），状态 `ACTIVE`。
> 二者作用域不同；`PARAMETERS.yaml` 的 `dsh_adapter_version = 0.2.0` 指后者。
> 本节点**未**修改既有注册位文件（其 mtime 仍为 2026-09-12 23:53:28）。

## 1. 入口识别

| 项 | 值 |
| --- | --- |
| runtime_root | `E:\deepseek-harness` |
| entry_file | `C:\Users\29845\.dsh\AGENTS.md`（PROMPT_ENFORCED，11942 bytes） |
| execution_active_root | `E:\deepseek-harness\empire`（**非**共享治理权威） |
| project_id | `ai-kingdom-continuity` |
| project_root（候选） | `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\projects\ai-kingdom-continuity` |
| 若项目根缺失 | 标 `BLOCKED_MISSING_INPUT`，**不编造上下文** |

## 2. 恢复流程

先读共同理解与纠正记录 → 再读决定/开放项/参数/证据/最新交接 → 逐项报告路径、版本/哈希、时间。
**压缩后的恢复走同一流程，不依赖模型对话摘要。**

## 3. 执行纪律

事实 / 推断 / 提议 / 已确认决定 四类**分开**；参数保留原文单位、值、范围、来源、生效版本。

## 4. 写出与压缩前交接

- 增量写入：关键变化即时写 `STATE.md` / `events.jsonl` / `WORKING-NOTES.md`，不等会话结束。
- **压缩前交接：`MANUAL_REQUIRED`**。本节点**未证实**平台存在压缩前可触发钩子（Q4 未验证），
  因此**不得**报告"压缩前自动写盘成功"。由用户主动触发。

## 5. 本节点真实能力与限制（自陈，供他节点判断）

**能做**
- 读取任意操作系统可读路径（`read`/`glob`/`grep` 工具），并将实际读取内容作为证据引用。
- 在工作区内写入/编辑文件：`E:\deepseek-harness`（当前会话 file policy = `workspace-write`）。
- 计算 SHA256、对比目录前后状态（脚本实测证据）。
- 启动**无本会话上下文**的独立子会话，用作"新上下文读取回执"的**代理演练**。

**不能做（本会话实测）**
- **（原写"不能写工作区外路径"——已更正，R3-8）** 默认 file policy = `workspace-write` 时，
  对工作区外路径的写入**会被沙箱拒绝**（证据 E6）；但**经用户对该具体动作批准后**，
  本节点**已成功**把产物写入 `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE`（E14、STATE.md S8）。
  因此准确表述是：**工作区外写入需逐次用户批准，而非"不能"**。
- **不能触发平台级上下文压缩**，故本节点无法自行完成"压缩恢复"演练（Q5，只能判 `PARTIAL`）。
- **不能代表其他节点**读取其运行状态或提交回执。
- **（原写"不能确认执行门契约全文与内嵌摘要是否同一文本（本快照已知缺口）"——已关闭，R3-8）**
  本节点已读取 `EXECUTION-GATE-CONTRACT.md` **全文**（100 行），确认该文件自身即
  **v0.4 / ACTIVE**，与 `~/.dsh/AGENTS.md` 内嵌 v0.4 摘要**同版**（见 `EVIDENCE.md` E16，R6 关闭）。
  遗留的是**索引滞后**（索引记 v0.2），非本节点能力缺口。

**已知冲突（本节点不擅自解决）**
- R1 `~/.dsh/AGENTS.md` 声明的 Active Root `C:\Users\29845\.codex\ai-kingdom\system-root.yaml` **不存在**。
- R2 其声明的治理 Skill `C:\Users\29845\.codex\skills\ai-kingdom\SKILL.md` **不存在**。
- R3 `~/.dsh/AGENTS.md` §三「AI Kingdom 文件只读」与本轮「创建缺失项目文件」指令冲突（Q2）。

## 6. 回执要求

写入 `nodes/deepseek/receipts/RECEIPT-<handoff_id>.md`，字段同 `handoffs/RECEIPT-template`：
`handoff_id` / `reader_node` / `read_at` / `read_method` / `actual_files_read`（含哈希）/
`missing_files` / `version_conflicts` / `receipt_status`，并附"共同理解、用户纠正、未决问题、
已敲定/待固化/精确参数、下一动作及受阻范围"的复述。

`receipt_status: RECEIVED` **只表示本节点声称实际读取**，不代表用户已采纳任何建议。

## 7. 并发

同一任务同一权威状态文件仅一个写入者。本节点先在自己 `outbox/` 产出提议，
由记录员核对基线版本后合并；基线已变则**停止自动合并**，保留两份并提交用户裁决。
