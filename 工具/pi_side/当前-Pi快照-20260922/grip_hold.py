# -*- coding: utf-8 -*-
"""夹爪单档保持：SERVO 命令只保持 2s，这里每 2.2s 重发一次以维持位置。"""
import serial, sys, time

us = int(sys.argv[1])
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0

s = serial.Serial("/dev/serial0", 115200, timeout=0.5)
time.sleep(0.3)

def send(c, w=0.25):
    s.reset_input_buffer()
    s.write((c + "\r\n").encode("ascii"))
    time.sleep(w)
    return s.read(4000).decode("ascii", "replace").strip()

def first(t):
    ls = [l.strip() for l in t.splitlines() if l.strip()]
    return ls[0] if ls else "(空应答)"

print("PING -> " + first(send("PING")))
print("目标 -> SERVO PB10 P%d ，保持 %.0f 秒" % (us, dur))
print("-" * 60)
sys.stdout.flush()

t0 = time.time()
try:
    while time.time() - t0 < dur:
        a = first(send("SERVO ARM", 0.2))
        b = first(send("SERVO PB10 P%d" % us, 0.15))
        print("  [%5.1fs] %-22s | %s" % (time.time() - t0, a, b))
        sys.stdout.flush()
        time.sleep(max(0.0, 2.2 - 0.35))
finally:
    print("-" * 60)
    print("收尾 SERVO STOP -> " + first(send("SERVO STOP", 0.4)))
    s.close()