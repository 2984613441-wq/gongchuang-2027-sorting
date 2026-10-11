#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""立刻问板子现在的状态与输入位，并尝试停掉一切测试运动。只读+安全停机。"""

import time

import serial

port = serial.Serial("/dev/serial0", 115200, timeout=0.3)
time.sleep(0.3)

port.reset_input_buffer()
port.write(b"STOP ALL\r\n")
time.sleep(0.5)
port.write(b"INPUTS\r\n")
time.sleep(0.5)
port.write(b"STATUS\r\n")
time.sleep(0.5)
# AXIS 会报 FAULTS / TICK_MS / LAST_KIND / LAST_AXIS / LAST_STEPS ——
# 用来对账"板子自己认的上一动"，比只看 STEP_RESULT 多一层证据。
port.write(b"AXIS\r\n")
time.sleep(1.5)

data = port.read(6000)
port.close()

for line in data.decode("ascii", "replace").splitlines():
    line = "".join(ch for ch in line if 32 <= ord(ch) < 127).strip()
    if line.startswith(("STATUS", "INPUTS", "AXIS", "OK", "ERR", "ACTIVE")):
        print(line)
