# ITEM_TASK X/Y/angle 编解码落地 — 交接稿

日期：2026-08-25
状态：**计划已批准，代码未实施**（本轮交接前已完成的只有文件通读 + 金标核对 + 一处关键涟漪发现）
交接对象：下一轮实现者（人或模型），或本会话压缩后续做。

---

## 1. 交接范围

只落地 `ITEM_TASK` 完整 8 字节载荷的编解码（C 侧 + Python 侧 + 跨语言金标互证）。
**不落**：落点表物理量（篮圈半径 R / 角度约定 / 类别→篮子赋值，用户已拍板「物理量先不管」）、时序/超时/重发/心跳、状态机运动接线。
**不碰**：串口、屏幕、STM32 板、电机、实机上电（用户红线，见 §8）。

---

## 2. 已签字冻结的事实（不可改，写死即对）

来源 `docs/design/2026-08-25-rpi-pre-hardware-freeze-list.md`（用户 2026-08-25 签字）：

| 项 | 冻结值 |
|---|---|
| 外层帧 | `A5 5A` + 版本 `01` + CRC-16/MODBUS + `task_id/frame_seq/data_len` 大端 |
| 设备 ID | `0x01` MaixCAM、`0x02` 树莓派、`0x03` STM32 |
| ITEM_TASK 载荷 | **8 字节** = `target_seq(1) + class_id(1) + image_id(1) + X(2, int16 有符号大端) + Y(2, int16 有符号大端) + angle(1, 恒 0xFF)` |
| X/Y 单位 | `0.1 mm`，原点=装置中心，`|value| > 1350`（±135.0 mm）越界拒绝 |
| angle | 恒 `0xFF`（夹爪不旋转），`0..180` 本轮不用，不另加标志字节 |
| image_id | `== class_id`，1:1，active 集 `{0,2,3,4,5,6}`；编解码层只透传，不断言 |

### 已冻结且已在绿的外部事实（本轮不动，保持通过）

- CRC-16/MODBUS：`"123456789"` → `0x4B37`（`ec_crc16_modbus`）
- DISPLAY_ACK 内容 CRC-32/ISO-HDLC：`01 02 03 04 05` → `0x470B99F4`
- 外层帧 C/Python 字节一致：`A5 5A 01 02 03 12 34 00 07 21 00 03 AA BB CC B2 6F`

---

## 3. 本轮任务（待实施）

`interface-contract.md` V0.6 已把 ITEM_TASK 冻结为 8 字节，但两侧代码仍停在「3 字节身份前缀已冻结、X/Y/angle 未冻结」旧状态：

- **C 侧** `ec_proto_item_task_t` 只解 `target_seq/class_id/image_id`，X/Y/angle 用 `unfrozen/unfrozen_len` 保留 opaque，无配套 encode，无越界拒绝。
- **Python 侧** `ItemTaskPayload` 三个 `_u8` 校验，`x_position/y_position/grip_angle` 未校验；`encode_item_task_payload` 直接 `raise ContractNotFrozen`。

---

## 4. 金标向量（跨语言一致，两侧各断言一次）

| 用例 | 值 (mm) | 十进制 | X/Y 字节 | 说明 |
|---|---|---|---|---|
| +100.0 mm | +1000 | `03 E8` | 正样本 |
| −100.0 mm | −1000 | `FC 18` | 负样本（补码：~0x03E8+1） |
| +135.0 mm | +1350 | `05 46` | 正边界（接受） |
| −135.0 mm | −1350 | `FA BA` | 负边界（接受：~0x0546+1） |
| +135.1 mm | +1351 | — | 越界（拒绝） |
| −135.1 mm | −1351 | — | 越界（拒绝） |
| 角度 ≠ 0xFF | — | — | 拒绝 |

**完整 8 字节样例**（image_id==class_id=2）：
`target_seq=1, class_id=2, image_id=2, X=−100.0mm, Y=+100.0mm, angle=0xFF`
→ `01 02 02 FC 18 03 E8 FF`

---

## 5. 剩余实施步骤（精确文件清单）

### C 侧（`电控/stm32_logic/`，纯逻辑无 HAL）

1. `include/ec_protocol.h`（现 133 行，ITEM_TASK 段 116-131）
   - 删 `unfrozen/unfrozen_len`，改结构体为 `target_seq/class_id/image_id/x_mm10(int16_t)/y_mm10(int16_t)/grip_angle(uint8_t)`。
   - 常量：`EC_PROTO_ITEM_TASK_PAYLOAD_LEN 8U`、`EC_PROTO_ITEM_TASK_X_LIMIT 1350`、`EC_PROTO_ITEM_TASK_ANGLE_NONE 0xFF`（替换 `EC_PROTO_ITEM_TASK_FROZEN_LEN 3U`）。
   - 新增 `bool ec_proto_encode_item_task(const ec_proto_item_task_t *item, uint8_t *payload, uint16_t cap)` 声明。
