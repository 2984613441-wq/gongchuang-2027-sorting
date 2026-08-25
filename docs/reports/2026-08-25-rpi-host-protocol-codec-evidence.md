# Host-only RPi protocol codec evidence

Date: 2026-08-25
Scope: host-side pure logic and offline tests only.
No serial port, display, STM32 firmware flash, motor, wiring, or hardware run is
claimed by this record.

## Change summary

Added the Python-side V0.5 unified outer-frame codec and a small logical vision
ingest layer. No unfrozen ITEM_TASK X/Y/angle wire bytes, timeout, retry,
heartbeat, screen, or power parameter was invented.

Changed or added files:

- `电控/src/electrical_control/protocol/outer_frame.py` (new)
- `电控/src/electrical_control/protocol/item_context.py`
- `电控/src/electrical_control/protocol/types.py`
- `电控/src/electrical_control/protocol/__init__.py`
- `电控/src/electrical_control/rpi/vision_ingest.py` (new)
- `电控/src/electrical_control/rpi/__init__.py`
- `电控/src/electrical_control/protocol/frames.py` (new)
- `电控/src/electrical_control/rpi/gateway.py` (new)
- `电控/src/electrical_control/rpi/log.py` (new)
- `电控/tests/protocol/test_outer_frame.py` (new)
- `电控/tests/protocol/test_item_task_identity.py` (new)
- `电控/tests/protocol/test_frames.py` (new)
- `电控/tests/rpi/test_vision_ingest.py` (new)
- `电控/tests/rpi/test_gateway.py` (new)
- `电控/tests/rpi/test_log.py` (new)
- `电控/tests/rpi/test_offline_main_chain.py` (new)
- `电控/stm32_logic/tests/frame_vector_cli.c` (new)

Related decision record:

- `docs/design/2026-08-25-rpi-pre-hardware-freeze-list.md` (new)

## Frozen vectors verified

- CRC-16/MODBUS: `b"123456789"` -> `0x4B37`.
- DISPLAY_ACK display-content CRC-32/ISO-HDLC: `01 02 03 04 05` -> `0x470B99F4`.
- Outer frame from Python and from C are byte-identical:
  `A5 5A 01 02 03 12 34 00 07 21 00 03 AA BB CC B2 6F`.
- ITEM_TASK frozen identity prefix: `target_seq + class_id + image_id`, three
  bytes, with the remaining payload kept opaque.
- DISPLAY_ACK full outer frame from the Pi: `task_id=7`, `frame_seq=21`,
  `target_seq=1`, `render_result=0x00`, `content_crc32=0x470B99F4` encodes to
  `A5 5A 01 02 03 00 07 00 15 25 00 06 01 00 47 0B 99 F4 85 32`.

## Commands and results

Python (from repository root, `PYTHONPATH=电控/src`):

- `python -m unittest discover -s 电控/tests/protocol -v`: 46 tests OK.
- `python -m unittest discover -s 电控/tests/rpi -v`: 37 tests OK.
- `python -m unittest discover -s 电控/tests/integration -v`: 14 tests OK.
- `python -m unittest discover -s 电控/tests/state_machine -v`: 19 tests OK.
- `python -m unittest discover -s 电控/tests/drivers -v`: 12 tests OK.

The four electrical-control groups total 128 host tests. The offline main-chain
test drives two complete `BARRIER_READY -> MOTION_DONE -> ITEM_RESULT -> render
receipt -> DISPLAY_ACK` cycles at the byte level using a fake STM32 peer.

Vision (from repository root, `PYTHONPATH=视觉/src`):

- `python -m unittest discover -s 视觉/tests -v`: 45 tests OK.

STM32 logic C (gcc `-std=c11 -Wall -Wextra -Wpedantic -Werror`):

- Compile and run the existing test suite: `ALL 55 STM32 LOGIC TESTS PASSED`.
- `frame_vector_cli.c` emits the same outer-frame bytes as the Python reference.

The Pi gateway assembles STM32 -> Pi frames byte-by-byte, resyncs on `0xA5 0x5A`,
checks Scheme-B direction, deduplicates by `(task_id, frame_seq)`, decodes
`BARRIER_READY`, `MOTION_DONE`, `ITEM_RESULT`, and `ESTOP`, and encodes the first
valid `DISPLAY_ACK` only after an explicit render receipt. No screen, serial, or
motion adapter is involved.

## Boundaries

The outer-frame codec is device-agnostic and command-agnostic. Command payload
parsing remains in the higher-level codecs. The vision ingest layer is logical
and never emits a serial frame. `ITEM_TASK` X/Y/angle wire encoding still raises
`ContractNotFrozen`.
