# P1-A · Keil 工程修复（🔨 实现者）

> **先读** `../协作-2026-09-15/00-总览与交接规则.md`（冻结参数、红线、环境坑）
> 和 `../协作-2026-09-15/01-电控固件.md` 的 §1、§2。
>
> 你只做 **P1 这一个问题**。不要碰 P2~P6 的文件。

---

## 任务

`电控/firmware/stm32f407_m144z/MDK-ARM/diankongv1.0.uvprojx` 里缺源文件，
导致 `ec_app.c` 引用的函数**没有定义** → **链接必然失败** → **烧不进板子**。

**把缺的文件加进工程，让 Rebuild 通过。**

---

## 只加这 6 个（🔴 必须）

| 文件 | 所在目录 |
|---|---|
| `ec_axis_driver.c` | `App/Src/` |
| `ec_motion_plan.c` | `App/Src/` |
| `ec_startup_sequence.c` | `App/Src/` |
| `ec_demo.c` | `App/Src/` |
| `ec_protocol.c` | `电控/stm32_logic/src/` |
| `ec_protocol_gateway.c` | `电控/stm32_logic/src/` |

**依据**：`ec_app.c` 直接调用它们里面的符号（`ec_motion_plan_build`、
`ec_axis_driver_start_pick_place`、8 个 `ec_startup_sequence_*`、`ec_demo_poll`
（`ec_app.c:539` 无条件调用）、12 个 `ec_proto_*`、11 个 `ec_gateway_*`）。

---

## 🟡 先别加这 2 个

| 文件 | 为什么 |
|---|---|
| `ec_motion_plan_interp.c` | 定义 `ec_motion_plan_build_interp` |
| `ec_interp.c` | Bresenham 插补 |

**实测依据**：`ec_motion_plan_build_interp` 这个符号**只出现在它自己的定义 + 3 份文档里**，
**`ec_app.c` 根本不调用它** → **XY 插补功能压根没接进主循环**。

- 若只需工程**编过** → **不加**
- 若要**启用插补** → 那不只是加文件，还得改 `ec_app.c:162/236` 把
  `ec_motion_plan_build(...)` 换成 `ec_motion_plan_build_interp(...)`。
  **那是行为变更，不属本任务** —— 写进你的"建议"里，别自己做。

---

## ⚫ 绝对不要加这 1 个

| 文件 | 证据 |
|---|---|
| `ec_config_handler.c` | 全仓 grep `ec_config_handler` 只有 3 行，**全是它自己**（两个 include guard + 自己的 `#include`）。**没有任何调用点。** 它内部 `extern` 了 `is_system_idle()` / `uart_send_frame()`，这两个函数**全固件无定义** → **加进去必然链接失败** |

> 连带结论：`is_system_idle` / `uart_send_frame` **不需要实现**；
> 台账 **E-10（`0x20` 撞 `BARRIER_READY`）随之失效**（撞号的两侧都没在跑）。

---

## 你还要做的

1. **确认头文件搜索路径**包含 `App/Inc` 与 `stm32_logic` 的 include 目录。
2. **确认分组**：`App/Src` 的 4 个放 App 组；`stm32_logic/src` 的 2 个放逻辑组
   （参考工程里现有 `ec_crc32.c` / `ec_dedup.c` / `ec_state_machine.c` / `ec_step_profile.c` 在哪一组）。
3. **Rebuild All**，把 Build Output 末尾贴出来。

---

## ⚠️ 已知的第二阶段（**本次不做，只报告**）

`uvprojx` 里 5 个调试开关**已于 2026-09-15 被置 0**
（`EC_DIAGNOSTIC_BUILD=0` / `EC_MOTION_TEST_BUILD=0` / `EC_SERVO_TEST_BUILD=0` /
`EC_GROUP_TEST_BUILD=0` / `EC_BARRIER_TEST_BUILD=0`）。

**已核实置 0 不会导致链接失败**：
- `ec_diag.c` 整个文件体被 `#if EC_DIAGNOSTIC_BUILD` 包住，`#else` 分支给了 5 个空壳
- `ec_diag_port_write` 定义在 `ec_board_stm32.c:657`（无条件下编译）

**但**：`ec_servo_test.c` / `ec_group_test.c` / `ec_barrier_test.c` / `ec_step_test.c`
这 4 个**台架测试模块里一个 `#if` 都没有** → **永远编译、永远链接、每帧被 poll**，
只是**触发入口被 `ec_diag` 的空壳掐掉了**。

> 🚧 **用户指示：先别删这 4 个模块，等编译时再看。** 你**不要动它们**。
> 若 Rebuild 报与它们相关的错，**如实贴出来**，别自作主张删文件。

---

## 验收

- [ ] `.uvprojx` 的 `<FileName>` 条目从 **35 → 41**（加 6 个）
- [ ] **Rebuild All 通过（0 error）**，贴 Build Output 末尾 5~10 行
- [ ] 若报新错，**如实贴出**，不要"顺手"改逻辑绕过

## 红线

- ❌ **不烧录、不上电、不接线**（L4）
- ❌ 不改 I/O 映射、不改通信协议
- ❌ 不改任何 `.c/.h` 的业务逻辑 —— **本任务只修工程文件**
- ❌ 不动 `ec_*_test.c` 这 4 个台架模块
- ❌ 不碰 `电控/deploy/`、`电控/deployment/` 的配置文件
