# P3 · `ITEM_TASK` 8 → 12 字节（追加抓取点）— 完整 diff

> **状态**：⚪ **提案，未落工作区**。等用户签收后再贴。
> **级别**：🔴 **L4**（修改系统间通信协议）—— 必须用户明确批准
> **日期**：2026-09-16
> **目的**：让"抓取点随机"成为可能。赛题要求抓取点随机、落料点固定；现在固件里
> 抓取点写死 `(0,0)`（台账 E-18），实机必抓空。

---

## 0. 怎么用这份文档

**不要自己改工作区。** 贴的时候按 §2 的顺序逐个文件改，改完按 §4 验证。

**三方必须同时贴**（§3），只贴一半 → 编译通过但通信失败 → 静默 fail-closed。

---

## 1. wire 变更总览

**选「尾部追加」，不选「复用现有字段」。** 理由：现有 `offset 3-6` 是落料点，
`interface-contract.md §5.2` 已冻结该语义；改为抓取点会误导所有旧文档与注释。

```
offset  0     target_seq(1)
offset  1     class_id(1)
offset  2     image_id(1)
offset  3-4   x_mm10(2, int16 BE)        落料点 X   ← 语义不变
offset  5-6   y_mm10(2, int16 BE)        落料点 Y   ← 语义不变
offset  7     grip_angle(1) = 0xFF
offset  8-9   pick_x_mm10(2, int16 BE)   ★新增 抓取点 X
offset 10-11  pick_y_mm10(2, int16 BE)   ★新增 抓取点 Y
                                       总长 8 → 12
```

**边界确认（已核实）**：

| 项 | 结论 |
|---|---|
| 外层帧 `data_len` 上限 | `uint16_t` → 65535。12 字节毫无压力 |
| 帧总长 | 14（固定开销）+ 12 = **26 字节** |
| CRC 覆盖 | `ec_crc16_modbus(out, HEADER_LEN + payload_len)` 随 `payload_len` 自动适应，**无需改** |
| `EC_GATEWAY_RX_MAX` | 64，12 字节足够 |
| 向后兼容 | ❌ 不兼容。旧固件收到 12 → `payload_len != 8` → 解码失败；新固件收到 8 → 同理。**双方 fail-closed，不会错位执行** |

---

## 2. 逐文件 diff

### 2.1 `电控/stm32_logic/include/ec_protocol.h`

**改 `:142-159`。**

