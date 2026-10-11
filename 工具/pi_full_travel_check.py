#!/usr/bin/env python3
# XY 全程联动检查 —— 分段走，每段 40mm，每段前探活，可随时 Ctrl-C / 拔电
# 正方向 = DIR1（用户 2026-09-18 确认：X、Y 的第二个才是正方向）
import serial, time, re, sys

PORT, BAUD = '/dev/serial0', 115200
SEG_MM   = 40
SEG_STEPS = SEG_MM * 80        # 80 步/mm → 3200 步
SEGS     = 5                   # 5 × 40mm = 200mm
HZ       = 1200

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
            line, buf = buf.split(b"\n", 1)
            t = line.decode("utf-8", "replace").strip()
            if t and not t.startswith(HB):
                lines.append(t)
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

def run_axis(axis):
    print("\n" + "=" * 62)
    print("轴 %s ：往正方向（DIR1）分 %d 段，每段 %dmm，共 %dmm"
          % (axis, SEGS, SEG_MM, SEG_MM * SEGS))
    print("=" * 62)
    for i in range(1, SEGS + 1):
        if not ping():
            print("  🔴 段%d：板子失联 → 中止" % i); return False
        s.write(b"MOTION ARM\r\n"); s.flush(); read_for(0.5)
        s.write(("MOVE %s DIR1 STEPS %d HZ %d\r\n" % (axis, SEG_STEPS, HZ)).encode())
        s.flush()
        resp = read_for(0.7)
        ok = any("STARTING" in x for x in resp)
        # 理论耗时 SEG_STEPS/HZ ≈ 2.7s，等 2 倍
        time.sleep(SEG_STEPS / float(HZ) * 2 + 0.8)
        m, rem, res = st()
        print("  段%d/%d  累计 %3dmm   %s   MODE=%s REMAIN=%s RESULT=%s"
              % (i, SEGS, i * SEG_MM,
                 "OK" if ok else "⚠️无STARTING",
                 m, rem, res))
        time.sleep(0.4)
    return True

print("=" * 62)
print("XY 全程联动检查  （正方向 = DIR1，用户确认）")
print("每段 %dmm，每段走完会打印一行；要停就 Ctrl-C 或拔电" % SEG_MM)
print("=" * 62)
time.sleep(2)
print("探活:", "✅ 活着" if ping() else "🔴 无响应")

if run_axis("X"):
    run_axis("Y")

s.write(b"STEP STOP\r\n"); s.flush(); read_for(0.5)
s.close()
print("\n" + "=" * 62)
print("请报告：哪个轴走起来【不顺 / 有异响 / 卡顿 / 丢步】？哪个轴正常？")
