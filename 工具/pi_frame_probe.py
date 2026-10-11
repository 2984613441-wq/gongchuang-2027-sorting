#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动发合法 ITEM_TASK 并**正确解码板子的二进制应答帧**，把时序钉死。

上一版把板子的二进制帧当 ASCII 打印，看起来像"没回话"，实际是解码错了。
本版：扫出 0xA5 0x5A 帧并逐字段解出来（命令 / task_id / frame_seq / 载荷）。

零运动风险：ITEM_TASK 只推进启动序列与状态机（POST->HOMING->BARRIER->WAIT_TASK
->VALIDATE_TASK），HOMING 按方案 A 不移动（ec_startup_sequence.c:91-94）；
必须再收到 DISPLAY_ACK 才可能进入运动，本脚本不发。
"""

import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200

HDR0, HDR1, VER = 0xA5, 0x5A, 0x01
DEV_PI, DEV_STM32, DEV_MAIXCAM = 0x02, 0x03, 0x01
CMD_ITEM_TASK = 0x21

CMD_NAMES = {
    0x01: "HEARTBEAT", 0x02: "HEARTBEAT_ACK", 0x03: "DEVICE_READY",
    0x04: "ERROR", 0x05: "ACK", 0x06: "NACK", 0x10: "BATCH_TARGETS",
    0x20: "BARRIER_READY", 0x21: "ITEM_TASK", 0x22: "MOTION_DONE",
    0x23: "ITEM_RESULT", 0x24: "DISPLAY_DATA", 0x25: "DISPLAY_ACK",
    0x26: "ESTOP",
}
ACK_REASONS = {0x00: "ACCEPTED", 0x01: "ACK_CONSUMED"}
NACK_REASONS = {0x01: "WRONG_ROUND", 0x02: "SINGLE_TASK_ONLY",
                0x03: "TASK_REJECTED"}


def crc16_modbus(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def _i16(v):
    return int(v).to_bytes(2, "big", signed=True)


def item_task_payload(target_seq, class_id, x_mm10, y_mm10, pick_x_mm10,
                      pick_y_mm10):
    return (bytes((target_seq & 0xFF, class_id & 0xFF, class_id & 0xFF))
            + _i16(x_mm10) + _i16(y_mm10) + b"\xff"
            + _i16(pick_x_mm10) + _i16(pick_y_mm10))


def build_frame(task_id, frame_seq, command, payload):
    body = (bytes((HDR0, HDR1, VER, DEV_PI, DEV_STM32))
            + int(task_id).to_bytes(2, "big")
            + int(frame_seq).to_bytes(2, "big")
            + bytes((command,))
            + len(payload).to_bytes(2, "big"))
    frame = body + payload
    return frame + crc16_modbus(frame).to_bytes(2, "big")


def drain(port, seconds):
    end = time.time() + seconds
    out = bytearray()
    while time.time() < end:
        waiting = port.in_waiting
        chunk = port.read(waiting if waiting else 1)
        if chunk:
            out.extend(chunk)
        else:
            time.sleep(0.02)
    return bytes(out)


def describe(data):
    """把字节流里的二进制帧解出来，同时保留 ASCII 文本行。"""
    frames = []
    chunks = []
    i = 0
    text_start = 0
    while i < len(data) - 1:
        if data[i] == HDR0 and data[i + 1] == HDR1 and i + 14 <= len(data):
            data_len = int.from_bytes(data[i + 10:i + 12], "big")
            total = 12 + data_len + 2
            if i + total <= len(data):
                blob = data[i:i + total]
                if crc16_modbus(blob[:-2]) == int.from_bytes(blob[-2:], "big"):
                    chunks.append(data[text_start:i])
                    frames.append(blob)
                    i += total
                    text_start = i
                    continue
        i += 1
    chunks.append(data[text_start:])

    for blob in frames:
        cmd = blob[9]
        name = CMD_NAMES.get(cmd, "CMD_0x%02X" % cmd)
        payload = blob[12:-2]
        extra = ""
        if cmd in (0x05, 0x06) and len(payload) >= 2:
            table = ACK_REASONS if cmd == 0x05 else NACK_REASONS
            extra = " reason=%s target_seq=%d" % (
                table.get(payload[0], "REASON_0x%02X" % payload[0]), payload[1])
        print("    [帧] %-14s task_id=%d frame_seq=%d payload=%s%s" % (
            name,
            int.from_bytes(blob[5:7], "big"),
            int.from_bytes(blob[7:9], "big"),
            " ".join("%02X" % b for b in payload) or "-",
            extra,
        ))

    for chunk in chunks:
        for line in chunk.decode("ascii", "replace").splitlines():
            line = "".join(ch for ch in line if 32 <= ord(ch) < 127).strip()
            if not line:
                continue
            if line.startswith("STATUS"):
                fields = dict(
                    part.split("=", 1) for part in line.split() if "=" in part)
                print("    [STATUS] APP_STATE=%s" % fields.get("APP_STATE", "?"))
            else:
                print("    [文本] " + line[:120])


def main():
    plan = [(1, 10), (1, 10), (2, 11), (99, 12)]
    if len(sys.argv) > 1:
        plan = []
        for spec in sys.argv[1:]:
            tid, fseq = spec.split(":")
            plan.append((int(tid), int(fseq)))

    port = serial.Serial(PORT, BAUD, timeout=0.3)
    time.sleep(0.3)

    print("--- 基线（未发任何东西）---")
    describe(drain(port, 2.2))

    port.write(b"PING\r\n")
    print("--- PING ---")
    describe(drain(port, 1.2))

    for task_id, frame_seq in plan:
        payload = item_task_payload(
            target_seq=3, class_id=6,
            x_mm10=50, y_mm10=50,
            pick_x_mm10=0, pick_y_mm10=-450,
        )
        frame = build_frame(task_id, frame_seq, CMD_ITEM_TASK, payload)
        print("=== 发 ITEM_TASK task_id=%d frame_seq=%d ===" % (task_id, frame_seq))
        port.reset_input_buffer()
        port.write(frame)
        describe(drain(port, 3.0))

    port.close()
    print("=== 探针结束 ===")


if __name__ == "__main__":
    main()
