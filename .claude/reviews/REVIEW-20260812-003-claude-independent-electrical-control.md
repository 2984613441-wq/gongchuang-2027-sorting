# REVIEW-20260812-003：Claude 独立审查 — 电控方案 B 模块化设计

> 审查方：Claude (Opus 4.8)  
> 日期：2026-08-12  
> 审查类型：文档静态复核，按 `docs/design/claude-codex-collaboration.md` 独立阅读  
> 独立性声明：本审查在 VS Code 共享工作区中独立读取已修正文档，未参与起草过程  
> 审查范围：五份核心设计文档的接口一致性、安全边界、候选器件定位、未知参数处理与可执行性

---

## 1. 审查依据与方法

按协作约定第 3 节，本次审查：

1. **独立阅读**：接收 Codex 已完成的文档修正版本，未参与起草或修正过程
2. **核心关注**：PCB 模块边界、A4988 候选定位、协议方向一致性、`DISPLAY_ACK` 校验可实现性、状态机安全闭合性、急停语义、代码并行切入可行性
3. **输出格式**：采纳/驳回/待机械组确认三类，附文件定位
4. **不修改原文**：仅追加独立意见，不覆盖 Codex 审查结论

已读文档：
- `docs/design/electrical-control-practical-index.md`
- `docs/design/modular-pcb-design.md`
- `docs/design/interface-contract.md` (V0.3)
- `docs/design/stm32-state-machine-pseudocode.md` (V0.2)
- `docs/design/code-first-principles-entry.md`
- `docs/design/electrical-control-practical-hardware.md`
- `.claude/reviews/REVIEW-20260812-002-modular-pcb-protocol-code-entry.md`

---

## 2. 总体评估

**裁决：有条件通过，与 REVIEW-002 最终结论一致。**

方案在以下维度满足文档静态基线要求：

✅ **模块化边界清晰**：探索者开发板、自制载板、外购功能模块职责明确  
✅ **A4988 候选身份准确**：始终标为 X/Y 候选模块位，未升格为最终选型  
✅ **协议方向已修正**：`DISPLAY_ACK` 树莓派→STM32，与状态机 `WAIT_DISPLAY_ACK` 一致  
✅ **安全边界不可绕过**：急停硬切动力、状态机故障锁定、15秒不可续时  
✅ **未知参数明确标记**：电机、驱动器、电源、保护、线束额定值待参数卡  
✅ **代码并行泳道可行**：协议、状态机、fake HAL、STEP/DIR骨架可独立推进

仍需关闭 **REVIEW-002 第 7.2 节遗留项** 才可进入协议/状态机实现冻结：

- CRC32 已定义算法与测试向量 ✓（已关闭）
- 动力许可检查已在回零前和运行中闭合 ✓（已关闭）
- 版本标识已统一为 V0.3 ✓（已关闭）
- **P2-03 X/Y 驱动故障覆盖**：仍为硬件冻结门禁，不阻断文档静态通过 ✓

---

## 3. 采纳项（无需修改）

### 3.1 模块化 PCB 边界（[modular-pcb-design.md](../design/modular-pcb-design.md)）

**定位**：第 2 节、第 5 节、第 8 节  
**判定**：采纳

- 探索者 STM32F407 作为可拆卸主控，自制载板只承担互连、信号调理、低能量保护
- DC/DC、舵机供电、补光功率开关、急停动力切断明确位于外购成熟模块侧
- X/Y A4988 插座始终标为"候选模块位"，BOM 状态表正确列为"候选"
- 第三运动通道仅提供通用 STEP/DIR 接口，不指定驱动器
- 第 1.3 节明确"待验证推断"与"未知"边界

**证据强度**：强。文档多处重复且表述一致。

---

### 3.2 协议方向与 `DISPLAY_ACK` 校验（[interface-contract.md](../design/interface-contract.md) V0.3）

**定位**：第 4.3 节、第 5.5 节  
**判定**：采纳

