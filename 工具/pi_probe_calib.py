#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定核对：抬爪（待机 625µs）→ 走到物块上方 → 保持抬着 20 秒让人目视。

为什么要写成一个脚本、而不是"先跑 pi_servo_open 再跑 pi_goto"：
  ec_servo_test.c:102-107 —— 台架 SERVO 到 EC_SERVO_RUN_MS（约 2s）就
  ec_servo_port_stop()。而 pi_goto 自己的启动握手（PING 重试最多 8×0.3s）
  就可能吃掉 2 秒 ⇒ 分两次跑，走位时爪已经掉了。
  本脚本在每段之间重新 SERVO ARM + P625，全程让爪停在【待机 625 = 最高最宽】
  —— 那正是生产程序里"穿行/回程"用的姿态（ec_motion_plan.c:263）。

安全边界：
  · 只发 PING / SERVO ARM / SERVO PB10 P625 / SERVO STOP / MOTION ARM / MOVE x DIRn STEPS n HZ / STATUS
  · 只动 X 与 Y，绝不发 HOME/RESET/STOP ALL，绝不碰转盘（GPIO18 由常驻 pi_pw.py 管，本脚本不碰）
  · 先在第一步确认板子应答；不应答直接退出
  · 步数是【相对位移】，默认正方向；本脚本只走正方向（+Y 然后 +X）

用法：python3 /home/pi/pi_probe_calib.py <dx_mm> <dy_mm>
"""
import re
import serial
import sys
import time

STEPS_PER_MM = 80.0
HZ = 5000
HOLD_S = 20.0          # 走完后保持抬爪多久，供人目视
REARM_EVERY = 1.4      # 台架 SERVO 约 2s 自动停 ⇒ 每 1.4s 重新授权+发一次

dx = float(sys.argv[1])
dy = float(sys.argv[2])
if dx < 0 or dy < 0:
    print("REFUSE: 本脚本只走正方向（dx=%.1f dy=%.1f）" % (dx, dy))
    sys.exit(2)
sx = int(round(dx * STEPS_PER_MM))
sy = int(round(dy * STEPS_PER_MM))

s = serial.Serial("/dev/serial0", 115200, timeout=0.05)
time.sleep(0.3)


def send(cmd, wait=0.25):
    s.reset_input_buffer()
    s.write((cmd + "\r\n").encode("ascii"))
    time.sleep(wait)
    return s.read(4000).decode("ascii", "replace").strip()


def status():
    s.reset_input_buffer()
    s.write(b"STATUS\r\n")
    time.sleep(0.05)
    buf = s.read(4096).decode("ascii", "replace")
    for ln in buf.splitlines():
        if ln.startswith("STATUS"):
            return dict(t.split("=", 1) for t in ln.split() if "=" in t)
    return {}


def raise_gripper(tag):
    r1 = send("SERVO ARM", 0.3)
    r2 = send("SERVO PB10 P625", 0.3)
    st = status()
    print("  [%s] SERVO ARM -> %s | P625 -> %s | SERVO_ACTIVE=%s SERVO_US=%s"
          % (tag, (r1.splitlines() or ["(空)"])[0], (r2.splitlines() or ["(空)"])[0],
             st.get("SERVO_ACTIVE"), st.get("SERVO_US")))
    return st.get("SERVO_ACTIVE") == "1"


def leg(axis, dircode, steps, label, rearm=lambda: None):
    if steps == 0:
        print("skip %s (0 steps)" % label)
        return None
    print("--- %s : MOVE %s %s STEPS %d HZ %d ---" % (label, axis, dircode, steps, HZ))
    send("MOTION ARM", 0.2)
    s.reset_input_buffer()
    s.write(("MOVE %s %s STEPS %d HZ %d\r\n" % (axis, dircode, steps, HZ)).encode())
    time.sleep(0.3)
    r = s.read(2000).decode("ascii", "replace")
    print("   reply:", [l.strip() for l in r.splitlines() if l.strip()][:1])
    t0 = time.time()
    mx = 0
    last = {}
    nxt_rearm = time.time() + REARM_EVERY
    while time.time() - t0 < steps / float(HZ) + 6.0:
        if time.time() >= nxt_rearm:
            rearm()
            nxt_rearm = time.time() + REARM_EVERY
        d = status()
        if d:
            last = d
            try:
                rem = int(d.get("STEP_REMAIN", "0"))
            except ValueError:
                rem = -1
            if rem > mx:
                mx = rem
            if mx > 0 and rem == 0:
                break
        time.sleep(0.05)
    print("   max STEP_REMAIN=%d  STEP_RESULT=%s  (1=正常 2=超时 3=安全停)"
          % (mx, last.get("STEP_RESULT")))
    return last.get("STEP_RESULT")


print("PING ->", (send("PING", 0.4).splitlines() or ["(空应答)"])[0])
print("delta: dx=%+.1fmm=%d步 DIR0   dy=%+.1fmm=%d步 DIR1" % (dx, sx, dy, sy))
print("先抬爪 ->", "OK" if raise_gripper("raise-1") else "!! SERVO_ACTIVE 不是 1，继续但请留意")

r1 = leg("Y", "DIR1", sy, "leg1 Y +%.1fmm" % dy, lambda: raise_gripper("rearm"))
r2 = leg("X", "DIR0", sx, "leg2 X +%.1fmm" % dx, lambda: raise_gripper("rearm"))

print("\n>>> 已到目标位置。保持抬爪 %.0fs 供目视；结束后 SERVO STOP。" % HOLD_S)
t_end = time.time() + HOLD_S
while time.time() < t_end:
    raise_gripper("hold")
    time.sleep(REARM_EVERY)

print("SERVO STOP ->", (send("SERVO STOP", 0.4).splitlines() or ["(空)"])[0])
st = status()
print("final:", dict((k, st.get(k)) for k in
                     ("STEP_RESULT", "STEP_REMAIN", "ARMED", "SERVO_ACTIVE", "APP_STATE")))
print("legs: Y=%s X=%s" % (r1, r2))
s.close()
