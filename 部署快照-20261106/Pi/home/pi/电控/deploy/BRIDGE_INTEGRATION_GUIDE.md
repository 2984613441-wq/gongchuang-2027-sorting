# 桥接打通 · 部署指南（视觉 → 树莓派 → STM32）

> 版本：2026-09-05 ｜ 状态：主机侧已打通验证，**未烧录/未上电/未实机运动**

## 一、架构

```
MaixCAM (YOLO 视觉)  ──TCP:8765 长连接──▶  树莓派4B  ──UART 115200──▶  STM32F407
  main.py                 BATCH_TARGETS      run_chain.py                  ec_app (0xA5 二进制)
  每帧检测/心跳             裸数据区          SocketVisionSource             状态机→抓放
                                               + listener 线程
```

桥接核心是 `电控/src/electrical_control/rpi/socket_vision_source.py`：
`SocketVisionSource` 把 MaixCAM 的 BATCH_TARGETS 解析成 `ItemTaskContext`，
喂给 `run_chain.py` 里已有的 `Scheduler`，走**正式二进制 ITEM_TASK 协议**（不是文本命令）。

## 二、关键改动（本次）

| 文件 | 改动 |
|------|------|
| `电控/src/electrical_control/rpi/socket_vision_source.py` | 新建：SocketVisionSource + recv_batch + vision_listener |
| `电控/deploy/run_chain.py` | 注入真实源 + 主循环动态源不 break + 轮询 50ms→5ms |
| `视觉/src/maixcam_deploy/main.py` | TCP 长连接 + 心跳 + 0.3 阈值 + class_id 过滤 |
| `电控/tests/rpi/test_socket_vision_source.py` | 新建 6 个主机侧测试 |
| `电控/tests/rpi/test_outbound.py` | 同步 image_id==class_id 冻结 invariant |

## 三、启动步骤（真实模式）

### 1. 树莓派（先起，监听 8765）

```bash
cd ~/电控_deploy
PYTHONPATH=~/电控_src:$PYTHONPATH python3 run_chain.py \
  --port /dev/serial0 \
  --round-id 1 \
  --round-task-id 1 \
  --names-file ~/class_names.json \
  --image-dir ~/images
```

启动后日志出现 `视觉监听线程已启动: 0.0.0.0:8765` 即就绪。

### 2. MaixCAM（后起，连接树莓派）

```bash
# 关键：TASK_ID 必须等于树莓派 --round-task-id，否则桥接 fail-closed 拒收
export TASK_ID=1
python3 /root/main.py
```

## 四、⚠️ 部署前必读

1. **`TASK_ID` 必须对齐**（红线级）：MaixCAM 的 `TASK_ID` 默认 `0`，桥接端会
   fail-closed 拒收 `task_id=0` 或不匹配的 batch。树莓派 `--round-task-id` 和
   MaixCAM `TASK_ID` 必须是同一个值，否则链路通了也不分拣。

2. **drop_point 是占位点**：当前所有物体都投到固定点 `(10mm, 20mm)`（
   `run_chain.py` 的 `BRIDGE_DROP_POINT`），只为证明链路正确。标定后替换
   `_bridge_drop_point` 一张表为真实 6 盒坐标，其余代码零改动。

3. **box_id = class_id 是占位**：`socket_vision_source.py` 里 `replace(t, box_id=t.class_id)`
   是临时代替，真正的 `(颜色,形状) → box_id` 映射在标定阶段补。

4. **尚未实机验证**：以上全部是主机侧结果（逻辑+闭环）。烧录、上电、接线、
   实机运动需另行授权。

## 五、主机侧验证命令（无需硬件）

```bash
cd 电控
PYTHONPATH=src python -m pytest tests/rpi/ tests/integration/test_host_side_chain.py -q

# 无硬件闭环（--fake-link，模拟 STM32）
PYTHONPATH=src python deploy/run_chain.py --fake-link --round-id demo \
  --round-task-id 7 --frame-output none
```

## 六、延迟要点

- 串口 **不是** 瓶颈：ITEM_TASK 22 字节 ≈ 1.9ms，单件全往返 73 字节 ≈ 6.3ms。
- 真正瓶颈是**物理运动**：最坏 46400 步 @4kHz ≈ 11.6s，逼近 15s 上限。
- 桥接已消除两处人为延迟：MaixCAM 每帧新建 TCP 连接（→ 长连接）、
  run_chain 50ms+50ms 轮询（→ 5ms）。
- 桥接自身达标线：<50ms（目标）/ 200ms（硬顶）；端到端 <500ms / 1s。
