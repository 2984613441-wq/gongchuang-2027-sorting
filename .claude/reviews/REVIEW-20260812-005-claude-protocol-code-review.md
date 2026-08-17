# 协议代码独立审查报告 REVIEW-20260812-005

> 审查者：Claude Opus 4.8  
> 审查日期：2026-08-12  
> 审查类型：只读独立审查，不修改生产代码  
> 审查范围：协议 V0.3 冻结子集的 Python 实现

---

## 1. 审查范围

本轮审查仅针对**已冻结的协议 V0.3 子集**，不包括：
- 外层帧编码（帧头、外层CRC-16未冻结）
- UART 驱动实现
- 完整状态机
- 树莓派或STM32固件

### 1.1 实际读取文件清单

| 文件 | 版本/状态 | 读取确认 |
|------|----------|---------|
| `docs/design/interface-contract.md` | V0.3 | ✅ 251行，2026-08-12 |
| `docs/design/code-first-principles-entry.md` | — | ✅ 177行 |
| `.claude/tasks/TASK-20260812-002-protocol-implementation.md` | 实施记录 | ✅ 148行，含TDD证据 |
| `电控/src/electrical_control/protocol/codec.py` | 生产代码 | ✅ 26行 |
| `电控/src/electrical_control/protocol/types.py` | 生产代码 | ✅ 58行 |
| `电控/src/electrical_control/protocol/errors.py` | 生产代码 | ✅ 18行 |
| `电控/src/electrical_control/protocol/direction.py` | 生产代码 | ✅ 22行 |
| `电控/src/electrical_control/protocol/display_ack.py` | 生产代码 | ✅ 110行 |
| `电控/tests/protocol/test_protocol_contract.py` | 测试代码 | ✅ 182行，14个测试 |

---

## 2. 总体裁决

**✅ 有条件通过**

**通过理由**：
- 方向矩阵严格符合接口契约V0.3
- CRC32算法、测试向量和字节序正确
- 反方向消息在生成领域事件前被拒绝
- 职责分离清晰（codec ≠ context validator）
- 未猜写任何未冻结参数
- 14项自动化测试通过，包含反例覆盖

**条件**：
1. **P0阻塞项**：`image_id` 和 `success_count` 的传递路径未冻结，影响STM32实际使用CRC校验（见3.1节）
2. **P1建议项**：需补充独立CRC32实现对照测试（见3.2节）

**不通过的情况将是**：
- 方向矩阵与契约不一致
- CRC32算法错误
- 存在未冻结参数的硬编码默认值

---

## 3. 发现清单

### 3.1 P0 发现（阻塞正式显示闭环）

#### P0-001：显示内容期望值传递路径未冻结

**事实**：
- `DISPLAY_ACK` 的CRC32需要校验五个字段：`target_seq + class_id + image_id + success_count + result_code`
- 接口契约V0.3第165行明确规定"这些字段必须与本件 `ITEM_RESULT` 一致"
- 当前 `ITEM_TASK` (0x21) 只定义了：`目标序号 + 类别ID + X坐标 + Y坐标 + 抓取角度`（契约125-130行）
- `ITEM_RESULT` (0x23) 只定义了：`目标序号 + 结果码 + 依据`（契约133-151行）

**推断**：
- STM32需要知道 `image_id` 和 `success_count` 才能验证树莓派发来的 `DISPLAY_ACK`
- 当前冻结的消息格式中，这两个字段没有传递给STM32

**证据定位**：
- `display_ack.py:74-83` decode函数要求 `expected_content: DisplayContent`
- `display_ack.py:25-30` DisplayContent包含五个字段
- 但接口契约未冻结如何将这五个字段传给STM32

**影响**：
- 协议代码可以通过主机测试（因为测试显式注入expected_content）
- 但真实STM32固件无法实现CRC校验（缺少两个期望值）
- 正式显示确认闭环被阻塞

**建议方案（三选一，需用户裁决）**：

**方案A（推荐）**：在 `ITEM_TASK` 中增加 `image_id` 字段
```
当前：目标序号 + 类别ID + X + Y + 角度
修改：目标序号 + 类别ID + image_id + X + Y + 角度
```
- 优点：树莓派在下发任务时就告知STM32"本件应显示哪张图"
- 缺点：需修改 `ITEM_TASK` 载荷格式（但该格式尚未实现）

