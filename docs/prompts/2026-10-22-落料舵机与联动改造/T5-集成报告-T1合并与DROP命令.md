# T5 集成报告 · 落料舵机合并进主工程

> **执行**：DSH（Lead）
> **日期**：2026-10-22
> **范围**：把 Codex 的 T1 交付合并进 Keil 工程 + 加 `DROP` 诊断命令 + 补主机侧桩与测试
> **结论**：**集成完成，主机测试 7/7 通过，`DROP` 命令有断言覆盖**

---

# 一、先说结论：Codex 的 T1 我独立验证过了

| 验证项 | 结果 |
|---|---|
| 新文件 `ec_drop_servo.h/.c` 存在 | ✅ |
| 主机测试 7/7 | ✅ **我自己重跑：`100% tests passed out of 7`，0.40 秒** |
| 夹爪常量未被动（800/625/1900） | ✅ |
| ToF `EC_TOF_CONF_MAX=100U` 未被动 | ✅ |
| WS2812 白色 255/200/90 未被动 | ✅ |
| `ec_diag.c` 未被 Codex 改 | ✅（mtime 仍是 10-18） |
| `uvprojx` 未被 Codex 改 | ✅（mtime 仍是 10-18） |
| 上电只到中位、不动作 | ✅ 代码证据：`ec_drop_servo_init()` 只调 `set_us(MID)` |
| 越界不改状态 | ✅ 代码证据：`set_us` 先校验再下发 |
| 板级失败不改状态 | ✅ 代码证据：`if (!ec_board_drop_servo_set_us(...)) return false;` |

---

# 二、🔴 Codex 纠正了我任务书里的一个**真错误**

## 2.1 TIM9 在 APB2，不是 APB1

| 项 | 我原写（**错**） | Codex | **核实结论** |
|---|---|---|---|
| 总线 | APB1 | APB2 | **APB2** ✅ |
| 定时器时钟 | 84 MHz | 168 MHz | **168 MHz** ✅ |
| Prescaler（要 1MHz） | 83 | 167 | **167** ✅ |
| Period | 19999 | 19999 | 一致 |

**我的错误来源**：照抄了 `main.c:221` 的原有注释
「TIM9 **APB1** 预留 : 159 → 839」—— **那条注释本身就是错的。**

**我事后核实的证据**：
`Drivers/STM32F4xx_HAL_Driver/Inc/stm32f4xx_hal_rcc.h` 里
```c
#define __HAL_RCC_TIM9_CLK_ENABLE()  ...  SET_BIT(RCC->APB2ENR, RCC_APB2ENR_TIM9EN);
```
→ **TIM9 在 APB2**，`__HAL_RCC_TIM8_CLK_ENABLE()` 也是 APB2，与 `main.c:213` 的
「PCLK2 = 84 MHz（APB2 DIV2）」→ APB2 定时器时钟 168 MHz 一致。

**附带发现（潜在 bug）**：原 `Prescaler = 839` 在 168 MHz 下实际是 **200 kHz**，
不是注释说的 100 kHz。因为 TIM9 一直没用过，这个错误从未暴露。

**已更正**：`00-总控` §2.2 加更正框、`05-审查清单` T1-2 改 PSC=167。

## 2.2 Codex 的 `PE5 = Y_DIR` 警告 —— **我没找到依据**

Codex 报告 §未决第 4 条说「活跃接线表将 PE5 标为 Y_DIR」。我查了全部 `docs/` 与 `电控/`：

| 文档 | 对 PE5 的说法 |
|---|---|
| `引脚口径-待确认-20261002.md:37` | PE5 = S_TIM9_CH1，「App 层 htim9 0 命中 ⇒ **无业务用途**」 |
| `硬件连线清单-省赛版-20261011.md:269` | PE5 = TIM9_CH1，「**空闲**」 |
| `m144z-m4-tested-pin-pcb-map.md:34` | STEP_Z = PE5，**「弃用（Z 轴改舵机，TIM9 保留未用）」** |
| 固件 `Core/Inc/main.h:80-81` | **`DIR_Y_Pin = GPIO_PIN_7` / `DIR_Y_GPIO_Port = GPIOC`** ⇒ DIR_Y = **PC7** |
| 固件全仓 grep `GPIO_PIN_5` + `GPIOE` | **零命中** ⇒ PE5 在固件里没有任何其他用途 |

搜遍 `docs/电控` 的 `Y_DIR` 只命中方向宏 `EC_MOTION_POSITIVE_Y_DIR`，**不是引脚**。

**⇒ 结论：不存在「PE5 = Y_DIR」。PE5 是空闲的，可安全用于落料舵机。**