2. `src/ec_protocol.c`（现 153 行，decode 段 140-152）
   - `ec_proto_decode_item_task`：要求 `payload_len == 8` 否则 false；大端 int16 用显式字节运算 `(int16_t)(((uint16_t)p[3]<<8)|p[4])`（**勿 `*(int16_t*)` 直接解引用**，规避小端 ARM 端序错）；校验 `|x|<=1350`、`|y|<=1350`、`angle==0xFF`，任一不满足 false。
   - 新增 `ec_proto_encode_item_task`（镜像 `ec_proto_encode_display_ack` 的 encode/decode 成对模板）。
3. `src/ec_protocol_gateway.c` + `include/ec_protocol_gateway.h` — 只消费 `target_seq/class_id/image_id`（91-93 行），已核实不引用 `unfrozen` 字段，**多半无需改动**，实现时确认即可。
4. `tests/test_protocol.c`（P-ITEM-001，133-159 行）— 重写为 8 字节金标。
5. `tests/test_protocol_gateway.c` — 4 处 `uint8_t payload[3]` 改 `payload[8]` 并填合法 X/Y/angle（`00 00 00 00 FF`）；`test_boot_and_frame_assembly` 现 `payload[8]` 内 `DE AD BE EF 2D` 会解成 X=0xDEAD 越界被拒，须改合法值。
6. `电控/firmware/stm32f407_m144z/tests/test_protocol.c`（ITEM_TASK 段 124-144）— 编译同一份 `ec_protocol.c`，用 `TEST_ASSERT` 风格镜像金标。

### Python 侧（`电控/src/electrical_control/protocol/`）

7. `item_context.py` — 实现 `encode_item_task_payload`（返回 8 字节）+ 新增 `decode_item_task_payload`，校验放**编解码边界**（见 §6 决策）。序列化用 `x.to_bytes(2, "big", signed=True)`，不引入 `struct`。
8. `frames.py`（`encode_item_task_frame`，70-100 行）— 现收 `identity_prefix + unfrozen_payload`，改为收完整 8 字节载荷，内部 `payload[:3] / payload[3:]`（或等价重构，对外字节不变）。
9. `__init__.py` — 增导出 `decode_item_task_payload`。
10. `errors.py` — `ContractNotFrozen` 类保留（`codec.py` 仍在用），但不再对 ITEM_TASK 抛。

### Python 测试（`电控/tests/`）

11. `protocol/test_item_task_identity.py`（36-41 行）— 删 `ContractNotFrozen` 断言，改为 8 字节金标。
12. `protocol/test_frames.py`（`ItemTaskFrameTests`，61-81 行）— 适配完整载荷语义。
13. `protocol/test_protocol_v04_enhanced_a.py`（`ItemTaskV04PayloadTests` 16-27、`DisplayContentFromItemResultTests` 109-116 行）— 两处构造 `x=0x1234/y=0x5678/grip_angle=90` 且断言 `ContractNotFrozen`，须重写为合法金标或负向用例。
14. `rpi/test_vision_ingest.py`（5、49-50 行）— 删 `ContractNotFrozen` 断言。

---

## 6. ⚠️ 关键发现：`grip_angle == 0xFF` 校验的涟漪（计划低估）

已批准计划写的是「`ItemTaskPayload.__post_init__` 增加 `grip_angle == 0xFF` 校验」。**这会在 `__post_init__` 里炸掉 ~13 处构造点**，计划只列了 `test_frames.py`/`test_item_task_identity.py`，漏了下面这些：

- **生产代码** `rpi/vision_ingest.py:79-86` — `build_item_task_queue` 用 `x_position=0, y_position=0, grip_angle=0` 作占位（该模块注释明确「logical layer, never emits serial frame」）。
- **`grip_angle=0` 的测试**（若 `__post_init__` 校验即全部失败）：
  - `integration/test_control_flow_guard.py`（47、48、243、267、268、302、303 共 7 处）
  - `rpi/test_boundaries_and_public_api.py:11`
  - `rpi/test_gateway.py:30`
  - `rpi/test_fake_source_and_recovery.py:10`
  - `rpi/test_scheduler_rendering.py:23、135`
  - `rpi/test_offline_main_chain.py:30`