```diff
-/* --- ITEM_TASK payload (0x21) - FROZEN (interface-contract.md sec. 5.2) ---
- * target_seq(1) + class_id(1) + image_id(1)
- * + X(2, int16 big-endian, 0.1 mm) + Y(2, int16 big-endian, 0.1 mm)
- * + grip_angle(1, always 0xFF) = 8 bytes.
- * X/Y origin = device center; |value| > 1450 (+-145.0 mm) is rejected.
- * grip_angle must be 0xFF (claw does not rotate); 0..180 unused this round. */
-#define EC_PROTO_ITEM_TASK_PAYLOAD_LEN 8U
+/* --- ITEM_TASK payload (0x21) - FROZEN (interface-contract.md sec. 5.2) ---
+ * 2026-09-16 (P3)：payload 由 8 字节扩到 12 字节，【在尾部追加】抓取点。
+ * 赛题要求抓取点随机、落料点固定；原 8 字节只带得下落料点，抓取点在固件里
+ * 写死 (0,0) → 实机必抓空（台账 E-18）。追加而非复用现有字段，是为了不破坏
+ * offset 3-6 已冻结的"落料点"语义。
+ *
+ *   offset 0     target_seq(1)
+ *   offset 1     class_id(1)
+ *   offset 2     image_id(1)
+ *   offset 3-4   x_mm10(2, int16 BE, 0.1mm)      落料点 X（语义不变）
+ *   offset 5-6   y_mm10(2, int16 BE, 0.1mm)      落料点 Y（语义不变）
+ *   offset 7     grip_angle(1, always 0xFF)
+ *   offset 8-9   pick_x_mm10(2, int16 BE, 0.1mm) ★新增 抓取点 X
+ *   offset 10-11 pick_y_mm10(2, int16 BE, 0.1mm) ★新增 抓取点 Y
+ *
+ * 两组坐标同坐标系：原点 = 装置中心，单位 0.1mm，|value| > 1450 拒绝。
+ * 抓取点另受更紧的机械可达域约束（ec_motion_plan.h 的 825），
+ * 但那由运动规划层判，协议层只管 1450。
+ * grip_angle 必须 0xFF（夹爪不旋转）；0..180 本轮未用。
+ *
+ * ⚠️ 严格长度检查使新旧固件互不兼容（12 != 8 → 解码失败 → fail-closed，
+ * 不会错位执行）。树莓派与 STM32 必须同时升级。 */
+#define EC_PROTO_ITEM_TASK_PAYLOAD_LEN 12U
 #define EC_PROTO_ITEM_TASK_X_LIMIT 1450
 #define EC_PROTO_ITEM_TASK_ANGLE_NONE UINT8_C(0xFF)
 
 typedef struct {
     uint8_t target_seq;
     uint8_t class_id;
     uint8_t image_id;
-    int16_t x_mm10;
-    int16_t y_mm10;
+    int16_t x_mm10;         /* 落料点 X（语义不变） */
+    int16_t y_mm10;         /* 落料点 Y（语义不变） */
     uint8_t grip_angle;
+    int16_t pick_x_mm10;    /* ★新增：抓取点 X */
+    int16_t pick_y_mm10;    /* ★新增：抓取点 Y */
 } ec_proto_item_task_t;
```

> **刻意不做的事**：P3-A 提案里把 `x_mm10` 改名为 `place_x_mm10`。
> **本 diff 不做这个改名** —— 它会连带触碰 `ec_protocol_gateway.c`、
> `ec_app.c` 等 P2 刚刚验证过的代码，扩大 diff 面却不改变行为。
> **留作可选清理**，不与本次协议变更混在一起。

---

### 2.2 `电控/stm32_logic/src/ec_protocol.c` — `encode` (`:142-166`)

```diff
 bool ec_proto_encode_item_task(const ec_proto_item_task_t *item,
                                uint8_t *payload, uint16_t cap)
 {
     if ((item == NULL) || (payload == NULL)) return false;
     if (cap < EC_PROTO_ITEM_TASK_PAYLOAD_LEN) return false;
     if ((item->x_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
         (item->x_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
         return false;
     }
     if ((item->y_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
         (item->y_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
         return false;
     }
+    /* 抓取点与落料点同域检查：两组坐标都会被下成脉冲，任一越界都必须拒绝。 */
+    if ((item->pick_x_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
+        (item->pick_x_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
+        return false;
+    }
+    if ((item->pick_y_mm10 < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
+        (item->pick_y_mm10 > EC_PROTO_ITEM_TASK_X_LIMIT)) {
+        return false;
+    }
     if (item->grip_angle != EC_PROTO_ITEM_TASK_ANGLE_NONE) return false;
 
     payload[0] = item->target_seq;
     payload[1] = item->class_id;
     payload[2] = item->image_id;
     payload[3] = (uint8_t)((uint16_t)item->x_mm10 >> 8U);
     payload[4] = (uint8_t)item->x_mm10;
     payload[5] = (uint8_t)((uint16_t)item->y_mm10 >> 8U);
     payload[6] = (uint8_t)item->y_mm10;
     payload[7] = item->grip_angle;
+    payload[8]  = (uint8_t)((uint16_t)item->pick_x_mm10 >> 8U);
+    payload[9]  = (uint8_t)item->pick_x_mm10;
+    payload[10] = (uint8_t)((uint16_t)item->pick_y_mm10 >> 8U);
+    payload[11] = (uint8_t)item->pick_y_mm10;
     return true;
 }
```

