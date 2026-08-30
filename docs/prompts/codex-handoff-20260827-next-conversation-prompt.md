# 电控交接稿 · 2026-08-27（下一对话继续用）

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

> 交接方：Claude（电控侧）
> 用途：新对话无缝接上电控 XY demo 状态，无需重读历史
> 上一份交接：`codex-handoff-20260824-next-conversation-prompt.md`（仍有效，本稿是增量）
> 详细事实版：[2026-08-27-stm32-xy-demo-handoff.md](../reports/2026-08-27-stm32-xy-demo-handoff.md)

---

## 一、一句话状态

机械子系统故障，校赛演示降级为两条独立链路：① 视觉识别显示（视觉侧独立）；② STM32 串口 `DEMO` 自动循环让 X/Y 走全行程 + Z 升降夹爪开合。XY 单腿行程经实机反复目测，当前定为 **16.5s（800Hz）= 165mm = 13200 步**，X/Y 共用同一值，**是逼近值，未卡尺精标**。demo 模块 + 交接文档已提交（`4012ab5d`）。

---

## 二、XY 行程现状（本次核心）

| 项目 | 值 | 状态 |
|------|-----|------|
| 单腿行程 | 16.5s = 165mm = 13200 步 | `ec_demo.c` `EC_DEMO_STEPS_PER_LEG`；**逼近值** |
| 步进速度 | 800 Hz（定频，无加减速） | `EC_DEMO_STEP_HZ` |
| steps/mm | 80（X=Y） | `ec_axis_driver.h` 冻结（20 齿 GT2 + 1/16 微步 = 3200 步/40mm） |
| 移动超时 | 17500ms | 代码自动推导 = 13200×1000/800 + 1000 |
| 协议落点合法域 | X/Y 各 ±145.0mm（`ITEM_TASK` `\|value\|>1450` 拒绝） | interface-contract V0.6 冻结，原点=装置中心 |

**必须知道的三件事**：

1. 165mm 是「从任意上电位置往外走固定步数、看会不会撞限位」逼近的，**不是**卡尺量出的机械行程，只说明「单边机械行程大概 ≥165mm」。
2. **X/Y 共用 `EC_DEMO_STEPS_PER_LEG` 一个宏**，未分别标定两轴行程是否一致；若不一致需拆成 `STEPS_PER_LEG_X/Y`。
3. demo 的「起点」是上电时轴所在位置，不是机械原点/限位；真正活动范围 = HOME→END 限位距离，尚未标。

---

## 三、demo 串口命令

串口 USART3（PD8 TX / PD9 RX），115200 8N1；USART2（PA2/PA3）备用。

| 命令 | HEX | 成功响应 |
|------|-----|---------|
| `DEMO` | `44 45 4D 4F 0D` | `OK DEMO START` |
| `DEMO STOP` | `44 45 4D 4F 20 53 54 4F 50 0D` | `OK DEMO STOP` |
| `STOP ALL` | `53 54 4F 50 20 41 4C 4C 0D` | `OK STOP ALL` |

- 启动前七路安全输入任一触发 → `ERR DEMO_INHIBITED`。
- demo 激活期间仅 `PING/STATUS/INPUTS/HELP/STOP ALL/DEMO STOP` 可用，其余返回 `ERR DEMO_ACTIVE`。
- 6 相位循环：`X_OUT → X_BACK → Y_OUT → Y_BACK → Z_OPEN → Z_CLOSE`。

---

## 四、demo 参数（`ec_demo.c` 顶部宏）

| 宏 | 当前值 | 含义 |
|-----|--------|------|
| `EC_DEMO_STEP_HZ` | 800 | 定频步进速度 |
| `EC_DEMO_STEPS_PER_LEG` | 13200 | 单腿步数 = 165mm = 16.5s |
| `EC_DEMO_SERVO_OPEN_US` | 1000 | Z 舵机下降=夹爪张开（占位待标定） |
| `EC_DEMO_SERVO_CLOSE_US` | 1900 | Z 舵机上升=夹爪闭合（占位待标定） |
| `EC_DEMO_SERVO_SETTLE_MS` | 200 | 舵机稳定时间 |
| `EC_DEMO_MOVE_TIMEOUT_MARGIN_MS` | 1000 | 移动超时余量 |

