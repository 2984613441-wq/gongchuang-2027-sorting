#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台架：任意轴/方向走指定步数。80 步/mm，慢速 1000Hz。

用法： python3 pi_move.py X DIR1 1488
"""
import sys
import time

import serial

axis, direction, steps = sys.argv[1], sys.argv[2], int(sys.argv[3])

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


print("=== %s %s %d 步 = %.1f mm ===" % (axis, direction, steps, steps / 80.0))
print("PING ->", send("PING"))
print("ARM  ->", send("MOTION ARM"))
print("MOVE ->", send("MOVE %s %s STEPS %d HZ 1000" % (axis, direction, steps), 0.4))

t0 = time.time()
res = "?"
while time.time() - t0 < 25.0:
    txt = send("STATUS", 0.25)
    if "STEP_REMAIN=0" in txt:
        for p in txt.split():
            if p.startswith("STEP_RESULT="):
                res = p.split("=", 1)[1]
        if res == "1":
            break
    time.sleep(0.15)
print("用时 %.2fs  STEP_RESULT=%s" % (time.time() - t0, res))
s.close()