---

### 2.3 `电控/stm32_logic/src/ec_protocol.c` — `decode` (`:168-196`)

```diff
 bool ec_proto_decode_item_task(const uint8_t *payload, uint16_t payload_len,
                                ec_proto_item_task_t *out)
 {
     int16_t x;
     int16_t y;
+    int16_t pick_x;
+    int16_t pick_y;
 
     if ((payload == NULL) || (out == NULL)) return false;
     if (payload_len != EC_PROTO_ITEM_TASK_PAYLOAD_LEN) return false;
     if (payload[7] != EC_PROTO_ITEM_TASK_ANGLE_NONE) return false;
 
     /* Big-endian int16 via explicit byte arithmetic (avoids a direct
      * *(int16_t*) dereference, which breaks on little-endian ARM). */
     x = (int16_t)(((uint16_t)payload[3] << 8U) | (uint16_t)payload[4]);
     y = (int16_t)(((uint16_t)payload[5] << 8U) | (uint16_t)payload[6]);
     if ((x < -EC_PROTO_ITEM_TASK_X_LIMIT) || (x > EC_PROTO_ITEM_TASK_X_LIMIT)) {
         return false;
     }
     if ((y < -EC_PROTO_ITEM_TASK_X_LIMIT) || (y > EC_PROTO_ITEM_TASK_X_LIMIT)) {
         return false;
     }
+    pick_x = (int16_t)(((uint16_t)payload[8] << 8U) | (uint16_t)payload[9]);
+    pick_y = (int16_t)(((uint16_t)payload[10] << 8U) | (uint16_t)payload[11]);
+    if ((pick_x < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
+        (pick_x > EC_PROTO_ITEM_TASK_X_LIMIT)) {
+        return false;
+    }
+    if ((pick_y < -EC_PROTO_ITEM_TASK_X_LIMIT) ||
+        (pick_y > EC_PROTO_ITEM_TASK_X_LIMIT)) {
+        return false;
+    }
 
     out->target_seq = payload[0];
     out->class_id = payload[1];
     out->image_id = payload[2];
     out->x_mm10 = x;
     out->y_mm10 = y;
     out->grip_angle = payload[7];
+    out->pick_x_mm10 = pick_x;
+    out->pick_y_mm10 = pick_y;
     return true;
 }
```

---

### 2.4 `电控/stm32_logic/include/ec_protocol_gateway.h`

**改 `:82-90` 附近的 latch 槽位**（在 `item_y_mm10` 之后加两行）：

```diff
     uint8_t item_target_seq;
     uint8_t item_class_id;
     uint8_t item_image_id;
     ...
     int16_t item_x_mm10;
     int16_t item_y_mm10;
+    /* ★P3 新增：抓取点 latch。与 item_x/y 同坐标系（0.1mm，原点=装置中心）。
+     * 必须与 item_x/y 【在同一次 latch 里一起写】，否则会出现
+     * "新抓取点配旧落料点"（或反之）—— 正是 E-18 那类错位的翻版。 */
+    int16_t item_pick_x_mm10;
+    int16_t item_pick_y_mm10;
```

> ⚠️ **贴的时候注意**：上面的 `...` 是省略的真实代码，实际结构体里
> `:85-88` 之间还有其他成员。请只插入标注 `+` 的那几行，**不要动别的**。

---

### 2.5 `电控/stm32_logic/src/ec_protocol_gateway.c` — **两处 latch**

> 🔴 **这是本次改动最危险的地方。** P2-A 复核明确警告过：
> *"latch 出现两次（:162-168 与 :174-180）。P3 若只在一处加 item_pick_x/y，
> 就会出现'新抓取点配旧落料点'→ 机构'在 A 抓、往 B 放'。"*
> **两处都要加，一处都不能漏。**

