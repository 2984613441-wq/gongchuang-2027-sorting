#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓一次台架 MOVE 的原始运动轨迹：不 sleep，立刻高频轮询 STATUS。

为什么要这个：pi_bench_goto.py 发完 MOVE 后 sleep(0.4) 才开始轮询，
如果这一动 0.4 秒内就跑完了，就永远看不到 STEP_REMAIN>0，
"完成判据"失效 → 有可能在上一动还没走完时又发下一条 → 真值记账全废。
本脚本只做一件事：把 STEP_REMAIN / STEP_RESULT / STATE 随时间打出来，
据此算出【真实脉冲频率】，并确认 HZ 参数到底有没有被采纳。

用法： python3 pi_step_trace.py <X|Y> <DIR0|DIR1> <steps> <hz>
"""
import sys
import time

import serial

axis, direction = sys.argv[1], sys.argv[2]
steps, hz = int(sys.argv[3]), int(sys.argv[4])

s = serial.Serial("/dev/serial0", 115200, timeout=0.15)
time.sleep(0.3)


def read_status():
    s.reset_input_buffer()
    s.write(b"STATUS\r\n")
    deadline = time.time() + 0.15
    buf = b""
    while time.time() < deadline:
        chunk = s.read(2048)
        if chunk:
            buf += chunk
            if b"APP_STATE" in buf:
                break
    for ln in buf.decode("ascii", "replace").splitlines():
        if "STEP_TARGET" in ln:
            d = {}
            for tok in ln.split():
                if "=" in tok:
                    k, _, v = tok.partition("=")
                    d[k] = v
            return d
    return None


print("PING ->", (read_status() or {}).get("APP_STATE", "?"))
print("ARM  ->", end=" ")
s.reset_input_buffer()
s.write(b"MOTION ARM\r\n")
time.sleep(0.2)
print(s.read(300).decode("ascii", "replace").strip().splitlines()[0])

cmd = "MOVE %s %s STEPS %d HZ %d" % (axis, direction, steps, hz)
print("下发 %s（%d 步 = %.2f mm @%d Hz）" % (cmd, steps, steps / 80.0, hz))

t0 = time.time()
s.reset_input_buffer()
s.write((cmd + "\r\n").encode("ascii"))

prev = None
first_seen = None
while time.time() - t0 < 6.0:
    d = read_status()
    if d is None:
        continue
    rem = d.get("STEP_REMAIN", "?")
    key = rem
    t = time.time() - t0
    if rem != "0" and first_seen is None:
        first_seen = t
    if key != prev or t < 0.5:
        print("  t=%.3fs  REMAIN=%-8s RESULT=%-3s TARGET=%-8s STATE=%s" %
              (t, rem, d.get("STEP_RESULT", "?"), d.get("STEP_TARGET", "?"),
               d.get("APP_STATE", "?")))
        prev = key
    if rem == "0" and first_seen is not None:
        break

elapsed = time.time() - t0
print("\n总耗时 %.3fs（含握手开销）  首次见到运动 t=%.3fs" %
      (elapsed, first_seen if first_seen is not None else -1))
if first_seen is not None and elapsed > first_seen:
    span = elapsed - first_seen
    print("运动区间约 %.3fs -> 实测频率约 %.0f 步/秒（设定 %d Hz）" % (span, steps / span, hz))
print("理论：%.2fs（%d 步 / %d Hz，含 200Hz->cruise 斜坡约 0.20s）" %
      (steps / float(hz) + 0.2, steps, hz))
s.close()