- `DISPLAY_ACK` 方向固定为 **树莓派→STM32**，与状态机 `WAIT_DISPLAY_ACK` 一致
- 数据区包含：目标序号、渲染结果、显示内容 CRC32（4字节）
- CRC32 使用 CRC-32/ISO-HDLC，多项式 `0x04C11DB7`（反射），初值/最终异或 `0xFFFFFFFF`
- 规范输入：`目标序号 + 类别ID + 图片ID + 累计成功数 + 结果码`（5个单字节，按序拼接）
- 网络字节序输出，已知测试向量：`01 02 03 04 05` → `0x470B99F4`（载荷 `47 0B 99 F4`）
- STM32 必须校验：任务号、目标序号、渲染结果(`RENDERED`)、显示内容 CRC32 全部匹配

**证据强度**：强。算法参数完整，测试向量可验证，树莓派与 STM32 可独立实现并对齐。

**补充建议**（非阻断）：在协议实现测试中，建议增加"错误 CRC 拒绝"和"字段顺序/字节序错误检测"测试用例，确保两端不会因实现差异通过测试但实际不兼容。

---

### 3.3 状态机安全闭合性（[stm32-state-machine-pseudocode.md](../design/stm32-state-machine-pseudocode.md) V0.2）

**定位**：第 3 节、第 4 节、第 6 节主循环、第 7 节故障锁定  
**判定**：采纳

**核心不变量验证通过**：

1. ✅ **一件最多执行一次**：`activeTask` 唯一，`isDuplicate()` 只重发缓存响应（第 6 节 `WAIT_TASK`）
2. ✅ **下一件必须等待首个有效 `DISPLAY_ACK`**：`WAIT_DISPLAY_ACK` 状态直到 `isFirstValidDisplayAck()` 且 `displayAckConsumed=false` 才结案（第 6 节）
3. ✅ **四事件分离**：`BARRIER_READY`、`MOTION_DONE`、`ITEM_RESULT`、`DISPLAY_ACK` 独立定义，不互相替代（第 3 节事件表）
4. ✅ **急停不可绕过**：主循环开头检查 `emergencyStopActive()`，任何活动状态均调用 `fault()`（第 6 节循环顶部）
5. ✅ **15秒不可续时**：只有 `pollProgress()` 新 token 和首个有效 `DISPLAY_ACK` 更新基准，心跳/重传/日志不续时（第 5 节）

**安全门检查**：

- ✅ `POST` 在 `permitActuatorPower()` 后确认 `actuatorPowerPermitted()` 才进入 `HOMING`（第 6 节 `POST` 分支）
- ✅ 主循环在所有活动状态持续检查 `actuatorPowerPermitted()`，丢失即 `fault(ACTUATOR_POWER_PERMISSION_LOST)`（第 6 节循环中段）
- ✅ 故障锁定调用 `stopAll()`、`disable()`、`inhibitActuatorPower()`，不自动恢复（第 7 节 `fault()` 函数）
- ✅ `manualResetPermitted()` 要求本轮结束、急停释放、人工确认、无旧任务可恢复（第 7 节）

**证据强度**：强。伪代码逻辑完整，状态机图与伪代码一致，故障场景表覆盖关键注入。

---

### 3.4 硬件抽象接口解耦（[stm32-state-machine-pseudocode.md](../design/stm32-state-machine-pseudocode.md) 第 2 节）

**定位**：第 2 节接口定义  
**判定**：采纳

- `AxisDriver`、`ServoBarrier`、`Gripper`、`LimitInput`、`SafetyPower` 五个接口不绑定引脚、定时器、PWM 参数或驱动器型号
- 所有调用返回 `Result = OK | FAIL(FaultCode)`，状态机只依赖该抽象
- `SafetyPower.canPermitActuatorPower()` 与 `actuatorPowerPermitted()` 语义已明确拆分（REVIEW-002 P1-02 已关闭）

**证据强度**：强。接口声明清晰，状态机伪代码未出现硬件细节。

---

### 3.5 代码并行切入可行性（[code-first-principles-entry.md](../design/code-first-principles-entry.md)）

**定位**：第 4 节模块边界、第 5 节四条泳道、第 6 节测试  
**判定**：采纳

- **泳道 A（协议）**、**泳道 B（状态机+fake HAL）**、**泳道 C（STEP/DIR 骨架）** 可并行，不依赖电机参数
- **泳道 D（HIL）** 明确阻塞在机械参数与台架验证后
- 首批测试（第 6.1 节）不需要真实电机，可在主机侧执行
- 测试 ID 明确（`PROTO-DIR-001/002`、`SM-ONCE-001/002`、`SM-GATE-001/002` 等），可追溯

