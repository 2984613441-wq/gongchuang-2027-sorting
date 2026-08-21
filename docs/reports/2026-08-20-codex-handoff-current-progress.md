# 2026-08-20 电控代码交接单（对话整合版）

> 用途：新对话继续 STM32 电控开发时，直接以本文件为起点，不依赖已消失的对话。
> 前一份交接：`docs/reports/2026-08-18-codex-handoff-current-progress.md`
> 本文件合并该交接单 + 2026-08-18/19/20 对话中的履带测试参数修改、组合动作修改、硬件事故与电源结论、视觉需求待确认项。

## 1. 一句话状态

STM32 已具备：X/Y 单轴履带测试（100 Hz、10 秒）、X/Y 组合动作（100 Hz、10 秒）、PB10 舵机开合接口、串口命令、九路安全输入门禁。源码已修改；最新 HEX 时间晚于源码修改时间，最可能已包含新参数，但未由本代理复核构建日志，烧录前建议在 Keil 重新构建确认。

## 2. 证据分类

### 用户现场已观察（事实）

- X 轴电机能够转动，且能带动履带移动。
- Y 轴电机能够转动。
- X/Y 联动时能同时运动，但接近末端时“动不了”，判断为机械阻力问题（用户结论：接线/机械问题，非代码问题）。
- PB10 舵机能够动作；OPEN 开口最大合适值约 1000 us，CLOSE 约 1900 us；PWM 停止后夹爪可保持位置。
- 九路输入曾见 `RAW=01FF STABLE=01FF ACTIVE=0000`，并能观察到位变化。
- 降压模块 AMS1117 附近器件冒烟烧毁；用户更换电源模块。
- 舵机目前未单独供电。
- 用户已把“比赛版电控”作为当前目标，时间紧，优先演示链路。

### 代码/构建已验证

- X/Y 单轴测试、舵机测试、GROUP 组合状态机已接入 Keil 工程。
- 组合命令为“软件近同时”，不是三个定时器硬件同边沿同步。
- 本对话修改：步进频率支持 10 Hz 与 100 Hz（动态设置 ARR）；真实运动与组合动作改为 100 Hz、10 秒。
- 此前严格主机测试输出 `ALL FIRMWARE HOST TESTS PASSED`；GROUP 禁用构建退出码 0；Keil 曾 `0 Error(s), 0 Warning(s)`。
- 本对话尝试复用旧主机测试构建目录失败（CMakeCache 记录旧 S: 盘路径），未完成新参数的主机测试；源码 diff 检查无空白错误。

### 尚未验证

- 新参数（100 Hz/10 s）烧录后的实机行为未复核。
- 最新 HEX 是否确实包含 100 Hz/10 s（时间证据支持，缺构建日志确认）。
- X/Y DIR0/DIR1 最终机械方向未冻结。
- 三执行器同时上电的电源压降、峰值电流、机械干涉。
- 上电/复位/下载期间驱动侧 ENABLE/STEP 失效安全。
- 视觉真实联动、完整抓取-投放动作序列。

## 3. 关键引脚（冻结）

| 对象 | 功能 | STM32 引脚/外设 | 备注 |
|---|---|---|---|
| X轴 | STEP | PC6 / TIM8_CH1 | 100 Hz 测试 |
| X轴 | DIR | PA7 | DIR0/1 真实方向待记录 |
| X轴 | ENABLE | PA5 | 低有效 |
| Y轴 | STEP | PB6 / TIM4_CH1 | 100 Hz 测试 |
| Y轴 | DIR | PC7 | DIR0/1 真实方向待记录 |
| Y轴 | ENABLE | PD7 | 低有效 |
| 夹爪舵机 | PWM | PB10 / TIM2_CH3 | OPEN=1000 us，CLOSE=1900 us |
| 串口3 | TX/RX | PD8 / PD9 | 115200 8N1 |

旧 Z 步进通道 PE5/TIM9_CH1、PE6 DIR、PG15 ENABLE 未在演示主链使用。

## 4. 九路安全输入（持续门禁，非“出问题才用”）

全部低有效，外部 10 kΩ 上拉到 3.3 V；正常目标 `ACTIVE=0000`。

| 位 | 引脚 | 名称 |
|---:|---|---|
| 0001 | PG7 | X_HOME |
| 0002 | PG6 | X_END |
| 0004 | PG9 | Y_HOME |
| 0008 | PD5 | Y_END |
| 0010 | PF11 | Z_UP |
| 0020 | PG14 | Z_DOWN |
| 0040 | PG13 | ESTOP_FB |
| 0080 | PA4 | START_SIG |
| 0100 | PF8 | MANUAL_RESET_SIG |