**方案B**：让STM32只校验 `target_seq + result_code`，不校验 `image_id + class_id + success_count`
```
缩减CRC输入：target_seq + result_code（2字节）
```
- 优点：不需要新消息
- 缺点：CRC保护力度降低，无法防止树莓派显示了错误图片/类别

**方案C**：引入新消息 `DISPLAY_EXPECT` (STM32→树莓派) 或扩展 `ITEM_RESULT`
```
ITEM_RESULT扩展：目标序号 + 结果码 + 依据 + image_id + class_id
```
- 优点：保持 `ITEM_TASK` 不变
- 缺点：需新增消息或扩展已部分冻结的 `ITEM_RESULT`

**当前状态**：
- 代码实现预留了接口（`expected_content`参数）
- 测试通过但依赖显式注入
- **阻塞实机显示闭环，不阻塞主机测试和状态机开发**

**建议决策流程**：
1. 用户选择方案A/B/C
2. 更新接口契约至V0.4
3. 更新协议代码和测试
4. 重新审查

---

### 3.2 P1 发现（增强可信度）

#### P1-001：建议补充独立CRC32实现对照测试

**事实**：
- 当前实现使用 `zlib.crc32()` （display_ack.py:21）
- 测试也使用同一实现验证（test_protocol_contract.py:34）
- 存在"实现和测试犯同一种错误"的理论风险

**推断**：
- Python `zlib.crc32` 是C实现，广泛使用，极不可能错误
- 但跨语言实现（Python ↔ C/STM32固件）时可能出现参数理解偏差

**建议**：
补充以下任一验证：
1. 使用独立CRC32库（如 `crcmod`）对照测试
2. 使用在线CRC计算器手工验证 `01 02 03 04 05 → 0x470B99F4`
3. 在任务记录中明确记录"已通过独立工具验证"

**证据**：
- 已知测试向量通过（test_protocol_contract.py:31-37）
- 但验证工具与实现工具相同

**风险等级**：低（Python zlib是标准库）

**建议采纳条件**：如STM32固件实现CRC32时出现不匹配，优先执行此项

---

#### P1-002：测试覆盖反例完整，但缺少边界用例

**事实**：
- 当前测试覆盖：
  - ✅ 方向正确/反向（PROTO-DIR-001/002）
  - ✅ CRC错误、字段错序、字节序错误（各项DisplayAckPayloadTests）
  - ✅ 非RENDERED状态拒绝（test_non_rendered_result_is_not_a_valid_display_ack）
  - ✅ 错误目标序号拒绝（test_wrong_target_is_rejected）

**推断**：
- 缺少以下边界测试：
  1. `target_seq=0` 是否合法（若0是保留值）
  2. `target_seq=255` 边界
  3. 五字段中某一字段为0的合法性
  4. 载荷长度不足6字节的各种截断情况
  5. 载荷长度超过6字节的情况

**建议**：
补充边界测试用例：
```python
def test_target_seq_boundary_values(self):
    # 测试0和255是否合法
    for seq in [0, 255]:
        content = DisplayContent(seq, 2, 3, 4, 5)
        # ... 验证接受或拒绝的预期行为

def test_payload_length_validation(self):
    # 测试截断和超长
    self.assertRaises(PayloadError, decode_display_ack_payload, b"\x01\x00\x47")  # 太短
    self.assertRaises(PayloadError, decode_display_ack_payload, b"\x01\x00\x47\x0B\x99\xF4\xFF")  # 太长
```

**风险等级**：低（当前实现有明确长度检查，display_ack.py:62）

---

### 3.3 P2 发现（非阻塞，文档与未来改进）

#### P2-001：`parse_display_ack_payload` 函数命名导出可能引起混淆

**事实**：
- `display_ack.py:109` 定义 `parse_display_ack_payload = _parse_display_ack_payload`
- `_parse_display_ack_payload` 是无上下文校验的版本（display_ack.py:61）
- `decode_display_ack_payload` 是有上下文校验的版本（display_ack.py:71）
- `ProtocolCodec.to_validated_message` 调用 `parse_display_ack_payload`（codec.py:18）