**但保留一条待确认**：载板草图里 PE5 曾是 `STEP_Z`（`carrier-schematic-candidate-sketch.md:97`），
若载板真的按草图做了，PE5 可能物理连到 Z 驱动器 STEP 脚（Z 已改舵机，该脚应悬空）。
**这条需要用户看一眼实物确认，不影响软件。**

---

# 三、我做的集成改动（**4 个文件**）

## 3.1 `MDK-ARM/diankongv1.0.uvprojx`（+6 行）

在 `App/Src` 组末尾（`ec_light_ws2812.c` 之后）加入：

```xml
<File>
  <FileName>ec_drop_servo.c</FileName>
  <FileType>1</FileType>
  <FilePath>../App/Src/ec_drop_servo.c</FilePath>
</File>
```

**验证**：XML 解析合法；`App/Src` 组文件数 17 → **18**；节点结构（FileName+FileType+FilePath 连续）已核对。

## 3.2 `App/Src/ec_diag.c`（+70 行）

**新增 `DROP` 命令族**（位置：`GRIP` 之后、`TOF` 之前）：

| 命令 | 行为 | 成功 | 失败 |
|---|---|---|---|
| `DROP OPEN` | `ec_drop_servo_open()` | `OK DROP MOVING` | `ERR DROP_NOT_READY` |
| `DROP CLOSE` | `ec_drop_servo_close()` | `OK DROP MOVING` | `ERR DROP_NOT_READY` |
| `DROP MID` | `ec_drop_servo_mid()` | `OK DROP MOVING` | `ERR DROP_NOT_READY` |
| `DROP POS <us>` | `ec_drop_servo_set_us()` | `OK DROP POS <us>` | `ERR DROP_RANGE DROP POS 500-2500` |
| `DROP?` | 查询 | `OK DROP ready=1 current_us=1500 open_us=1500 close_us=1500` | — |
| 其他 `DROP *` | — | — | `ERR DROP_USAGE DROP OPEN\|CLOSE\|MID\|POS us\|?` |

**同时**：`#include "ec_drop_servo.h"`（L6）；`HELP` 文本增加 `DROP OPEN|CLOSE|MID|POS us|?`。

## 3.3 `tests/CMakeLists.txt`（+3 行）

`ec_diag.c` 被 3 个测试目标引用，**三个都要加 `ec_drop_servo.c`**，否则链接报
`undefined reference to ec_drop_servo_*`：

| 目标 | 改动 |
|---|---|
| `ec_firmware_host_tests` | +`../App/Src/ec_drop_servo.c` |
| `ec_progress_source_disabled_tests` | +`../App/Src/ec_drop_servo.c` |
| `ec_diag_disabled_tests` | +`../App/Src/ec_drop_servo.c` |

## 3.4 主机侧桩（`test_diag.c` / `test_diag_disabled.c`）

`ec_drop_servo.c` 依赖两个板级函数，而主机测试用 `host_stubs` 而不是 `ec_board_stm32.c`
⇒ 必须在测试文件里打桩（这是本仓库既有模式，如 `ec_grip_port_move`）：

**`test_diag.c`**：新增可断言假实现
```c
uint16_t fake_drop_us;
bool fake_drop_ok = true;
bool ec_board_drop_servo_set_us(uint16_t pulse_us) { if (!fake_drop_ok) return false; fake_drop_us = pulse_us; return true; }
void ec_board_drop_servo_stop(void) { fake_drop_us = 0U; }
```
**`test_diag_disabled.c`**：新增恒成功桩。

---

# 四、新增的测试断言（`test_diag.c`，+50 行）

**这是"DROP 命令真的能用"的唯一证据**，不能只靠"编译过了"：

| 断言 | 验证什么 |
|---|---|
| `DROP OPEN`（init 前）→ `ERR DROP_NOT_READY` | **未初始化必须拒绝（fail-closed）** |
| `ec_drop_servo_init()` | 桩恒成功 |
| `DROP?` → `OK DROP ready=1 current_us=1500` | 上电默认中位 |
| `DROP POS 600` → `OK DROP POS 600` 且 `fake_drop_us==600` | 合法脉宽真的下发 |
| `DROP POS 499` → `ERR DROP_RANGE` 且 `fake_drop_us` **仍是 600** | **越界拒绝且不改变输出** |
| `DROP POS 2501` → `ERR DROP_RANGE` 且不变 | 上界同上 |
| `DROP POS 500` / `2500` → `fake_drop_us` 分别为 500 / 2500 | **边界值可用** |
| `DROP MID/OPEN/CLOSE` → 均为 1500 | 三个别名（占位值一致） |
| `DROP BOGUS` → `ERR DROP_USAGE` | **未知子命令不得静默通过** |
| `fake_drop_ok=false; set_us(700)` → false 且 `current_us != 700` | **板级失败时状态不更新** |

