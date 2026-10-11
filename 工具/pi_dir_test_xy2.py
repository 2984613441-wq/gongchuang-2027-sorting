#!/usr/bin/env python3
# XY 方向标定 —— 带存活保护的稳版
# 每次运动前先 PING；板子一失联立刻中止，不再往下发
import serial, time, re, sys

PORT, BAUD = '/dev/serial0', 115200
STEPS, HZ = 1600, 1000        # 1600 步 = 20mm = 半圈

s = serial.Serial(PORT, BAUD, timeout=0.25)
time.sleep(0.3); s.reset_input_buffer()

HB = ("STATUS ", "OK MOTION ARMED")   # 要过滤掉的定期/例行输出

def read_for(sec):
    t0 = time.time(); lines = []; buf = b""
    while time.time() - t0 < sec:
        d = s.read(256)
        if not d:
            continue
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            t = line.decode("utf-8", "replace").strip()
            if t and not t.startswith(HB):
                lines.append(t)
    return lines

def ping():
    """存活检测：True=板子活着"""
    s.write(b"PING\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < 1.5:
        d = s.read(256)
        if d:
            buf += d
            if b"PONG" in buf:
                return True
    return False

def status_line(timeout=1.5):
    s.write(b"STATUS\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < timeout:
        d = s.read(256)
        if d:
            buf += d
            if b"BARRIER_US=" in buf:
                break
    return buf.decode("utf-8", "replace")

def g(txt, k):
    m = re.search(k + r"=(-?\d+)", txt)
    return m.group(1) if m else "?"

def do(axis, direction, label):
    print("\n   ---- %s : %s %s ----" % (label, axis, direction))
    if not ping():
        print("   🔴 板子失联（PING 无 PONG）→ 中止，不再发指令")
        return False
    print("   存活 ✅")
    s.reset_input_buffer()
    s.write(b"MOTION ARM\r\n"); s.flush(); read_for(0.6)
    s.write(("MOVE %s %s STEPS %d HZ %d\r\n" % (axis, direction, STEPS, HZ)).encode())
    s.flush()
    resp = read_for(0.8)
    print("   响应: %s" % (resp[:1] if resp else "(只有心跳)"))
    # 运动理论耗时 STEPS/HZ 秒，再多等一倍
    time.sleep(STEPS / float(HZ) * 2 + 1.0)
    st = status_line()
    print("   结束: MODE=%s REMAIN=%s RESULT=%s  (RESULT 2=超时 0=正常)"
          % (g(st, "MODE"), g(st, "STEP_REMAIN"), g(st, "STEP_RESULT")))
    time.sleep(0.5)
    return True

print("=" * 64)
print("XY 方向标定  %d 步 = %.1f mm = 半圈，%d Hz" % (STEPS, STEPS / 80.0, HZ))
print("  X 的 DIR0 期望【往右】；Y 的 DIR0 期望【往前】")
print("=" * 64)

print("\n等板子启动完成…")
time.sleep(3)
print("首次探活:", "✅ 活着" if ping() else "🔴 无响应")

for axis, direction, label in (
    ("X", "DIR0", "1/4  X 往右？"),
    ("X", "DIR1", "2/4  X 回原位"),
    ("Y", "DIR0", "3/4  Y 往前？"),
    ("Y", "DIR1", "4/4  Y 回原位"),
):
    if not do(axis, direction, label):
        print("\n⚠️ 因板子失联而中止。请断电重启后再试。")
        break

s.write(b"STEP STOP\r\n"); s.flush(); read_for(0.5)
s.close()
print("\n" + "=" * 64)
print("请报告：X 的 DIR0 往【左/右】？   Y 的 DIR0 往【前/后】？")
