#!/usr/bin/env python3
# X 轴方向标定测试 —— 只走 5mm，来回各一次
# 400 步 / 80 步每毫米 = 5.00 mm
import serial, time, sys

PORT, BAUD = '/dev/serial0', 115200
STEPS = 400     # = 5.00 mm
HZ = 500        # 慢速

def talk(s, cmd, wait=1.0, n=400):
    s.reset_input_buffer()
    s.write(cmd.encode() + b'\r\n'); s.flush()
    time.sleep(wait)
    return s.read(n).decode('utf-8', 'replace').strip()

try:
    s = serial.Serial(PORT, BAUD, timeout=1.5)
except Exception as e:
    print("打开串口失败:", e); sys.exit(1)
time.sleep(0.3)

print("=" * 60)
print("X 轴方向测试：每步 %d 步 = %.2f mm，速度 %d Hz" % (STEPS, STEPS / 80.0, HZ))
print("=" * 60)

print("\n--- 1) MOTION ARM（开 10 秒窗口）---")
print("   ", talk(s, "MOTION ARM", 0.6))

print("\n--- 2) 走 DIR0（看往左还是往右！）---")
r = talk(s, "MOVE X DIR0 STEPS %d HZ %d" % (STEPS, HZ), 2.5)
print("   ", r if r else "(无回应)")
print("   ", talk(s, "STATUS", 0.5)[:150])

print("\n--- 3) 等 2 秒 ---")
time.sleep(2)

print("\n--- 4) 重新 ARM ---")
print("   ", talk(s, "MOTION ARM", 0.6))

print("\n--- 5) 反向走 DIR1（应该回到原位）---")
r = talk(s, "MOVE X DIR1 STEPS %d HZ %d" % (STEPS, HZ), 2.5)
print("   ", r if r else "(无回应)")

print("\n--- 6) 收尾：停止 + 状态 ---")
print("   ", talk(s, "STEP STOP", 0.5))
print("   ", talk(s, "STATUS", 0.5)[:150])

s.close()
print("=" * 60)
print("请报告：第 2 步时滑台【往左】还是【往右】动了？")