---

# 五、验证结果

## 5.1 主机测试（集成后）

```
100% tests passed out of 7
Total Test time (real) = 0.45 sec
```

7 个目标全过：`ec_firmware_host_tests` / `ec_progress_source_disabled_tests` /
`ec_bus_servo_tests` / `ec_diag_disabled_tests` / `ec_axis_driver_tests` /
`ec_motion_plan_tests` / `ec_demo_tests`

## 5.2 编译无警告

编译选项 `-Wall -Wextra -Werror -pedantic`（三个目标都有），**零错误零警告**。

## 5.3 XML 合法性

`[xml]` 解析 `diankongv1.0.uvprojx` 成功，`ec_drop_servo.c` 节点位置正确。

---

# 六、⚠️ 仍未验证（**必须让 Claude 和你都知道**）

| # | 项 | 为什么未验证 | 谁能验 |
|---|---|---|---|
| 1 | **Keil 全工程编译** | 本机无 Keil | 用户（Keil 打开编译一次） |
| 2 | **固件烧录** | 无硬件连接 | 用户 |
| 3 | **PE5 实际 PWM 波形** | 需示波器 | 用户 |
| 4 | **舵机实际动作** | 舵机型号未知、脉宽全是 1500 占位 | 用户（型号确定后） |
| 5 | **`STOP ALL` 能否停 PE5** | **未接入**，见下 | Codex 补做（T1 二期） |

## 🔴 6.1 急停缺口（**这是真问题，Codex 也主动承认了**）

`ec_safety_port_stop_all()` 当前只停 PB10（夹爪），**没有停 PE5**。

**⇒ 按下 `STOP ALL` 后，落料舵机会继续保持当前脉宽出力。**

**处理建议**（需用户拍板）：
- **方案 A**：把 `ec_drop_servo_stop()` 加进 `ec_safety_port_stop_all()`（推荐）
- **方案 B**：保持现状，但**明确记录"落料舵机不在急停范围内"**，并确保机构上不会因保持位置而伤人

**这条我故意没自己做** —— 它改的是安全路径（L4 级），且任务书把 `ec_safety_*` 划在授权范围之外。

## 6.2 上电语义（Codex 提的，很重要）

`ec_drop_servo_init()` 会立即输出 1500µs。**"发中位命令"≠"舵机物理静止"** ——
如果该型号的中位不是机械安全位，上电瞬间可能动作。

**⇒ 首次上电必须脱开机构（或手扶）验证。**

---

# 七、给 Claude 审查的具体清单

按这个顺序看，**别只看我的报告**：

| # | 检查 | 怎么验 |
|---|---|---|
| 1 | `git diff` 看 4 个文件的真实改动 | `git diff -- App/Src/ec_diag.c MDK-ARM/ tests/` |
| 2 | 自己跑 7/7 | 拷到 ASCII 路径 + 保留 `stm32_logic` 结构，`ctest` |
| 3 | `DROP` 的 11 条断言是否真的在测东西（不是空断言） | 看 `test_diag.c` 新增段 |
| 4 | 越界是否真的不改输出 | 看 `DROP POS 499` 后 `fake_drop_us` 仍是 600 |
| 5 | HELP 里 `P1000\|…` 那段有没有被我误改 | **我没动**，因为 `test_diag.c:109` 断言了它 |
| 6 | `uvprojx` 节点有没有破坏原结构 | `[xml]` 解析 |
| 7 | **急停缺口是否属实** | 看 `ec_safety_port_stop_all()` |
| 8 | 上电 1500µs 的风险是否被准确描述 | 看 §6.2 |

---

# 八、已知的、我**没修**的坑（留给后续，别当已解决）

| # | 坑 | 状态 |
|---|---|---|
| 1 | **`HELP` 里 SERVO 语法写错**（`P1000\|P1100\|…` 看着像裸 P，实际必须 `SERVO PB10 P1000`） | **未修** —— 因为 `test_diag.c:109` 断言了这段文本，修它要同时改测试，属独立变更 |
| 2 | `main.c:221` 三处注释仍写"TIM9 **APB1**" | **未修**（改它不影响功能，但会继续误导后人，可顺手修） |
| 3 | 载板草图 PE5=STEP_Z 的物理残留 | 需用户看实物 |

---

**报告生成**：2026-10-22
**改动文件**：4 个（uvprojx、ec_diag.c、tests/CMakeLists.txt、tests/test_diag.c）+ 1 个（test_diag_disabled.c）
**测试**：7/7 通过
