# 树莓派部署入口

## 链路

```text
视觉 JSONL  ->  action_bridge  ->  STM32 USART3 115200 8N1
```

视觉端只负责输出 JSONL，动作选择与安全门禁在桥接层。桥接层实现位于
`集成/demo_bridge/action_bridge.py`，支持完整 ASCII 指令清单：
`MOVE`、`MOVE STEPS`、`SERVO`、`GROUP`、`BARRIER`。

## 主机干跑（不需要串口、摄像头、模型）

```powershell
python ..\..\视觉\src\jsonl_emitter.py --source fake --label class_a --frames 8 |
python ..\demo_bridge\action_bridge.py --config ..\demo_bridge\config.full.example.json --dry-run
```

输出应显示类别已确认，但动作均为 `DRY_RUN`，因为示例配置全部 `enabled=false`。

## 树莓派实机运行

```bash
python 视觉/src/jsonl_emitter.py --source stdin \
  | python 集成/demo_bridge/action_bridge.py \
      --config 集成/demo_bridge/config.full.example.json \
      --port /dev/ttyUSB0 \
      --allow-motion
```

实机运行前必须：

1. 把配置中动作的 `enabled` 改为 `true`；
2. 确认轴方向、步数、频率、挡板/舵机脉宽已标定；
3. 用真实串口先做一次单类别、低风险动作；
4. 树莓派侧把视觉输出接入 stdin，或后续把推理端接到
   `视觉/src/jsonl_emitter.py` 的 fake source 位置。

## 安全边界

- 默认 dry-run；`--allow-motion` 且配置显式启用才会发运动命令。
- 任何 `ERR`、超时、串口断开、`BOOT SAFE` 都会锁存故障，不会自动重发运动。
- 故障未确认停止时必须物理切断执行器动力。
