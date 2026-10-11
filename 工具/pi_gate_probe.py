#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FAULT_LOCK 静默门限探针：用链路**生产类** PySerialLink 直接问板子。

为什么要有它（2026-09-18）：
    同一条链、同一个端口，04:13 那次日志里有入站帧（BARRIER_READY / ACK /
    DUPLICATE），04:14 那次 35 秒零入站。要把两种假设分开：
        H1  Pi 侧读不出板子的二进制帧（链路代码问题）
        H2  板子压根没回（固件状态机问题）
    本脚本收发都用链路真正在跑的那个类
    (electrical_control.rpi.serial_link_serial.PySerialLink)，
    不是另写的解码器 —— 所以它的结果直接代表链路的能力。

模式：
    selftest                  离线自检（不碰串口）：已知帧 → 解码器
    passive <秒>              只读，不发任何字节
    status                    发 ASCII INPUTS/STATUS，原始读回（含 APP_STATE）
    item <task_id> <seq> [秒] 用 PySerialLink 发**一条** ITEM_TASK 并解码应答

🔴 安全：item 模式一次只发一条。板子处于 FAULT_LOCK 时，单条 ITEM_TASK
   不产生任何运动（板子端必须先 ACK 才 VALIDATE_TASK→EXECUTING）。但
   **同一轮里第二条被接受的 ITEM_TASK 会立刻启动运动**（实机 04:13 已复现：
   第 1 发只回 BARRIER_READY，第 2 发同样字节回 ACK → 开始运动）。
   所以本脚本一次一条，发几条必须由操作者决定，绝不循环重发。