- **`grip_angle=90` / `grip_angle=0x2D` + 越界 x/y**：`protocol/test_protocol_v04_enhanced_a.py:22、115`、`protocol/test_item_task_identity.py:37`（`x=0x1234=4660`、`y=0x5678=22136` 本身也越界）。

### 建议裁决（推荐方案 A）

**A（推荐）：校验放编解码边界，不放 `__post_init__`。**
- `ItemTaskPayload.__post_init__` 保持现状（3 个 `_u8`），顶多加 `_u8("grip_angle", ...)`（0/90/0x2D/0xFF 都合法，安全）。
- `encode_item_task_payload` / `decode_item_task_payload` 里做 `|x|<=1350`、`|y|<=1350`、`grip_angle==0xFF` 校验，违规抛 `PayloadError`。
- 理由：`ItemTaskPayload` 是逻辑载体，占位 0/0/0 是合法中间态（落点表未到）；冻结规则只在线格式边界强制。`vision_ingest` 从不编码，故不受影响。

**B（按原计划）：校验放 `__post_init__`。**
- 需要把 §6 列出的全部 ~13 处占位构造改成 `grip_angle=0xFF`（且 x/y 落在 ±1350 内），同时 `vision_ingest.py` 生产代码也要改占位值。
- 代价大、且违背「物理量先不管」的中间态语义，不推荐。

> 本交接稿未替用户做此裁决，推荐 A，但落 A 或 B 都需在实施时一并收口 §5 的测试改动。

---

## 7. 验证命令（V3：全量，两侧）

环境坑：本机 `PATH` 里 `/d/Scripts/cmake.exe` 是坏的 venv launcher，会遮蔽真实 cmake（`/d/cmake/bin/cmake.exe` v4.4.0）。**用绝对路径，不改用户 PATH**。

```bash
# C 逻辑（电控/stm32_logic/）
/d/cmake/bin/cmake.exe -S 电控/stm32_logic -B 电控/stm32_logic/build -G "Visual Studio 17 2022"
/d/cmake/bin/cmake.exe --build 电控/stm32_logic/build --config Release
ctest --test-dir 电控/stm32_logic/build -C Release --output-on-failure

# 固件主机测试（电控/firmware/stm32f407_m144z/tests/）
/d/cmake/bin/cmake.exe -S 电控/firmware/stm32f407_m144z/tests -B 电控/firmware/stm32f407_m144z/tests/build -G "Visual Studio 17 2022"
/d/cmake/bin/cmake.exe --build 电控/firmware/stm32f407_m144z/tests/build --config Release
ctest --test-dir 电控/firmware/stm32f407_m144z/tests/build -C Release --output-on-failure

# Python（仓库根，PYTHONPATH=电控/src）
PYTHONPATH=电控/src python -m unittest discover -s 电控/tests/protocol -v
PYTHONPATH=电控/src python -m unittest discover -s 电控/tests/rpi -v
PYTHONPATH=电控/src python -m unittest discover -s 电控/tests/integration -v
```

完成标准：
- C 逻辑全绿（现 55 项 + 新增金标/负向用例）；固件主机测试全绿（128 项内）。
- Python protocol/rpi/integration 三组全绿（现 46 + 37 + 14）。
- C 与 Python 各自断言同一 8 字节样例 `01 02 02 FC 18 03 E8 FF` 与正/负边界字节。
- C 编译 `-Wall -Wextra -Wpedantic -Werror`（gcc）或 `/W4 /WX`（MSVC）0 告警；C 源保持 ASCII（避开 C4819）。

---

## 8. 红线约束（用户原话，不可违）

> 「上机前主机侧能做的已经做完了，仍保持不碰屏幕、串口、STM32 和实机。」

- 本轮只改纯逻辑源码 + 主机离线测试，**不产生任何串口/屏幕/电机/实机通过声明**。
- 落点表物理量、时序参数缺位不影响本任务（X/Y 用测试样本金标占位，落点表到位后再填）。

---

## 9. 下一步

1. 用户裁决 §6 的 A/B 后，按 §5 顺序实施（先 C 后 Python，最后跨语言对账）。
2. 改完跑 §7 全量验证，产出 `docs/reports/` 下新证据稿（如 `2026-08-25-item-task-codec-evidence.md`）。
3. 更新 `docs/design/2026-08-25-rpi-pre-hardware-freeze-list.md` 状态行（ITEM_TASK 从「已签字冻结」改为「已落地实现」）。