**第一处（`:162-168`）：**

```diff
     if (g->sm.state == EC_STATE_WAIT_TASK) {
         g->item_target_seq = item.target_seq;
         g->item_class_id = item.class_id;
         g->item_image_id = item.image_id;
         g->item_x_mm10 = item.x_mm10;
         g->item_y_mm10 = item.y_mm10;
+        g->item_pick_x_mm10 = item.pick_x_mm10;
+        g->item_pick_y_mm10 = item.pick_y_mm10;
     }
```

**第二处（`:174-180`）：**

```diff
     if (t.state == EC_STATE_VALIDATE_TASK) {
         g->item_target_seq = item.target_seq;
         g->item_class_id = item.class_id;
         g->item_image_id = item.image_id;
         g->item_x_mm10 = item.x_mm10;
         g->item_y_mm10 = item.y_mm10;
+        g->item_pick_x_mm10 = item.pick_x_mm10;
+        g->item_pick_y_mm10 = item.pick_y_mm10;
     }
```

---

### 2.6 `电控/stm32_logic/src/ec_protocol_gateway.c` — `ec_gateway_item_pick`（`:537-559`）

**这一处是"把 P2 的桩接上"。**

```diff
-/* 2026-09-16 临时台架抓取点 —— P3 上线后连同 ec_gateway_item_pick() 的函数体
- * 一起恢复成 return false。
- *
- * 背景：P2 已把抓取点从写死常量改成 ITEM_TASK 参数，但 wire 上还没有这个字段
- * （P3 才把 ITEM_TASK 从 8 字节扩到 12 字节）。在那之前本函数恒 false，
- * ec_app.c:172-179 的 || 短路会让机构完全不 arm —— 台架什么都验证不了。
- * 这两个常量让机构用【固定抓取点】跑通全链路，仅供台架验证。
- *
- * 定义在本文件内而不放 App 头文件：stm32_logic 要被主机测试独立编译，
- * 不能反向依赖 App 层。 */
-#define EC_GATEWAY_PICK_STUB_X_MM10 ((int16_t)0)
-#define EC_GATEWAY_PICK_STUB_Y_MM10 ((int16_t)0)
-
 bool ec_gateway_item_pick(const ec_gateway_t *g, int16_t *x_mm10,
                           int16_t *y_mm10)
 {
     if ((g == NULL) || (x_mm10 == NULL) || (y_mm10 == NULL)) {
         return false;
     }
-    *x_mm10 = EC_GATEWAY_PICK_STUB_X_MM10;
-    *y_mm10 = EC_GATEWAY_PICK_STUB_Y_MM10;
+    /* P3 (2026-09-16)：读取 ITEM_TASK 锁存的抓取点，与同族的
+     * ec_gateway_item_target() 形状一致。
+     *
+     * 不做 has_pick 标志位：调用点唯一（ec_app.c:173 的 start_motion），
+     * 而 start_motion 只在 EC_ACTION_START_MOTION（VALIDATE_TASK→EXECUTING）
+     * 下执行，该转移的前提是条目已被接受，而接受路径必然写 latch
+     * （见本文件 handle_item_task 的两处 latch）。invariant 由状态机保证。 */
+    *x_mm10 = g->item_pick_x_mm10;
+    *y_mm10 = g->item_pick_y_mm10;
     return true;
 }
```

> ⚠️ **必须同时告知**：贴上这一段后，**P2-A 的那个"临时台架抓取点"就消失了**。
> 好处是抓取点从此来自 wire；代价是**工具/树莓派必须开始填 `pick_x/pick_y`**，
> 否则它们会是 0（= 原点），机构会去装置中心抓。

---

### 2.7 `电控/src/electrical_control/protocol/item_context.py`

**`ItemTaskPayload`（`:16-25`）加两个字段：**