安全掩码（低有效，任一置位即停）：`X_HOME|X_END|Y_HOME|Y_END|Z_UP|Z_DOWN|ESTOP_FB` 七位。

---

## 五、关键引脚（⚠️ 含一处更正）

| 对象 | 功能 | 引脚/外设 |
|------|------|-----------|
| X 轴 | STEP / DIR / ENABLE | PC6/TIM8_CH1 · PA7 · PA5（低有效） |
| Y 轴 | STEP / DIR / ENABLE | PB6/TIM4_CH1 · PC7 · PD7（低有效） |
| **升降夹爪舵机** | PWM | **PB11/TIM2_CH4**（唯一舵机，复用原 WRIST_PWM） |

> ⚠️ **更正**：旧交接单写「夹爪舵机 PB10/TIM2_CH3」已过时。当前夹爪无独立舵机，唯一舵机是 Z 轴升降 = PB11/TIM2_CH4。PB10 已弃用。

九路安全输入：X_HOME=PG7、X_END=PG6、Y_HOME=PG9、Y_END=PD5、Z_UP=PF11、Z_DOWN=PG14、ESTOP_FB=PG13、START_SIG=PA4、MANUAL_RESET_SIG=PF8（全低有效、内部上拉；当前无开关，悬空即 `ACTIVE=0000`）。

---

## 六、下一步（接手后建议顺序）

1. **Keil 重编译烧录**：确认 `EC_DEMO_STEPS_PER_LEG=13200` 进入 HEX（源码已改，构建日志未复核）。
2. **卡尺量行程**：发 `DEMO` 走一腿后量 X、Y 各自实际位移，与 165mm 比对；若两轴不一致，拆 `STEPS_PER_LEG_X/Y`。
3. **标 DIR 方向**：`MOTION ARM` → `MOVE X DIR0 STEPS 400 HZ 500`（5mm），记录 X/Y 各 DIR0/DIR1 对应机械正反。
4. **标 Z 舵机脉宽**：`SERVO ARM` → `SERVO PB11 P1000..1900`，回填 `EC_DEMO_SERVO_OPEN/CLOSE_US` 与 `ec_axis_driver.h` 的 `EC_AXIS_Z_DOWN/UP_US`。
5. **标挡板**：四路 MG996R 逐通道扫脉宽，写入上层配置（固件不猜死）。

---

## 七、红线 / 门禁

- 不得把主机测试/Keil 构建结果写成实机通过。
- 不得猜写落点坐标、每毫米步数、方向、脉宽、超时、重发、心跳、屏幕或电源参数。
- 接线、上电、烧录、实机运动需用户对具体动作授权。
- **165mm/16.5s 是逼近值**，任何正式文档或上层配置标注「待精标」，不得升格为既定事实。

---

## 八、关键文件路径

- 固件：`电控/firmware/stm32f407_m144z/App/Src/ec_demo.c`（行程宏）、`App/Inc/ec_axis_driver.h`（steps/mm=80）
- 命令协议：`docs/design/2026-08-20-motion-command-list-v1.md`
- 引脚权威：`docs/design/m144z-m4-tested-pin-pcb-map.md`
- 标定清单：`docs/design/2026-08-26-实机标定测试清单.md`
- 接口契约：`docs/design/interface-contract.md`（ITEM_TASK ±145mm）

---

**交接完毕。新对话读本稿 + 详细版 [2026-08-27-stm32-xy-demo-handoff.md](../reports/2026-08-27-stm32-xy-demo-handoff.md) 即可接手。**