**证据强度**：强。泳道边界清晰，汇合闸口明确，测试可自动化。

---

### 3.6 未知参数不越界（全文档）

**定位**：各文档"未知"/"待参数"章节  
**判定**：采纳

- PCB 文档未写入引脚号、GPIO、端子型号、线宽、铜厚、具体电压/电流（[modular-pcb-design.md](../design/modular-pcb-design.md) 第 1.3 节、第 9 节）
- 硬件文档参数卡要求供应商资料与台架实测（[electrical-control-practical-hardware.md](../design/electrical-control-practical-hardware.md) 第 5 节）
- 状态机伪代码未出现步数、频率、回零方向、速度/加速度（[stm32-state-machine-pseudocode.md](../design/stm32-state-machine-pseudocode.md) 第 1 节、第 2 节）
- 代码入口未写可烧录主循环或实机参数（[code-first-principles-entry.md](../design/code-first-principles-entry.md) 第 2 节"未知"行）

**证据强度**：强。多文档交叉验证，未发现参数越界。

---

## 4. 驳回项（需修改）

**本次审查无驳回项。**

Codex 已完成 REVIEW-002 P1-01、P1-02、P2-01、P2-02 的修正，当前版本未发现新的接口冲突或安全漏洞。

---

## 5. 待机械组确认项

### 5.1 X/Y A4988 适配验证（延续 REVIEW-002 P2-03）

**定位**：[modular-pcb-design.md](../design/modular-pcb-design.md) 第 3.2 节、第 8 节 BOM 状态表  
**分类**：待机械组确认

**现状**：
- A4988 为 X/Y 候选模块位，PCB 可预留插座
- 文档明确"只有取得电机相电流、绕组参数、供电条件、微步/速度需求、工作周期、散热和急停行为，并通过空载、负载、堵转风险、温升、掉压、干扰与急停台架测试后，A4988 才可由'候选'转为'已确认'"（第 3.2 节最后一段）
- BOM 状态："候选"→"已确认"条件：冻结电机参数、核对模块实物针序、完成负载/热/干扰/急停台架验证（第 8 节）

**待确认**：
1. X/Y 步进电机具体型号、相电流、绕组电阻/电感
2. 运动工况：速度、加速度、负载、占空比、同时动作峰值
3. A4988 模块针序实物核对（不同厂商模块可能不同）
4. 限流设置、散热方案、急停后电机行为

**不阻断当前文档静态通过**：按 REVIEW-002 最终裁决，P2-03 不阻止无电机的协议、纯状态机与 fake HAL 开发，但继续阻止真实驱动适配冻结和实机放行。

---

### 5.2 第三运动通道执行器类型

**定位**：[modular-pcb-design.md](../design/modular-pcb-design.md) 第 3.3 节、[electrical-control-practical-hardware.md](../design/electrical-control-practical-hardware.md) 第 4 节功能表  
**分类**：待机械组确认

**现状**：
- 载板仅提供通用 STEP/DIR 控制/反馈接口
- 第三驱动器完全外接，不在载板上集成功率级
- 文档明确"若最终驱动器不是 STEP/DIR 接口，应通过更换外接适配线/小板或修订载板接口处理"

**待确认**：
1. 第三轴是步进、伺服、直线电机还是其他类型？
2. 是否为重力轴？如是，断电防坠方案是什么？
3. 负载、行程、速度要求
4. 控制接口是否确为 STEP/DIR，还是需要 CAN/RS485/模拟量？

---

### 5.3 挡板到位验证判据

**定位**：[stm32-state-machine-pseudocode.md](../design/stm32-state-machine-pseudocode.md) 第 3 节事件表、第 6 节 `PREPARE_BARRIER`  
**分类**：待机械组确认

**现状**：
- 状态机要求 `ServoBarrier.isAvoidPositionVerified()` 返回 `true` 才产生 `BARRIER_READY`
- 伪代码第 6 节 `PREPARE_BARRIER` 分支：`require(ServoBarrier.moveToAvoidPosition())` → `require(ServoBarrier.isAvoidPositionVerified())` → `emit(BARRIER_READY)`

