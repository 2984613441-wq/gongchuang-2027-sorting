# 应答帧（RESEND / 重传应答）定义推荐方案

> 版本：V0.1（方案提案）
> 日期：2026-08-29
> 状态：**只读分析 + 方案文档，未实施、未改任何生产代码、未提交 git**
> 范围：电控（STM32 C 网关）+ 视觉/树莓派（RPi 出站/入站）两侧的"应答帧"语义与 RESEND/重传落地方案
> 依据文档：`docs/design/interface-contract.md`（V0.6）、`docs/design/stm32-state-machine-pseudocode.md`（V0.2）、`docs/design/2026-08-25-item-task-codec-handoff.md`、`docs/design/2026-08-25-rpi-pre-hardware-freeze-list.md`、`docs/design/2026-08-29-host-side-chain-interfaces.md`，以及 `电控/stm32_logic/`（ec_state_machine.c / ec_protocol_gateway.c / ec_dedup.h / ec_protocol.h）、`电控/src/electrical_control/`（rpi/outbound.py、rpi/gateway.py、rpi/__init__.py、state_machine/core.py、protocol/display_ack.py、protocol/item_context.py、protocol/types.py）

---

## 0. 背景：用户三问与本方案的三个产出

| # | 用户原问 | 对应章节 | 一句话结论 |
|---|---------|---------|-----------|
| ① | "应答帧定义是不是图像的应答帧（DISPLAY_ACK）？" | §1（问题 A） | **不是**。DISPLAY_ACK(0x25) 是树莓派渲染完成后的**事件确认**；通用 ACK(0x05)/NACK(0x06) 才是对请求的**应答帧** |
| ② | "视觉中不是有三个参数吗？" | §2（问题 B） | 视觉/ITEM_TASK 的三个身份参数 = **target_seq / class_id / image_id**（DisplayContent 前三字段），它们参与"重传应答"的判重与 DISPLAY_ACK 期望 CRC 重建 |
| ③ | "看一下应答帧有无推荐，要包含电控视觉两份方面" | §3（问题 C，电控）/ §4（问题 D，视觉） | 有推荐：C 网关补齐 RESEND 执行者 + 旧帧/乱序 NACK + 按身份响应缓存；视觉侧现状已判重幂等、无需主链改动，仅建议可选增强 |

> 编号说明：用户原话提到的"接口契约 §6.3 已定义行为"，在 interface-contract.md **V0.6 中对应 §7 幂等与去重规则第 2 条**（Line 250："重复帧 → 重发上次应答，**不得重复执行运动或投放**"）及 §4.1 命令表（ACK 0x05 / NACK 0x06 含原因码）。§6.3 疑为旧版/口误编号，语义相同；下文统一以 V0.6 实际编号引用。

---

## 1. 问题 A："应答帧" ≠ DISPLAY_ACK（概念澄清）

### 1.1 结论

- **通用应答帧 = ACK(0x05) / NACK(0x06)**（interface-contract §4.1，L0 基础命令，双向）：ACK 为通用肯定应答；NACK 为通用否定应答，**含原因码**。它们是"接收方对请求帧的应答"。
- **DISPLAY_ACK(0x25)**（interface-contract §4.3/§5.5）是树莓派**在本件界面实际完成渲染后**才发送的"事件确认"，方向固定为 树莓派→STM32，语义是"本件画面已真实渲染完毕"，不是对任何请求的应答。
- 两者的根本区别：**应答帧回答"你的请求我收到了/拒了"；DISPLAY_ACK 报告"我完成了一个动作（渲染）"**。

### 1.2 协议层面区分表

| 维度 | ACK 0x05（通用肯定应答） | NACK 0x06（通用否定应答） | DISPLAY_ACK 0x25（渲染事件确认） |
|------|--------------------------|---------------------------|----------------------------------|
| 方向 | 双向 | 双向 | **固定 树莓派→STM32** |
| 语义 | 对请求帧的肯定应答（已接受/已消费） | 对请求帧的否定应答，含原因码 | 树莓派**实际完成渲染**的事件确认 |
| 触发时机 | 收到请求帧、判定可接受后 | 收到请求帧、判定拒绝后 | 渲染真正完成、界面可见后（不得在收到 ITEM_RESULT/开始渲染时提前发） |
| 是否放行下一件 | 否 | 否 | **是**（首个、有效、匹配的 RENDERED 才放行；interface-contract §5.5、§6） |
| 重复帧处理 | 重复请求 → 重发上次应答（§7.2） | 重复请求 → 重发上次应答 | 重复 ACK → 仅重发状态，不二次消费（状态机伪代码 §3） |
| 载荷 | 契约未冻结（本文 §3.3 给推荐值，见未决项 E-1） | "含原因码"，枚举未冻结（推荐值见 §3.3 / E-2） | **已冻结 6 字节**：target_seq(1) + render_result(1) + display_crc32(4)，CRC32 输入为五字段规范字节序（§5.5） |
| 误用后果 | 不涉及放行，无安全后果 | 同左 | 误用会绕过"渲染完成才能下一件"的赛题闭环 |

