#!/usr/bin/env python3
# 常驻脉宽输出：读 /home/pi/pw.txt，持续输出。
# 2026-09-21 改：改用 (内容, mtime) 判定 —— 同一个数值重写也会重新下发（便于做"重发"实验）。
import time, os, pigpio

PIN = 18
F   = "/home/pi/pw.txt"
LO, HI = 500, 2500

pi = pigpio.pi()
if not pi.connected:
    raise SystemExit("!! pigpiod not running")

print("pi_pw up, watching %s (range %d-%d, resend-on-touch)" % (F, LO, HI), flush=True)
last = None
while True:
    try:
        st  = os.stat(F)
        key = (open(F).read().strip(), st.st_mtime_ns)
    except Exception:
        key = ("0", 0)
    if key != last:
        last = key
        s = key[0]
        try:
            u = int(s) if s else 0
        except Exception:
            u = 0
        if u != 0 and not (LO <= u <= HI):
            print("  !! REJECT %s us" % u, flush=True)
        else:
            try:
                pi.set_servo_pulsewidth(PIN, u)
                print("  -> %s us%s" % (u, " (release)" if u == 0 else ""), flush=True)
            except Exception as e:
                print("  !! ERROR %s us: %s" % (u, e), flush=True)
    time.sleep(0.1)