"""

import sys
import time

sys.path.insert(0, "/home/pi/电控/src")

import serial  # noqa: E402

from electrical_control.protocol import (  # noqa: E402
    CRC_LEN,
    HEADER_LEN,
    ItemTaskPayload,
    crc16_modbus,
    encode_item_task_frame,
    encode_item_task_payload,
)
from electrical_control.rpi.serial_link_serial import PySerialLink  # noqa: E402

PORT = "/dev/serial0"
BAUD = 115200

CMD_NAMES = {
    0x01: "HEARTBEAT", 0x02: "HEARTBEAT_ACK", 0x03: "DEVICE_READY",
    0x04: "ERROR", 0x05: "ACK", 0x06: "NACK", 0x10: "BATCH_TARGETS",
    0x20: "BARRIER_READY", 0x21: "ITEM_TASK", 0x22: "MOTION_DONE",
    0x23: "ITEM_RESULT", 0x24: "DISPLAY_DATA", 0x25: "DISPLAY_ACK",
    0x26: "ESTOP",
}
ACK_REASONS = {0x00: "ACCEPTED", 0x01: "ACK_CONSUMED"}
NACK_REASONS = {
    0x10: "STALE_OR_ORDER", 0x12: "SINGLE_TASK_ONLY",
    0x14: "WRONG_ROUND", 0x15: "TASK_REJECTED",
}


def decode_frames(buf):
    """扫出 buf 里所有 CRC 合法的外层帧（字节流可能混着 ASCII STATUS 文本）。"""
    out = []
    i = 0
    while i + HEADER_LEN + CRC_LEN <= len(buf):
        if buf[i] == 0xA5 and buf[i + 1] == 0x5A and buf[i + 2] == 0x01:
            data_len = (buf[i + 10] << 8) | buf[i + 11]
            total = HEADER_LEN + data_len + CRC_LEN
            if data_len <= 512 and i + total <= len(buf):
                blob = bytes(buf[i:i + total])
                if crc16_modbus(blob[:-CRC_LEN]) == int.from_bytes(
                        blob[-CRC_LEN:], "big"):
                    out.append(blob)
                    i += total
                    continue
        i += 1
    return out


def describe(blob):
    """把一条合法帧解成人看的行（命令 / task_id / frame_seq / 载荷 / ACK 原因）。"""
    cmd = blob[9]
    name = CMD_NAMES.get(cmd, "CMD_0x%02X" % cmd)
    task_id = int.from_bytes(blob[5:7], "big")
    frame_seq = int.from_bytes(blob[7:9], "big")
    payload = blob[HEADER_LEN:-CRC_LEN]
    extra = ""
    if cmd in (0x05, 0x06) and len(payload) >= 2:
        table = ACK_REASONS if cmd == 0x05 else NACK_REASONS
        extra = " reason=%s target_seq=%d" % (
            table.get(payload[0], "REASON_0x%02X" % payload[0]), payload[1])
    return "[帧] %-14s task_id=%d frame_seq=%d payload=%s%s" % (
        name, task_id, frame_seq,
        " ".join("%02X" % b for b in payload) or "-", extra)


def drain_raw(port, seconds):
    buf = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        waiting = port.in_waiting
        chunk = port.read(waiting if waiting else 1)
        if chunk:
            buf.extend(chunk)
    return bytes(buf)


def mode_selftest():
    """离线自检：生产编码器造帧 → 本文件解码器，必须逐字段还原。"""
    payload = ItemTaskPayload(
        target_seq=7, class_id=6, image_id=6, x_position=50, y_position=50,
        grip_angle=0xFF, pick_x_position=0, pick_y_position=-450,
    )
    frame = encode_item_task_frame(
        task_id=1, frame_seq=42, payload=encode_item_task_payload(payload))
    frames = decode_frames(b"junk STATUS ...\r\n" + frame + b"trailing")
    assert len(frames) == 1, frames
    assert frames[0] == frame, (frames[0].hex(), frame.hex())
    print("selftest OK:", describe(frame))
    return 0


def mode_passive(seconds):
    port = serial.Serial(PORT, BAUD, timeout=0.3)
    buf = drain_raw(port, seconds)
    port.close()
    frames = decode_frames(buf)
    print("passive %.1fs: 收到 %d 字节，其中 CRC 合法二进制帧 %d 条"
          % (seconds, len(buf), len(frames)))
    print("  头部文本: %r" % buf[:160].decode("ascii", "replace"))
    for blob in frames[:8]:
        print("   " + describe(blob))
    return 0


def mode_status():
    port = serial.Serial(PORT, BAUD, timeout=0.3)
    drain_raw(port, 1.5)          # 丢掉在途的旧 STATUS 半行，不 reset_input_buffer
    port.write(b"INPUTS\r\n")
    time.sleep(0.4)
    port.write(b"STATUS\r\n")
    buf = drain_raw(port, 2.0)
    port.close()
    for raw in buf.decode("ascii", "replace").splitlines():
        line = "".join(ch for ch in raw if 32 <= ord(ch) < 127).strip()
        if not line:
            continue
        if line.startswith("STATUS"):
            # 打全字段：排障真正要看的是 STEP_AXIS/STEP_TARGET/STEP_REMAIN/
            # STEP_RESULT/SERVO_*/APP_STATE，截成四个字段会把关键信息丢掉。
            print("  [STATUS] " + line)
        else:
            print("  [文本] " + line[:150])
    return 0


def mode_item(task_id, frame_seq, seconds):
    payload = ItemTaskPayload(
        target_seq=9, class_id=6, image_id=6, x_position=0, y_position=0,
        grip_angle=0xFF, pick_x_position=0, pick_y_position=0,
    )
    frame = encode_item_task_frame(
        task_id=task_id, frame_seq=frame_seq,
        payload=encode_item_task_payload(payload))

    link = PySerialLink(PORT)     # ← 链路真正在用的那个类
    end = time.time() + 0.5
    while time.time() < end:      # 排掉在途字节（只读）
        link.receive()

    print("发 1 条 ITEM_TASK task_id=%d frame_seq=%d (%d B): %s"
          % (task_id, frame_seq, len(frame), frame.hex(" ")))
    link.send(frame)

    got = []
    end = time.time() + seconds
    while time.time() < end:
        got_frame = link.receive()
        if got_frame is not None:
            got.append(got_frame)
            print("  <- " + describe(got_frame))
    link.close()
    print("PySerialLink 解出 %d 条应答" % len(got))
    if not got:
        print("  （板子在 %.1fs 内零应答 —— 注意：链路日志里看到的「无入站」"
              "就是这一种）" % seconds)
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mode = sys.argv[1]
    if mode == "selftest":
        return mode_selftest()
    if mode == "passive":
        return mode_passive(float(sys.argv[2]) if len(sys.argv) > 2 else 4.0)
    if mode == "status":
        return mode_status()
    if mode == "item":
        seconds = float(sys.argv[4]) if len(sys.argv) > 4 else 3.0
        return mode_item(int(sys.argv[2]), int(sys.argv[3]), seconds)
    print("未知模式: %s" % mode)
    return 2


if __name__ == "__main__":
    sys.exit(main())