**待确认**：
1. 挡板到位判据是：位置编码器反馈、独立传感器、电流/扭矩检测，还是延时后假定到位？
2. 如果是延时假定，是否满足赛规安全要求？
3. 四路挡板需要逐一验证还是联合验证？

**安全关注**：如果挡板未实际到位就放行运动，可能导致碰撞。建议采用可验证的到位判据（传感器或编码器），不建议仅用"发送 PWM 后延时"作为就绪证据。

---

### 5.4 限位数量、类型、位置

**定位**：[modular-pcb-design.md](../design/modular-pcb-design.md) 第 3.5 节、[electrical-control-practical-hardware.md](../design/electrical-control-practical-hardware.md) 第 4 节  
**分类**：待机械组确认

**现状**：
- PCB 预留可复制的限位输入单元，"数量、常态、电平、PNP/NPN/干接点类型和线长未定"
- 功能表："按机械布置预留"

**待确认**：
1. X/Y/第三轴各需几个限位（仅原点，还是原点+两端行程限位）？
2. 常开/常闭？PNP/NPN 还是干接点？
3. 24V/12V/5V 传感器？
4. 是否需要双限位冗余（安全关键轴）？

---

### 5.5 补光参数

**定位**：[electrical-control-practical-hardware.md](../design/electrical-control-practical-hardware.md) 第 4 节、`电控/资料/要求汇总.md` 第 6.3 节（已从确定值改为待参数，REVIEW-002 P2-01 已关闭）  
**分类**：待机械组 + 视觉组确认

**待确认**：
1. 补光颜色、形状（环形/条形/点阵）、安装位置
2. 工作电压、功率
3. 控制兼容性（3.3V GPIO 直接控制，还是需要驱动模块）
4. 曝光稳定时间（影响识别流程时序）

---

### 5.6 显示屏是否触摸

**定位**：接口契约未明确，赛题要求"显示屏"  
**分类**：待确认

**影响**：
- 如果是触摸屏，是否需要预留触摸反馈接口？
- 触摸操作是否进入控制链（不建议，但需明确排除）

**建议**：在接口契约或硬件文档中明确"显示屏仅用于显示，不接受触摸输入作为控制来源"。

---

## 6. 补充建议（非阻断）

### 6.1 测试可执行性优先级

**定位**：[code-first-principles-entry.md](../design/code-first-principles-entry.md) 第 6 节  
**建议**：采纳

测试 ID 清晰，但建议增加以下优先级标记，指导实施顺序：

**P0（第一批，协议方向与帧结构）**：
- `PROTO-DIR-001/002`：方向白名单
- `PROTO-FRAME-001/002`：帧往返与坏帧拒绝

**P1（第二批，状态机核心不变量）**：
- `SM-ONCE-001/002`：一件最多一次
- `SM-GATE-001/002`：下一件必须等待 `DISPLAY_ACK`
- `SM-EVENT-001/002`：四事件分离

**P2（第三批，安全边界）**：
- `SM-ESTOP-001`：急停锁定
- `SM-POWER-001`：动力许可检查
- `SM-TIME-001/002`：15秒不可续时
- `SM-RESET-001`：旧任务不可恢复

**P3（第四批，驱动适配骨架）**：
- `DRV-SKEL-001/002`：DIR 先于 STEP、故障传播

**P4（集成）**：
- `INTEG-HOST-001`：完整单件序列

**P5（实机，阻塞在机械参数后）**：
- `HIL-*` 全系列

---

### 6.2 协议实现与状态机实现的接口合约

**定位**：泳道 A 与泳道 B 的汇合点  
**建议**：采纳

建议在协议与状态机之间定义清晰的"领域事件"接口，例如：

```rust
// 伪代码示例，语言不限
enum DomainEvent {
    ItemTaskReceived { taskId, frameSeq, target, isFirstSeen: bool },
    DisplayAckReceived { taskId, frameSeq, targetSeq, crcMatch: bool, isFirstValid: bool },
    DuplicateFrame { taskId, frameSeq, cachedResponse },
    InvalidFrame { reason },
    // ...
}
```

这样协议层只负责"帧→领域事件"映射，状态机只消费领域事件，两者可独立测试且接口明确。

---

### 6.3 A4988 候选模块位的 DNP 标识

