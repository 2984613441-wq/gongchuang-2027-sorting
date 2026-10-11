#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PWM 夹爪舵机脉宽扫描：把固件允许的六个定值走一遍，便于挑张开/闭合值。

已确认：P1000 = 张开，P1500 = 中位，P1900 = 闭合。
固件对 SERVO PB10 仅接受 P1000/P1100/P1200/P1300/P1500/P1700/P1900。

用法：python3 pi_grip_sweep.py [每步停顿秒数，默认 3]
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200

# 先回中位，再由开到闭扫一遍，最后回张开
SWEEP = [1500, 1000, 1200, 1500, 1700, 1900, 1000]


def drain(ser, seconds):
    end = time.time() + seconds
    buf = b""
    while time.time() < end:
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        else:
            time.sleep(0.02)
    return buf.decode("ascii", "replace")


def main():
    hold = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    ser = serial.Serial(PORT, BAUD, timeout=0.15)
    time.sleep(0.5)
    drain(ser, 0.8)

    print("=== PWM 脉宽扫描（每步停顿 %.1fs）===" % hold)
    for pulse in SWEEP:
        print(">>> SERVO PB10 P%d" % pulse)
        ser.write(("SERVO ARM\r\n").encode("ascii"))
        ser.flush()
        time.sleep(0.3)
        drain(ser, 0.5)
        ser.write(("SERVO PB10 P%d\r\n" % pulse).encode("ascii"))
        ser.flush()
        time.sleep(0.35)
        for line in drain(ser, 0.6).splitlines():
            line = line.strip()
            if line and not line.startswith("STATUS"):
                print("      %s" % line)
        time.sleep(hold)
    ser.write(("SERVO STOP\r\n").encode("ascii"))
    ser.flush()
    drain(ser, 0.5)
    ser.close()
    print("=== 结束（已 SERVO STOP）===")


if __name__ == "__main__":
    main()