```diff
 @dataclass(frozen=True, slots=True)
 class ItemTaskPayload:
-    """Frozen logical ITEM_TASK fields; wire encoding remains incomplete."""
+    """ITEM_TASK logical fields.
+
+    V0.9 (2026-09-16, P3): payload 8 -> 12 bytes, adding the grasp (pick) point.
+    x_position/y_position remain the DROP point (semantics unchanged)."""
 
     target_seq: int
     class_id: int
     image_id: int
-    x_position: int
-    y_position: int
+    x_position: int          # 落料点 X，0.1mm
+    y_position: int          # 落料点 Y，0.1mm
     grip_angle: int
+    pick_x_position: int = 0  # ★新增 抓取点 X，0.1mm
+    pick_y_position: int = 0  # ★新增 抓取点 Y，0.1mm
```

> 给默认值 0 是为了**不破坏现有构造点**（`run_chain.py` 等按关键字构造）。
> 贴完 P3 后应尽快改为显式传值，并把默认值删掉。

**`encode_item_task_payload`（`:92-116`）尾部：**

```diff
     x = _coord("x_position", item.x_position)
     y = _coord("y_position", item.y_position)
+    pick_x = _coord("pick_x_position", item.pick_x_position)
+    pick_y = _coord("pick_y_position", item.pick_y_position)
     _u8("grip_angle", item.grip_angle)
     if item.grip_angle != _ITEM_TASK_ANGLE_NONE:
         raise PayloadError("grip_angle must be 0xFF (claw does not rotate)")
     if item.image_id != item.class_id:
         raise PayloadError("image_id must equal class_id (frozen 1:1 invariant)")
     if not 1 <= item.target_seq <= 255:
         raise PayloadError("target_seq must be within [1, 255]")
     return (
         bytes((item.target_seq, item.class_id, item.image_id))
         + x.to_bytes(2, "big", signed=True)
         + y.to_bytes(2, "big", signed=True)
         + bytes((item.grip_angle,))
+        + pick_x.to_bytes(2, "big", signed=True)
+        + pick_y.to_bytes(2, "big", signed=True)
     )
```

**`decode_item_task_payload`（`:119-140+`）同步：**

```diff
-    if len(payload) != 8:
-        raise PayloadError("ITEM_TASK payload must be exactly 8 bytes")
+    if len(payload) != 12:
+        raise PayloadError("ITEM_TASK payload must be exactly 12 bytes")
     if payload[7] != _ITEM_TASK_ANGLE_NONE:
         raise PayloadError("grip_angle must be 0xFF (claw does not rotate)")
     x = int.from_bytes(payload[3:5], "big", signed=True)
     y = int.from_bytes(payload[5:7], "big", signed=True)
+    pick_x = int.from_bytes(payload[8:10], "big", signed=True)
+    pick_y = int.from_bytes(payload[10:12], "big", signed=True)
     if not -_ITEM_TASK_X_LIMIT <= x <= _ITEM_TASK_X_LIMIT:
         raise PayloadError("x_position out of range (+-1450)")
     if not -_ITEM_TASK_X_LIMIT <= y <= _ITEM_TASK_X_LIMIT:
         raise PayloadError("y_position out of range (+-1450)")
+    if not -_ITEM_TASK_X_LIMIT <= pick_x <= _ITEM_TASK_X_LIMIT:
+        raise PayloadError("pick_x_position out of range (+-1450)")
+    if not -_ITEM_TASK_X_LIMIT <= pick_y <= _ITEM_TASK_X_LIMIT:
+        raise PayloadError("pick_y_position out of range (+-1450)")
```

> 解码尾部构造 `ItemTaskPayload(...)` 的地方也要补 `pick_x_position=pick_x,
> pick_y_position=pick_y`。（该函数体在 `:135` 之后，贴的时候一并改。）

---

### 2.8 `电控/src/electrical_control/protocol/frames.py`（`:85-86`）

