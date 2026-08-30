# 电控/STM32 三侧联调交接提示词（2026-08-26）

> ⚠️ 2026-08-30 用户拍板：主链路已变更为 USART2/PA2/PA3；本文 USART3 主内容为历史事实，仅作参考。

> 用途：用户把本提示词贴给接手电控侧三侧联调的 agent，目标是在今天中午把
> 视觉(MaixCAM) + 树莓派(Raspberry Pi 4B) + 电控(STM32F407) 三大模块串起来。
> 先做主机侧纯逻辑联调，再按授权接真实串口/上电。

```text
你是接手 2027 年工创赛“智能分拣装置”电控/STM32 侧三侧联调的 agent。当前目标是
把 视觉(MaixCAM) -> 树莓派(Pi 4B) -> STM32F407 这条主链串起来，先完成离线纯逻辑
联调与跨语言协议向量互证，再按授权推进串口/烧录/上电。

请先阅读并对齐（不要凭记忆假设，先读后用）：
1. AGENTS.md 与 CLAUDE.md（唯一治理权威：范围、红线、不得猜写未冻结参数）
2. docs/design/interface-contract.md（协议 V0.6，统一外帧与 ITEM_TASK wire 已冻结）
3. 电控/资料/要求汇总.md（赛规硬要求、方案 B 职责边界、验收标准）
4. 电控/src/electrical_control/protocol/（Python 协议 V0.6 冻结子集与 codec）
5. 电控/src/electrical_control/rpi/（Pi 离线调度器/协议网关/结构化视觉接入）
6. 电控/stm32_logic/（STM32 C 侧外帧与网关实现，供跨语言对照）
7. 集成/demo_bridge/（ASCII 调试命令桥 action_bridge + 运动命令配置）
8. 视觉/README.md 与 视觉/src/sorting_vision/sort_plan.py（形状+颜色分组主链）
9. docs/design/2026-08-20-motion-command-list-v1.md（STM32 ASCII 调试命令清单）

一、三侧数据流（主链时序，已冻结）
逐件主链为：ITEM_TASK -> MOTION_DONE -> ITEM_RESULT -> Pi 完成本件画面实际渲染
-> Pi 发送 DISPLAY_ACK -> STM32 校验匹配后放行下一件。
只有成功的 ITEM_RESULT 才更新 success_count；MOTION_DONE 只表示运动序列结束，
不代表本件成功，也不能放行下一件。

二、已冻结（本轮不得改）
- 统一外帧：帧头 0xA5 0x5A、版本 0x01、设备 ID（0x01=MaixCAM, 0x02=Pi, 0x03=STM32）、
  task_id/frame_seq/data_len 大端、帧级 CRC-16/MODBUS（大端输出）。
- 已知向量：CRC-16/MODBUS 123456789 -> 0x4B37。
- 命令字 0x20 BARRIER_READY、0x21 ITEM_TASK、0x22 MOTION_DONE、0x23 ITEM_RESULT、
  0x24 DISPLAY_DATA(保留非主链)、0x25 DISPLAY_ACK、0x26 ESTOP；基础命令 0x01..0x06。
- ITEM_TASK 完整 wire（V0.6）：共 8 字节 =
  target_seq(1) + class_id(1) + image_id(1) + X(2, 有符号16位补码, 0.1mm, 大端)
  + Y(2, 同上) + angle(1, 恒 0xFF，夹爪不旋转)。
  原点 = 装置中心，|X|/|Y| > 1450（+-145.0 mm）越界拒绝；image_id == class_id，
  活跃 class_id 集合 {0,2,3,4,5,6}（1=cuboid 本轮不出现）。
- DISPLAY_ACK 载荷 6 字节：target_seq(1) + render_result(1, 0x00=RENDERED)
  + 内容 CRC32(4, 大端)。内容 CRC32 输入 = target_seq+class_id+image_id
  +success_count+result_code 五字节拼接，CRC-32/ISO-HDLC，已知向量
  01 02 03 04 05 -> 0x470B99F4。
- 串口：STM32 主链路 USART3 PD8 TX / PD9 RX，115200 8N1，交叉连接共 GND_LOGIC；
  备用 USART2 PA2/PA3；Pi 与 STM32 之间经探索者板转 USB 串口（连接器与线材待确认）。

三、今天中午必须补/确认（电控/机械实测，不得猜写）
方案 A 已定：box_id = 固定物理盒编号（1..6），落点表按 box_id -> (X,Y) 键，
跨批次稳定，不再每批动态字典序分配。当前阻塞视觉侧的两项机械实测输入：
1. (颜色,形状) -> box_id 冻结映射表（6 条，哪类物料放哪个物理盒）：赛题规则 +
   机械布局；视觉手已搭好 sort_plan.BoxAssignment 冻结容器，只差填值。
2. 落点表 box_id(1..6) -> 实际落点 X/Y（单位 0.1mm，原点=装置中心，有符号）：
   机械实测 + 视觉复核；drop_table.DropTable 注入点已在，只差 6 组坐标。
3. 每毫米步数、DIR0/DIR1 对应机械正反、归零与限位逻辑（电控自身标定，独立于上两项）。
4. 挡板/夹爪舵机脉宽标定（500..2500 us 内），写入上层配置，不写死进固件。
5. 超时、重发次数上限、心跳间隔、失联判定、阶段时间预算（待台架实测）。
6. 顶部屏幕到货后的分辨率/供电/自动亮屏/全屏无裁剪。
7. 探索者板转 USB 串口的连接器与线材确认，禁止用 Type-C 代替未知接口。

四、已有代码（先读再用，不要重写）
- 电控/src/electrical_control/protocol/：outer_frame、frames、item_context、
  display_ack、types、direction（Python codec）。
- 电控/src/electrical_control/rpi/：Scheduler、PiProtocolGateway、vision_ingest、
  log（Pi 离线主链骨架）。
- 电控/stm32_logic/src/ec_protocol.c 与 ec_protocol_gateway.c（STM32 C 对照）。
- 集成/demo_bridge/action_bridge.py（ASCII 运动事务：INPUTS -> ARM -> 执行
  -> STATUS，带 fault latch）。

五、今天中午最小验收（离线可做，不需要先上电）
1. Python 与 STM32 C 对同一向量互证：CRC16 0x4B37、CRC32 0x470B99F4、
   ITEM_TASK 8 字节与 DISPLAY_ACK 6 字节编解码一致。
2. 用 Fake 视觉源 + 临时落点表，跑通 box_id -> X/Y -> ItemTaskPayload
   -> encode -> decode 的双向纯逻辑。
3. ASCII 桥 dry-run：action_bridge --dry-run --manual-label 输出正确的
   MOVE/MOVE STEPS/SERVO/GROUP/BARRIER 事务。

六、红线与门禁
- 接线、上电、烧录、采购、实机运动必须等用户对具体动作授权，不得擅自执行。
- 不得把主机测试写成串口/屏幕/STM32/电机/实机通过。
- 不得猜写落点坐标、每毫米步数、方向、脉宽、超时、重发、心跳、屏幕或电源参数。
- 同一识别结果不得同时被 Pi 和 STM32 两个调度端执行。
- 未取得对应授权前，先只做主机侧纯逻辑，不要改代码或接线。

第一个动作：请我提供上述文件或关键片段，并确认当前是“只做主机纯逻辑联调”，
还是“要接真实串口/烧录/上电”；在取得对应授权前不要先动代码或接线。
```