**推断**：
- 职责分离正确：codec用无校验版本，context validator用有校验版本
- 但函数名 `parse` vs `decode` 的语义区别不明显

**建议**：
- 当前实现可接受（职责正确）
- 未来重构时考虑更清晰的命名，如：
  - `parse_display_ack_wire_format()` - 纯解析
  - `validate_display_ack_context()` - 上下文校验

**风险等级**：极低（不影响功能）

---

#### P2-002：未来需补充帧去重和序号管理测试

**事实**：
- 当前协议代码只处理单帧解析
- 帧去重、序号管理、缓存响应属于状态机职责
- 接口契约V0.3第220-225行定义了幂等与去重规则

**推断**：
- 协议层职责边界清晰（不应包含去重）
- 但状态机实现时需要补充测试

**建议**：
在状态机测试中补充：
- `SM-ONCE-001`：重复 `(taskId, frameSeq)` 只执行一次
- `SM-GATE-002`：重复 `DISPLAY_ACK` 不重复消费

**当前状态**：不影响协议代码审查

---

## 4. 逐项检查结果

| 检查项 | 契约要求 | 实现位置 | 结果 |
|--------|---------|---------|------|
| 1. BARRIER_READY/MOTION_DONE/ITEM_RESULT 方向 | 仅STM32→树莓派 | direction.py:8-10 | ✅ 通过 |
| 2. DISPLAY_ACK 方向 | 仅树莓派→STM32 | direction.py:11 | ✅ 通过 |
| 3. 反方向拒绝时机 | 生成领域事件前 | codec.py:13, direction.py:15-21 | ✅ 通过 |
| 4. CRC32 算法 | CRC-32/ISO-HDLC | display_ack.py:18-21 | ✅ 通过 |
| 5. 规范输入字段 | 目标序号+类别ID+图片ID+累计成功数+结果码 | display_ack.py:32-41 | ✅ 通过 |
| 6. 测试向量 01..05 | 0x470B99F4, 网络序 47 0B 99 F4 | test_protocol_contract.py:32-37,79-86 | ✅ 通过 |
| 7. 错误拒绝 | CRC错/字段错序/小端/非RENDERED/错目标 | test_protocol_contract.py:88-118 | ✅ 通过 |
| 8. 职责分离 | Codec无状态，Validator有上下文 | codec.py:12-25, display_ack.py:86-106 | ✅ 通过 |
| 9. 未冻结参数 | 不得写入帧头/外层CRC16/波特率等 | 全部源文件检查 | ✅ 通过 |
| 10. 测试同源错误风险 | 实现和测试使用不同依据 | zlib.crc32同时用于实现和测试 | ⚠️ P1-001 |

---

## 5. 事实、推断与未知分类

### 5.1 事实（已验证）

| 事实 | 证据位置 | 可信度 |
|------|---------|--------|
| 方向矩阵符合契约V0.3 | direction.py:7-12, 接口契约88-94行 | 强 |
| CRC32使用ISO-HDLC标准 | display_ack.py:18-21, Python zlib文档 | 强 |
| 测试向量正确 | test_protocol_contract.py:32-37 | 强 |
| 14项测试全部通过 | TASK-002任务记录10.1节 | 强 |
| 未写入未冻结参数 | grep搜索确认无帧头/波特率等 | 强 |
| 职责分离清晰 | codec.py与display_ack.py的类分离 | 强 |

### 5.2 推断（合理但需验证）

| 推断 | 依据 | 验证方式 |
|------|------|---------|
| image_id/success_count需通过ITEM_TASK传递 | 逻辑推导 | 用户裁决协议修改方案 |
| Python zlib.crc32实现正确 | 标准库广泛使用 | 可选：独立工具对照 |
| 边界值(0/255)应合法 | 单字节无符号范围 | 补充边界测试 |

### 5.3 未知（需外部输入）

| 未知项 | 阻塞范围 | 决策者 |
|--------|---------|--------|
| image_id/success_count传递方案 | 实机显示闭环 | 用户 |
| target_seq=0是否为保留值 | 边界测试设计 | 协议设计者 |
| 帧头、外层CRC16具体值 | 完整外层帧实现 | 后续任务 |

