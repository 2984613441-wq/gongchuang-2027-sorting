# 校赛主控指令清单 V1

> 日期：2026-08-20
> 用途：视觉/树莓派/电脑端按本清单向 STM32 发送控制指令。参数名和值由上层按本清单对照，不在本文件外另立协议。
> 状态：随固件一起生效；挡板脉宽仍需实机标定，标定值写入上层配置，不在固件里猜死。

## 1. 串口与帧格式

- 主串口：USART3，PD8=TX，PD9=RX，交叉连接，共地。
- 参数：115200，8 数据位，无校验，1 停止位。
- 文本命令以 `\r\n` 结尾，一行一条，行长度不超过 60 字节。
- 每条命令必须返回一行响应；上位机收到响应后再发下一条，不流水线连发运动命令。

## 2. 通用响应与重试规则

| 响应 | 含义 |
|---|---|
| `OK ...` | 命令被接受 |
| `ERR ...` | 命令被拒绝，按错误码处理 |
| `STATUS ...` | 周期性状态行，不作为命令响应消费 |
| `INPUTS ...` | 九路输入查询结果 |

上位机规则：

1. 非运动命令（`PING`、`STATUS`、`INPUTS`、各类 `ARM`、`STOP`）超时 200 ms，最多重发 2 次。
2. 运动命令（`MOVE`、`GROUP START`、`SERVO PB10 P...`、`BARRIER P...`）一旦发出并收到 `OK`，禁止自动重发；超时先发 `STOP ALL` 确认停止。
3. `STOP ALL` 超时最多重发 3 次；仍无确认时必须物理切断执行器动力，不能自动继续。
4. 任何 `ERR ...`、串口断开、收到 `BOOT SAFE` 都进入锁存故障，直到人工处理。

## 3. 安全门禁

- 九路输入全部低有效、外部 10k 上拉；正常目标为 `ACTIVE=0000`。
- `ACTIVE != 0000` 时，`ARM` 被拒绝；运行中触发任一输入立即停止对应测试。
- 组合动作（`GROUP`、`BARRIER`）使用全部九路门禁；单轴运动使用限位/急停相关七路门禁。
- 每次运动前必须重新 `ARM`，授权窗口 10 秒，授权一次性使用。

## 4. 命令表