```diff
-    if len(payload) != 8:
-        raise PayloadError("ITEM_TASK payload must be exactly 8 bytes")
+    if len(payload) != 12:
+        raise PayloadError("ITEM_TASK payload must be exactly 12 bytes")
```

同时更新 `:78-79` 的 docstring（"complete frozen 8-byte payload" → 12-byte）。

---

### 2.9 `docs/design/interface-contract.md` §5.2

按 §1 的表格改字段表与总长度，并把协议版本从 `V0.8` 提到 **`V0.9`**
（⚠️ 外层帧的 `version` 字节**仍是 `0x01`，不要改** —— 那是不兼容才动的东西；
这里说的 V0.9 只是文档里给这版协议变更起的名字）。

---

### 2.10 `工具/pc_item_task.py`（工具尚未写出）

**工具的 payload 必须按 12 字节写**，并新增两个参数：

```
--pick-x   抓取点 X，0.1mm，默认 0
--pick-y   抓取点 Y，0.1mm，默认 0
```

**帧长断言从 22 改为 26**（14 固定开销 + 12 payload）。

> 🔴 **给工具任务的一句话更正**：之前那份工具提示词是按 **8 字节**写的。
> 如果 P3 先落地，**把提示词里的"8 字节 / 帧长 22"改成"12 字节 / 帧长 26"，
> 并加上 `--pick-x/--pick-y`**。其余不变。

---

## 3. 三方同步清单（只贴一半 = 静默失效）

| # | 文件 | 侧 |
|---|---|---|
| 1 | `ec_protocol.h` | 固件 |
| 2 | `ec_protocol.c`（encode + decode） | 固件 |
| 3 | `ec_protocol_gateway.h` | 固件 |
| 4 | `ec_protocol_gateway.c`（**两处 latch** + `item_pick` 函数体） | 固件 |
| 5 | `item_context.py`（类 + encode + decode） | 树莓派 Python |
| 6 | `frames.py` | 树莓派 Python |
| 7 | `interface-contract.md` | 文档 |
| 8 | `工具/pc_item_task.py` | PC 工具 |

**⚠️ 漏贴 #8 的后果**：工具仍发 8 字节 → 固件 `payload_len != 12` → 解码失败 →
**静默不响应**（你会以为"机构坏了"，其实是长度不匹配）。

**⚠️ 漏贴 #4 两处 latch 中任一处**：会出现"新抓取点配旧落料点"→
机构在 A 抓、往 B 放。

---

## 4. 验证步骤（按顺序，每步都要过）

1. **主机侧编译** —— 贴完 #1-#4 后，用 Keil `Rebuild All`，期望 **0 error 0 warning**
2. **固件侧帧长自检** —— 构造 12 字节载荷走 `ec_proto_encode_item_task` /
   `ec_proto_decode_item_task`，确认往返一致；再喂 8 字节的旧载荷，
   确认**被拒绝**（这是 fail-closed 的证明）
3. **Python 侧往返** —— `encode_item_task_payload` → `decode_item_task_payload`
   自洽；断言输出长度 == 12
4. **跨语言一致性** —— 用同一个 `(task_id, frame_seq, 全部字段)`，
   C 侧编码的字节与 Python 侧编码的字节**必须逐字节相同**
   （含 CRC）。这是最容易出问题的一步
5. **端到端** —— 树莓派（或 PC 工具）发一帧 12 字节 → STM32 应当
   回 `ACK(ACCEPTED)`，随后 `MOTION_DONE` → `ITEM_RESULT`，机构动

---

## 5. 回滚

**不能部分回滚**（新旧协议不兼容）。全量回退：
- 把 §2 所有改动逐条反贴
- 重新 `Rebuild All`
- 重烧

**回滚窗口**：建议当天。旧固件 hex 建议先另存一份
（`diankongv1.0\diankongv1.0.hex` → `…-pre-P3.hex`）。

---

## 6. 我没验证的（如实声明）

