#!/usr/bin/env python3
"""Host-only C/Python ITEM_TASK 12-byte vector compare. Does not touch protocol sources.

Usage (from repo root or anywhere):
    py -3 docs/reports/_grok_item_task_vector_host.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent
_LOGIC = _REPO / "电控" / "stm32_logic"
sys.path.insert(0, str(_REPO / "电控" / "src"))

from electrical_control.protocol import (  # noqa: E402
    Device,
    ItemTaskPayload,
    OuterFrame,
    PayloadError,
    VERSION,
    crc16_modbus,
    decode_item_task_payload,
    decode_outer_frame,
    encode_item_task_frame,
    encode_item_task_payload,
    encode_outer_frame,
)

C_SRC = r"""
#include "ec_protocol.h"
#include <stdio.h>
#include <string.h>
#include <stdint.h>

static void print_hex(const uint8_t *data, size_t len)
{
    size_t i;
    for (i = 0U; i < len; ++i) {
        (void)printf("%02X%s", data[i], (i + 1U < len) ? " " : "");
    }
}

static int encode_named(const char *name, uint8_t target_seq, uint8_t class_id,
                        uint8_t image_id, int16_t x, int16_t y, uint8_t grip,
                        int16_t pick_x, int16_t pick_y, uint16_t task_id,
                        uint16_t frame_seq)
{
    ec_proto_item_task_t item;
    ec_proto_frame_t frame;
    uint8_t payload[EC_PROTO_ITEM_TASK_PAYLOAD_LEN];
    uint8_t buf[64];
    size_t written;

    (void)memset(&item, 0, sizeof(item));
    item.target_seq = target_seq;
    item.class_id = class_id;
    item.image_id = image_id;
    item.x_mm10 = x;
    item.y_mm10 = y;
    item.grip_angle = grip;
    item.pick_x_mm10 = pick_x;
    item.pick_y_mm10 = pick_y;

    if (!ec_proto_encode_item_task(&item, payload, sizeof(payload))) {
        (void)printf("%s ENCODE_REJECT\n", name);
        return 0;
    }

    frame.version = EC_PROTO_VERSION;
    frame.sender = EC_DEVICE_PI;
    frame.receiver = EC_DEVICE_STM32;
    frame.task_id = task_id;
    frame.frame_seq = frame_seq;
    frame.command = EC_CMD_ITEM_TASK;
    frame.payload = payload;
    frame.payload_len = (uint16_t)sizeof(payload);
    written = ec_proto_encode(&frame, buf, sizeof(buf));
    if (written == 0U) {
        (void)printf("%s FRAME_REJECT\n", name);
        return 1;
    }
    (void)printf("%s PAYLOAD ", name);
    print_hex(payload, sizeof(payload));
    (void)printf(" | FRAME ");
    print_hex(buf, written);
    (void)printf("\n");
    return 0;
}

static int decode_named(const char *name, const uint8_t *payload, uint16_t len)
{
    ec_proto_item_task_t item;
    if (!ec_proto_decode_item_task(payload, len, &item)) {
        (void)printf("%s DECODE_REJECT\n", name);
        return 0;
    }
    (void)printf("%s DECODE_ACCEPT ts=%u cid=%u iid=%u x=%d y=%d grip=0x%02X px=%d py=%d\n",
                 name, (unsigned)item.target_seq, (unsigned)item.class_id,
                 (unsigned)item.image_id, (int)item.x_mm10, (int)item.y_mm10,
                 (unsigned)item.grip_angle, (int)item.pick_x_mm10,
                 (int)item.pick_y_mm10);
    return 0;
}