### 1.3 证据出处（文档原文定位）

- interface-contract.md §4.1（Line 68-75）：`0x05 ACK 双向 通用肯定应答`、`0x06 NACK 双向 通用否定应答，含原因码`。
- interface-contract.md §4.3（Line 95）：`0x25 DISPLAY_ACK 树莓派→STM32 树莓派在本件界面实际完成渲染后发送；STM32 收到匹配确认后才允许下一件`。
- interface-contract.md §5.5（Line 180-199）：DISPLAY_ACK 只能在**实际完成渲染后**发送；CRC32 输入 `目标序号 + 类别 ID + 图片 ID + 累计成功数 + 结果码`，金标向量 `01 02 03 04 05 → 0x470B99F4`。
- interface-contract.md §7.2（Line 250）：`重复帧 → 重发上次应答，不得重复执行运动或投放`。

---

## 2. 问题 B：视觉三参数 = target_seq / class_id / image_id

### 2.1 结论

"视觉中的三个参数" = **ITEM_TASK 载荷的身份三字段 `target_seq(1) + class_id(1) + image_id(1)`**（interface-contract §5.2 冻结的 8 字节载荷前三字节），同时也是 **DisplayContent（DISPLAY_ACK 内容 CRC 输入）的前三字段**（display_ack.py `DisplayContent.target_seq/class_id/image_id`）。

| 参数 | 来源 | 语义 | 冻结约束 |
|------|------|------|---------|
| `target_seq` 目标序号 | MaixCAM 视觉管线（`VisionTarget.target_seq`，1..255） | 本轮内单件序号 | ITEM_TASK 载荷第 1 字节 |
| `class_id` 类别 ID | YOLO 识别（active 集 `{0,2,3,4,5,6}`） | 货物类别 | ITEM_TASK 载荷第 2 字节 |
| `image_id` 图片 ID | **树莓派**在创建本件任务时确定（`image_id_for_class` 映射，TF 卡按 image_id 索引） | 显示用图片索引 | `image_id == class_id`，1:1；ITEM_TASK 载荷第 3 字节 |

### 2.2 三参数如何参与"重传应答"与 DISPLAY_ACK

**（1）参与"重传应答"的判重（谁是重复帧）：**

- 外层判重键 = `(task_id, frame_seq)`（interface-contract §7.1；Pi 侧入站 `PiProtocolGateway._inbound_cache` 同键）。
- 载荷级区分 = C 侧 `payload_fingerprint`：`ec_dedup_key_t = (task_id, frame_seq, payload_fingerprint)`，其中 fingerprint 取整帧载荷的 CRC32（ec_protocol_gateway.c Line 91-92）。三参数是载荷的前三字节，**同 (task_id, frame_seq) 而三参数不同 → 载荷指纹不同 → `EC_DEDUP_CONFLICT` → FAULT_LOCK**（interface-contract §5.2："相同 (任务号, 目标序号) 若携带不同载荷，视为协议冲突并进入故障，不得运动"）。**冲突不是"重发"，是故障**。
- 状态机上下文匹配 `matches_current_context` 比较完整 identity（ec_state_machine.c Line 22-28），三参数随 `current_item` 锁存（`g->item_target_seq/class_id/image_id`）。

**（2）参与 DISPLAY_ACK 期望 CRC 重建（已冻结五字段）：**

- STM32 用锁存的 `target_seq/class_id/image_id` + 本地 `success_count` + 当前 `item_result_code`，按规范字节序 `target_seq + class_id + image_id + success_count + result_code` 计算期望 CRC32（interface-contract §5.5/§6.1；C 侧 `ec_proto_display_content_crc32`，金标 `01 02 03 04 05 → 0x470B99F4`）。
- 树莓派侧同一算法（`DisplayContent.canonical_bytes()/crc32`），两端必须得到相同期望值；三参数不一致 → CRC 校验失败 → STM32 不放行（且本方案建议回 NACK，见 §3.4）。

**（3）视觉链（MaixCAM↔树莓派）本身不产生应答帧：**

