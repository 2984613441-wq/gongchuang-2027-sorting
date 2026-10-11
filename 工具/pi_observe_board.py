#!/usr/bin/env python3
"""只读观察板子：只发 PING / STATUS / AXIS，**绝不发 MOTION ARM / MOVE / STOP**。

用途三条：
  1) 判断板子是否在反复重启（APP_STATE 若循环 POST→HOMING→BARRIER 即为重启）
  2) 读**构建宏组合** —— STATUS 里的 MOTION_TEST / SERVO_TEST / GROUP_TEST /
     BARRIER_TEST 四个字段直接来自编译期 Define（ec_diag.c:390-412 读的是
     EC_*_TEST_BUILD）。用来回答"板上烧的到底是哪一套、是不是当前源码的产物"：
         diankongv1.0.uvprojx            → 1 1 0 0
         diankongv1.0.uvprojx.bak-20260916 → 0 0 0 0
  3) 读 AXIS 锁存故障现场（**新固件才有这条命令**）。旧固件没有 AXIS，会走到
     ec_diag 的兜底分支 —— 所以"AXIS 能用"本身就是"新固件真烧进去了"的自证。
"""
import re
import sys
import time

import serial

PORT = "/dev/serial0"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12

# 期望值：与 MDK-ARM/diankongv1.0.uvprojx:337 的 <Define> 一一对应
EXPECT = {"MOTION_TEST": "1", "SERVO_TEST": "1",
          "GROUP_TEST": "0", "BARRIER_TEST": "0"}


def grab(s, cmd, wait=0.4):
    s.write((cmd + "\r\n").encode("ascii"))
    t0 = time.time()
    buf = b""
    while time.time() - t0 < wait:
        buf += s.read(8192)
    return buf.decode("ascii", "replace")


def field(line, key):
    m = re.search(key + r"=([^\s]*)", line)
    return m.group(1) if m else "?"


def status_lines(d):
    return [l.strip() for l in d.splitlines() if l.strip().startswith("STATUS")]


s = serial.Serial(PORT, 115200, timeout=0.2)
time.sleep(0.4)
print("PING ->", grab(s, "PING").strip() or "(无应答)")

# ── ① 构建宏组合：判断板上烧的是哪一套 ────────────────────────────────
got = {}
lines = status_lines(grab(s, "STATUS"))
print("\n── 构建宏组合 ──")
print("   期望(当前 uvprojx): " + " ".join("%s=%s" % (k, v) for k, v in EXPECT.items()))
if lines:
    line = lines[-1]          # 第一条可能是陈旧行，取最后一条
    for k in EXPECT:
        got[k] = field(line, k)
    print("   实测(板上 STATUS):  " + " ".join("%s=%s" % (k, got[k]) for k in EXPECT))
    bad = [k for k in EXPECT if got[k] != EXPECT[k]]
    if bad:
        print("   *** 不一致: %s —— 板上固件可能不是 diankongv1.0.uvprojx 的产物 ***"
              % ",".join(bad))
    else:
        print("   ✓ 与 diankongv1.0.uvprojx:337 的宏组合一致")
else:
    print("   *** 没收到 STATUS —— 板子没应答，或串口被别的进程占着 ***")

# ── ② AXIS：新固件自证 + 锁存故障现场 ─────────────────────────────────
print("\n── AXIS（锁存故障现场）──")
ax = grab(s, "AXIS", 0.8)
found = [l.strip() for l in ax.splitlines() if "AXIS" in l]
if found:
    for l in found:
        print("   " + l)
else:
    print("   *** 没有 AXIS 行，原始回显: %r" % ax.strip()[:200])
    print("   → 若刚烧过观测补丁，说明它没进去（或没编译进这个构建）")

# ── ③ 轮询 APP_STATE：看是否在循环重启 ────────────────────────────────
print("\n%-4s %-10s %-10s %-6s %-11s %-11s" % (
    "#", "APP_STATE", "SAFE_LOCK", "ARMED", "STEP_REMAIN", "STEP_RESULT"))
print("-" * 62)
prev = None
for i in range(N):
    lines = status_lines(grab(s, "STATUS"))
    line = lines[-1] if lines else "(空/无 STATUS)"
    st = field(line, "APP_STATE")
    print("%-4d %-10s %-10s %-6s %-11s %-11s" % (
        i, st, field(line, "SAFE_LOCK"), field(line, "ARMED"),
        field(line, "STEP_REMAIN"), field(line, "STEP_RESULT")))
    if prev is not None and st != prev:
        print("      ↑↑↑ APP_STATE 变化: %s -> %s  <<< 重启/状态迁移" % (prev, st))
    prev = st
    time.sleep(0.6)

s.close()
print("\n(只读观察结束，未发送任何运动命令)")
