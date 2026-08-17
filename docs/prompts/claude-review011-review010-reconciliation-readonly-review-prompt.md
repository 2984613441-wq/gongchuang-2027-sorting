# 给 Claude 的 REVIEW-010 对账只读审核词

## 用途

用于在 Codex 完成 `REVIEW-20260812-010` 的 P1/P2 对账、P2 改动落地和本机重现验证后，委托 Claude 做一次独立、只读的 L3 回归审核。

该审核只评价当前工作区的代码、测试、证据和对账记录，不授权修改文件、采购、投板、接线、上电、烧录、实机运动或任何外部写入。

## 可直接发送的提示词

```text
你是本项目的独立只读审核方（Claude）。请对“REVIEW-010 对账后的第二批电控代码补充改动”做 L3 有限试行回归审核。你的职责是复核 Codex 的采纳/驳回/待确认清单、P2 改动、测试覆盖和结论表述；你不是设计者，也不修改任何文件。

工作区：
C:\Users\29845\Desktop\工创赛

审核性质与权限：
- 只读。不得创建、修改、删除、重命名或覆盖工作区文件；不得运行会写入工作区的命令。
- 不得采购、投板、接线、上电、烧录、驱动实物、访问真实串口或外部账号。
- 可读取本地文件、检查 git 状态与差异、执行不会写入工作区的文本搜索和静态一致性检查。
- C 测试复现需要临时 `subst` 盘符映射。若你不愿或无法修改系统盘符映射，必须标注“C 执行环境阻塞”，不得把未实际运行写成通过。
- 你的结论是建议，不改变用户最终裁决，也不构成实机执行授权。

先完整读取下列基线，再核对本次变更文件；不要只依赖本提示词：
1. 当前 AGENTS.md 与 CLAUDE.md
2. docs/requirements/analysis.md
3. docs/design/interface-contract.md
4. docs/superpowers/plans/2026-08-12-second-batch-parallel-development.md
5. .claude/tasks/TASK-20260812-005-cross-layer-integration.md
6. .claude/tasks/TASK-20260812-006-stm32-c-logic-skeleton.md
7. .claude/tasks/TASK-20260812-007-rpi-display-scheduler.md
8. docs/reports/2026-08-12-second-batch-codex-implementation.md
9. 电控/.claude/reviews/REVIEW-20260812-010-claude-second-batch-code-review.md
10. docs/reports/2026-08-13-review010-codex-reconciliation.md
11. 本次声明变更的文件：
    - 电控/stm32_logic/tests/test_dedup.c
    - 电控/stm32_logic/tests/test_state_machine.c
    - 电控/src/electrical_control/rpi/__init__.py
12. 电控/stm32_logic/ 的现有生产代码、测试与证据文件，以及电控/src/electrical_control/rpi/ 的现有测试，作为对照。

审查事实基线：
- REVIEW-010 原结论为“主机侧纯逻辑有条件通过”，P0 为 0，P1 为 2 项，P2 为 3 项。
- P1-001 为 C 测试环境未直接验证；P1-002 为 Python↔C CRC 一致性依赖文档证据。
- P2-001 为 C 状态机缺少对 `EC_DEDUP_INVALID` 的显式处理；P2-002 为树莓派 `diagnostic_snapshot` 缺少文档；P2-003 为 C 去重缓存缺少容量 1、容量 255 等边界测试。
- Codex 本轮声明：P1 两项在本机新鲜重跑通过；P2 三项已落地；三处变更只涉及测试与文档，没有修改生产逻辑。
- 实机门禁不变：完整 `ITEM_TASK` wire 格式、外层帧、CRC16、波特率、GPIO、定时器、电机、限位和 A4988 参数仍未冻结；接线、上电、烧录、投板、采购和实机运动严格禁止。

请按下列顺序审核，并给出可复查的文件与行号定位。

一、变更范围与对账一致性
1. 对照 `docs/reports/2026-08-13-review010-codex-reconciliation.md`，逐项核对 P1-001、P1-002、P2-001、P2-002、P2-003 的采纳/驳回/待确认结论是否与代码实际一致。
2. 检查三处变更是否越权修改其他泳道目录，是否把“测试覆盖补充”误写成新生产行为，是否引入任何未冻结硬件参数。
3. 检查对账报告是否错误宣称实机、固件、屏幕、串口或 A4988 已验证。

二、P2-001：`EC_DEDUP_INVALID` 显式处理
1. 现有 `ec_state_machine.c` 是否确实把 `EC_DEDUP_INVALID` 与 `EC_DEDUP_FULL` 一并转入 `EC_FAULT_DEDUP_CAPACITY_EXHAUSTED` 锁定。
2. 新增测试 `C-SM-REVIEW-INVALID-DEDUP-001` 是否真实触发 `dedup = NULL` 的路径，并断言：进入 `FAULT_LOCK`、故障码为容量耗尽、无 `START_MOTION`。
3. 检查测试是否只是 Mock 假象，是否遗漏 INVALID 仍可能绕过锁定的等价路径。

三、P2-002：树莓派诊断快照文档
1. `Scheduler` 类文档是否明确 `diagnostic_snapshot` 只读、仅用于诊断、不得恢复或续跑旧轮。
2. 检查新增文档是否引入新的可执行行为或接口变化；现有 21 项树莓派测试是否仍通过。

四、P2-003：C 去重边界测试
1. `C-DEDUP-005` 是否仍覆盖容量 0；`C-DEDUP-007` 是否覆盖容量 1 的 `NEW/FULL/DUPLICATE` 无淘汰语义。
2. `C-DEDUP-008` 是否真实插入 255 个身份，验证 `used == 255`、第 256 个身份返回 `FULL`、已知身份仍返回 `DUPLICATE`，且清除后回到 0。
3. 检查边界测试是否存在测试自身期望错误、未覆盖溢出、或把未插入身份误当已知身份的情况。

五、验证复现
按以下命令新鲜执行并记录退出状态、通过数量和失败摘要；未执行的项目必须明确标注“未执行”。

Python：
```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
python -m unittest discover -s '电控/tests/protocol' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/state_machine' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/drivers' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/integration' -p 'test_*.py' -v
python -m unittest discover -s '电控/tests/rpi' -p 'test_*.py' -v
python -m compileall -q '电控/src' '电控/tests'
```

C（若已经存在 `S:` 映射或你已得到用户授权使用该盘符；否则改为明确环境阻塞）：
```powershell
subst S: C:\Users\29845\Desktop\工创赛\电控\stm32_logic
cmake -S S: -B S:/build -G 'MinGW Makefiles' -DCMAKE_BUILD_TYPE=Debug
cmake --build S:/build --clean-first
& S:/build/ec_logic_tests.exe
ctest --test-dir S:/build --output-on-failure
subst S: /D
```

Python↔C CRC 对照：
```powershell
$env:PYTHONPATH = (Resolve-Path '电控/src').Path
$pythonCrc = python -c "from electrical_control.protocol import crc32_iso_hdlc; print(format(crc32_iso_hdlc(bytes([1,2,3,4,5])), '08X'))"
$cCrc = & 'S:/build/crc32_vector_cli.exe'
if ($pythonCrc -ne '470B99F4' -or $cCrc -ne $pythonCrc) { throw "CRC mismatch: Python=$pythonCrc C=$cCrc" }
"CRC_MATCH=$cCrc"
```

静态检查：
```powershell
$sourceFiles = Get-ChildItem '电控/stm32_logic/include','电控/stm32_logic/src' -Recurse -File
$forbidden = $sourceFiles | Select-String -Pattern 'malloc|calloc|realloc|free|HAL_|GPIO|UART|USART|DMA|TIM[0-9]|A4988|baud|steps_per_mm|pulse_width|acceleration'
if ($forbidden) { $forbidden; throw 'Forbidden STM32 logic binding found' }
git diff --check
```

预期基线：Python 90/90；C 35 个显式测试 ID；CTest 1/1；`CRC_MATCH=470B99F4`；禁项扫描 0 命中；`git diff --check` 退出 0。若实际数量不同，以实际为准并说明原因，不得沿用旧数字。

六、结论边界
1. 明确区分“本机主机侧通过”“纯 C 逻辑通过”“Python↔C CRC 一致”与“STM32 固件、真实串口、真实屏幕、真实电机已通过”的差异。
2. 检查对账报告和代码没有隐含冻结完整 wire 协议、硬件参数或 A4988 适配结论。
3. 列出实机前仍必须完成的门禁：WSL/Linux 或目标环境复验、固件 CRC 已知向量、完整线协议冻结、真实串口/屏幕/电机/限位/急停台架验证、人工新轮握手。

输出要求：
1. 将审核记录创建为新的文件，不要覆盖旧审核：
   .claude/reviews/REVIEW-YYYYMMDD-NNN-claude-review010-reconciliation.md
   若只读权限严格禁止写入，则在回复中输出完整同等内容，并明确“审核记录未写入工作区”。
2. 首先给出总体裁决，格式必须为：采纳闭环 / 条件采纳 / 驳回，并说明主机侧范围。
3. 随后按 P0、P1、P2 排序列出发现项。每项包含：编号、严重性、事实或证据、精确定位、风险、可验证的整改建议、整改后需要复查的证据。没有发现也要明确写“P0（无）”等。
4. 单列“已确认事实、推断、建议、未知、弱独立性限制”，不得混写。
5. 单列“通过的检查、未执行的检查、不能得出的结论”。
6. 最后给出最小整改清单和复审触发条件。不得修改生产代码、测试或历史审查文件，不得以审核建议替代用户授权。
```

## 审核通过后的处理

Claude 的发现项先由 Codex 对照工作区证据逐项验证，再形成新的采纳/驳回/待确认记录。任何实机、采购、投板或外部写入动作仍须等待用户对具体动作授权。