- 我**没有编译过**这份 diff（没有 Keil，且不改工作区）
- 我**没有跑过** Python 往返
- 我**没有做**跨语言字节一致性比对
- §2.4 的结构体插入位置是**按读到的行号推断**的；实际插入点请以你打开文件时
  的上下文为准（`:82-90` 之间还有别的成员，我没有逐行列出）
- `interface-contract.md` §5.2 的**实际表格行**我没有读，只给了改法说明

---

## 7. 🔴 P3 落地 ≠ 抓取点就随机了

**P3 只提供"运输通道"，不提供"数据源"。**

```
MaixCAM 检测框中心(像素)
        ↓  ← 【① 尚未实现】像素 → 装置坐标(mm) 的标定
  抓取点 mm10
        ↓  ← 【P3 本次提供】ITEM_TASK offset 8-11
    STM32
```

已定：**换算放在树莓派侧**（`BATCH_TARGETS` 的 X/Y 本来就是像素，
协议注释明写 *"not calibrated … never for motion"*）。
所以 P3 贴完之后，**还必须在树莓派侧补一个"像素→mm"的换算**，
否则 `pick_x/pick_y` 只能填固定值。

**换算还牵涉两件事**：
- 相机内外参 / 单应矩阵（`docs/plans-2026-09-16/01-相机安装方案.md`）
- **高度视差补偿**（台账挂账项 **H-1**）：视差 ≈ `x·h/(d−h)`，
  d=400/h=40/x=80 时约 **8.9mm**，在 ±82.5mm 可达域里占 11%，**不能忽略**

---

## 8. 工时估算

| 段 | 估时 |
|---|---|
| 贴 #1-#4（固件） | 1~1.5 h |
| 贴 #5-#6（Python） | 1 h |
| 贴 #7（文档） | 0.5 h |
| 改 #8（工具） | 10 min |
| §4 五步验证 | 1.5~2 h |
| **实机端到端** | 1~2 h |
| **合计** | **≈ 7~8 h ≈ 1 个工作日** |

联调（§4 第 4、5 步）是变数所在。

---

# 9. 🔴 复核后必改项（2026-09-16 追加）

> 来源：独立对抗复核 `RD-P2P3-20260916`。
> **本节列的漏洞在初版 §2 里确实存在**，贴之前必须先按本节改。
> 初版作者（我）的疏漏如实登记，不掩盖。

## 9.1 【必改·最严重】漏了两处 pick 清零 → "旧抓取点配新落料点"

初版只改了 **latch 两处**（`:162-168`、`:174-180`），**漏了清零两处**：

```c
/* ec_protocol_gateway.c:269-273 —— ec_gateway_init() */
g->item_target_seq = 0U;
g->item_class_id = 0U;
g->item_x_mm10 = 0;
g->item_y_mm10 = 0;
/* ← 必须补：g->item_pick_x_mm10 = 0;  g->item_pick_y_mm10 = 0; */

/* ec_protocol_gateway.c:481-485 —— 新轮次（verified new round） */
g->item_target_seq = 0U;
g->item_class_id = 0U;
g->item_x_mm10 = 0;
g->item_y_mm10 = 0;
/* ← 同样必须补两行 */
```

**后果**：新轮次把落料点清零、却留下上一件的抓取点 →
**"旧抓取点配新落料点"**，正是 P2-A 警告的那类错位（只是方向相反）。

**→ 除 §2.5 的两处 latch 之外，必须再加这两处的 diff。**

## 9.2 【必改】禁止 `pick_x_position: int = 0` 这个默认值

初版 §2.7 给新字段加了默认值 `= 0`，理由是"不破坏现有构造点"。**这是错的**：
现有构造点不传 pick 也能编过 → 于是发出**合法的 12 字节帧**、pick=(0,0) →
**确定性地去装置中心空夹**，与 E-18 同一个终点，而且是静默的。

