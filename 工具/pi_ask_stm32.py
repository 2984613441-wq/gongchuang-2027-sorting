#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""问 STM32 几个 diag 命令，看 App 为什么不接受 ITEM_TASK。

App 要跑运动，前提是安全输入满足（电源许可 EC_INPUT_POWER_PERMISSION、
急停未触发）。台架上如果这些信号没接，App 会锁住、对 ITEM_TASK 不理不睬。
`INPUTS` 会把输入位直接报出来。
"""
import time
import serial

port = serial.Serial("/dev/serial0", 115200, timeout=0.4)
port.reset_input_buffer()

for cmd in ("PING", "INPUTS", "STATUS", "VERSION", "HELP"):
    port.reset_input_buffer()
    port.write((cmd + "\r\n").encode())
    port.flush()
    time.sleep(0.6)
    data = port.read(8192).decode("utf-8", "replace")
    # 只打印非 STATUS 心跳的行，避免刷屏
    lines = [l for l in data.splitlines() if l.strip() and not l.startswith("STATUS ")]
    print("── %s ──" % cmd)
    if lines:
        for l in lines[:12]:
            print("   ", l)
    else:
        print("    （无有效应答）")
port.close()
