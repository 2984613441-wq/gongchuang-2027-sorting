# AUTHORITY-STATUS：本目录的权威地位声明

**authority_type: `DISTRIBUTION_SNAPSHOT_NOT_AUTHORITY`**

本目录 `CONTRACT-v0.1/` 是 AI Kingdom 连续性包 **v0.1 的分发快照**（distribution snapshot），
由 DeepSeek Harness 节点于 `2026-09-25T21:12:00+08:00` 自
`C:\Users\29845\Downloads\AI-KINGDOM-CONTINUITY-v0.1.zip`（17963 bytes，mtime 2026-09-25 20:28:43）解包存档。

## 它是什么

- 一份**字节可核验**的候选契约副本，附全量 SHA256（见 `MANIFEST-SHA256.txt`）。
- 供五个节点读取**同一份字节**，避免"各自手里的包不一样"。

## 它不是什么（重要）

1. **不是共享权威规则**。包内 `README.md` 明文：各节点"不能直接把此包写成第二套权威规则"。
2. **不替代**既有共享权威源：
   - `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\governance\AUTHORITATIVE-SOURCES.yaml`
     （其中 `handoff` 与 `workflow` 两域当前标为 `UNRESOLVED`）
   - `C:\Users\29845\AI-KINGDOM-PORTABLE-CORE\workflow\EXECUTION-GATE-CONTRACT.md`
     （**文件自身版本 v0.4 / ACTIVE**；`AUTHORITATIVE-SOURCES.yaml` 索引记 v0.2 属**滞后**，
     见 `EVIDENCE.md` E16 / R11 / Q9；按用户裁决 D-013 **只登记、不改索引**）
     ← **本行原写"v0.2"，系沿用滞后索引值，已由第三轮审计发现并更正（R3-7）**
3. **未获用户批准**、**未在五节点间完成分发与回执**。因此不得引用本目录声称"契约已生效"。

## 与既有候选的关系（本节点提议，未裁决）

既有 `workflow/CONTINUITY-CONTRACT.md`（v1，CANDIDATE）与本包 `core/RUNTIME-RULES.md`（v0.1，候选）
在**同一问题**（跨 Provider 连续性交接）上并存。本节点**不宣布任何一方胜出**，
建议由用户裁决二者关系（详见 `WORKING-NOTES.md` W4）。

## 建议的处置

任一节点若引用本契约，必须同时引用 `MANIFEST-SHA256.txt` 中的哈希，
并在自己的回执中写明 `authority_type: DISTRIBUTION_SNAPSHOT_NOT_AUTHORITY`。
