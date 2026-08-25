# Codex 侧交付说明（树莓派调度 + 协议主机逻辑）

日期：2026-08-25
目的：给电控、树莓派、视觉三侧合并时使用的当前交付清单。
范围：主机侧纯逻辑与离线测试；不包含串口、屏幕、STM32 实机、电机或现场通过声明。

## 已保存的版本快照

- 提交号：`291b92ec`
- 分支：`codex/stm32-motion-test-v1`
- 说明：`snapshot: 保存初赛视觉方案前的当前工作区`

## 本侧已完成内容

1. 协议 V0.5 统一外层帧 codec：
   - 帧头 `A5 5A`、版本 `01`、设备 ID、`task_id`/`frame_seq`/`data_len` 大端。
   - 帧级 CRC-16/MODBUS。
   - `DISPLAY_ACK` 六字节载荷和内容 CRC-32/ISO-HDLC。
   - `ITEM_TASK` 冻结身份前缀 `target_seq + class_id + image_id`。

2. 树莓派离线调度器：
   - 新轮验证、任务队列、成功计数、渲染回执和 `DISPLAY_ACK` 门禁。
   - 只有显式渲染回执完成后才产生首个 `DISPLAY_ACK`。

3. Pi 协议网关：
   - 按字节组装 `STM32 -> Pi` 帧，支持 `A5 5A` 重同步。
   - 校验方案 B 方向，按 `(task_id, frame_seq)` 去重。
   - 解析 `BARRIER_READY`、`MOTION_DONE`、`ITEM_RESULT`、`ESTOP`。
   - 渲染回执后编码 `DISPLAY_ACK` 外层帧。

4. 结构化视觉接入：
   - `BatchTargets`、`TargetReacquireResponse` 等逻辑数据类。
   - 可注入 Fake 视觉源，批次到任务队列的映射。
   - `image_id` 必须由调用方提供，不自行猜写。

5. 集中日志：
   - 容量受限、结构化，覆盖启动、任务、结果、显示、故障、阶段时间。
   - 不存连续原始视频。

## 关键文件

Python 协议层：

- `电控/src/electrical_control/protocol/outer_frame.py`
- `电控/src/electrical_control/protocol/frames.py`
- `电控/src/electrical_control/protocol/item_context.py`
- `电控/src/electrical_control/protocol/display_ack.py`
- `电控/src/electrical_control/protocol/types.py`
- `电控/src/electrical_control/protocol/direction.py`

树莓派侧：

- `电控/src/electrical_control/rpi/__init__.py`
- `电控/src/electrical_control/rpi/gateway.py`
- `电控/src/electrical_control/rpi/log.py`
- `电控/src/electrical_control/rpi/vision_ingest.py`

STM32 侧协议实现（供跨语言对照）：

- `电控/stm32_logic/include/ec_protocol.h`
- `电控/stm32_logic/src/ec_protocol.c`
- `电控/stm32_logic/include/ec_protocol_gateway.h`
- `电控/stm32_logic/src/ec_protocol_gateway.c`
- `电控/stm32_logic/include/ec_crc32.h`
- `电控/stm32_logic/src/ec_crc32.c`

## 冻结与未冻结边界

已冻结：

- 统一外层帧和 CRC。
- 设备 ID、命令字。
- `DISPLAY_ACK` 六字节载荷和内容 CRC32 输入/输出。
- `ITEM_TASK` 身份前缀。
- `success_count` 规则。

未冻结，合并前必须补齐：

- `ITEM_TASK` 的 X/Y/角度单位、端序、有效值和总长度。
- 超时、重发次数、心跳间隔、阶段时间预算。
- MaixCAM 与树莓派间串口参数。
- 探索者板载 USB 串口连接器和线材。
- 顶部屏分辨率、供电、自动亮屏、全屏无裁切。

未冻结项建议候选见：

- `docs/design/2026-08-25-rpi-pre-hardware-freeze-list.md`

## 验证命令与结果

Python（仓库根目录，`PYTHONPATH=电控/src`）：

```powershell
$env:PYTHONPATH=(Resolve-Path '电控\src').Path
python -m unittest discover -s '电控\tests\protocol' -v
python -m unittest discover -s '电控\tests\rpi' -v
python -m unittest discover -s '电控\tests\integration' -v
python -m unittest discover -s '电控\tests\state_machine' -v
python -m unittest discover -s '电控\tests\drivers' -v
```

结果：

- protocol：46 项通过
- rpi：37 项通过
- integration：14 项通过
- state_machine：19 项通过
- drivers：12 项通过

STM32 逻辑 C 测试（`-Wall -Wextra -Wpedantic -Werror`）：

- 55 项全部通过。

视觉侧现有测试：

- 45 项全部通过。

## 合并时的注意点

- 树莓派只发高层 `ITEM_TASK`，不发脉冲或逐关节实时量。
- 同一识别结果只能由树莓派一个调度端执行，不能同时由 STM32 执行。
- 只有成功 `ITEM_RESULT` 更新成功计数；重复帧、重传、心跳和重复刷新不计数。
- `DISPLAY_ACK` 只有在实际渲染回执完成后才发送。
- 未经用户授权不接串口、不上电、不烧录、不运动。