- 视觉链命令 `BATCH_TARGETS(0x10)/TARGET_REACQUIRE_REQ(0x11)/TARGET_REACQUIRE_RSP(0x12)/DIAG_SCAN(0x13)` 的线格式**未冻结**（interface-contract §5.1 标注 [待定]；vision_ingest.py 明确"logical layer, never emits serial frame"）。
- 三参数由视觉管线产出（target_seq、class_id）并由树莓派补全（image_id），进入的是**调度链逻辑层**（RPi Scheduler → OutboundGateway → STM32），不涉及视觉串口上的应答帧。视觉侧本轮无应答帧义务（见 §4）。

---

## 3. 问题 C：电控侧推荐方案（STM32 C 网关实现 RESEND）

> 定位声明：**本方案是"实现接口契约已定义的行为"，不是新协议**——命令字 ACK(0x05)/NACK(0x06) 已在 §4.1 定义；"重复帧→重发上次应答、不得重复执行运动或投放"已在 §7 定义；"重复 ITEM_TASK | 若 (taskId, frameSeq) 已处理，重发原 ACK/最后状态，绝不再次抓放或重新计数""旧帧/乱序 → 丢弃或 NACK""重复 DISPLAY_ACK → 仅重发状态"已在状态机伪代码 §3（Line 72-77）与 §8（Line 273-277）定义。**唯一"新"内容**是 ACK/NACK 载荷的字节布局与 NACK 原因码枚举（契约未冻结，列为未决项 E-1/E-2，需拍板后冻结）。

### 3.1 现状盘点与缺口（只读分析结论）

| 组件 | 现状 | 缺口 |
|------|------|------|
| `ec_state_machine.h` | 已有动作位 `EC_ACTION_RESEND_CACHED_RESPONSE`（bit10）与 `EC_ACTION_REJECT_NEW_TASK`（bit11） | — |
| `ec_state_machine.c` | 已设置 RESEND：①非 WAIT_TASK 状态收到与当前件同身份的 ITEM_TASK（Line 110-114）；②dedup 判定 DUPLICATE（Line 122-123）。已设置 REJECT_NEW_TASK：非当前上下文/轮次不匹配（Line 114/117） | **无"旧序号/乱序"顺序门**：C 侧没有 `last_accepted_frame_seq` 检查（Python 主机模型 `state_machine/core.py` Line 266-271 有；伪代码 `isOldOrOutOfOrder → NACK(STALE_OR_ORDER)` 有），旧但未见过的 frame_seq 会被当新帧处理 |
| `ec_protocol_gateway.c` `consume_and_emit`（Line 41-59） | 只物化 `EMIT_BARRIER_READY / EMIT_MOTION_DONE / EMIT_ITEM_RESULT` 三帧 | **RESEND_CACHED_RESPONSE 与 REJECT_NEW_TASK 无执行者**（动作位产生后无任何出站帧）；重复 ITEM_TASK 后 `tx_command` 为 0xFF（测试 C-GW-FRAME-002 只断言动作位） |
| `ec_protocol_gateway.c` `handle_item_task`（Line 61-111） | 接受新件时**不发射任何 ACK**（伪代码基线 `cacheAck(frame, ACCEPTED)` 未实现）；成功后锁存三参数 | 无 ACK(ACCEPTED) |
| `ec_protocol_gateway.c` `handle_display_ack`（Line 113-157） | 首个有效 DISPLAY_ACK → `WAIT_DISPLAY_ACK → PREPARE_BARRIER`，放行下一件；重复 ACK 落入 PREPARE_BARRIER/后续状态被**静默忽略**（安全，但不回状态）；无效/不匹配 ACK 也是静默忽略 | 无 ACK(ACK_CONSUMED)、无"重复 ACK 仅重发状态"执行、无 NACK(ACK_NOT_APPLICABLE) |
| `ec_protocol.h` | 已有 `EC_CMD_ACK 0x05 / EC_CMD_NACK 0x06` 常量 | **无 ACK/NACK 载荷编解码函数**（载荷布局未冻结） |

**结论**：状态机已经"想"重发（动作位齐全），网关没有"手"去发（执行者缺失）；这就是本方案要解决的缺口。其余（顺序门、ACK 应答、NACK 执行者）是契约/伪代码基线已定义、C 侧尚未落地的部分。

### 3.2 设计原则