int main(void)
{
    uint8_t crc_vec[] = {'1','2','3','4','5','6','7','8','9'};
    uint16_t crc = ec_crc16_modbus(crc_vec, sizeof(crc_vec));
    (void)printf("CRC_GOLDEN 0x%04X\n", (unsigned)crc);

    if (encode_named("POS_EXT", 1, 4, 4, 1450, 1450, 0xFF, 1450, 1450, 7, 1)) return 1;
    if (encode_named("NEG_EXT", 1, 4, 4, -1450, -1450, 0xFF, -1450, -1450, 7, 1)) return 1;
    if (encode_named("MIX_EXT", 1, 4, 4, 1450, -1450, 0xFF, -1450, 1450, 7, 1)) return 1;
    if (encode_named("BAD_ANGLE", 1, 4, 4, 50, 50, 0x00, 125, 54, 7, 1)) return 1;
    if (encode_named("REAL", 4, 4, 4, 50, 50, 0xFF, 125, 54, 7, 1)) return 1;
    if (encode_named("REAL_T7_F4", 4, 4, 4, 50, 50, 0xFF, 125, 54, 7, 4)) return 1;
    if (encode_named("IMG_NEQ", 1, 4, 9, 0, 0, 0xFF, 0, 0, 7, 1)) return 1;
    if (encode_named("TS0", 0, 4, 4, 0, 0, 0xFF, 0, 0, 7, 1)) return 1;
    if (encode_named("ZERO_PICK", 1, 4, 4, 50, 50, 0xFF, 0, 0, 7, 1)) return 1;

    {
        static const uint8_t bad_angle[] = {
            0x01, 0x04, 0x04, 0x00, 0x32, 0x00, 0x32, 0x00,
            0x00, 0x7D, 0x00, 0x36
        };
        static const uint8_t img_neq[] = {
            0x01, 0x04, 0x09, 0x00, 0x00, 0x00, 0x00, 0xFF,
            0x00, 0x00, 0x00, 0x00
        };
        static const uint8_t ts0[] = {
            0x00, 0x04, 0x04, 0x00, 0x00, 0x00, 0x00, 0xFF,
            0x00, 0x00, 0x00, 0x00
        };
        static const uint8_t old8[] = {
            0x01, 0x04, 0x04, 0x00, 0x32, 0x00, 0x32, 0xFF
        };
        static const uint8_t over[] = {
            0x01, 0x04, 0x04, 0x05, 0xAB, 0x00, 0x00, 0xFF,
            0x00, 0x00, 0x00, 0x00
        };
        (void)decode_named("BAD_ANGLE", bad_angle, (uint16_t)sizeof(bad_angle));
        (void)decode_named("IMG_NEQ", img_neq, (uint16_t)sizeof(img_neq));
        (void)decode_named("TS0", ts0, (uint16_t)sizeof(ts0));
        (void)decode_named("OLD8", old8, (uint16_t)sizeof(old8));
        (void)decode_named("OVER1451", over, (uint16_t)sizeof(over));
    }
    return 0;
}
"""


def _hex(data: bytes) -> str:
    return data.hex(" ").upper()


def py_encode(name, ts, cid, iid, x, y, grip, px, py, task_id=7, frame_seq=1):
    try:
        payload = encode_item_task_payload(
            ItemTaskPayload(
                target_seq=ts,
                class_id=cid,
                image_id=iid,
                x_position=x,
                y_position=y,
                grip_angle=grip,
                pick_x_position=px,
                pick_y_position=py,
            )
        )
    except (PayloadError, TypeError) as exc:
        return name, "ENCODE_REJECT", str(exc), None, None
    frame = encode_item_task_frame(task_id=task_id, frame_seq=frame_seq, payload=payload)
    return name, "ENCODE_OK", None, payload, frame


def py_decode(name, payload: bytes):
    try:
        item = decode_item_task_payload(payload)
    except PayloadError as exc:
        return name, "DECODE_REJECT", str(exc)
    return name, "DECODE_ACCEPT", item


def build_c(workdir: Path) -> Path:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if cc is None:
        raise SystemExit("NO_COMPILER")
    src = workdir / "vector_host.c"
    src.write_text(C_SRC, encoding="utf-8")
    exe = workdir / ("vector_host.exe" if os.name == "nt" else "vector_host")
    cmd = [
        cc, "-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Werror",
        "-I", str(_LOGIC / "include"),
        str(src),
        str(_LOGIC / "src" / "ec_protocol.c"),
        str(_LOGIC / "src" / "ec_crc32.c"),
        "-o", str(exe),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout + result.stderr)
        raise SystemExit("C_COMPILE_FAIL")
    return exe


def parse_c(stdout: str) -> dict:
    out = {"encode": {}, "decode": {}, "crc": None}
    for line in stdout.splitlines():
        if line.startswith("CRC_GOLDEN "):
            out["crc"] = line.split()[1]
            continue
        if " ENCODE_REJECT" in line:
            out["encode"][line.split()[0]] = ("ENCODE_REJECT", None, None)
            continue
        if " PAYLOAD " in line:
            name, rest = line.split(" PAYLOAD ", 1)
            payload_hex, frame_hex = rest.split(" | FRAME ")
            out["encode"][name] = ("ENCODE_OK", payload_hex.strip(), frame_hex.strip())
            continue
        if " DECODE_REJECT" in line:
            out["decode"][line.split()[0]] = ("DECODE_REJECT", line)
            continue
        if " DECODE_ACCEPT" in line:
            out["decode"][line.split()[0]] = ("DECODE_ACCEPT", line)
    return out


def main() -> int:
    failures = []
    workdir = Path(tempfile.mkdtemp(prefix="grok-item-task-"))
    exe = build_c(workdir)
    c_run = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
    c = parse_c(c_run.stdout)
    print("C_STDOUT_BEGIN")
    print(c_run.stdout.rstrip())
    print("C_STDOUT_END")
    print()
    print(f"CRC16('123456789') C={c['crc']} Py=0x{crc16_modbus(b'123456789'):04X}")
    if c["crc"] != f"0x{crc16_modbus(b'123456789'):04X}":
        failures.append("CRC golden mismatch")

    accept_vecs = [
        ("POS_EXT", 1, 4, 4, 1450, 1450, 0xFF, 1450, 1450, 7, 1),
        ("NEG_EXT", 1, 4, 4, -1450, -1450, 0xFF, -1450, -1450, 7, 1),
        ("MIX_EXT", 1, 4, 4, 1450, -1450, 0xFF, -1450, 1450, 7, 1),
        ("REAL", 4, 4, 4, 50, 50, 0xFF, 125, 54, 7, 1),
        ("REAL_T7_F4", 4, 4, 4, 50, 50, 0xFF, 125, 54, 7, 4),
        ("ZERO_PICK", 1, 4, 4, 50, 50, 0xFF, 0, 0, 7, 1),
    ]
    print()
    print("=== ACCEPT encode byte-compare ===")
    for vec in accept_vecs:
        name = vec[0]
        _, status, err, payload, frame = py_encode(*vec)
        c_status, c_payload, c_frame = c["encode"][name]
        same = status == "ENCODE_OK" and c_status == "ENCODE_OK" and c_payload == _hex(payload) and c_frame == _hex(frame)
        print(f"[{name}] C={c_status} Py={status} same={same}")
        if payload is not None:
            print(f"  Py payload: {_hex(payload)}")
            print(f"  C  payload: {c_payload}")
            print(f"  Py frame  : {_hex(frame)}")
            print(f"  C  frame  : {c_frame}")
            decoded = decode_outer_frame(frame)
            print(f"  roundtrip outer: sender={int(decoded.sender):02X} recv={int(decoded.receiver):02X} "
                  f"task={decoded.task_id} seq={decoded.frame_seq} cmd={decoded.command:02X} dlen={len(decoded.payload)}")
        else:
            print(f"  Py err: {err}")
        if not same:
            failures.append(f"{name} byte mismatch")

    print()
    print("=== REJECT encode ===")
    _, st, err, _, _ = py_encode("BAD_ANGLE", 1, 4, 4, 50, 50, 0x00, 125, 54)
    c_st = c["encode"]["BAD_ANGLE"][0]
    print(f"[BAD_ANGLE] C={c_st} Py={st} err={err}")
    if c_st != "ENCODE_REJECT" or st != "ENCODE_REJECT":
        failures.append("BAD_ANGLE not rejected both sides")

    try:
        encode_item_task_payload(
            ItemTaskPayload(4, 4, 4, 50, 50, 0xFF, None, None)
        )
        py_none = "ENCODE_OK"
        py_none_err = None
    except PayloadError as exc:
        py_none = "ENCODE_REJECT"
        py_none_err = str(exc)
    print(f"[NO_PICK] C=NO_NONE_API (zeroed pick would encode as 00 00) Py={py_none} err={py_none_err}")
    if py_none != "ENCODE_REJECT":
        failures.append("NO_PICK python did not reject")

    print()
    print("=== SEMANTIC DIFF probes ===")
    _, st, err, payload, frame = py_encode("IMG_NEQ", 1, 4, 9, 0, 0, 0xFF, 0, 0)
    print(f"[IMG_NEQ encode] C={c['encode']['IMG_NEQ'][0]} Py={st} err={err}")
    _, st, err, payload, frame = py_encode("TS0", 0, 4, 4, 0, 0, 0xFF, 0, 0)
    print(f"[TS0 encode] C={c['encode']['TS0'][0]} Py={st} err={err}")

    probes = {
        "BAD_ANGLE": bytes.fromhex("01 04 04 00 32 00 32 00 00 7D 00 36"),
        "IMG_NEQ": bytes.fromhex("01 04 09 00 00 00 00 FF 00 00 00 00"),
        "TS0": bytes.fromhex("00 04 04 00 00 00 00 FF 00 00 00 00"),
        "OLD8": bytes.fromhex("01 04 04 00 32 00 32 FF"),
        "OVER1451": bytes.fromhex("01 04 04 05 AB 00 00 FF 00 00 00 00"),
    }
    print()
    print("=== DECODE probes ===")
    for name, raw in probes.items():
        py_name, py_st, py_detail = py_decode(name, raw)
        c_st, c_detail = c["decode"][name]
        print(f"[{name}] C={c_st} Py={py_st}")
        print(f"  C : {c_detail}")
        print(f"  Py: {py_detail}")

    print()
    print("=== REAL payload independent rebuild ===")
    real = ItemTaskPayload(4, 4, 4, 50, 50, 0xFF, 125, 54)
    real_payload = encode_item_task_payload(real)
    print(f"payload 12B: {_hex(real_payload)}")
    print(f"fields: ts=4 cid=4 iid=4 drop_mm10=(50,50) grip=FF pick_mm10=(125,54)")
    for task_id, frame_seq in ((7, 1), (7, 4)):
        frame = encode_item_task_frame(task_id=task_id, frame_seq=frame_seq, payload=real_payload)
        body = frame[:-2]
        crc = int.from_bytes(frame[-2:], "big")
        print(f"envelope task_id={task_id} frame_seq={frame_seq} len={len(frame)}")
        print(f"  frame: {_hex(frame)}")
        print(f"  crc16_modbus(header+payload)=0x{crc:04X} bytes={frame[-2]:02X} {frame[-1]:02X}")
        print(f"  verify decode_outer_frame OK={decode_outer_frame(frame).payload == real_payload}")

    print()
    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1
    print("HOST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
