#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""张开夹爪 + X 往负方向挪指定距离（默认 20mm）。"""
import sys
import time

import serial

mm = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
steps = int(round(mm * 80))

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


print("1) 张开夹爪（P900 = 张开/抬起）")
print("   SERVO ARM ->", send("SERVO ARM"))
print("   SERVO PB10 P900 ->", send("SERVO PB10 P900", 0.6))

time.sleep(1.0)

print("2) X 往负方向挪 %.1f mm = %d 步（DIR1，慢速 1000Hz）" % (mm, steps))
print("   PING ->", send("PING"))
print("   ARM  ->", send("MOTION ARM"))
print("   MOVE ->", send("MOVE X DIR1 STEPS %d HZ 1000" % steps, 0.4))

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
print("   用时 %.2fs STEP_RESULT=%s" % (time.time() - t0, res))
s.close()
