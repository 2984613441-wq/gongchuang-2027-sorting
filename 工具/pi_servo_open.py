#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""张开夹爪：走台架 SERVO 通道，打印板子对每条命令的原始应答。

P900 = 张开/抬起（最低已验证值）；P1900 = 闭合/下压。
"""
import time

import serial

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.6):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


for cmd in ("PING", "SERVO ARM", "SERVO PB10 P900", "STATUS"):
    print("%-18s -> %s" % (cmd, send(cmd) or "(空应答)"))
    time.sleep(0.3)

print()
print(">>> 舵机应已张开并保持 P900 输出（单次 ARM 只消费一次，需重发 ARM）")
s.close()
