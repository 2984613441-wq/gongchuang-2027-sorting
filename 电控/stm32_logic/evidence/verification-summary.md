# STM32 C 纯逻辑骨架主机侧验证摘要

日期：2026-08-12  
范围：仅 `电控/stm32_logic/`；Windows 主机 GCC/CMake 纯 C 验证。  
结论边界：以下证据不构成板级工具链、固件、硬件、接线、上电或实机验证。

## 工具链

- CMake 4.4.0、CTest 4.4.0、GCC 16.1.0 均可解析。
- MinGW Make 无法可靠处理仓库中文绝对路径；将同一授权目录临时映射为 `S:` 后完成配置、严格编译和测试。所有源文件、构建物和证据仍位于 `电控/stm32_logic/`。

## 真实 RED/GREEN

| 阶段 | RED 命令 | 首个相关失败与退出码 | GREEN 命令 | 实际通过数与退出码 |
|---|---|---|---|---|
| CRC32 | `cmake --build S:/build --clean-first` | `undefined reference to ec_crc32_iso_hdlc`，2 | 严格构建后运行 `ec_logic_tests.exe` | 2 个测试 ID，0 |
| 固定容量去重 | 同上 | `undefined reference to ec_dedup_init`，2 | 同上 | 累计 8 个测试 ID，0 |
| 重启锁定 | 同上 | `undefined reference to ec_sm_init`，2 | 同上 | 累计 14 个测试 ID，0 |
| 主链状态机 | 构建后运行 `ec_logic_tests.exe` | 回零后仍为 `HOMING`；24 个 ID 中 18 个断言失败，1 | 同上 | 累计 24 个测试 ID，0 |
| 全局安全 | 构建后运行 `ec_logic_tests.exe` | `POWER_ON` 收到急停仍未锁定；28 个 ID 中 39 个断言失败，1 | 同上 | 累计 28 个测试 ID，0 |

CTest 将上述 28 个显式打印的测试 ID 汇总为 1 个可执行测试，因此 CTest 报告 `1/1`，不可把它误报为仅有一个领域用例。

## 最终验收项目

- C11 静态库、测试程序与固定向量 CLI 在 `-Wall -Wextra -Wpedantic -Werror` 下构建。
- CTest：1/1 可执行测试通过；领域测试程序：28/28 测试 ID 通过。
- Python 与 C 对 `01 02 03 04 05` 均得到 `470B99F4`。
- 既有 Python 回归：协议 24、状态机 19、驱动 12，共 55 项。
- 禁项和动态内存扫描：0 命中。
- `git diff --check`：退出 0；共享工作区其他差异未清理、覆盖或提交。

## 证据文件

- `crc32-red.txt` / `crc32-green.txt` / `crc32-cross-language.txt`
- `dedup-red.txt` / `dedup-green.txt`
- `state-boot-red.txt` / `state-boot-green.txt`
- `state-main-red.txt` / `state-main-green.txt`
- `state-safety-red.txt` / `state-safety-green.txt`
- `final-verification.txt` / `scope-and-diff.txt`

`final-verification.txt` 中末次额外扩展扫描曾因泛化关键词误命中领域变量 `current_item`；该次扫描规则错误，不是生产代码越界。`scope-and-diff.txt` 使用任务书规定的禁项集合并追加无歧义补充词，结果为 0 命中。
