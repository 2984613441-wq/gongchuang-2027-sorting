# 2026-08-27 电控侧交接单 — XY 演示行程与 demo 参数

> 用途：电控侧下一位 agent 接手 STM32 继续开发时，直接以本文件为起点，不依赖已消失的对话。
> 前一份交接：[2026-08-20-codex-handoff-current-progress.md](2026-08-20-codex-handoff-current-progress.md)
> 本文聚焦：机械故障后演示方案降级为「视觉显示 + XYZ 串口 demo 循环」，其中 XY 单腿行程已按实机目测调至 16.5s。

---

## 1. 一句话状态

机械子系统故障后，校赛演示降级为两条独立链路：① 视觉识别显示（视觉侧独立处理）；② STM32 串口 `DEMO` 自动循环，让 X/Y 轴连续走全行程 + Z 升降夹爪开合。XY 单腿行程经实机反复目测逼近，当前定为 **16.5s（800Hz）= 165mm = 13200 步**，X/Y 共用同一值，未分别标定。

---

## 2. XY 行程现状（本次核心，用户 2026-08-27 确认）

| 项目 | 值 | 来源 / 状态 |
|------|-----|------------|
| 单腿行程 | **16.5s** = 165mm = 13200 步 | `ec_demo.c` `EC_DEMO_STEPS_PER_LEG`；**逼近值，非标定** |
| 步进速度 | 800 Hz（定频，无加减速） | `ec_demo.c` `EC_DEMO_STEP_HZ` |
| steps/mm | 80（X=Y） | `ec_axis_driver.h` 冻结（20 齿 GT2 + 1/16 微步 = 3200 步/40mm） |
| 移动超时 | 17500ms（= 13200×1000/800 + 1000） | 代码自动推导，无需手改 |
| 协议层落点合法域 | X/Y 各 ±145.0mm（`ITEM_TASK` `\|value\|>1450` 越界拒绝） | interface-contract V0.6 冻结，原点=装置中心 |

**关键说明（务必读）**：

1. **165mm 是「从任意上电位置往外走固定步数、看会不会撞限位」逼近出来的**，不是卡尺量出来的机械行程。它只说明「单边机械行程大概 ≥165mm」。
2. **X/Y 共用 `EC_DEMO_STEPS_PER_LEG` 一个值**，未分别标定两轴行程是否一致。若两轴机械行程不同，需把 demo 拆成 `STEPS_PER_LEG_X/Y` 两个常量（现为单宏）。
3. 165mm ≥ 协议 ±145mm，**满足**落点覆盖要求，但这是巧合级结论，不是标定结论。
4. demo 的「起点」是上电时轴所在位置，**不是**机械原点/限位。真正的活动范围 = HOME→END 限位距离，尚未标。

---

## 3. demo 串口命令

串口：USART3（PD8 TX / PD9 RX），115200 8N1，交叉连接共地；USART2（PA2/PA3）备用。

| 命令 | HEX | 成功响应 |
|------|-----|---------|
| `DEMO` | `44 45 4D 4F 0D` | `OK DEMO START` |
| `DEMO STOP` | `44 45 4D 4F 20 53 54 4F 50 0D` | `OK DEMO STOP` |
| `STOP ALL` | `53 54 4F 50 20 41 4C 4C 0D` | `OK STOP ALL` |

- 启动前若七路安全输入任一触发，返回 `ERR DEMO_INHIBITED`，不启动。
- demo 激活期间，仅 `PING/STATUS/INPUTS/HELP/STOP ALL/DEMO STOP` 可用，其余命令返回 `ERR DEMO_ACTIVE`。
- 6 相位循环：`X_OUT → X_BACK → Y_OUT → Y_BACK → Z_OPEN → Z_CLOSE`，无限循环直到 `DEMO STOP` 或安全输入触发。

---

## 4. demo 参数（`ec_demo.c` 顶部宏）

| 宏 | 当前值 | 含义 |
|-----|--------|------|
| `EC_DEMO_STEP_HZ` | 800 | 定频步进速度 |
| `EC_DEMO_STEPS_PER_LEG` | 13200 | 单腿步数 = 165mm = 16.5s |
| `EC_DEMO_SERVO_OPEN_US` | 1000 | Z 舵机下降=夹爪张开（占位，待标定） |
| `EC_DEMO_SERVO_CLOSE_US` | 1900 | Z 舵机上升=夹爪闭合（占位，待标定） |
| `EC_DEMO_SERVO_SETTLE_MS` | 200 | 舵机稳定时间 |
| `EC_DEMO_MOVE_TIMEOUT_MARGIN_MS` | 1000 | 移动超时余量 |

