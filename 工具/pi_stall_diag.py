#!/usr/bin/env python3
# 低速小距离诊断：验证"是不是频率太高导致丢步"
# 800 步 = 10mm @ 200Hz（慢速，约 4 秒）—— 请用尺子量实际走了多少
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200

s = serial.Serial(PORT, BAUD, timeout=0.25)
time.sleep(0.3); s.reset_input_buffer()

def read_for(sec):
    t0 = time.time(); out = []; buf = b""
    while time.time() - t0 < sec:
        d = s.read(256)
        if not d: continue
        buf += d
        while b"\n" in buf:
            ln, buf = buf.split(b"\n", 1)
            t = ln.decode("utf-8", "replace").strip()
            if t and not t.startswith(("STATUS ", "OK MOTION ARMED")):
                out.append(t)
    return out

def st():
    s.write(b"STATUS\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < 1.2:
        d = s.read(256)
        if d:
            buf += d
            if b"BARRIER_US=" in buf: break
    t = buf.decode("utf-8", "replace")
    def g(k):
        m = re.search(k + r"=(-?\d+)", t); return m.group(1) if m else "?"
    return g("MODE"), g("STEP_REMAIN"), g("STEP_RESULT")

# 三档速度对比，每档 10mm，看哪一档能走满
TESTS = [
    ("很慢", 800, 200),    # 10mm @ 200Hz  约 4.0 秒
    ("中速", 800, 500),    # 10mm @ 500Hz  约 1.6 秒
    ("快  ", 800, 1000),   # 10mm @ 1000Hz 约 0.8 秒
]

print("=" * 64)
print("丢步诊断：同样走 800 步 = 10mm，只改速度")
print("  请每一档都用尺子量【滑台实际移动了多少毫米】")
print("=" * 64)

for label, steps, hz in TESTS:
    print("\n---- %s : %d 步 = %.1fmm @ %d Hz（理论 %.1f 秒）----"
          % (label, steps, steps / 80.0, hz, steps / float(hz)))
    if not read_for(0.1) and True:
        s.write(b"PING\r\n"); s.flush()
        if b"PONG" not in (b"".join([s.read(128) for _ in range(6)]) or b""):
            pass
    s.write(b"MOTION ARM\r\n"); s.flush(); read_for(0.5)
    s.write(("MOVE X DIR0 STEPS %d HZ %d\r\n" % (steps, hz)).encode()); s.flush()
    print("   响应:", (read_for(0.7) or ["(心跳)"])[0][:50])
    time.sleep(steps / float(hz) + 3.0)          # 多等 3 秒
    m, rem, res = st()
    print("   状态: MODE=%s REMAIN=%s RESULT=%s" % (m, rem, res))
    print("   👉 请量：这一档实际走了 ______ mm （期望 10.0mm）")
    time.sleep(1.5)

s.write(b"STEP STOP\r\n"); s.flush(); read_for(0.4)
s.close()
print("\n" + "=" * 64)
print("请报告三档各自实际走了多少毫米 —— 哪一档最接近 10.0mm？")
