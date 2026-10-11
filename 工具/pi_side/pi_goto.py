# -*- coding: utf-8 -*-
"""滑台系微调移动（默认只走正方向；加 --allow-neg 才允许负方向）。
用法: python3 /home/pi/pi_goto.py <dx_mm> <dy_mm> [--allow-neg]
方向口径: X 正 = DIR0, Y 正 = DIR1 (ec_motion_plan.h:44-45)。80 步/mm。
先 Y 后 X。负位移必须显式给 --allow-neg（用户现场授权才用）。"""
import serial, sys, time

STEPS_PER_MM = 80.0
HZ = 5000

args = [a for a in sys.argv[1:] if a != "--allow-neg"]
allow_neg = "--allow-neg" in sys.argv

dx = float(args[0]); dy = float(args[1])
if (dx < 0 or dy < 0) and not allow_neg:
    print("REFUSE: negative delta without --allow-neg. dx=%s dy=%s" % (dx, dy)); sys.exit(2)
sx = int(round(abs(dx) * STEPS_PER_MM))
sy = int(round(abs(dy) * STEPS_PER_MM))
xd = "DIR0" if dx >= 0 else "DIR1"
yd = "DIR1" if dy >= 0 else "DIR0"

s = serial.Serial("/dev/serial0", 115200, timeout=0.05)
time.sleep(0.3)

def send(c, w=0.25):
    s.reset_input_buffer(); s.write((c + "\r\n").encode("ascii")); time.sleep(w)
    return s.read(4000).decode("ascii", "replace").strip()

def hs(cmd, tries=8):
    for _ in range(tries):
        t = send(cmd, 0.3)
        if t:
            return t.splitlines()[0].strip()
        time.sleep(0.15)
    return "(no reply)"

def status():
    s.reset_input_buffer(); s.write(b"STATUS\r\n"); time.sleep(0.05)
    buf = s.read(4096).decode("ascii", "replace")
    for ln in buf.splitlines():
        if ln.startswith("STATUS"):
            return dict(t.split("=", 1) for t in ln.split() if "=" in t)
    return {}

def leg(axis, dircode, steps, label):
    if steps == 0:
        print("skip %s (0 steps)" % label); return None
    print("--- %s : MOVE %s %s STEPS %d HZ %d ---" % (label, axis, dircode, steps, HZ))
    s.reset_input_buffer()
    s.write(b"MOTION ARM\r\n"); time.sleep(0.1); s.read(2000)
    s.reset_input_buffer()
    s.write(("MOVE %s %s STEPS %d HZ %d\r\n" % (axis, dircode, steps, HZ)).encode())
    time.sleep(0.3)
    r = s.read(2000).decode("ascii", "replace")
    print("   reply:", [l.strip() for l in r.splitlines() if l.strip()][:1])
    t0 = time.time(); mx = 0; last = {}
    while time.time() - t0 < steps / float(HZ) + 5.0:
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
    res = last.get("STEP_RESULT")
    print("   max STEP_REMAIN=%d  STEP_RESULT=%s   (1=normal 2=timeout 3=safe-stop)" % (mx, res))
    return res

print("PING ->", hs("PING"))
print("ARM  ->", hs("MOTION ARM"))
print("delta: dx=%+.1fmm = %d steps %s   dy=%+.1fmm = %d steps %s   (neg allowed: %s)"
      % (dx, sx, xd, dy, sy, yd, allow_neg))
r1 = leg("Y", yd, sy, "leg1 Y")
r2 = leg("X", xd, sx, "leg2 X")
st = status()
print("final:", dict((k, st.get(k)) for k in ("STEP_RESULT", "STEP_REMAIN", "ARMED", "APP_STATE")))
print("legs: Y=%s X=%s" % (r1, r2))
s.close()