1. **唯一状态来源**：RESEND/REJECT 的判定仍由状态机给出（动作位），网关只负责执行；避免网关自行判重导致与 dedup 冲突判定（CONFLICT→FAULT_LOCK）打架。
2. **原样重放**：重发 = 重放首次处理该身份时缓存的**原始帧字节**（含 CRC），不递增 `tx_seq`。理由：Pi 侧入站按 `(task_id, frame_seq)` 判重（`PiProtocolGateway._inbound_cache`），原样重放会命中 Pi 的"DUPLICATE→缓存应答"路径；若换新 frame_seq 重发，Pi 会视为新帧重新派发——对 MOTION_DONE/ITEM_RESULT 等在错误状态的重放有 FAULT 风险。
3. **fail-closed 优先**：任何"无法证明幂等"的分支宁可**不发射、不执行、记日志**，绝不编造新响应。
4. **不续 15 秒**：RESEND/NACK/ACK 全部是非可观察事件，不得更新 `lastObservableAt`（状态机伪代码 §5）。
5. **窗口一致**：响应缓存与 dedup 缓存同容量、同清除时机、每身份写一次。

### 3.3 字段级设计（推荐值，待冻结项见 §5）

#### 3.3.1 ACK 载荷（推荐 2 字节；契约未冻结 → E-1）

```
┌──────────┬──────────┐
│ 应答原因  │ 目标序号  │
│ 1 byte   │ 1 byte   │
└──────────┴──────────┘
```

| 字段 | 值 | 说明 |
|------|----|------|
| 应答原因 | `0x00 = ACCEPTED`（ITEM_TASK 已接受）；`0x01 = ACK_CONSUMED`（DISPLAY_ACK 已消费） | 与伪代码 `cacheAck(frame, ACCEPTED)` / `cacheAck(frame, ACK_CONSUMED)` 同名对齐 |
| 目标序号 | ACK(ACCEPTED) = 该件的 `item.target_seq`；ACK(ACK_CONSUMED) = 该 ACK 的 `ack.target_seq` | 回显件身份，便于树莓派关联应答属于哪一件 |

#### 3.3.2 NACK 载荷（推荐 2 字节；枚举未冻结 → E-2）

```
┌──────────┬──────────┐
│ 原因码    │ 目标序号  │
│ 1 byte   │ 1 byte   │
└──────────┴──────────┘
```

| 原因码 | 名称 | 触发场景（与伪代码对齐） |
|-------|------|------------------------|
| `0x10` | `STALE_OR_ORDER` | 旧帧/乱序：`frame_seq <= last_accepted_frame_seq` 或轮次不符（新增顺序门后） |
| `0x11` | `UNEXPECTED_MESSAGE` | 非本状态期望的消息类型 |
| `0x12` | `SINGLE_TASK_ONLY` | 已有活动件时收到新 ITEM_TASK（伪代码 `activeTask != NONE`） |
| `0x13` | `ACK_NOT_APPLICABLE` | DISPLAY_ACK 不匹配当前件/已消费/内容校验失败（伪代码 `isFirstValidDisplayAck` 不成立） |
| `0x14` | `WRONG_ROUND` | 任务号与当前轮次不匹配 |
| `0x15` | `TASK_REJECTED` | 通用拒绝（如 `success_count==255` 拒收新件、解码语义失败） |

目标序号：可回显时回显（ITEM_TASK 场景为 `item.target_seq`），不可得时 `0xFF`。

#### 3.3.3 响应缓存（与 dedup 同窗口）

```c
typedef struct {
    ec_dedup_key_t key;                 /* (task_id, frame_seq, payload_fingerprint) */
    uint8_t frame[EC_GATEWAY_TX_MAX];   /* 首次处理时发出的原始响应帧字节（含 CRC） */
    uint16_t len;
    bool occupied;
} ec_gateway_resp_cache_entry_t;        /* ec_gateway_t 内新增数组，容量 = EC_GATEWAY_DEDUP_CAPACITY (8) */

/* 接口（新增，纯逻辑） */
void     ec_gateway_resp_cache_store(ec_gateway_t *g, ec_dedup_key_t key,
                                     const uint8_t *frame, uint16_t len);
bool     ec_gateway_resp_cache_lookup(const ec_gateway_t *g, ec_dedup_key_t key,
                                      const uint8_t **frame, uint16_t *len);
void     ec_gateway_resp_cache_clear(ec_gateway_t *g);   /* 与新轮确认同步调用 */
```

- **写入时机（每身份一次）**：ITEM_TASK 首次接受 → 写 ACK(ACCEPTED) 帧；DISPLAY_ACK 首次消费 → 写 ACK(ACK_CONSUMED) 帧。（可选：NACK 也写，重发 NACK 无害且幂等；但旧帧重发走不到缓存命中，写不写均可，建议写以对齐"重发上次应答"语义。）
- **读取时机**：`actions & EC_ACTION_RESEND_CACHED_RESPONSE` → 按事件 identity 的 `(task_id, frame_seq)` 查缓存 → 命中则**原样重放**。
- **清除时机**：与 `ec_dedup_clear_for_verified_new_round` 同一处（`MANUAL_NEW_ROUND_CONFIRMED` 生效时），保证**缓存窗口 == dedup 窗口**。
- **容量依据**：`EC_GATEWAY_DEDUP_CAPACITY 8U`（ec_protocol_gateway.h Line 34 注释：一轮由挡板/15 秒预算约束，8 够用）；响应缓存共用同一常数，两缓存同时扩容/收缩。