---

## 6. 建议分类与采纳指引

### 6.1 强烈建议采纳

| 编号 | 建议 | 理由 | 成本 |
|------|------|------|------|
| A-001 | 冻结 image_id/success_count 传递路径 | 阻塞实机显示闭环 | 协议修改+代码修改 |

### 6.2 建议采纳

| 编号 | 建议 | 理由 | 成本 |
|------|------|------|------|
| B-001 | 补充独立CRC32对照验证 | 降低跨语言实现风险 | 低（使用在线工具即可） |
| B-002 | 补充边界值测试 | 提升测试覆盖完整性 | 低（5-10个测试用例） |

### 6.3 可选采纳

| 编号 | 建议 | 理由 | 成本 |
|------|------|------|------|
| C-001 | 重命名parse/decode函数 | 语义更清晰 | 低（未来重构时） |

### 6.4 待确认

无。所有建议均有明确采纳或不采纳的判断依据。

---

## 7. 测试缺口

### 7.1 已覆盖

- ✅ 方向正确性与反向拒绝（PROTO-DIR-001/002）
- ✅ CRC32正确性与错误拒绝（已知向量、错误CRC、错序）
- ✅ 字节序正确性（网络序 vs 小端）
- ✅ 渲染状态校验（RENDERED vs 非RENDERED）
- ✅ 目标序号匹配
- ✅ 载荷长度校验（display_ack.py:62明确检查）
- ✅ 领域事件边界（Message vs Event分离）

### 7.2 未覆盖（建议补充）

| 缺口 | 示例用例 | 优先级 |
|------|---------|--------|
| 边界值 | target_seq=0, 255 | P1 |
| 五字段边界 | class_id=0, result_code=255 | P2 |
| 独立CRC实现对照 | 使用crcmod或在线工具 | P1 |
| 帧去重（状态机层） | 重复(taskId, frameSeq) | P0（状态机任务） |

### 7.3 不需要覆盖

- ❌ UART物理层（不在协议代码范围）
- ❌ 完整外层帧（帧头/外层CRC16未冻结）
- ❌ 超时重传（属于状态机层）

---

## 8. 与接口契约V0.3的逐项对照

| 契约章节 | 要求 | 实现位置 | 符合性 |
|---------|------|---------|--------|
| 4.3 调度链命令 | BARRIER_READY等仅STM32→树莓派 | direction.py:8-10 | ✅ |
| 4.3 调度链命令 | DISPLAY_ACK仅树莓派→STM32 | direction.py:11 | ✅ |
| 5.5 DISPLAY_ACK | 渲染结果0x00=RENDERED | display_ack.py:78,96 | ✅ |
| 5.5 DISPLAY_ACK | CRC32使用ISO-HDLC | display_ack.py:18-21 | ✅ |
| 5.5 DISPLAY_ACK | 规范输入五字段 | display_ack.py:32-41 | ✅ |
| 5.5 DISPLAY_ACK | 测试向量0x470B99F4 | test_protocol_contract.py:32-37 | ✅ |
| 5.5 DISPLAY_ACK | 网络字节序 | display_ack.py:58 | ✅ |
| 5.5 DISPLAY_ACK | 匹配任务号/目标序号/CRC | display_ack.py:79-82,97-100 | ✅ |
| 7. 幂等与去重 | (taskId, frameSeq)判重 | 🔄 状态机职责 | N/A |

**结论**：已实现部分与契约V0.3完全一致；未实现部分符合"仅冻结子集"的范围声明。

---

## 9. 代码质量评估

### 9.1 优点

1. **职责分离清晰**：
   - `ProtocolCodec`：无状态线路解析
   - `DisplayAckContextValidator`：有状态上下文校验
   - 不混淆"收到消息"与"可执行事件"

2. **类型安全**：
   - 使用 `dataclass(frozen=True, slots=True)`
   - 使用 `IntEnum` 而非魔数
   - 函数签名明确（type hints）

3. **错误处理明确**：
   - 三种错误类型：`DirectionError`, `PayloadError`, `ContractNotFrozen`
   - 错误消息包含具体原因

