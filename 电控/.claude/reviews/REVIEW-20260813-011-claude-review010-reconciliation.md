# REVIEW-20260813-011 — REVIEW-010 对账独立只读回归审核

> 审查者：Claude（独立只读审核方）
> 日期：2026-08-13
> 类型：L3 独立只读回归审核（对 `REVIEW-20260812-010` 的 P1/P2 对账闭环复核）
> 范围：对账后的第二批电控代码补充改动（P1-001/P1-002 新鲜复跑 + P2-001/P2-002/P2-003 落地）
> 权限：只读。未修改、未创建、未覆盖任何生产代码、测试、设计、任务或历史审查文件（本报告为唯一新建产出）。

---

## 0. 总体裁决

**条件采纳（主机侧纯逻辑范围）**

- 对账报告 `docs/reports/2026-08-13-review010-codex-reconciliation.md` 中所有可量化声明均经本轮新鲜复跑**一致确认**：Python 90/90、C 显式测试 ID 35/35、CTest 1/1、Python↔C CRC `470B99F4`、`compileall` 0、禁项扫描 0 命中、`git diff --check` 0。
- P1-001（C 测试环境）与 P1-002（跨语言 CRC）由本审核**独立新鲜复跑关闭**，不再仅依赖 Codex 自述。
- P2-001/P2-002/P2-003 三处改动**真实存在、内容正确、未越权、未改动生产逻辑**。
- 无 P0、无 P1 阻塞发现。
- 保留 3 项 P2 级（非阻塞）文档/证据完整性提示（见第 3 节）。
- 实机门禁不变：完整 `ITEM_TASK` wire 格式、外层帧、CRC16、波特率、GPIO、定时器、电机、限位、A4988 参数仍未冻结；接线、上电、烧录、投板、采购、实机运动仍严格禁止。

---

## 1. 审核方法与独立性

### 1.1 执行事实

按审核词要求，本轮真实执行：

| 项目 | 命令/动作 | 结果 |
|---|---|---|
| Python 协议 | `unittest discover 电控/tests/protocol` | 24/24 OK |
| Python 状态机 | `unittest discover 电控/tests/state_machine` | 19/19 OK |
| Python 驱动 | `unittest discover 电控/tests/drivers` | 12/12 OK |
| Python 集成 | `unittest discover 电控/tests/integration` | 14/14 OK |
| Python 树莓派 | `unittest discover 电控/tests/rpi` | 21/21 OK |
| Python 编译 | `python -m compileall -q 电控/src 电控/tests` | 退出 0 |
| C 配置/构建 | `subst S:` → `cmake -S S: -B S:/build` → `cmake --build S:/build --clean-first` | 退出 0（`-Wall -Wextra -Wpedantic -Werror`） |
| C 测试 | `S:/build/ec_logic_tests.exe` | `ALL 35 STM32 LOGIC TESTS PASSED`，退出 0 |
| CTest | `ctest --test-dir S:/build --output-on-failure` | 1/1，退出 0 |
| Python↔C CRC | `crc32_iso_hdlc(bytes([1,2,3,4,5]))` vs `crc32_vector_cli.exe` | `CRC_MATCH=470B99F4` |
| 禁项扫描 | `include`/`src` 下 `malloc|calloc|realloc|free|HAL_|GPIO|UART|USART|DMA|TIM[0-9]|A4988|baud|steps_per_mm|pulse_width|acceleration` | 0 命中 |
| 差异检查 | `git diff --check` | 退出 0 |
| 盘符清理 | `subst S: /D` | 退出 0，`S:` 已移除 |

### 1.2 独立性级别

**独立回归审核，存在两项已知限制：**

1. **无 git 基线**：`电控/` 整个目录在工作区为未跟踪（`?? 电控/`），无法用 `git diff`/`git log` 核验本轮究竟改了哪些文件。因此"三处变更只涉及测试与文档、未改生产逻辑"这一论断，只能由**文件 mtime + 代码内容 + 对账自述**三方互证，不能由版本历史直接证明。
2. **同族模型**：Claude 与 Codex 均为 AI，共享项目材料，仅构成模型/流程分离，不等同第三方或实机认证。

### 1.3 文件时间戳互证（对 P2-001 的关键证据）