#### 3.3.4 状态机动作位增量（推荐）

| 动作位 | 触发（新增于 ec_state_machine.c） |
|--------|----------------------------------|
| `EC_ACTION_ACK_ITEM_ACCEPTED`（新增 bit12） | `ITEM_TASK_ACCEPTED` 且 dedup NEW + WAIT_TASK → VALIDATE_TASK 时，与状态迁移同置 |
| `EC_ACTION_ACK_DISPLAY_CONSUMED`（新增 bit13） | `DISPLAY_ACK_VALIDATED` 且首个有效消费（WAIT_DISPLAY_ACK → PREPARE_BARRIER）时同置 |
| 复用 `EC_ACTION_RESEND_CACHED_RESPONSE` | 追加一条：`DISPLAY_ACK_VALIDATED` 到达时若 `matches_current_context` 但 `ack_consumed == true`（重复 ACK）→ RESEND（实现"重复 DISPLAY_ACK → 仅重发状态"） |
| 复用 `EC_ACTION_REJECT_NEW_TASK` | 追加顺序门：ITEM_TASK 的 `frame_seq <= last_accepted_frame_seq` → REJECT_NEW_TASK（补齐"旧帧/乱序"，与 Python `state_machine/core.py` 对齐） |

> 备选实现（不新增动作位）：网关在 `consume_and_emit` 内用"迁移前/后状态 + 事件类型"推断（如 `pre==WAIT_TASK && post==VALIDATE_TASK` → 发 ACK(ACCEPTED)）。推荐动作位方案，语义显式、可单测。

### 3.4 流程伪代码（consume_and_emit 扩展 + 关键帧处理）

```text
dispatch_frame(g, buf, len):
    if not ec_proto_decode(buf, len, &frame): return        # CRC 错：丢弃，不应答
    if frame.receiver != EC_DEVICE_STM32: return
    switch frame.command:
        ITEM_TASK:   handle_item_task(g, &frame)
        DISPLAY_ACK: handle_display_ack(g, &frame)
        default:     /* HEARTBEAT 等非本切片命令：仍静默（现状） */

handle_item_task(g, frame):
    if not ec_proto_decode_item_task(...): return            # 语义失败（X/Y 越界等）
    if frame.sender != EC_DEVICE_PI: return                  # P1-FIX 保留
    if success_count == 255 and state == WAIT_TASK:          # P1-FIX 保留
        emit_nack(g, TASK_REJECTED); return                  # [推荐] 显式拒绝，替代静默
    event = ITEM_TASK_ACCEPTED(task_id, frame_seq, fingerprint=CRC32(payload))
    t = consume_and_emit(g, &event)
    if t.state == VALIDATE_TASK: 锁存 item_target_seq/class_id/image_id/x/y

handle_display_ack(g, frame):
    if not ec_proto_decode_display_ack(...): return
    if frame.sender != EC_DEVICE_PI: return
    if 内容校验失败 (target_seq/渲染结果/CRC/round 任一不匹配):
        emit_nack(g, ACK_NOT_APPLICABLE); return             # [推荐] 替代现状静默忽略
    t = consume_and_emit(g, DISPLAY_ACK_VALIDATED(...))

consume_and_emit(g, event):
    t = ec_sm_consume(&g->sm, event)
    if t.actions & EMIT_BARRIER_READY: emit_frame(BARRIER_READY)
    elif t.actions & EMIT_MOTION_DONE: emit_frame(MOTION_DONE)
    elif t.actions & EMIT_ITEM_RESULT: emit_frame(ITEM_RESULT, {target_seq, code, basis})
    elif t.actions & ACK_ITEM_ACCEPTED:
        emit_frame(ACK, {ACCEPTED, g->item_target_seq})
        resp_cache_store(g, event.identity, tx_buf, tx_len)   # 写缓存（每身份一次）
    elif t.actions & ACK_DISPLAY_CONSUMED:
        emit_frame(ACK, {ACK_CONSUMED, ack.target_seq})
        resp_cache_store(g, event.identity, tx_buf, tx_len)
    elif t.actions & RESEND_CACHED_RESPONSE:
        if resp_cache_lookup(g, event.identity, &f, &len):
            replay(f, len)                                    # 原样重放，不递增 tx_seq
        else:
            log("RESEND cache miss: (task_id, frame_seq)")    # fail-closed：不发射、不执行
    elif t.actions & REJECT_NEW_TASK:
        reason = (event.round_id != g->sm.round_id) ? WRONG_ROUND : SINGLE_TASK_ONLY
        emit_nack(g, reason)
    return t
```