| 命令 | 说明 | 成功响应 |
|---|---|---|
| `PING` | 链路检查 | `OK PONG` |
| `STATUS` | 查询状态 | `STATUS SAFE_LOCK=1 ... STEP_RESULT=0|1|2` |
| `INPUTS` | 查询九路输入 | `INPUTS RAW=01FF STABLE=01FF ACTIVE=0000` |
| `STOP ALL` | 停止全部执行器并清空授权 | `OK STOP ALL` |
| `MOTION ARM` | 单轴运动授权 | `OK MOTION ARMED 10S` |
| `MOVE X DIR0` | X 轴 100 Hz/10 s，方向 0 | `OK MOTION STARTING` |
| `MOVE X DIR1` | X 轴 100 Hz/10 s，方向 1 | `OK MOTION STARTING` |
| `MOVE Y DIR0` | Y 轴 100 Hz/10 s，方向 0 | `OK MOTION STARTING` |
| `MOVE Y DIR1` | Y 轴 100 Hz/10 s，方向 1 | `OK MOTION STARTING` |
| `MOVE Z DIR0` | Z 通道 100 Hz/10 s（板外驱动预留） | `OK MOTION STARTING` |
| `MOVE Z DIR1` | Z 通道 100 Hz/10 s（板外驱动预留） | `OK MOTION STARTING` |
| `MOVE X DIR0 STEPS 2000 HZ 500` | X 轴走 2000 步，500 Hz，方向 0，发完自动停 | `OK MOTION STARTING` |
| `MOVE X DIR1 STEPS 2000 HZ 500` | X 轴走 2000 步，500 Hz，方向 1 | `OK MOTION STARTING` |
| `MOVE Y DIR0 STEPS 2000 HZ 500` | Y 轴走 2000 步，500 Hz，方向 0 | `OK MOTION STARTING` |
| `MOVE Y DIR1 STEPS 2000 HZ 500` | Y 轴走 2000 步，500 Hz，方向 1 | `OK MOTION STARTING` |
| `MOVE Z DIR0 STEPS 2000 HZ 500` | Z 通道走 2000 步，500 Hz（板外驱动预留） | `OK MOTION STARTING` |
| `MOVE Z DIR1 STEPS 2000 HZ 500` | Z 通道走 2000 步，500 Hz（板外驱动预留） | `OK MOTION STARTING` |
| `SERVO ARM` | 夹爪舵机授权 | `OK SERVO ARMED 10S` |
| `SERVO PB10 P1000` | 夹爪开（已标定） | `OK SERVO STARTING 2S` |
| `SERVO PB10 P1900` | 夹爪合（已标定） | `OK SERVO STARTING 2S` |
| `SERVO PB10 P1100/1200/1300/1500/1700` | 夹爪中间位 | `OK SERVO STARTING 2S` |
| `SERVO STOP` | 停止夹爪 PWM | `OK SERVO STOP` |
| `GROUP ARM` | X/Y+夹爪组合授权 | `OK GROUP ARMED 10S` |
| `GROUP START XDIR0 YDIR0 OPEN` | X/Y/夹爪组合，方向与开合自由组合 | `OK GROUP STARTING` |
| `GROUP STOP` | 停止组合动作 | `OK GROUP STOP` |
| `BARRIER ARM` | 四路挡板授权 | `OK BARRIER ARMED 10S` |
| `BARRIER P<us>` | 四路挡板同时设指定脉宽 | `OK BARRIER SET ALL` |
| `BARRIER 1 P<us>` | 仅挡板 1 | `OK BARRIER SET CHANNEL` |
| `BARRIER 2 P<us>` | 仅挡板 2 | `OK BARRIER SET CHANNEL` |
| `BARRIER 3 P<us>` | 仅挡板 3 | `OK BARRIER SET CHANNEL` |
| `BARRIER 4 P<us>` | 仅挡板 4 | `OK BARRIER SET CHANNEL` |
| `BARRIER COLLECT P<us>` | 四路挡板归集位 | `OK BARRIER COLLECT` |
| `BARRIER AVOID P<us>` | 四路挡板避让位 | `OK BARRIER AVOID` |
| `BARRIER STOP` | 停止挡板 PWM | `OK BARRIER STOP` |

## 5. 挡板通道映射

| 通道 | 引脚 | 定时器 |
|---:|---|---|
| 1 | PB0 | TIM3_CH3 |
| 2 | PB1 | TIM3_CH4 |
| 3 | PF6 | TIM10_CH1 |
| 4 | PF7 | TIM11_CH1 |

脉宽允许范围 500～2500 us。固件只做范围校验，不预设归集/避让角度；先用 `BARRIER 1 P1000` 这类命令逐通道标定，再把标定值填到视觉/树莓派配置里，由上层发 `BARRIER COLLECT P...` / `BARRIER AVOID P...`。

## 6. 视觉侧建议调用顺序

视觉端不要把动作写死成多命令流水线。建议每次动作走固定事务：

```text
INPUTS            ; 确认 ACTIVE=0000
<对应 ARM>        ; 按执行器类型选择
<执行命令>        ; 单条运动命令
STATUS            ; 轮询确认回到空闲
```

视觉需要从识别结果映射的动作参数只有三类：轴与方向、夹爪开合、挡板脉冲。类别到动作的映射放在树莓派/视觉配置里，STM32 只负责按命令执行，不解释类别 ID。

## 7. 当前版本边界

- `MOVE X DIR0 STEPS n HZ f` 为目标步数运动：步数范围 1～1,000,000，频率范围 10～10,000 Hz，发完指定步数后自动停止并回到空闲。旧版 `MOVE X DIR0` 仍保留为 100 Hz/10 秒传动测试命令。超时按 `steps/frequency_hz*1000 + 1000 ms` 推导；正常发完与超时由 `STATUS` 的 `STEP_RESULT` 区分（0=无结果，1=正常发完，2=超时）。
- `BARRIER COLLECT/AVOID` 不是“命令发出即认为挡板到位”；挡板到位判据需在实机标定后确定。
- 本清单是校赛主控的即时执行接口；正式方案 B 的二进制外层帧和 `ITEM_TASK` 冻结后，本清单可作为其 ASCII 调试镜像保留。