安全掩码（低有效，任一置位即停）：`X_HOME | X_END | Y_HOME | Y_END | Z_UP | Z_DOWN | ESTOP_FB` 七位。

---

## 5. 冻结引脚映射（权威来源 [m144z-m4-tested-pin-pcb-map.md](../design/m144z-m4-tested-pin-pcb-map.md)）

| 对象 | 功能 | 引脚 / 外设 | 备注 |
|------|------|------------|------|
| X 轴 | STEP | PC6 / TIM8_CH1 | PWM/联动通过 |
| X 轴 | DIR | PA7 | DIR0/1 机械正反**待标定** |
| X 轴 | ENABLE | PA5 | 低有效 |
| Y 轴 | STEP | PB6 / TIM4_CH1 | PWM/联动通过 |
| Y 轴 | DIR | PC7 | DIR0/1 机械正反**待标定** |
| Y 轴 | ENABLE | PD7 | 低有效 |
| **升降夹爪舵机** | PWM | **PB11 / TIM2_CH4** | 唯一舵机（复用原 WRIST_PWM）；PB10 旧夹爪舵机**已弃用** |
| 串口主链路 | TX/RX | PD8 / PD9 = USART3 | 115200 8N1 |
| 串口备用 | TX/RX | PA2 / PA3 = USART2 | 115200 8N1 |

> ⚠️ 更正：旧交接单（2026-08-20）写「夹爪舵机 PB10/TIM2_CH3」已过时。当前夹爪无独立舵机，唯一舵机是 Z 轴升降 = PB11/TIM2_CH4。

九路安全输入：X_HOME=PG7、X_END=PG6、Y_HOME=PG9、Y_END=PD5、Z_UP=PF11、Z_DOWN=PG14、ESTOP_FB=PG13、START_SIG=PA4、MANUAL_RESET_SIG=PF8（全部低有效、内部上拉；当前无开关，悬空即 `ACTIVE=0000`）。

---

## 6. 已确定 vs 待标定

### 已确定（可据此继续开发）

- steps/mm = 80（X/Y），微步 1/16。
- 协议层 ITEM_TASK 落点合法域 ±145mm（有符号 16 位 0.1mm，原点=装置中心）。
- 串口命令集、demo 6 相位循环、七位安全掩码。
- 引脚映射（上表，均实测通过）。

### 待标定（不得凭记忆/猜测写死进固件或上层配置）

| 待标定项 | 说明 | 建议手段 |
|---------|------|---------|
| X 轴机械总行程（mm） | HOME→END 实际距离 | 卡尺/直尺量 |
| Y 轴机械总行程（mm） | 同上，**并与 X 比对是否一致** | 卡尺/直尺量 |
| DIR0/DIR1 ↔ 机械正反 | X/Y 各记录 | 发 `MOVE X DIR0 STEPS 400 HZ 500` 看方向 |
| 原点（装置中心）在行程中的位置 | 决定 `ITEM_TASK` X/Y 有符号坐标与实际落点对应 | 结合限位开关标定 |
| Z 舵机脉宽（升降） | 1000/1900us 是占位，实机找「下降张开套住、上升闭合夹住」两点 | `SERVO PB11 P1000..1900` 扫 |
| 挡板脉宽（MG996R×4） | 归集位/避让位 | `BARRIER 1..4 P500..2500` 扫 |

---

## 7. 下一步（下一位 agent 建议顺序）

1. **Keil 重编译烧录**：确认 `EC_DEMO_STEPS_PER_LEG=13200` 进入 HEX（源码已改，构建日志未复核）。
2. **卡尺量行程**：发 `DEMO` 走一腿后量 X 轴、Y 轴各自实际位移，与 165mm 比对；若两轴不一致，拆 `STEPS_PER_LEG_X/Y`。
3. **标 DIR 方向**：`MOTION ARM` → `MOVE X DIR0 STEPS 400 HZ 500`（5mm），记录 X/Y 各 DIR0/DIR1 对应机械正反。
4. **标 Z 舵机脉宽**：`SERVO ARM` → `SERVO PB11 P1000..1900`，回填 `EC_DEMO_SERVO_OPEN/CLOSE_US` 与 `ec_axis_driver.h` 的 `EC_AXIS_Z_DOWN/UP_US`。
5. **标挡板**：四路 MG996R 逐通道扫脉宽，写入上层配置（固件不猜死）。

---

## 8. 交接约束（沿用）

- 不得把主机测试/Keil 构建结果写成实机通过。
- 不得猜写未冻结的落点坐标、每毫米步数、方向、脉宽、超时、重发、心跳、屏幕或电源参数。
- 接线、上电、烧录、实机运动需用户对具体动作授权。
- 165mm/16.5s 是**逼近值**，任何正式文档或上层配置中标注「待精标」，不得升格为既定事实。