### 3.5 边界规则（实现时必须满足）

| 规则 | 行为 |
|------|------|
| **不重复执行** | RESEND 路径只重放字节；状态机在 dedup 命中时不发生状态转移，执行器/计数器/`success_count` 均不动（对齐伪代码 §3 与 interface-contract §6.1 第 3 条"消息重传不得改变计数"） |
| **15 秒不续时** | RESEND/NACK/ACK 均为非可观察事件；应用层不得因任何重发/应答更新 `lastObservableAt`（状态机伪代码 §5）；重复帧、重传不重置 deadline |
| **与 dedup 缓存窗口一致** | 响应缓存容量 = `EC_GATEWAY_DEDUP_CAPACITY`，与 dedup 在同一"验证新轮"时清除；每身份只写一次 |
| **旧帧/乱序 NACK** | 新增顺序门：`frame_seq <= last_accepted_frame_seq` 或轮次不符 → NACK(STALE_OR_ORDER / WRONG_ROUND)，不改变 `activeTask`、执行器与 15 秒基准（伪代码 §3 表格第 3 行） |
| **无缓存时 fail-closed** | dedup 判 DUPLICATE 但缓存 miss：**不发射、不执行、记日志**（该帧已处理过，不重复执行天然成立；"重发应答"无法满足时宁可让 Pi 侧超时，也不编造新响应）。由构造保证近乎不可能：dedup 与响应缓存同窗口、每身份写一次 |
| **冲突即故障** | 同 `(task_id, frame_seq)` 载荷指纹不同 → `EC_DEDUP_CONFLICT` → FAULT_LOCK（契约 §5.2），响应缓存路径不得掩盖冲突（所以缓存查询只挂在 RESEND 动作位上，不做"先查缓存"的全局捷径） |
| **DISPLAY_ACK 幂等** | 首个有效 ACK 才消费并写缓存；重复 ACK（同身份或已消费）→ RESEND 缓存状态，绝不二次消费、不重复放行（伪代码 §3 表格第 4 行） |
| **成功计数不变** | 重传/重复应答不触发 `success_count` 更新（interface-contract §6.1 第 3 条） |

### 3.6 落地范围（建议的下一步实施切片，本文不实施）

1. `ec_protocol.h/.c`：新增 ACK/NACK 编解码（§3.3.1/3.3.2 布局，E-1/E-2 拍板后写死）。
2. `ec_state_machine.h/.c`：新增 `last_accepted_frame_seq` 顺序门（按轮重置）、`ACK_ITEM_ACCEPTED`/`ACK_DISPLAY_CONSUMED` 动作位、重复 DISPLAY_ACK 的 RESEND 分支。
3. `ec_protocol_gateway.h/.c`：新增响应缓存三函数 + `consume_and_emit` 四个执行分支 + `handle_item_task/handle_display_ack` 的 NACK 出口。
4. 测试：`tests/test_protocol_gateway.c` 增补——重复 ITEM_TASK → tx 为 ACK(ACCEPTED) 且 `tx_seq` 不变；旧序号 → NACK(STALE_OR_ORDER)；冲突载荷 → FAULT_LOCK；重复 DISPLAY_ACK → 重放 ACK(ACK_CONSUMED)；缓存 miss → 无出站；跨轮清除后旧身份不再命中。
5. 与 Python `state_machine/core.py` 行为对齐（顺序门、RESEND、REJECT 已在 Python 主机模型存在，作为交叉参照）。

---

## 4. 问题 D：视觉/树莓派侧推荐方案

### 4.1 现状确认（主链**无需改动**，已具备判重与幂等）

