#!/usr/bin/env python3
# X 轴方向标定 —— 干净版：先测稳定性，再每次 arm 完立刻动
import serial, time, sys

PORT, BAUD = '/dev/serial0', 115200
STEPS, HZ = 400, 500          # 400/80 = 5.00 mm

def talk(s, cmd, wait=0.8, n=400):
    s.reset_input_buffer()
    s.write(cmd.encode() + b'\r\n'); s.flush()
    time.sleep(wait)
    return s.read(n).decode('utf-8', 'replace')

def one(s, cmd, wait=0.8):
    return talk(s, cmd, wait).strip().replace('\r', ' | ')

s = serial.Serial(PORT, BAUD, timeout=1.2)
time.sleep(0.5)

print("=" * 62)
print("A) 稳定性：PING 十次（看会不会中途重启）")
ok = 0
for i in range(10):
    r = one(s, "PING", 0.15)
    if "PONG" in r: ok += 1
    if "BOOT" in r: print("   ⚠️ 第%d次发现重启: %s" % (i+1, r[:80]))
    time.sleep(0.25)
print("   PONG 成功 %d/10" % ok)

print()
print("B) 方向测试：arm 完【立刻】动，避免窗口过期")
for label, direction in (("DIR0", "DIR0"), ("DIR1", "DIR1")):
    print("   --- %s ---" % label)
    a = one(s, "MOTION ARM", 0.4)
    print("     ARM  ->", a[:120])
    if "BOOT" in a:
        print("     ⚠️ ARM 时发生重启，重来")
        a = one(s, "MOTION ARM", 0.4); print("     重试 ->", a[:120])
    m = one(s, "MOVE X %s STEPS %d HZ %d" % (direction, STEPS, HZ), 0.5)
    print("     MOVE ->", m[:160].replace('\n', ' / '))
    # 等它走完（400步@500Hz = 0.8s）
    time.sleep(1.5)
    st = one(s, "STATUS", 0.3)
    import re
    def g(k):
        mm = re.search(k + r"=(\d+)", st)
        return mm.group(1) if mm else "?"
    print("     STATUS -> MODE=%s STEP_TARGET=%s STEP_REMAIN=%s STEP_RESULT=%s"
          % (g("MODE"), g("STEP_TARGET"), g("STEP_REMAIN"), g("STEP_RESULT")))
    time.sleep(1.0)

print()
print("C) 收尾")
print("   ", one(s, "STEP STOP", 0.4)[:120])
s.close()
print("=" * 62)
print("请报告：滑台在 DIR0 和 DIR1 分别往哪边动？")