GROUP 使用更严格规则：任一路 `ACTIVE != 0`，授权/启动/运行都会被拒绝或停止。

## 5. 本对话代码修改（100 Hz / 10 秒）

文件与当前参数：

- `电控/firmware/stm32f407_m144z/App/Src/ec_step_test.c`
  - `EC_TRACK_TEST_FREQUENCY_HZ = 100`
  - `EC_MOTION_DURATION_MS = 10000`
  - 无动力信号测试仍 10 Hz / 5 s
- `电控/firmware/stm32f407_m144z/App/Src/ec_group_test.c`
  - `EC_GROUP_STEP_HZ = 100`
  - `EC_GROUP_RUN_MS = 10000`
- `电控/firmware/stm32f407_m144z/App/Src/ec_board_stm32.c`
  - `ec_step_port_start()` 支持 10 Hz 与 100 Hz；
  - 100 kHz 定时器时钟下动态设置 ARR：`period = 100000 / freq - 1`，比较值取半周期。

源码 mtime：ec_board_stm32.c 2026-08-18 12:48；ec_step_test.c / ec_group_test.c 2026-08-18 15:55。
最新 HEX：`MDK-ARM/diankongv1.0/diankongv1.hex`，2026-08-18 16:14:32，晚于源码修改；SHA256 见文件属性（本交接未复核构建日志）。

## 6. 串口命令（ASCII 与 HEX）

串口设置：115200、8 数据位、无校验、1 停止位、HEX 发送。

查输入：
```
49 4E 50 55 54 53 0D 0A
```
期望 `INPUTS ... ACTIVE=0000`。

单轴（每次 MOVE 前必须重新 ARM）：
```
4D 4F 54 49 4F 4E 20 41 52 4D 0D 0A            ; MOTION ARM
4D 4F 56 45 20 58 20 44 49 52 30 0D 0A          ; MOVE X DIR0
4D 4F 56 45 20 58 20 44 49 52 31 0D 0A          ; MOVE X DIR1
4D 4F 56 45 20 59 20 44 49 52 30 0D 0A          ; MOVE Y DIR0
4D 4F 56 45 20 59 20 44 49 52 31 0D 0A          ; MOVE Y DIR1
```

组合（每次 START 前必须重新 GROUP ARM）：
```
47 52 4F 55 50 20 41 52 4D 0D 0A                ; GROUP ARM
47 52 4F 55 50 20 53 54 41 52 54 20 58 44 49 52 30 20 59 44 49 52 30 20 4F 50 45 4E 0D 0A
47 52 4F 55 50 20 53 54 41 52 54 20 58 44 49 52 30 20 59 44 49 52 30 20 43 4C 4F 53 45 0D 0A
```
OPEN=1000 us、CLOSE=1900 us；X/Y 方向可组合 DIR0/DIR1。

停止：
```
53 54 4F 50 20 41 4C 4C 0D 0A                  ; STOP ALL
```

舵机单测（旧版 SERVO 命令保留）：`SERVO ARM`，`SERVO PB10 P1000/P1100/.../P1900`。

## 7. 硬件事故与电源结论

- AMS1117 附近器件烧毁冒烟；AMS1117 是线性稳压器，不适合给大扭矩舵机供电，不能把原因简单归为“三轴电压太大”，更可能是总电流、发热、舵机启动/堵转电流、反接或短路。
- 电源选型（用户已认可方向）：
  - X/Y 驱动：12 V 直流电源，建议明纬 LRS-150-12（12 V/12.5 A/150 W）。
  - 舵机：12 V 转 6.0 V、连续 5 A、峰值 8~10 A 的同步降压模块（舵机额定 DC 4.8–6.8 V，取 6 V）。
  - STM32 逻辑：稳定 5 V/1 A 以上（USB 或 5V 3A 模块）。
- 接线原则：STM32 GND、驱动器逻辑 GND、舵机信号 GND 必须共地；动力电源可分开；25.2 V 充电器不能直接接系统；每路入口建议保险丝；先空载调好输出电压再接负载。
- 舵机不能从 STM32 3.3 V 或 AMS1117 取电。

## 8. 视觉/桥接现状与需求待确认

- 视觉目录仅 README + 空目录，无推理代码。
- README 约定：MaixCAM Pro 部署 YOLO，输出类别 ID、置信度、机械坐标、抓取角度；视觉不直接控制执行器。
- 电脑桥接（演示用）：`集成/demo_bridge/bridge.py`，JSONL 输入 `{"frame_id","label","confidence","ts_ms"}`，默认置信度 0.70、连续 5 帧、无目标释放 1000 ms；事务为 STOP ALL → STATUS → INPUTS → MOTION ARM → MOVE；故障锁存不重试。
- 视觉方案设计前需用户确认四点：
  1. 推理端：MaixCAM Pro / 树莓派 / 电脑（README 写 MaixCAM，用户曾提树莓派，需定死）。
  2. 识别目标与输出：仅类别触发固定动作，还是需要机械坐标 + 抓取角度。
  3. 摄像头安装与光照：固定俯拍或随动、现场光照可控性。
  4. 数据集：每类现有照片/视频数量。