| 组件 | 现状（只读核实） | 与"重传应答"的关系 |
|------|------------------|--------------------|
| `rpi/outbound.py` `OutboundGateway` | `send_item_task`/`send_display_ack`：单调 `_tx_seq`（1 起，每帧 +1）；fail-closed——`task_id` 必须等于 `config.round_task_id` 且 u16 范围合法，否则发前抛 `PayloadError` | 出站半侧：帧身份 `(task_id, frame_seq)` 每次新发，天然满足"新件新身份" |
| `rpi/gateway.py` `PiProtocolGateway` | 入站按 `(task_id, frame_seq)` 判重（`_inbound_cache`，容量 256），重复帧回"DUPLICATE + 缓存出站"（多为 None） | 入站半侧已实现契约 §7.2"重复帧→重发上次应答"的 Pi 视角 |
| `rpi/__init__.py` `Scheduler` | ①`_seen_tasks` 按 `(round_id, task_id, frame_seq)` 判重：同身份同载荷幂等、同身份异载荷 → FAULT；②`accept_item_result` 幂等（WAIT_RENDER 重发同结果返回同一 `display_model`）；③`accept_render_receipt` **缓存唯一 `display_ack_intent`**，重复 receipt 复用同一 DISPLAY_ACK 意图（测试 `RPI_ACK_DUP_001`）；④`note_retransmission()` 现为空桩 | ③即"同身份重传 → 复用缓存应答意图"的现网实现；④为预留钩子 |
| `protocol/display_ack.py` `DisplayContent` | 五字段 `target_seq/class_id/image_id/success_count/result_code`，`canonical_bytes()` + `crc32` 与 C 侧同一算法、同一金标 | 与 C 侧 `ec_proto_display_content_crc32` 完全一致，DISPLAY_ACK 闭环两端可互证 |
| `state_machine/core.py`（主机侧 STM32 语义模型） | 已有 `RESEND_CACHED_RESPONSE`/`REJECT_NEW_TASK` 动作与 `last_accepted_frame_seq` 顺序门 | 是 C 网关落地（§3）的交叉参照/行为基线 |

### 4.2 与 C 侧推荐方案的一致性确认

- **判重键一致**：两侧均以 `(task_id, frame_seq)` 为重复判定键（Pi 入站 / STM32 dedup / 响应缓存），无歧义。
- **"重复帧→重发上次应答"双向成立**：STM32 收到重复 ITEM_TASK/DISPLAY_ACK → 重放缓存应答（§3）；Pi 收到重复 STM32 帧（如重放的 MOTION_DONE/ITEM_RESULT）→ 命中入站缓存、不重复处理。
- **三参数语义一致**：`image_id` 由树莓派赋值并随 ITEM_TASK 显式下发；两端用同一五字段计算 DISPLAY_ACK 期望 CRC。

### 4.3 可选增强（不阻塞主链，按需实施）

| # | 增强 | 内容 | 价值 |
|---|------|------|------|
| D-1 | **同身份重传出站**：`OutboundGateway.resend_item_task(task)` | 原样重放上一次编码的 ITEM_TASK **帧字节**（不递增 `_tx_seq`），并接到 `Scheduler.note_retransmission()`（现空桩）；应用层在超时重传时复用同一 `(task_id, frame_seq)` | 使 STM32 的 dedup→RESEND 路径可被真实触发；若用新 seq 重发，STM32 会视为新帧（对已接受件回 NACK(SINGLE_TASK_ONLY)），语义混淆 |
| D-2 | **NACK 原因码日志**：`PiProtocolGateway` 解析入站 ACK(0x05)/NACK(0x06) | 目前 `_handle` 对 ACK/NACK 一律返回 IGNORED；增强为解析 §3.3.2 原因码并写入 `rpi/log.py`，outcome 事件化为 `"ACK"/"NACK" + 原因名` | 联调期可观察 STM32 的拒绝原因（STALE_OR_ORDER/SINGLE_TASK_ONLY/ACK_NOT_APPLICABLE 等），快速定位丢帧/乱序/时序问题 |
| D-3 | **不触碰 MaixCAM/YOLO 侧** | 视觉链线格式未冻结，视觉侧无应答帧义务；三参数只进调度链逻辑层 | 本轮视觉侧零改动，避免未冻结格式被提前写死 |

---

## 5. 未决项清单（需用户拍板）

> 每项给出：推荐值 + 依据 + 需用户拍板的原因。凡涉及"线上字节/枚举"的项，拍板后须同步冻结到 interface-contract.md 并做 C/Python 双端金标测试。

