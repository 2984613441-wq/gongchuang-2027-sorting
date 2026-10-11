#!/usr/bin/env python3
# 树莓派串口握手测试（只读命令，不动任何电机）
import serial, time, sys

PORT = '/dev/serial0'
BAUD = 115200

def talk(s, cmd, wait=0.8, n=512):
    s.reset_input_buffer()
    s.write(cmd.encode() + b'\r\n')
    s.flush()
    time.sleep(wait)
    return s.read(n)

try:
    s = serial.Serial(PORT, BAUD, timeout=1.2)
except Exception as e:
    print("  打开串口失败:", e); sys.exit(1)

time.sleep(0.3)
print("=" * 58)
print("树莓派 %s @ %d —— 只发只读命令，不动电机" % (PORT, BAUD))
print("=" * 58)

# 先敲个空行，看有没有残留/提示符
r = talk(s, "", 0.5)
print("[空行]      -> %r" % r)

for cmd in ("PING", "STATUS", "INPUTS"):
    r = talk(s, cmd)
    txt = r.decode('utf-8', 'replace').strip()
    print("[%-7s] -> %s" % (cmd, txt if txt else "(无回应)"))

s.close()
print("=" * 58)
