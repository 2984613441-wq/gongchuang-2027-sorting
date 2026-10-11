#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定第2点：Y 走 4000 步，并用 AXIS/STATUS 核实是否真的走完。"""
import time

import serial

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.5):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(700).decode("ascii", "replace").strip()


def field(txt, key):
    for part in txt.replace("AXIS", "").replace("STATUS", "").split():
        if part.startswith(key + "="):
            return part.split("=", 1)[1]
    return "?"


print("PING ->", send("PING"))
print("ARM  ->", send("MOTION ARM"))
print("MOVE ->", send("MOVE Y DIR1 STEPS 4000 HZ 1000", 0.4))

t0 = time.time()
last = ""
while time.time() - t0 < 15.0:
    st = send("STATUS", 0.3)
    if "STEP_REMAIN=0" in st and field(st, "MODE") == "0":
        last = st
        break
    last = st
    time.sleep(0.2)

print("用时 %.2fs" % (time.time() - t0))
print("最终 STATUS: STEP_TARGET=%s STEP_REMAIN=%s STEP_RESULT=%s MODE=%s"
      % (field(last, "STEP_TARGET"), field(last, "STEP_REMAIN"),
         field(last, "STEP_RESULT"), field(last, "MODE")))
print()
print(">>> 若 STEP_RESULT=1 说明真的走完了 4000 步（=50mm）")
print(">>> 请把物块摆到夹爪正下方，然后喊我读 pixel_y")
s.close()
