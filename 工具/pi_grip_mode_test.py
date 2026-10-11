#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""夹爪舵机类型判定测试：先试 PWM（TIM2_CH3），再试总线（USART3）。

固件已做 PB10 复用功能运行时切换：SERVO 命令切到 AF1_TIM2，
GRIP 命令切到 AF7_USART3。两条路径共用同一根信号线。

用法：python3 pi_grip_mode_test.py [每步停顿秒数，默认 3]
"""
import sys
import time

import serial

PORT = "/dev/serial0"
BAUD = 115200

SEQ = [
    ("PWM · 中位",        ["SERVO ARM", "SERVO PB10 P1500"]),
    ("PWM · 一端 P1000",   ["SERVO ARM", "SERVO PB10 P1000"]),
    ("PWM · 另一端 P1900", ["SERVO ARM", "SERVO PB10 P1900"]),
    ("PWM · 停止",        ["SERVO STOP"]),
    ("总线 · 张开最大 400（应=升）", ["GRIP 400 500"]),
    ("总线 · 闭合 640（应=降）",     ["GRIP 640 1000"]),
    ("总线 · 回中位 500",           ["GRIP 500 800"]),
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
    drain(ser, 0.8)

    print("=== 舵机类型判定测试（每步停顿 %.1fs）===" % hold)
    for label, cmds in SEQ:
        print(">>> [%s]" % label)
        for cmd in cmds:
            print("      -> %s" % cmd)
            ser.write((cmd + "\r\n").encode("ascii"))
            ser.flush()
            time.sleep(0.35)
            for line in drain(ser, 0.6).splitlines():
                line = line.strip()
                if line and not line.startswith("STATUS"):
                    print("         %s" % line)
        time.sleep(hold)
    ser.close()
    print("=== 结束 ===")


if __name__ == "__main__":
    main()
