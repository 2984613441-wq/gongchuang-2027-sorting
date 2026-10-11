#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自适应夹爪（HX-06L 总线舵机）台架测试序列。

树莓派经 /dev/serial0 给 STM32 发文本命令；STM32 再经 USART3/PB10
按幻尔总线协议驱动舵机。舵机不是挂在树莓派上的。

用法：python3 pi_grip_test.py [每步停顿秒数，默认 3]
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200

# 出厂参考值：400 张开最大(升) / 500 中位 / 640 闭合(降)
SEQ = [
    ("中位 500",        "GRIP 500 800"),
    ("张开最大 400（应=升）", "GRIP 400 500"),
    ("中位 500",        "GRIP 500 800"),
    ("闭合 640（应=降）",   "GRIP 640 1000"),
    ("回中位 500",       "GRIP 500 800"),
]


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
    drain(ser, 0.8)                     # 丢掉开机残留与心跳

    print("=== 夹爪测试序列开始（每步停顿 %.1fs）===" % hold)
    for label, cmd in SEQ:
        print(">>> [%s]  %s" % (label, cmd))
        ser.write((cmd + "\r\n").encode("ascii"))
        ser.flush()
        time.sleep(0.3)
        for line in drain(ser, 0.7).splitlines():
            line = line.strip()
            if line and not line.startswith("STATUS"):   # 过滤 1Hz 心跳
                print("      %s" % line)
        time.sleep(hold)
    ser.close()
    print("=== 序列结束 ===")


if __name__ == "__main__":
    main()
