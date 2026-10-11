#!/usr/bin/env python3
# X 轴半圈方向测试：1600 步 = 20mm = 半圈（1圈=40mm=3200步）
import serial, time, re

PORT, BAUD = '/dev/serial0', 115200
STEPS = 1600      # 半圈 = 20mm
HZ = 1000         # 1.6 秒走完

def cmd(s, text, wait=1.2):
    """发一条命令，循环读到没有新数据为止（避免响应被截断）。"""
    s.reset_input_buffer()
    s.write(text.encode() + b'\r\n'); s.flush()
    buf = b""
    t0 = time.time()
    while time.time() - t0 < wait:
        chunk = s.read(256)
        if chunk:
            buf += chunk
            t0 = time.time()          # 有数据就继续等
        else:
            time.sleep(0.05)
    return buf.decode('utf-8', 'replace').replace('\r', '').replace('\n', ' / ').strip()

def field(txt, key):
    m = re.search(key + r"=(-?\d+)", txt)
    return m.group(1) if m else "?"

s = serial.Serial(PORT, BAUD, timeout=0.3)
time.sleep(0.5)

print("=" * 64)
print("X 轴半圈测试：%d 步 = %.1f mm = 半圈，速度 %d Hz（约 %.1f 秒）"
      % (STEPS, STEPS / 80.0, HZ, STEPS / float(HZ)))
print("=" * 64)

print("\n[1] 让板子报一次启动横幅之外的状态")
print("   ", cmd(s, "STATUS", 1.0)[:130])

print("\n[2] MOTION ARM")
print("   ", cmd(s, "MOTION ARM", 0.8)[:130])

print("\n[3] 🔴 走 DIR0 —— 请看滑台往哪边！")
r = cmd(s, "MOVE X DIR0 STEPS %d HZ %d" % (STEPS, HZ), 1.0)
print("   ", r[:220])

print("\n[4] 等它走完（最多 4 秒，每秒报一次进度）")
for i in range(8):
    time.sleep(0.5)
    st = cmd(s, "STATUS", 0.15)
    mode, rem, res = field(st, "MODE"), field(st, "STEP_REMAIN"), field(st, "STEP_RESULT")
    print("   %.1fs  MODE=%s REMAIN=%s RESULT=%s" % ((i + 1) * 0.5, mode, rem, res))
    if mode == "0" and rem == "0":
        break

print("\n[5] 收尾")
print("   ", cmd(s, "STEP STOP", 0.4)[:120])
s.close()
print("=" * 64)
print("请报告：滑台往【左】还是往【右】走了？大约走了多少毫米？")
