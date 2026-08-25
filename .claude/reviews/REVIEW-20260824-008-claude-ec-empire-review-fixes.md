# REVIEW-20260824-008 · 帝国机制复审 + 整改：电控固件（6 代码 + 1 文档）

> 审核方：帝国机制四官（御史 sonnet / 监察官 sonnet / 求是官 opus / 执行官 opus）
> 审核对象：电控固件当前代码（P0 / volatile 整改后）
> 审核等级：L3（模型分离 + 信息隔离：审查官只看代码 + 客观事实，不看调度方结论）
> 审核日期：2026-08-24
> 关联：REVIEW-007（8-23 四官审核存档）、REVIEW-004（P0/P2 整改）

---

## 0. 总体裁决

- 电控固件：**有条件通过（静态/编译级闭环）**
- 实机动作：未授权（P0 运行时正确性待上机复核）

---

## 1. 四官结论（8-24 复审，模型分离）

### 【御史】（sonnet，模型分离）
- **有条件通过**；三项重点核查全通过（计数中断接线、volatile 9 变量、100kHz 时钟数学）。
- 新发现 8 项 F-01~F-08；放行条件 = F-01（DONE/TIMEOUT 竞争）、F-02（ISR 内 HAL 锁）、F-03（结果粘滞）。

### 【监察官】（sonnet）
- **Level 2（高风险可控），不触发红线冻结**，附升级冻结条件。
- 3 项上机前强制动作：限位/ESTOP 极性核对、共地导通、Z 轴不挂载先测。

### 【求是官】（opus）
- 「代码静态闭环」基本成立，但须精确为「链接级/编译级闭环」，P0 修复路径**零执行覆盖**是最大证据空洞。
- 「实机可用」事实占比 **~5%**（纯猜测）。上机判据：`STEP_RESULT=1(DONE)` 证成 / `=2(TIMEOUT)` 回反例。

### 【执行官】（opus）
- 可执行，工程质量中上；计数 DONE 路径中断链完整（不依赖 TIMEOUT 兜底）。
- P2-2（UART 截断）/P2-7（100kHz 魔数）/P2-4（ABORTED）值得上机前修。

---

## 2. 整改（6 代码 + 1 文档）

| 项 | 文件 | 处理 |
|---|---|---|
| P2-2 UART 20ms 截断 | `ec_board_stm32.c` | 超时按长度算 `2×发送时间+10ms` |
| F-01 DONE→TIMEOUT 竞争 | `ec_step_test.c` | 写 TIMEOUT 前检查 `result==NONE`，DONE 优先 |
| F-05 `uart_main_rx_byte` 非 volatile | `ec_board_stm32.c` | **撤销 volatile + 文档化**（读写均在 UART ISR 上下文，主循环不触碰，无 ISR↔主循环竞争，无需 volatile；在 8-25 上机前修订中改为「去 volatile + 注释论证」） |
| P2-7 100kHz 魔数 | `ec_board_stm32.c` | 提为 `#define EC_STEP_TIMER_HZ` + 时钟耦合注释 |
| P2-4 无 ABORTED 观测 | `ec_step_test.h/.c` | 枚举加 `EC_STEP_RESULT_ABORTED` + 抑制中止设值 |
| F-03 `counted_result` 粘滞 | 命令清单 | **文档化**（不改代码：`start_steps` 已复位，粘滞是 host 读结果的前提） |
| F-02 ISR 内 HAL 锁 | `ec_board_stm32.c` | **注释固化**（不改代码：GPIO 直写兜底，安全无虞） |

---

## 3. 测试

- 主机测试 **2/2 通过**（`-Wall -Wextra -Werror -pedantic` 零警告）。
- **盲区**：`ec_board_stm32.c` 不在测试编译列表（`tests/CMakeLists.txt`），其 4 处改动（P2-2/F-05/P2-7/F-02）正确性靠 Keil 编译 + 静态核对，未被主机测试覆盖。

---

## 4. 待办

- Keil 重新编译 → 烧录 → 上机 P0 复核（`MOVE X DIR0 STEPS 2000 HZ 500` → `STEP_RESULT=1`）。
- 上机前 3 项强制动作（监察官）：限位/ESTOP 极性核对、共地导通、Z 轴不挂载。

---

## 5. 独立性限制（如实声明）

- 御史/监察用 sonnet（与执行方 opus 模型分离）；求是/执行用 opus，与御史结论存在同会话先验一致性风险。
- `ec_board_stm32.c` 的 4 处改动未经独立重编译验证（Keil 编译由用户执行）。
