#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定用：让 Y 轴精确走指定步数（台架 MOVE 命令），并打印运动后的 Y 毫米位置。

用法： python3 pi_calib_move_y.py <步数> [起始Y_mm]

约定：HOME = Y 的 −97.5mm（最里角）。Y 正方向 = DIR1。
      80 步/mm。步数n => 位移 n/80 mm。

安全：只走 Y、慢速 1000Hz；跑之前请把滑台推到最里角（原点），且手别离开急停。
"""
import sys
import time

import serial

STEPS_PER_MM = 80.0
HOME_Y_MM = -97.5

steps = int(sys.argv[1])
start_y = float(sys.argv[2]) if len(sys.argv) > 2 else HOME_Y_MM
delta_mm = steps / STEPS_PER_MM
end_y = start_y + delta_mm

print("本次：Y 走 %d 步 = %.1f mm（DIR1 = +Y，慢速 1000Hz）" % (steps, delta_mm))
print("=> 运动后 Z 轴应停在 Y = %.1f mm" % end_y)
print()
print("⚠️ 请确认：滑台此刻在最里角（原点），且手在急停上。3 秒后开始……")
time.sleep(3)

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)


def send(cmd, wait=0.4):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(600).decode("ascii", "replace").strip()


print(send("PING", 0.5) or "(PING 无应答)")
print(send("MOTION ARM", 0.5) or "(ARM 无应答)")
cmd = "MOVE Y DIR1 STEPS %d HZ 1000" % steps
print("%s -> %s" % (cmd, send(cmd, 0.3) or "(无应答)"))

t0 = time.time()
while time.time() - t0 < 12.0:
    txt = send("STATUS", 0.3)
    if "STEP_REMAIN=0" in txt:
        break
print("到位，用时 %.2fs" % (time.time() - t0))
print()
print(">>> 现在请把物块摆到【夹爪正下方】，摆好喊我读 pixel_y")
s.close()