4. **测试驱动**：
   - 有RED/GREEN证据（TASK-002记录）
   - 测试先于实现
   - 反例覆盖充分

5. **未冻结参数隔离**：
   - 使用 `ContractNotFrozen` 异常明确标注
   - Frame类不包含二进制编码细节
   - 注释明确声明外层帧未实现

### 9.2 可改进点

1. **文档注释**：
   - 建议补充模块级docstring说明设计约束
   - `DisplayContent.canonical_bytes()` 建议补充字段顺序说明

2. **边界条件**：
   - 建议补充0/255边界值测试

3. **独立验证**：
   - 建议补充CRC32独立工具对照

---

## 10. 独立性声明

### 10.1 独立性级别

**✅ 独立审查（非弱独立性）**

### 10.2 独立性依据

1. **审查者与实现者分离**：
   - 实现者：Codex（根据TASK-002记录）
   - 审查者：Claude（本报告）
   - 无共享上下文或协同编码

2. **时间分离**：
   - 实现完成时间：2026-08-12（TASK-002记录）
   - 审查时间：2026-08-12（本报告）
   - 审查在实现完成后独立进行

3. **信息分离**：
   - 审查仅基于已交付文件
   - 未参与实现过程讨论
   - 未提前知晓实现细节

4. **输出分离**：
   - 审查结果写入独立文件（本文件）
   - 不修改生产代码或测试
   - 建议需由实现者对账采纳

### 10.3 潜在独立性限制

1. **模型族限制**：
   - Claude和Codex均为AI模型
   - 共享部分训练数据和编程范式
   - 可能存在相同的"思维盲区"

2. **工具限制**：
   - 未运行实际测试（只读取测试代码和运行记录）
   - 未使用独立CRC32工具验证

3. **领域知识限制**：
   - 审查者和实现者都具有协议和Python知识
   - 不构成"外行审查专家"的独立性

### 10.4 风险缓解

- ✅ 建议P1-001补充独立CRC实现对照
- ✅ 在P0-001发现协议级阻塞项（非代码错误）
- ✅ 要求用户裁决而非自行修改

---

## 11. 审查结论与下一步

### 11.1 可以继续的工作

以下工作**不受协议代码审查阻塞**：
- ✅ 纯状态机设计与fake HAL测试（使用`DisplayAckReceived`事件）
- ✅ STEP/DIR适配骨架与fake pulse测试
- ✅ 主机侧集成测试（协议→状态机→fake HAL）

### 11.2 被阻塞的工作

以下工作**必须等待P0-001解决**：
- ❌ STM32固件的`DISPLAY_ACK` CRC校验实现
- ❌ 实机显示确认闭环测试
- ❌ 树莓派发送`DISPLAY_ACK`的正式实现

### 11.3 建议决策流程

```
1. 用户阅读本审查报告
   ↓
2. 用户裁决P0-001的三个方案（A/B/C）
   ↓
3. 更新接口契约至V0.4
   ↓
4. Codex修改协议代码和测试
   ↓
5. Claude重新审查修改部分
   ↓
6. 解除实机显示闭环阻塞
```

### 11.4 并行工作建议

在等待P0-001决策期间：
1. 状态机团队：继续fake HAL测试，假设`expected_content`会通过某种方式提供
2. 驱动团队：继续STEP/DIR骨架，不受协议影响
3. 协议团队：补充P1-001（CRC对照）和P1-002（边界测试）

---

## 12. 审查签名

| 项目 | 内容 |
|------|------|
| 审查者 | Claude Opus 4.8 |
| 审查日期 | 2026-08-12 |
| 审查范围 | 协议V0.3冻结子集（Python实现） |
| 审查方式 | 只读独立审查 |
| 文件数量 | 9个文件（生产6+测试1+文档2） |
| 代码行数 | ~234行生产代码，182行测试代码 |
| 测试用例 | 14个自动化测试 |
| 发现数量 | P0: 1个, P1: 2个, P2: 2个 |
| 总体裁决 | ✅ 有条件通过 |
| 独立性 | ✅ 独立审查 |

---

**本审查报告结束。等待用户裁决P0-001后继续。**
