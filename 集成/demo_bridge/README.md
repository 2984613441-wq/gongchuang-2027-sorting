# 电脑视觉到 STM32 的最小演示桥接

本目录只实现今晚演示使用的主控侧桥接，不实现 YOLO，也不修改正式通信协议。
视觉对话只需向标准输入逐行输出 JSON；桥接器完成稳定判定、安全门禁和 STM32
现有 ASCII 测试命令事务。

> 完整指令清单版本见 `action_bridge.py` 与 `config.full.example.json`，
> 覆盖 `MOVE STEPS / SERVO / GROUP / BARRIER`；本文件描述的 `bridge.py`
> 保持为 X/Y 固定动作的最小演示版本。

## 边界

- 仅支持已实机观察过的 X/Y 固定 2 秒测试动作。
- 不把动作称为坐标移动，不支持回零、定位、多轴同步或自动重试运动。
- 所有类别映射默认 `enabled=false`，不得猜测 `DIR0/DIR1` 的机械方向。
- Z 舵机实体尚未动作，本桥接不发送舵机命令。
- 默认是 `--dry-run`；真实串口运动还必须同时提供 `--allow-motion`。
- 这不是 `docs/design/interface-contract.md` 中的正式二进制协议。

## 临时视觉输入

标准输入每行一个 JSON 对象：

```json
{"frame_id": 123, "label": "class_a", "confidence": 0.91, "ts_ms": 123456}
```

无目标帧使用：

```json
{"frame_id": 124, "label": null, "confidence": 0.0, "ts_ms": 123556}
```

只有同一类别连续达到配置帧数且置信度不低于阈值时才触发。触发后锁存，必须连续
无目标达到 `release_after_ms` 才能接受下一件。

## STM32 临时事务

每次动作严格执行：

1. `STOP ALL`，等待 `OK STOP ALL`；
2. `STATUS`，确认步进与舵机均为空闲；
3. `INPUTS`，确认 `ACTIVE=0000`；
4. `MOTION ARM`，等待 `OK MOTION ARMED 10S`；
5. `MOVE X|Y DIR0|DIR1`，等待 `OK MOTION STARTING`；
6. 先观察对应 `MODE=3 STEP_AXIS=1|2`，再观察完全空闲状态。

任何 `ERR ...`、超时、串口断开或 `BOOT SAFE` 都进入锁存故障。故障处理最多重复
三次 `STOP ALL`，但绝不自动重发运动命令；如果无法确认停止，关闭串口并要求物理
切断执行器动力。故障不会自动恢复。

## 配置

复制 `config.example.json`，确认真实方向后才把对应动作的 `enabled` 改为 `true`：

```json
{
  "actions": {
    "class_a": {"enabled": true, "axis": "X", "direction": "DIR0"}
  }
}
```

未提供的字段使用安全默认值；未知字段、非法轴或方向会拒绝启动。

## 使用

只验证稳定判定与动作选择，不打开串口：

```powershell
python bridge.py --config config.json --dry-run --manual-label class_a
```

读取另一视觉进程的 JSONL：

```powershell
python vision_output.py | python bridge.py --config config.json --dry-run
```

真实串口执行（需要 pyserial，且映射必须显式启用）：

```powershell
python bridge.py --config config.json --port COM17 --allow-motion
```

`Ctrl+C` 会尝试执行 `STOP ALL`。串口软件停止不能替代现场物理断电。

## 最小验收

1. 单元测试证明连续帧阈值、低置信度重置、触发锁存和无目标释放。
2. 配置中的所有动作默认禁用；非法动作配置启动失败。
3. Fake Serial 成功路径严格完成 STOP→INPUTS→ARM→MOVE→running→idle。
4. Fake Serial 注入 `ERR`、`BOOT SAFE`、安全输入和超时后均锁存故障并发送
   `STOP ALL`，且不重试 `MOVE`。
5. `--dry-run` 和 `--manual-label` 无需 pyserial 即可运行。
6. 真实演示前先用一个已确认方向、一个类别完成一次动作，再增加第二类。