## 9. 下一步（新对话建议顺序）

1. 用 Keil 打开 `MDK-ARM/diankongv1.0.uvprojx`，重新构建并确认 100 Hz/10 s 参数进入 HEX；记录构建日志与 HEX SHA256。
2. 若方便，补跑主机测试（新建当前路径构建目录，旧 build-* 目录的 CMakeCache 指向 S: 盘不可复用）。
3. 实机：先单独 X 轴 100 Hz/10 s，确认履带带动与方向；再单独 Y；再 X/Y 组合；记录 DIR0/DIR1 真实方向。
4. 电源：按第 7 节采购/更换，舵机独立 6 V 供电后再测 PB10。
5. 机械：末端“动不了”按机械阻力处理（履带张紧、轮平行、联轴器/紧定螺丝），未解决前不加电流。
6. 视觉：待用户回答第 8 节四问后设计训练与部署方案；演示桥接只做类别→固定动作，不直接控制 PWM。
7. Git 提交：工作树含大量未提交/未跟踪文件，提交时精确选择本次电控文件，不得一把提交整个工作树。

## 10. 交接约束

- 不得把主机测试/Keil 构建结果写成实机通过。
- 不得猜写未冻结的正式通信协议、ITEM_TASK wire、CRC16、波特率、GPIO、定时器、电机、限位参数。
- 接线、上电、烧录、采购、投板、实机运动需用户对具体动作授权。
- 新知识先作为候选，验证后才能升格。

## 11. 2026-08-20 本对话增量

- 主机测试已与 100 Hz/10 秒参数同步：`test_step_test.c`、`test_group_test.c` 更新频率与时长断言；在纯英文临时目录全新构建，`ec_firmware_host_tests` 与 `ec_diag_disabled_tests` 共 2/2 通过。
- 新增四路挡板模块 `ec_barrier_test.c/h`：PB0/TIM3_CH3、PB1/TIM3_CH4、PF6/TIM10_CH1、PF7/TIM11_CH1；命令 `BARRIER ARM`、`BARRIER P<us>`、`BARRIER 1..4 P<us>`、`BARRIER COLLECT P<us>`、`BARRIER AVOID P<us>`、`BARRIER STOP`；脉宽校验 500～2500 us，归集/避让角度留待实机标定。
- 新增 `PING` → `OK PONG` 链路检查。
- 新增视觉/上位机指令清单：[2026-08-20-motion-command-list-v1.md](../../design/2026-08-20-motion-command-list-v1.md)。
- 新增 XY/Z 目标步数运动：命令 `MOVE X DIR0 STEPS 2000 HZ 500`，步数 1～1,000,000、频率 10～10,000 Hz；STM32 用 TIM4/TIM8/TIM9 更新中断计数，发完指定步数自动停止；`STATUS` 新增 `STEP_TARGET/STEP_REMAIN`。旧版 100 Hz/10 s `MOVE` 保留。
- Keil 工程已加入 `EC_BARRIER_TEST_BUILD=1` 与 `ec_barrier_test.c`；挡板版与 XY 步数版均已由用户本机 Keil V5.06 重建通过：0 Error(s), 0 Warning(s)。P1 超时修复后由 UV4 命令行重建（退出码 0），最新 XY 版 HEX SHA256：`A977A9FA20FC837A10401FEEE2DE42382C6F888D977DF8DAD65AFE4E69A458DE`（该次重建日志未落盘）。
- 已生成 Claude 只读审核词：[claude-review-20260820-barrier-command-v1-readonly-review-prompt.md](../../prompts/claude-review-20260820-barrier-command-v1-readonly-review-prompt.md)。
- 下一步：烧录最新 HEX → 串口验证 `PING/STATUS/BARRIER` 与 `MOVE X DIR0 STEPS 2000 HZ 500` → 实机标定四路挡板脉宽 → 标定 XY 每毫米步数与正方向。
- Claude 只读审核 `REVIEW-20260820-001` 的 P1（60s 计数超时静默截断）已整改：超时按 steps/freq 推导 + 1s 余量，STATUS 新增 `STEP_RESULT=0|1|2`；主机测试 2/2 通过。Keil 命令行已重建（退出码 0），新 HEX SHA256 为 `A977A9FA...458DE`；构建日志未落盘。git 提交尚未完成。
