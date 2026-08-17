# REVIEW-010 Codex 对账记录

> 日期：2026-08-13
> 范围：第二批电控代码 Claude 只读审查 `REVIEW-20260812-010` 的 P1/P2 对账与闭环
> 结论：主机侧纯逻辑有条件通过维持；实机权限不因本对账改变

## 1. 裁决

- 采纳 REVIEW-010 的 `P2-001/P2-002/P2-003` 所有改进项，并补充回归测试与文档。
- `P1-001/P1-002` 在本机重新执行并拿到新鲜证据；仍保留 Linux/WSL、真实固件与真实串口门禁。
- 没有新的 P0 阻塞问题。

## 2. P1 对账

### P1-001 C 测试环境未直接验证

结论：接受，并本轮在本机关闭“未直接运行”的缺口。

执行结果：

| 命令 | 退出码 | 结果 |
|---|---|---|
| `subst S: C:\Users\29845\Desktop\工创赛\电控\stm32_logic` | 0 | 临时盘符映射 |
| `cmake -S S: -B S:/build -G "MinGW Makefiles" -DCMAKE_BUILD_TYPE=Debug` | 0 | 配置成功 |
| `cmake --build S:/build --clean-first` | 0 | 严格告警构建成功 |
| `S:/build/ec_logic_tests.exe` | 0 | `ALL 35 STM32 LOGIC TESTS PASSED` |
| `ctest --test-dir S:/build --output-on-failure` | 0 | `100% tests passed out of 1` |

限制：仅证明 Windows 主机 MinGW 工具链下的纯 C 逻辑；STM32 目标环境、Linux/WSL 和真实板级构建仍未验证，仍属于实机前门禁。验证完成后已移除临时 `S:` 盘符映射，不保留系统级副作用；后续复跑需重新执行同一映射步骤。

### P1-002 跨语言 CRC 一致性依赖文档证据

结论：接受，并本轮重新执行新鲜对照。

```text
CRC_MATCH=470B99F4
```

限制：证明 Python 生产函数与 C 向量工具在本机对 `01 02 03 04 05` 一致；不代表真实串口通信或固件 CRC 已完成验证。

## 3. P2 对账

### P2-001 C 状态机显式处理 `EC_DEDUP_INVALID`

结论：采纳。当前 `ec_state_machine.c` 已把 `EC_DEDUP_INVALID` 与 `EC_DEDUP_FULL` 统一转入 `EC_FAULT_DEDUP_CAPACITY_EXHAUSTED` 锁定。

变更：新增回归测试 `C-SM-REVIEW-INVALID-DEDUP-001`：

- 构造 `dedup = NULL` 的 TASK 事件；
- 断言进入 `FAULT_LOCK`；
- 断言故障码为 `EC_FAULT_DEDUP_CAPACITY_EXHAUSTED`；
- 断言不产生 `START_MOTION`。

TDD 记录：该行为在写入回归测试前已经存在，测试首轮运行即通过；未伪造新的 RED，仅补覆盖。

### P2-002 树莓派诊断快照缺少文档说明

结论：采纳。

变更：`电控/src/electrical_control/rpi/__init__.py` 为 `Scheduler` 增加类文档，明确：

- `diagnostic_snapshot` 只读，仅用于诊断；
- 不得恢复、续跑或清零旧轮状态；
- 不能作为旧轮继续执行的新轮授权。

### P2-003 C 测试未覆盖边界容量

结论：采纳。

变更：`电控/stm32_logic/tests/test_dedup.c` 新增：

- `C-DEDUP-007`：容量 1，首个新身份 `NEW`，第二个不同身份 `FULL`，已知身份重复仍 `DUPLICATE`，无淘汰；
- `C-DEDUP-008`：容量 255，插入 255 个身份后 `used == 255`，第 256 个身份 `FULL`，已知身份重复 `DUPLICATE`，清除后回到 0。

容量 0 由既有 `C-DEDUP-005` 覆盖。

TDD 记录：新增测试首轮出现 1 个失败，但失败原因为测试自身期望错误（把未插入的 `first` 误当已插入），不是生产代码缺陷；修正测试后通过。生产逻辑未因此改动。

## 4. 变更文件

- `电控/stm32_logic/tests/test_dedup.c`
- `电控/stm32_logic/tests/test_state_machine.c`
- `电控/src/electrical_control/rpi/__init__.py`
- `docs/reports/2026-08-13-review010-codex-reconciliation.md`（本文件）

说明：本次 `apply_patch` 工具不可用，文件修改通过 PowerShell 以 UTF-8 无 BOM、LF 行尾写回；未改历史证据文件。

## 5. 验证汇总

| 项目 | 结果 | 退出码 |
|---|---|---|
| Python protocol | 24/24 | 0 |
| Python state_machine | 19/19 | 0 |
| Python drivers | 12/12 | 0 |
| Python integration | 14/14 | 0 |
| Python rpi | 21/21 | 0 |
| Python 合计 | 90/90 | 0 |
| C 显式测试 ID | 35/35 | 0 |
| CTest | 1/1 | 0 |
| Python↔C CRC | `470B99F4` | 0 |
| `compileall` | 通过 | 0 |
| STM32 逻辑禁项扫描 | 0 命中 | 0 |
| `git diff --check` | 通过 | 0 |

## 6. 采纳/驳回/待确认清单

| 编号 | 建议 | 裁决 | 状态 |
|---|---|---|---|
| A-001 | Linux/WSL 环境验证 C 测试 | 采纳，待执行 | 保留为实机前门禁 |
| A-002 | 跨语言 CRC 通信实测 | 采纳，待真实固件/串口后执行 | 保留为实机前门禁 |
| B-001 | C 去重边界测试 | 采纳 | 本轮完成 |
| B-002 | 树莓派快照文档 | 采纳 | 本轮完成 |
| C-001 | C 状态机显式处理 INVALID | 采纳 | 本轮完成（已有实现 + 回归测试） |

暂无驳回项；所有建议均有明确去向。

## 7. 安全边界

- 本轮只涉及主机侧 Python、纯 C 逻辑、fake/fake HAL 测试与文档。
- 接线、上电、烧录、投板、采购、实机运动仍然严格禁止。
- 完整 `ITEM_TASK` wire 格式、外层帧、CRC16、波特率、GPIO、定时器、电机和 A4988 参数仍未冻结，不得猜写。