| # | 未决项 | 推荐值 | 依据 | 需拍板原因 |
|---|--------|--------|------|-----------|
| E-1 | **ACK/NACK 载荷格式** | ACK/NACK 均 2 字节：`原因(1) + 目标序号(1)`（§3.3.1/3.3.2） | 最小可关联件身份；与伪代码原因名对齐；目标序号回显便于 Pi 关联应答对象 | 契约 §4.1 只定义命令字与"NACK 含原因码"，**载荷字节布局未冻结**；这是唯一需要新增冻结的线格式 |
| E-2 | **NACK 原因码枚举** | 6 枚：`0x10 STALE_OR_ORDER / 0x11 UNEXPECTED_MESSAGE / 0x12 SINGLE_TASK_ONLY / 0x13 ACK_NOT_APPLICABLE / 0x14 WRONG_ROUND / 0x15 TASK_REJECTED` | 全部可由状态机伪代码（Line 72-77/273-277）与 C 动作位实际产生；不虚设场景 | wire 枚举必须 C/Python 两侧一致、冻结后才可写死；增删一枚影响两端 |
| E-3 | **"重发哪个响应"** | **按 `(task_id, frame_seq)` 键控的任务响应缓存**（伪代码 `acceptedFrameCache` 语义），**拒绝"最近 emit 帧"方案** | "最近 emit 帧"可能把上一件的 MOTION_DONE/ITEM_RESULT 当作本件应答重发——跨件错答，Pi 侧重放 ITEM_RESULT 在错误状态有 FAULT 风险；按键缓存保证应答与该请求身份绑定 | 两种方案的语义与安全边界不同，属设计取向，需用户确认采用任务缓存而非最近帧 |
| E-4 | **是否要求 STM32 在 ITEM_TASK 接受时回 ACK(ACCEPTED)** | **实现**（伪代码基线 `cacheAck(frame, ACCEPTED)`；与 ACK(ACK_CONSUMED)、RESEND、NACK 一起构成完整闭环） | 没有"上次应答"就没有可重发的对象；当前 C 实现接受新件不发射任何帧，"重发应答"无从谈起 | 会新增 Pi 侧入站帧类型（现 IGNORED，行为兼容）；若用户只想最小化"仅补重发路径"，可改为"首帧仍不回 ACK、重复帧只重发最近状态"（该降级方案需另行评估语义） |
| E-5 | **重发帧的 `frame_seq` 策略** | **原样重放（不递增 `tx_seq`）** | Pi 入站按 `(task_id, frame_seq)` 判重；原样重放命中"DUPLICATE→缓存应答"；新 seq 会被 Pi 当新帧重处理（MOTION_DONE 重放在错误状态 → FAULT） | 影响 Pi 入站行为；若选新 seq，须同时加固 Pi 入站幂等 |
| E-6 | **重传上限次数 / 应答超时** | 候选：每类重发 ≤ 3 次，耗尽后发 `ERROR(0x04, 等级 0x01 数据扰动)` 并停止重发；**最终值待台架实测**（interface-contract §6 标 [待定]；15 秒阶段预算优先，显示确认剩余不足时不得再重发） | 契约 §6/§8 与预冻结清单 §3 均标"待台架实测，不写死"；重传不续 15 秒，上限受阶段预算硬约束 | 涉及比赛阶段时间预算与故障分级，主机侧不能定死；需实测后冻结 |
| E-7 | **响应缓存窗口容量** | = `EC_GATEWAY_DEDUP_CAPACITY`（现 8），与 dedup 同清 | 一轮由挡板 + 15 秒预算约束，8 覆盖典型件数；两缓存同常数避免窗口错位 | 若单轮件数可能 >8（`success_count` 上限 255），须同步上调两缓存容量（单一常数），需用户确认件数预期 |
| E-8 | **DISPLAY_ACK 无效帧是否回 NACK** | 回 `NACK(ACK_NOT_APPLICABLE)`（替代现状静默忽略），但仅限"能解析出帧、内容校验失败"的情形；CRC 错帧一律丢弃不应答 | 伪代码 `sendNack(frame, ACK_NOT_APPLICABLE)`；NACK 属非可观察事件，不续 15 秒、不引发执行 | 改变当前静默行为；需确认联调期是否希望暴露这类失败（涉及 E-2 枚举已含此值） |

---

## 6. 本方案不做什么（边界声明）

- **不改任何生产代码、不做任何实施**：本文档为方案提案；§3.6 的落地切片需另行排期并在 `docs/reports/` 留证据。
- **不新增命令字、不改冻结格式**：不动 DISPLAY_ACK(0x25) 六字节/五字段 CRC 规则、不动 ITEM_TASK 八字节载荷、不动外层帧；只实现契约已定义行为的缺失执行者 + 待冻结的 ACK/NACK 载荷参数。
- **不预设时序数值**：超时/重发上限/心跳仍为 [待定]，本文只给候选与边界约束（不续 15 秒）。
- **不涉及 MaixCAM 线格式**：视觉链 BATCH_TARGETS 等未冻结，不在本文冻结。
- **不触碰实机**：无串口、屏幕、STM32 板、电机、上电操作。

## 7. 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| V0.1 | 2026-08-29 | 首版：三问三答（A/B）+ 电控 RESEND 落地推荐（C）+ 视觉/树莓派推荐（D）+ 未决项清单（E）；只读分析，未实施 |