**改法**：去掉默认值，**强制所有构造点显式传**；无毫米抓取点时**不得序列化**
（对标仓库已有的 `grip_angle != 0xFF` 拒绝模式，见 `vision_ingest.py:136-139`）。

## 9.3 【必改】`ec_gateway_item_pick` 不得恒 `true`

初版 §2.6 让它与同族 `ec_gateway_item_target` 同形（非空指针即写 latch 并返回 true），
并声称"状态机保证 invariant"。**复核指出：这个 invariant 只保证"接受过 ITEM_TASK"，
不保证 pick 来自视觉毫米坐标** —— 因为 `vision_ingest.py` 根本不填抓取点。

**后果**：无法区分"没给"和"就在中心"，（0,0）会被当成真实抓取点。

**改法**：加一个显式条件（如 `has_pick` 标志，或在 latch 时校验来源），
不满足时保持 `return false` 的 fail-closed 语义。

> ⚠️ 别与**当前台架临时态**混淆：桩现在返回 `true` + `(0,0)`，那是**临时**的，
> `ec_protocol_gateway.h` 的声明注释已改为如实描述并写明退出条件。

## 9.4 【必改】§2.4 的插入点说明有误

初版写"`:85-88` 之间还有其他成员，请只插入标注 `+` 的那几行"。
**实际 `:82-90` 就是身份三字节 + 落料点，中间没有第三组字段。**
插入点应在 `item_y_mm10` 之后直接紧跟，不要留 `...` 占位。

## 9.5 【必改】同步清单漏了构造点

§3 的 8 项清单漏了**所有构造 `ItemTaskPayload` 的地方**。漏一个 = 默认中心抓：
- `电控/src/electrical_control/rpi/vision_ingest.py:174-181`
- `电控/src/electrical_control/scheduler/bridge.py:125-132`
- `工具/pc_item_task.py:134-141`（§2.10 提了工具，但没提它的**构造点**）
- 归档的 Python / C 测试
- `电控/deploy/` 里写"22 字节"的注释与 SOP（贴 P3 后会变 26，旧 SOP 全错）

## 9.6 【必改】`decode_item_task_payload` 的构造要写成明确一步

§2.7 只在括号里提醒"尾部构造要补 pick 字段"，**容易漏**。

## 9.7 【必改】`interface-contract.md` 要删的两句

除改字段表，还必须删掉这两句（否则合同仍规定着 E-18）：
- "总载荷 8 字节…**不允许临时扩展**"
- "X/Y = 落点…**抓取固定圆心**"

## 9.8 【强调】文档版本号与线 `version` 分开写

`V0.9` 只是**文档里给这次变更起的名字**；外层帧的 `version` 字节**仍是 `0x01`**。

---

## 9.9 复核确认成立的部分（不用改）

- **两处 latch 都覆盖到了** ✅
- **encode/decode 的域检查**：抓取点与落料点同等对待，无漏 ✅
- **不改 `x_mm10` 标识符**：复核同意，不扩大 diff 面 ✅
- **新旧固件互收不会错位执行**（精确长度检查 → decode false → fail-closed）✅
  ⚠️ 但**是静默丢弃且不发 NACK** —— 联调时会误判成"机构坏了"，排障时要知道
- **§7「P3 ≠ 随机抓取」的判断** ✅ 复核同意，并追加一句：
  **在缺像素→mm 换算时还让默认 0 上线，比"还不能随机"更差 —— 那是确定性空夹**

## 9.10 两个初版没想到的坑（复核提出）

1. **去重指纹是整段 payload 的 CRC32**（`ec_protocol_gateway.c:148-149`）。
   pick 进入指纹是对的，但**树莓派重传必须字节级一致**，否则会被判成新任务。
2. **C 侧 `encode` 检查 `cap < 12`** —— 调用方若还有按 8 分配的栈缓冲会失败。
   初版**没有穷举** `uint8_t payload[8]` 之类的临时缓冲，**这一项未验证**。