| 文件 | mtime | 本轮（08-13）是否改动 |
|---|---|---|
| `电控/stm32_logic/src/ec_state_machine.c` | 2026-08-12 16:05 | 否 |
| `电控/stm32_logic/src/ec_dedup.c` | 2026-08-12 15:33 | 否 |
| `电控/stm32_logic/src/ec_crc32.c` | 2026-08-12 15:28 | 否 |
| `电控/stm32_logic/tests/test_state_machine.c` | 2026-08-13 10:21 | **是** |
| `电控/stm32_logic/tests/test_dedup.c` | 2026-08-13 10:32 | **是** |
| `电控/src/electrical_control/rpi/__init__.py` | 2026-08-13 10:22 | **是** |

mtime 与对账报告"变更文件"清单完全一致：本轮只改了 3 个测试/文档文件，`ec_state_machine.c` 自 08-12 起未再改动。这支持"INVALID 处理在补回归测试前已存在"的结论（详见 P2-a）。

---

## 2. 发现项

### P0（无）

未发现阻塞性安全、正确性或越权问题。

### P1（无）

未发现需要重新对账或阻止闭环的实质问题。

### P2（3 项，均非阻塞）

#### P2-a：REVIEW-010 的 P2-001 实为误报，对账已正确闭环，但两份文档存在文字矛盾

- **事实**：`ec_state_machine.c:126-128` 明确将 `EC_DEDUP_FULL` 与 `EC_DEDUP_INVALID` 一并锁定为 `EC_FAULT_DEDUP_CAPACITY_EXHAUSTED`：
  ```c
  } else if ((result == EC_DEDUP_FULL) ||
             (result == EC_DEDUP_INVALID)) {
      lock_machine(machine, EC_FAULT_DEDUP_CAPACITY_EXHAUSTED);
  }
  ```
  `ec_dedup.c:25-28` 在 `cache==NULL`、`entries==NULL`、`capacity==0`、`used>capacity` 时返回 `EC_DEDUP_INVALID`。新增测试 `C-SM-REVIEW-INVALID-DEDUP-001`（`test_state_machine.c:190-200`）通过 `ec_sm_init(&machine, NULL)` 真实触发 `dedup=NULL` → `INVALID` → `CAPACITY_EXHAUSTED` 路径，并非 Mock 假象，且断言无 `START_MOTION`。
- **矛盾**：REVIEW-010 的 P2-001 却断言"代码未显式检查 `EC_DEDUP_INVALID`（缺少 else 分支）"。其引用的代码片段使用变量名 `dedup_result`（实际为 `result`）、分支顺序为 CONFLICT→FULL→DUPLICATE→NEW（实际为 DUPLICATE→CONFLICT→FULL/INVALID→NEW），与真实代码不符，表明该片段是**重建/记忆化引用而非逐字引读**，遗漏了 `|| EC_DEDUP_INVALID` 子句。
- **定位**：`电控/stm32_logic/src/ec_state_machine.c:118-135`（真实现）；`docs/reports/2026-08-13-review010-codex-reconciliation.md:43-54`（对账自述）。
- **结论**：mtime（`ec_state_machine.c` 为 08-12）+ 代码内容 + 对账自述三方一致，**对账报告"该行为在写入回归测试前已存在"成立，REVIEW-010 的 P2-001 为误报**。对账正确补了回归测试且诚实标注"未伪造新的 RED，仅补覆盖"。
- **风险**：低。纯文档一致性；未来读者对照两份文档会看到矛盾。若 `ec_state_machine.c` 实为被静默修改，则上升为 P1（未披露的生产改动）；当前证据（mtime）不支持该情形。
- **建议**：在 REVIEW-010 的 P2-001 或本对账记录中补一行"REVIEW-010 对 `EC_DEDUP_INVALID` 分支的识别有误，实为已存在"，关闭文档矛盾。

#### P2-b：本轮 P2 改动未留存本轮 RED/GREEN 证据文件，TDD 叙述为纯文本自述

