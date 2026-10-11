#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收 TIM 中断修复：STEP_REMAIN 是否真的从 800 递减到 0。

修复前：MOVE 后 MODE=4 REMAIN=800 永不变化、RESULT=0。
修复后预期：REMAIN 一路递减到 0、RESULT=1(DONE)。

用法：python3 /home/pi/pi_verify_timfix.py [轴X|Y] [DIR0|DIR1] [步数] [HZ]
示例：python3 pi_verify_timfix.py X DIR0 800 500
"""
import re
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200


def drain(ser, seconds=0.4):
    """读取 seconds 秒内到达的所有字节（串口有 1Hz 无请求 STATUS 心跳）。"""
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.02)
    return buf.decode("ascii", "replace")


def send(ser, cmd):
    ser.write((cmd + "\r\n").encode("ascii"))
    ser.flush()


def ask_status(ser):
    """发一条 STATUS 并捕获它自己的回包，丢弃心跳。"""
    drain(ser, 0.25)
    send(ser, "STATUS")
    end = time.time() + 1.5
    buf = ""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n).decode("ascii", "replace")
            tail = buf.split("STEP_REMAIN")[-1]
            if "STEP_REMAIN" in buf and "\n" in tail:
                break
        else:
            time.sleep(0.02)
    for line in buf.splitlines():
        if line.startswith("STATUS"):
            return line.strip()
    return buf.strip() or "(no reply)"


def field(line, key):
    m = re.search(key + r"=(-?\d+)", line)
    return m.group(1) if m else "?"


def main():
    axis = (sys.argv[1] if len(sys.argv) > 1 else "X").upper()
    direction = (sys.argv[2] if len(sys.argv) > 2 else "DIR0").upper()
    steps = sys.argv[3] if len(sys.argv) > 3 else "800"
    hz = sys.argv[4] if len(sys.argv) > 4 else "500"
    assert axis in ("X", "Y"), axis
    assert direction in ("DIR0", "DIR1"), direction

    ser = serial.Serial(PORT, BAUD, timeout=0.15)
    time.sleep(0.5)

    print("=== 启动横幅 / 残留输出 ===")
    print(drain(ser, 1.5)[-500:])

    print("=== 发送 MOTION ARM ===")
    send(ser, "MOTION ARM")
    time.sleep(0.3)
    print(drain(ser, 0.6).strip())

    print("=== 运动前 ===")
    print(ask_status(ser))

    cmd = "MOVE %s %s STEPS %s HZ %s" % (axis, direction, steps, hz)
    print("=== 发送 %s ===" % cmd)
    send(ser, cmd)
    time.sleep(0.2)
    print(drain(ser, 0.6).strip())

    print("")
    print("=== 时间序列：STEP_REMAIN 应 %s -> 0 ===" % steps)
    last = None
    for i in range(20):
        line = ask_status(ser)
        rem = field(line, "STEP_REMAIN")
        res = field(line, "STEP_RESULT")
        mode = field(line, "MODE")
        print("t=%4.1fs  REMAIN=%-6s RESULT=%-3s MODE=%s"
              % (i * 0.35, rem, res, mode))
        if rem == "0":
            break
        if rem == last and i >= 3:
            pass
        last = rem
        time.sleep(0.15)

    print("")
    print("=== 运动后完整 STATUS（原始行）===")
    print(ask_status(ser))
    ser.close()


if __name__ == "__main__":
    main()
