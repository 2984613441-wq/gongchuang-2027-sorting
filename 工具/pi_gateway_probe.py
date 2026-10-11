#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手动发合法 ITEM_TASK，逐字打印板子回话；用不同 task_id 试探建轮次的门槛。

目的：分清"帧没到状态机"和"round_id 门槛卡住"。
  * task_id=99 能触发  -> 卡在 ec_state_machine.c:78 的 (round_id != machine->round_id)
  * 全都静默           -> 帧根本没走到状态机，需要固件插桩

零解析：板子说什么就原样打什么。不做任何"推断"。
零运动风险：ITEM_TASK 只推进启动序列（POST->HOMING->BARRIER->WAIT_TASK），
            HOMING 按方案 A 不移动（ec_startup_sequence.c:91-94），挡板直接放行。
"""

import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200

HDR0, HDR1, VER = 0xA5, 0x5A, 0x01
DEV_PI, DEV_STM32 = 0x02, 0x03
CMD_ITEM_TASK = 0x21


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
    """12 字节 ITEM_TASK 载荷，布局见 ec_protocol.h:150-157。"""
    return (bytes((target_seq & 0xFF, class_id & 0xFF, class_id & 0xFF))
            + _i16(x_mm10) + _i16(y_mm10) + b"\xff"
            + _i16(pick_x_mm10) + _i16(pick_y_mm10))


def build_frame(task_id, frame_seq, command, payload):
    """外层帧：A5 5A ver sender receiver task_id frame_seq cmd len payload crc。"""
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


def show(tag, data):
    print("--- %s : 收到 %d 字节 ---" % (tag, len(data)))
    if not data:
        print("    (空 —— 板子一句话都没说)")
        return
    for line in data.decode("ascii", "replace").splitlines():
        line = line.strip()
        if line:
            print("    " + line[:160])


def main():
    task_ids = [int(a) for a in sys.argv[1:]] or [1, 2, 99]

    port = serial.Serial(PORT, BAUD, timeout=0.3)
    time.sleep(0.3)

    # 0) 底线：先被动听 2.5 秒心跳，证明链路活着
    show("基线（未发任何东西）", drain(port, 2.5))

    # 1) PING 证明双向通
    port.write(b"PING\r\n")
    show("PING", drain(port, 1.5))

    # 2) 逐个 task_id 试建轮次
    for index, task_id in enumerate(task_ids):
        frame_seq = index + 1
        payload = item_task_payload(
            target_seq=3, class_id=6,
            x_mm10=50, y_mm10=50,          # 落料 (5.0, 5.0) mm —— 故意取小
            pick_x_mm10=0, pick_y_mm10=-450,  # 抓取 (0.0, -45.0) mm
        )
        frame = build_frame(task_id, frame_seq, CMD_ITEM_TASK, payload)
        print("=== 发送 ITEM_TASK task_id=%d frame_seq=%d ===" % (task_id, frame_seq))
        print("    线上字节: " + " ".join("%02X" % b for b in frame))
        port.reset_input_buffer()
        port.write(frame)
        show("应答（发后 4 秒）", drain(port, 4.0))

    port.close()
    print("=== 探针结束 ===")


if __name__ == "__main__":
    main()