- **事实**：`电控/stm32_logic/evidence/` 中现有 `review-fix-red/green.txt` 记录的是 32 个测试 ID、`9 OF 32 FAILED`，属于上一轮"弱独立审查整改"（B 泳道"旧轮/错件事件"，见 `docs/reports/2026-08-12-second-batch-codex-implementation.md` §5.1）；`final-verification*.txt` 记录的是 28 个 ID。**没有任何证据文件记录本轮 35 个 ID 的新鲜 GREEN，或 P2-003 所述"首轮 1 个失败（测试自身期望错误）"的 RED**。
- **定位**：`docs/reports/2026-08-13-review010-codex-reconciliation.md:54`（"测试首轮运行即通过"）、`:77`（"新增测试首轮出现 1 个失败…修正测试后通过"）。
- **结论**：对账报告在 §4 明确"未改历史证据文件"，且 P2-001 诚实声明"未伪造新的 RED"；P2-003 也如实披露了测试自身的期望错误。故这不是造假，只是**本轮改动缺独立可核验的 TDD 证据留存**，P2-003 的"1 失败"叙事只能采信自述，无法复核历史。
- **风险**：低。当前代码与测试均已由本审核新鲜复跑确认正确，仅历史证据链不完整。
- **建议**：补存一份 `35 个 ID` 的新鲜 GREEN 摘要（如 `evidence/p2-reconciliation-green.txt`），并在其中附 P2-003 修正前/后的关键断言差异，使未来复审可回溯。

#### P2-c：审核词要求的 `AGENTS.md` 在工作区不存在

- **事实**：审核词第 24 行要求"先完整读取当前 AGENTS.md 与 CLAUDE.md"，但全工作区无 `AGENTS.md`（`Glob **/AGENTS.md` 与 `**/AGENTS*` 均无结果）。项目入口为 `工创赛/CLAUDE.md` 与全局 `C:\Users\29845\CLAUDE.md`。
- **风险**：极低。未影响本次审核结论（治理指令已由两份 CLAUDE.md 覆盖），但后续审核/新会话若以 `AGENTS.md` 为必读基线会落空。
- **建议**：确认 `AGENTS.md` 是否应存在；若为文档笔误，在审核词模板中改为"当前 CLAUDE.md 与治理指令"。

---

## 3. 已确认事实 / 推断 / 建议 / 未知 / 弱独立性限制

### 3.1 已确认事实（本轮实测或代码直证）

| 事实 | 证据 | 强度 |
|---|---|---|
| Python 90/90 通过（24+19+12+14+21） | 本轮 unittest 复跑 | 强 |
| C 显式测试 ID 35/35 通过 | `ec_logic_tests.exe` 输出 `ALL 35 STM32 LOGIC TESTS PASSED` | 强 |
| CTest 1/1 | `ctest --test-dir S:/build` | 强 |
| Python↔C CRC 一致为 `470B99F4` | 两端独立复算 | 强 |
| 禁项扫描 0 命中、`git diff --check` 0 | 本轮执行 | 强 |
| `ec_state_machine.c` 已显式处理 `EC_DEDUP_INVALID` | `ec_state_machine.c:126-128` | 强 |
| 新增 3 个测试 ID（`C-SM-REVIEW-INVALID-DEDUP-001`、`C-DEDUP-007`、`C-DEDUP-008`）真实存在且通过 | `test_state_machine.c`、`test_dedup.c` | 强 |
| `C-DEDUP-005` 覆盖容量 0 | `test_dedup.c:16`（`ec_dedup_init(&cache, storage, 0U)` → false） | 强 |
| `C-DEDUP-007` 覆盖容量 1 的 NEW/FULL/DUPLICATE 无淘汰 | `test_dedup.c:44-56` | 强 |
| `C-DEDUP-008` 覆盖容量 255 的 used==255/第256个FULL/已知DUPLICATE/清空归0 | `test_dedup.c:58-77` | 强 |
| `Scheduler` 类文档明确 `diagnostic_snapshot` 只读、仅诊断、不恢复/续跑/清零/授权 | `rpi/__init__.py:138-145` | 强 |
| 三处改动均在本泳道目录内，未越权、未改生产逻辑 | 文件清单 + mtime + 代码 | 强 |
| 对账报告无实机/固件/屏幕/串口/A4988 已通过的过度声称 | `docs/reports/2026-08-13-review010-codex-reconciliation.md` §1/§7 | 强 |

### 3.2 推断

| 推断 | 依据 | 验证方式 |
|---|---|---|
| `ec_state_machine.c` 本轮未改，INVALID 处理预先存在 | mtime（08-12 16:05）晚于本轮、代码与对账自述一致 | 建立 git 基线后 `git log`/`git diff` 复核 |
| REVIEW-010 的 P2-001 片段为重建引用而非逐字引读 | 变量名/分支顺序/缺失子句与真实代码不符 | 无（已由代码内容确证） |

