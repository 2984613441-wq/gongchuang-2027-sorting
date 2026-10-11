#!/usr/bin/env python3
# X 轴半圈方向测试 —— 固定窗口读取版（板子每秒发心跳 STATUS，必须过滤）
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200
STEPS, HZ = 1600, 1000        # 1600步 = 20mm = 半圈

s = serial.Serial(PORT, BAUD, timeout=0.2)
time.sleep(0.5)
s.reset_input_buffer()

def drain(sec):
    """固定读 sec 秒，返回所有非心跳行。"""
    t0 = time.time()
    lines = []
    buf = b""
    while time.time() - t0 < sec:
        d = s.read(256)
        if not d:
            continue
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            t = line.decode("utf-8", "replace").strip()
            if t and not t.startswith("STATUS "):     # 过滤每秒心跳
                lines.append(t)
    if buf.strip():
        t = buf.decode("utf-8", "replace").strip()
        if t and not t.startswith("STATUS "):
            lines.append(t)
    return lines

def send(text):
    s.write(text.encode() + b"\r\n"); s.flush()
    return drain(1.2)

def status():
    s.write(b"STATUS\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < 1.0:
        d = s.read(256)
        if d: buf += d
        if b"BARRIER_US=" in buf: break
    txt = buf.decode("utf-8", "replace")
    out = {}
    for k in ("MODE", "STEP_REMAIN", "STEP_RESULT", "STEP_TARGET", "SAFE_LOCK", "ARMED"):
        m = re.search(k + r"=(\d+)", txt)
        out[k] = m.group(1) if m else "?"
    return out

print("=" * 64)
print("X 轴半圈测试：%d 步 = %.1f mm = 半圈（1圈=40mm），速度 %d Hz（约 %.1f 秒）"
      % (STEPS, STEPS / 80.0, HZ, STEPS / float(HZ)))
print("=" * 64)

print("\n[A] 开窗口")
print("   ", send("MOTION ARM") or ["(只有心跳，无额外响应)"])

print("\n[B] 🔴 走 DIR0 —— 请看滑台往哪边！")
print("   ", send("MOVE X DIR0 STEPS %d HZ %d" % (STEPS, HZ)))

print("\n[C] 跟踪进度（每 0.8 秒报一次）")
for i in range(7):
    time.sleep(0.8)
    st = status()
    print("   %.1fs  MODE=%s REMAIN=%s/%s RESULT=%s"
          % ((i + 1) * 0.8, st["MODE"], st["STEP_REMAIN"], st["STEP_TARGET"], st["STEP_RESULT"]))
    if st["MODE"] == "0" and st["STEP_REMAIN"] == "0" and i > 0:
        break

print("\n[D] 收尾")
print("   ", send("STEP STOP"))
s.close()
print("=" * 64)
print("请报告：滑台往【左】还是往【右】？大约走了几毫米？")
