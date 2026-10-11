#!/usr/bin/env python3
# X 轴 DIR1 半圈测试（DIR0 反了，测反方向）
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200
STEPS, HZ = 1600, 1000        # 20mm = 半圈

s = serial.Serial(PORT, BAUD, timeout=0.2)
time.sleep(0.5); s.reset_input_buffer()

def drain(sec):
    t0 = time.time(); lines = []; buf = b""
    while time.time() - t0 < sec:
        d = s.read(256)
        if not d: continue
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            t = line.decode("utf-8", "replace").strip()
            if t and not t.startswith("STATUS "):
                lines.append(t)
    return lines

def send(cmd, wait=1.2):
    s.write(cmd.encode() + b"\r\n"); s.flush()
    return drain(wait)

def status():
    s.write(b"STATUS\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < 1.0:
        d = s.read(256)
        if d: buf += d
        if b"BARRIER_US=" in buf: break
    txt = buf.decode("utf-8", "replace")
    return {k: (re.search(k + r"=(\d+)", txt).group(1) if re.search(k + r"=(\d+)", txt) else "?")
            for k in ("MODE", "STEP_REMAIN", "STEP_RESULT")}

print("=" * 60)
print("X 轴 DIR1：%d 步 = %.1f mm = 半圈，%d Hz" % (STEPS, STEPS / 80.0, HZ))
print("（DIR0 刚才往一边走，DIR1 应该往反方向）")
print("=" * 60)

print("\n[A] ARM     ->", send("MOTION ARM"))
print("[B] 🔴 DIR1 ->", send("MOVE X DIR1 STEPS %d HZ %d" % (STEPS, HZ)))

for i in range(6):
    time.sleep(0.8)
    st = status()
    print("    %.1fs  MODE=%s REMAIN=%s RESULT=%s" % ((i+1)*0.8, st["MODE"], st["STEP_REMAIN"], st["STEP_RESULT"]))
    if st["MODE"] == "0" and st["STEP_REMAIN"] == "0" and i > 0:
        break

print("\n[C] STOP    ->", send("STEP STOP"))
s.close()
print("=" * 60)
print("请报告：这次往【左】还是往【右】？跟上次是不是反的？")
