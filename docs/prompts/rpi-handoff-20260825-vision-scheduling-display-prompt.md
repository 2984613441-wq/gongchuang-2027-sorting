# 树莓派视觉/调度/显示侧交接提示词（2026-08-25）

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

> 用途：用户在另一个对话粘贴此提示词，接手“树莓派 4B”在智能分拣装置中的视觉数据消费、
> 任务队列、名称/图片映射、顶部屏显示、`DISPLAY_ACK` 闭环和集中日志工作。
> 文件读取方式：对方若不能直接读本机文件，请按需粘贴或上传下列文件，或先提供关键片段。

```text
你是接手 2027 年工创赛“智能分拣装置”树莓派侧工作的 agent。当前目标是完成树莓派 4B 在
校赛方案 B 中的“视觉数据消费 → 队列 → 显示 → DISPLAY_ACK”主链，不越界做运动控制。

请先阅读并据此对齐（不要凭记忆假设）：
1. AGENTS.md 与 CLAUDE.md（唯一治理权威：范围、红线、不得猜写未冻结参数）
2. docs/design/interface-contract.md（已升到 V0.5，统一外层帧已冻结）
3. 电控/资料/要求汇总.md（赛规硬性要求、方案 B 职责边界、验收标准）
4. 电控/src/electrical_control/protocol/（Python 协议 V0.5 冻结子集）
5. 电控/src/electrical_control/rpi/__init__.py（离线调度骨架）
6. 电控/src/electrical_control/integration/control_flow.py（STM32 侧防护，供对照）
7. 视觉/README.md（视觉推理端是 MaixCAM，树莓派不跑正式 YOLO）

一、树莓派在方案 B 中的角色（已确认，不得改）
- 界面与调度端：保存整批目标队列、决定抓取顺序、名称与图片映射、顶部屏实际渲染、
  成功计数与集中日志。
- 视觉数据消费方：接收 MaixCAM Pro 的结构化视觉结果（BATCH_TARGETS、TARGET_REACQUIRE_RSP），
  不把原始视频拉回树莓派做二次 YOLO。
- 运动指令发出方：只向 STM32 发单件高层任务 ITEM_TASK，禁止发步进脉冲或逐关节实时量。
- 本件放行闸口：只有收到与本件匹配的成功 ITEM_RESULT，完成本地名称/图片映射并
  实际刷新屏幕后，才发送首次有效 DISPLAY_ACK。
- 禁止：直接控制电机/舵机、覆盖 STM32 安全参数、比赛运行中接受遥控、通过 UART 传图片文件。

二、已冻结的协议基线（V0.5，2026-08-25）
- 统一外层帧：帧头 0xA5 0x5A，版本 0x01，设备 ID（0x01=MaixCAM，0x02=树莓派，0x03=STM32），
  task_id/frame_seq/data_len 大端，帧级 CRC=CRC-16/MODBUS（大端输出）。
- 命令字：0x20 BARRIER_READY，0x21 ITEM_TASK，0x22 MOTION_DONE，0x23 ITEM_RESULT，
  0x24 DISPLAY_DATA（保留非主链），0x25 DISPLAY_ACK，0x26 ESTOP；L0 通用命令 0x01~0x06。
- DISPLAY_ACK 载荷 6 字节：target_seq(1) + render_result(1，0x00=RENDERED) + 内容 CRC32(4，大端)。
  内容 CRC32 输入 = target_seq+class_id+image_id+success_count+result_code 五个单字节按序拼接，
  用 CRC-32/ISO-HDLC，已知向量 01 02 03 04 05 → 0x470B99F4。
- ITEM_TASK 已冻结身份前缀 target_seq/class_id/image_id；X/Y/角度完整线格式仍未冻结，
  不得猜写单位、端序和总长度。
- success_count：每轮初值 0，范围 0..255，只由首次有效的成功 ITEM_RESULT 加一，失败/重复/
  重传/心跳/重复渲染/重复 DISPLAY_ACK 不改变计数，255 不回绕，只有经验证的新轮次才复位为 0。
- STM32 串口：主链路 USART3 PD8/PD9，备用 USART2 PA2/PA3，均 115200 8N1；树莓派侧经
  探索者板载 USB 串口（连接器和线材待确认，不得用 Type-C 替代未知接口）。

三、仍未冻结（本轮不得写死）
- ITEM_TASK 的 X/Y/角度单位、端序、有效值表达与完整载荷长度。
- 超时、重发次数、心跳间隔、阶段时间预算。
- 顶部屏到货后的分辨率/供电/自动亮屏/全屏无裁切等实测参数。

四、已有代码（先读再用，不要重写）
- 电控/src/electrical_control/protocol/：DisplayContent、DisplayAckPayload、
  RoundSuccessCounter、encode/decode_display_ack_payload、ItemTaskPayload、方向白名单。
- 电控/src/electrical_control/rpi/__init__.py：Scheduler、PendingRender、FakeRenderer、
  VerifiedNewRound、DisplayAckIntent 的离线骨架。
- 电控/stm32_logic/src/ec_protocol.c 与 ec_protocol_gateway.c：STM32 侧外层帧与网关实现，
  供跨语言对照；CRC-16/MODBUS 已知向量 123456789 → 0x4B37。

五、建议下一步（按序，先读后改）
1. 先复现现有 Python 测试并核对协议向量，不先动生产逻辑。
2. 实现树莓派侧统一外层帧 codec（帧头 0xA5 0x5A + CRC-16/MODBUS + 大端），
   与 STM32 的 ec_protocol.c 双向一致，并做跨语言向量互证。
3. 实现 MaixCAM→树莓派的结构化视觉数据接入（先以可注入的 Fake 源 + 明确的数据类）。
4. 实现任务队列 + 单件 ITEM_TASK 构造 + DISPLAY_ACK 构造与内容 CRC32。
5. 用离线渲染回执证明“实际刷新后才发 DISPLAY_ACK”，并把本件内容保持到下一件完成。
6. 集中日志：启动、任务、结果、显示、故障码、关键阶段时间，限制容量，不存连续原始视频。

六、红线与门禁
- 不得把主机测试写成串口/屏幕/STM32/电机/实机通过。
- 不得猜写未冻结的 ITEM_TASK X/Y/角度 wire、超时、重传、心跳、屏幕或电源参数。
- 接线、上电、烧录、采购、实机运动必须等用户对具体动作授权。
- 同一识别结果不得同时被树莓派和 STM32 两个调度端执行。
- 经验沉淀用五字段：来源、证据强度、适用条件、反例、验证时间/状态/版本；未经验证不升格。

第一个动作：请我提供上述文件或关键片段，并确认当前是只做主机侧纯逻辑，还是要接真实
串口/屏幕；在取得对应授权前不要先改代码或接线。
```
