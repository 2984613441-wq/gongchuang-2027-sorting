#!/usr/bin/env python3
# XY 双轴方向标定：每轴来回各半圈（20mm），共 4 次运动
# 期望：X 的 DIR0 = 往右（+X），Y 的 DIR0 = 往前（+Y）
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200
STEPS, HZ = 1600, 1000        # 1600 步 = 20mm = 半圈

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
            if t and not t.startswith("STATUS ") and not t.startswith("OK MOTION ARMED"):
                lines.append(t)
    return lines

def send(cmd, wait=1.0):
    s.write(cmd.encode() + b"\r\n"); s.flush()
    return drain(wait)

def wait_done(max_s=6.0):
    """等运动结束（MODE 回 0）"""
    t0 = time.time()
    while time.time() - t0 < max_s:
        s.write(b"STATUS\r\n"); s.flush()
        t1 = time.time(); buf = b""
        while time.time() - t1 < 0.6:
            d = s.read(256)
            if d: buf += d
            if b"BARRIER_US=" in buf: break
        txt = buf.decode("utf-8", "replace")
        m = re.search(r"MODE=(\d+)", txt)
        rem = re.search(r"STEP_REMAIN=(\d+)", txt)
        res = re.search(r"STEP_RESULT=(\d+)", txt)
        if m and m.group(1) == "0" and rem and rem.group(1) == "0":
            return "%s 秒" % round(time.time() - t0, 1), (res.group(1) if res else "?")
        time.sleep(0.3)
    return "超时未结束", "?"

def move(axis, direction):
    print("   ARM    ->", (send("MOTION ARM", 0.5) or ["(ok)"])[0][:40])
    r = send("MOVE %s %s STEPS %d HZ %d" % (axis, direction, STEPS, HZ), 0.6)
    print("   MOVE   ->", (r or ["(无额外响应)"])[0][:60])
    t, res = wait_done()
    print("   完成   -> 耗时 %s   STEP_RESULT=%s %s" % (t, res, "(2=超时,0=正常)"))
    time.sleep(0.6)

print("=" * 64)
print("XY 方向标定：每次 %d 步 = %.1f mm = 半圈，%d Hz" % (STEPS, STEPS / 80.0, HZ))
print("=" * 64)

print("\n【1】X 轴 DIR0  —— 期望【往右】")
move("X", "DIR0")

print("\n【2】X 轴 DIR1  —— 回到原位")
move("X", "DIR1")

print("\n【3】Y 轴 DIR0  —— 期望【往前】")
move("Y", "DIR0")

print("\n【4】Y 轴 DIR1  —— 回到原位")
move("Y", "DIR1")

print("\n收尾:", send("STEP STOP", 0.4))
s.close()
print("=" * 64)
print("请报告：")
print("  X 轴 DIR0 时往【左】还是【右】？  （期望：右）")
print("  Y 轴 DIR0 时往【前】还是【后】？  （期望：前）")
