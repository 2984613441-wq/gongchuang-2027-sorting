# 给 Claude 的 2026-08-21/22 提交与仓库卫生只读审核词

## 用途

委托 Claude 对以下内容做一次独立、只读审核：

1. 分支 `codex/stm32-motion-test-v1` 上的 4 笔新提交是否完整、精确、无夹带。
2. `.gitignore` 是否真的挡住了大件参考材料与编译产物。
3. 仓库对象库仍然很大（约 3.42 GiB pack）是否属于历史/远端残留，以及清理建议是否安全。
4. `fd369a28` 中混入的 `easyeda-api.zip`、`sketch_apr05a/` 是否应留在提交里。

该审核只读，不授权修改、push、fetch、清理 `.git`、删除文件或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“2026-08-21/22 电控与视觉集成
提交批次 + 仓库卫生”做回归审核。你只负责发现事实错误、提交范围错误、
忽略规则漏洞、仓库体积问题和清理建议中的风险；你不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入
  工作区的命令。
- 不得执行 git push、fetch、rebase、reset、filter-branch、gc、prune、
  clean 或任何改变 refs/objects 的命令；只允许 git log、status、show、
  check-ignore、rev-list、cat-file、ls-files、branch、remote 等只读检查。
- 若无法独立验证，明确标注“弱独立性”及原因；不得以猜测补齐事实。
- 你的审核结论是建议，不构成执行授权。

基线文件：
1. AGENTS.md 与 CLAUDE.md
2. docs/prompts/codex-handoff-20260821-next-conversation-prompt.md
3. docs/reports/2026-08-21-vision-stm32-action-bridge.md
4. docs/reports/2026-08-21-open-source-reference-review.md
5. .gitignore
6. 分支 codex/stm32-motion-test-v1 的以下 4 笔提交：
   - dee8e836 chore: ignore reference archives, vendor data, and build artifacts
   - d8496e04 chore: archive task, review, and experience records
   - ae13b00f docs: add design, report, and review documents
   - fd369a28 feat: add vision JSONL emitter, STM32 action bridge, and firmware docs
7. 更早基线提交：37b06182、0f23f84c

审查事实基线（Codex 已实测）：
- 4 笔提交共 40 个文件、+3514 行，与提交说明一致。
- 工作区当前干净：git status --porcelain 无输出。
- .gitignore 已命中：开源参考/、智能分类垃圾桶全套文件.zip、
  电控/7寸10寸 1024x600分辨率显示屏客户资料/、
  电控/firmware/stm32f407_m144z/tests/build-*/、视觉/datasets/*、*.pt。
- HEAD 追踪文件实测：364 个文件、约 2.2 MB。
- git count-objects -vH 实测：pack 约 3.42 GiB、loose 约 29.29 MiB、
  garbage 3 个 tmp 对象约 224.42 MiB。
- 大对象（如 dotnet/samples 的 PDF、website/docs 的 GIF、
  sk-azfunc-server 的 DLL、显示屏客户资料中的软件安装包、yolo学习.docx）
  仍在对象库中；其中部分被远端 gongchuang（指向 autogen 仓库）的历史分支
  持有，因此普通 gc 不会清除。
- fd369a28 实际包含 easyeda-api.zip 与 sketch_apr05a/sketch_apr05a.ino，
  而 codex-handoff-20260821 的提交清单明确“不提交”这两类内容。

请按下列顺序审核：

一、提交完整性
1. 核对 4 笔提交的哈希、提交信息、文件数和插入行数。
2. 逐提交检查文件范围是否与提交信息一致，是否夹带无关内容。
3. 检查 fd369a28 中 easyeda-api.zip 与 sketch_apr05a/ 是否违反交接清单，
   并评估移除方案与风险。

二、忽略规则
1. 检查 .gitignore 是否覆盖所有大件参考材料、供应商资料、编译产物。
2. 检查是否存在已跟踪文件依赖被忽略目录，导致 clone 后缺失。
3. 检查忽略规则是否会误伤将来需要提交的源文件。

三、仓库体积
1. 判断 3.42 GiB pack 的来源：当前分支历史、远端历史、垃圾对象分别占多少。
2. 评估只删除 3 个 tmp_obj_* 是否安全，是否需要先确认没有进程正在使用。
3. 评估“清理远端分支引用 + git gc --prune=now”能否安全回收体积，以及
   需要保留哪些远端历史。
4. 明确指出任何会丢失未推送提交或历史记录的操作风险。

四、提交与文档一致性
1. 检查提交内容是否与实施记录、审核记录、交接单一致。
2. 检查是否有应更新而未更新的交接单/验证记录。

输出要求：
1. 将审核记录创建为新的文件（不要覆盖旧审核）：
   .claude/reviews/REVIEW-YYYYMMDD-NNN-claude-git-commits-repo-hygiene.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确
   “审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：
   - 提交范围：通过 / 有条件通过 / 不通过
   - 仓库卫生：通过 / 有条件通过 / 不通过
3. 随后按 P0、P1、P2 排序列出发现项。每项必须包含：编号、严重性、事实
   或证据、精确定位、风险、可验证的整改建议、整改后需要复查的证据。
   没有发现也必须明确写“P0（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得执行任何清理或 git 写入操作，
   不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成采纳/驳回/待确认
记录。任何 `.git` 清理、提交改写、push、删除文件或外部写入都需用户对具体
动作授权。
