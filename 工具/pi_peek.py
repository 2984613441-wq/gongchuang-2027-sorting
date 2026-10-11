#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读探针：PING / AXIS / STATUS，不发任何运动命令。"""
import time

import serial

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def ask(cmd, wait=0.6):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


for cmd in ("PING", "AXIS", "STATUS", "INPUTS"):
    print("%-7s -> %s" % (cmd, ask(cmd) or "(空)"))
s.close()