**定位**：[modular-pcb-design.md](../design/modular-pcb-design.md) 第 3.2 节、第 8 节  
**建议**：采纳

文档已明确 A4988 为候选，BOM 状态为"候选"。建议在 KiCad 原理图和 PCB 丝印上增加醒目的 **"CANDIDATE - DNP UNTIL VERIFIED"** 标识，避免装配时误以为已定型。

---

### 6.4 急停回路独立审查

**定位**：[electrical-control-practical-hardware.md](../design/electrical-control-practical-hardware.md) 第 3 节  
**建议**：强烈建议

文档多处强调"急停为独立硬件动力切断回路"，但当前文档中未包含急停回路的详细设计（接触器/继电器选型、线圈控制、触点容量、冗余、自检等）。

**建议**：
1. 由具有安全回路设计经验的人员（或外部专家）单独审查急停回路设计
2. 审查内容应包括：单点故障模式、触点粘连风险、线圈失效后状态、重力轴断电防坠与急停协调
3. 审查结论单独归档，不与软件/协议审查混同

---

### 6.5 15秒计时的时钟源

**定位**：[stm32-state-machine-pseudocode.md](../design/stm32-state-machine-pseudocode.md) 第 5 节  
**建议**：采纳

文档提到"单调时钟"，但未明确时钟源。建议在实施时明确：

- 使用 `HAL_GetTick()` 还是硬件定时器？
- 时钟精度要求（建议 ≤10ms）
- 溢出处理（STM32 `HAL_GetTick()` 约 49.7 天溢出）

---

## 7. 最终裁决

**文档静态审查：通过。**

当前版本已关闭 REVIEW-002 的 P1-01、P1-02、P2-01、P2-02，满足以下条件：

✅ A4988 候选身份不越界  
✅ 成熟模块与自制载板责任清楚  
✅ 第三运动通道、四路挡板、夹爪、限位、急停、补光、通信边界完整  
✅ `DISPLAY_ACK` 方向、内容校验（CRC32）和逐件放行门可一致实现  
✅ 硬件无关状态机与依赖参数的 STEP/DIR/HIL 层分离  
✅ 并行代码切入具有共同测试汇合点  

**仍然开放且不得被"静态通过"覆盖的事项**（与 REVIEW-002 一致）：

- 电机与执行器参数
- A4988 适配和故障覆盖（P2-03，待机械组确认）
- 电源/保护/线束/连接器/PCB 额定设计
- 探索者物理引脚映射
- 限位和重力轴安全
- 显示合规
- 15 秒实测预算
- ERC/DRC
- 台架和实机证据

**任何相应硬件动作仍须取得具体授权。**

---

## 8. 与 Codex 审查的对账

本次 Claude 审查与 REVIEW-002（Codex）在以下方面达成一致：

1. **总体裁决一致**：有条件通过，放行文档基线与无电机的协议/状态机/fake HAL 开发
2. **P1-01、P1-02、P2-01、P2-02 关闭确认**：Claude 独立验证修正有效
3. **P2-03 保持开放**：A4988 驱动故障覆盖待参数卡，不阻断文档静态通过
4. **核心不变量验证一致**：一件最多一次、下一件等待 `DISPLAY_ACK`、急停不可绕过、15秒不可续时
5. **未知参数边界一致**：未发现参数越界或候选升格

**无实质性分歧。**

---

## 9. 后续行动建议

1. **协议实现**：优先实现 `PROTO-DIR-001/002` 和 `PROTO-FRAME-001`，验证 `DISPLAY_ACK` 方向与 CRC32 计算一致性
2. **状态机实现**：并行实现纯状态机 + fake HAL，通过 `SM-ONCE-*`、`SM-GATE-*`、`SM-ESTOP-*` 测试
3. **机械参数收集**：推进第 5 节"待机械组确认项"，填写参数卡
4. **急停回路独立审查**：在任何实机上电前完成
5. **A4988 适配验证**：取得电机参数后，按 PCB 文档第 3.2 节要求完成台架验证
6. **HIL 准备**：在机械参数到位后，按代码入口第 6.2 节顺序进入实机测试

---

**审查完成。本文件追加到 `.claude/reviews/`，不覆盖 REVIEW-002。**
