#!/usr/bin/env python3
# XY 全程联动检查（正方向版）
# 正方向：X = DIR0，Y = DIR1   ← 2026-09-18 用户实测判定，两者不同！
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200
SEG_MM, SEGS, HZ = 40, 5, 1200          # 5 × 40mm = 200mm
SEG_STEPS = SEG_MM * 80                 # 80 步/mm

s = serial.Serial(PORT, BAUD, timeout=0.25)
time.sleep(0.3); s.reset_input_buffer()
HB = ("STATUS ", "OK MOTION ARMED")

def read_for(sec):
    t0 = time.time(); lines = []; buf = b""
    while time.time() - t0 < sec:
        d = s.read(256)
        if not d: continue
        buf += d
        while b"\n" in buf:
            ln, buf = buf.split(b"\n", 1)
            t = ln.decode("utf-8", "replace").strip()
            if t and not t.startswith(HB): lines.append(t)
    return lines

def ping():
    s.write(b"PING\r\n"); s.flush()
    t0 = time.time(); buf = b""
    while time.time() - t0 < 1.5:
        d = s.read(256)
        if d:
            buf += d
            if b"PONG" in buf: return True
    return False

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

def run_axis(axis, direction):
    print("\n" + "=" * 60)
    print("【%s 轴】正方向 = %s    分 %d 段 × %dmm = %dmm"
          % (axis, direction, SEGS, SEG_MM, SEG_MM * SEGS))
    print("=" * 60)
    for i in range(1, SEGS + 1):
        if not ping():
            print("  段%d：🔴 板子失联 → 中止该轴" % i); return
        s.write(b"MOTION ARM\r\n"); s.flush(); read_for(0.5)
        s.write(("MOVE %s %s STEPS %d HZ %d\r\n" % (axis, direction, SEG_STEPS, HZ)).encode())
        s.flush()
        r = read_for(0.7)
        ok = any("STARTING" in x for x in r)
        time.sleep(SEG_STEPS / float(HZ) * 2 + 0.8)
        m, rem, res = st()
        print("  段%d/%d  累计 %3dmm  %s  MODE=%s REMAIN=%s RESULT=%s"
              % (i, SEGS, i * SEG_MM, "OK" if ok else "⚠️", m, rem, res))
        time.sleep(0.3)

print("=" * 60)
print("XY 全程联动检查   X→DIR0(正)  Y→DIR1(正)")
print("每段 %dmm，共 %dmm/轴。有异常请立刻拔电。" % (SEG_MM, SEG_MM * SEGS))
print("=" * 60)
time.sleep(2)
print("探活:", "✅ 活着" if ping() else "🔴 无响应")

run_axis("X", "DIR0")
run_axis("Y", "DIR1")

s.write(b"STEP STOP\r\n"); s.flush(); read_for(0.5)
s.close()
print("\n" + "=" * 60)
print("请报告：哪个轴【不顺/异响/卡顿/丢步】？哪个轴正常？")