### 3.3 建议

| 建议 | 优先级 | 对应发现 |
|---|---|---|
| 在 REVIEW-010 或对账记录中注明 P2-001 识别有误 | P2 | P2-a |
| 补存本轮 35-ID 新鲜 GREEN 与 P2-003 RED 摘要 | P2 | P2-b |
| 澄清 `AGENTS.md` 是否应存在 | P2 | P2-c |

### 3.4 未知（非本轮可决，需外部输入）

- 完整 `ITEM_TASK` wire 格式、X/Y/角度单位与端序、载荷长度。
- 统一外层帧头、外层 CRC16、波特率、超时、重传、心跳数值。
- 电机/驱动器型号与参数、A4988 针序、GPIO/定时器映射、限位、防坠。
- 去重缓存生产容量（本轮仅测试注入 1/2/255，未裁决生产值）。
- STM32 固件工程结构、真实串口/屏幕/电机的台架验证。

### 3.5 弱独立性限制

1. `电控/` 无 git 基线，"未改生产逻辑"只能靠 mtime+代码+自述互证，无法版本级证明。
2. 本审核与 Codex 同属 AI，模型/流程分离不等于第三方或实机认证。
3. 本轮 P2 改动缺独立 TDD 证据文件（P2-b），历史 RED 只能采信自述。

---

## 4. 通过的检查 / 未执行的检查 / 不能得出的结论

### 4.1 通过的检查

- Python 全量回归、`compileall`、C 严格构建与 35 个测试 ID、CTest、Python↔C CRC 对照、禁项扫描、`git diff --check` —— 全部通过。
- P1-001/P1-002 闭环：已由本审核新鲜复跑确认。
- P2-001/P2-002/P2-003 的真实性、正确性、覆盖范围 —— 逐项核对通过。
- 越权扫描：三处改动均限本泳道，未触及协议/状态机/驱动生产代码或未冻结硬件参数。
- 过度声称扫描：对账报告未宣称实机/固件/屏幕/串口/A4988 已验证。

### 4.2 未执行的检查

- Linux/WSL 或 STM32 目标环境的 C 构建与测试（属实机前门禁，本轮主机 MinGW 复跑不代表目标环境通过）。
- 真实串口、真实屏幕、真实电机/限位/急停的台架验证（严格禁止）。
- `git diff` 版本级核验（因 `电控/` 未跟踪，无法执行）。

### 4.3 不能得出的结论

- 不能得出"STM32 固件、真实串口、真实屏幕、真实电机已通过"。
- 不能得出"完整 wire 协议、外层帧、CRC16、波特率、硬件参数已冻结"。
- 不能由 mtime 之外的方式版本级证明"生产代码从未被改动"。

---

## 5. 最小整改清单与复审触发条件

### 5.1 最小整改清单（均可并行，均不阻塞当前闭环）

1. 在 REVIEW-010 P2-001 或对账记录中补注：`EC_DEDUP_INVALID` 分支识别有误、实为已存在。
2. 在 `电控/stm32_logic/evidence/` 补存本轮 35-ID 新鲜 GREEN 与 P2-003 修正前后差异。
3. 澄清 `AGENTS.md` 是否存在，修正审核词基线引用。

### 5.2 复审触发条件（出现任一才需重新对账）

- 建立 git 基线后，`git log`/`git diff` 显示 `ec_state_machine.c` 或其他生产文件在本轮确被改动，且与"未改生产逻辑"相矛盾。
- 在 Linux/WSL 或目标环境复跑 C 测试出现与主机 35/35 不一致的失败。
- 后续冻结任何未冻结参数（wire 格式、CRC16、波特率、硬件参数）并写入生产代码。

### 5.3 实机前仍必须完成的门禁（不变）

WSL/Linux 或目标环境 C 复验；固件 CRC 已知向量与跨语言实测；完整线协议与物理参数冻结；真实串口/屏幕/电机/限位/急停台架验证；人工新轮握手；接线、上电、烧录、投板、采购、实机运动须另行授权。

---

**本报告只评价主机侧纯逻辑代码及其测试与对账记录，不构成任何固件、硬件、实机或 A4988 适配的通过结论。**
