# ITEM_TASK 8-byte payload codec evidence (C + Python)

Date: 2026-08-25
Scope: host-side pure logic and offline tests only.
No serial port, display, STM32 firmware flash, motor, wiring, or hardware run is
claimed by this record.

## Decision

`grip_angle == 0xFF` (and X/Y range) validation lives at the **encode/decode
wire boundary** (Plan A), not in `ItemTaskPayload.__post_init__`. The payload
class stays a loose logical carrier — placeholder `0/0/0` is a valid
intermediate state until the drop table lands. Only the frozen wire format is
enforced, in both `encode_item_task_payload` / `decode_item_task_payload`
(Python) and `ec_proto_encode_item_task` / `ec_proto_decode_item_task` (C).

## Change summary

Landed the full 8-byte ITEM_TASK payload codec on both sides, replacing the old
"3-byte identity prefix + opaque tail" state.

C side (`电控/stm32_logic/`, pure logic, no HAL):

- `include/ec_protocol.h` — `ec_proto_item_task_t` now
  `target_seq/class_id/image_id/x_mm10(int16_t)/y_mm10(int16_t)/grip_angle`;
  constants `EC_PROTO_ITEM_TASK_PAYLOAD_LEN 8U`, `EC_PROTO_ITEM_TASK_X_LIMIT 1350`,
  `EC_PROTO_ITEM_TASK_ANGLE_NONE 0xFF`; added `ec_proto_encode_item_task`.
- `src/ec_protocol.c` — `ec_proto_decode_item_task` requires `payload_len == 8`,
  big-endian int16 via explicit byte arithmetic (no `*(int16_t*)` dereference),
  rejects `|x|>1350`, `|y|>1350`, `angle != 0xFF`; added
  `ec_proto_encode_item_task` mirroring the display-ack encode/decode pair.
- `src/ec_protocol_gateway.c` / `include/ec_protocol_gateway.h` — unchanged
  (only consume `target_seq/class_id/image_id`).

Python side (`电控/src/electrical_control/`):

- `protocol/item_context.py` — implemented `encode_item_task_payload` and added
  `decode_item_task_payload`; validation at the boundary; serialize with
  `x.to_bytes(2, "big", signed=True)` (no `struct`).
- `protocol/frames.py` — `encode_item_task_frame` now takes a full 8-byte
  `payload` (was `identity_prefix` + `unfrozen_payload`).
- `protocol/__init__.py` — exported `decode_item_task_payload`.
- `rpi/vision_ingest.py` — docstring corrected (placeholder coordinates, not
  "unfrozen").
- `protocol/errors.py` — `ContractNotFrozen` retained (still used by `codec.py`
  for the still-unfrozen commands), no longer raised for ITEM_TASK.

## Frozen vectors verified (C and Python each assert the same bytes)

| case | value | decimal | X/Y bytes | result |
|---|---|---|---|---|
| +100.0 mm | +1000 | `03 E8` | accepted |
| −100.0 mm | −1000 | `FC 18` | accepted |
| +135.0 mm | +1350 | `05 46` | accepted (boundary) |
| −135.0 mm | −1350 | `FA BA` | accepted (boundary) |
| +135.1 mm | +1351 | — | rejected |
| −135.1 mm | −1351 | — | rejected |
| angle ≠ 0xFF | — | — | rejected |

Full 8-byte golden (image_id == class_id == 2):
`target_seq=1, class_id=2, image_id=2, X=−100.0 mm, Y=+100.0 mm, angle=0xFF`
→ `01 02 02 FC 18 03 E8 FF`.

## Commands and results

All offline, host-only.

```
C logic (电控/stm32_logic/):            58 tests passed
C firmware host (stm32f407_m144z/tests): 3 test executables passed
Python protocol (电控/tests/protocol):  49 tests passed
Python rpi (电控/tests/rpi):            37 tests passed
Python integration (电控/tests/integration): 14 tests passed
```

Cross-language parity: `P-ITEM-001..004` (C) and
`test_full_payload_round_trips_frozen_8_byte_golden`,
`test_boundary_coordinates_encode_big_endian`,
`test_out_of_range_and_bad_angle_reject_at_wire_boundary` (Python) assert the
same golden `01 02 02 FC 18 03 E8 FF` and boundary bytes `05 46` / `FA BA`, and
the same reject conditions.

## Remaining (out of scope, unchanged)

- Drop-table physical quantities (basket radius R, angle convention, class→basket
  assignment) — still not provided; X/Y use golden test samples as placeholders.
- Timing / timeout / retry / heartbeat — still candidates for bench test.
- Serial port, display, STM32 flash, motor, wiring, real hardware run — untouched.
