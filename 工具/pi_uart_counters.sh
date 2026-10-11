#!/bin/sh
# UART 客观计数：读 /proc/tty/driver/serial 的 tx/rx/错误计数，发 200 字节前后各一次。
# 只向串口写 200 个 'A'（对端若在跑诊断解析器，只会看到一行未知命令，无副作用）。
echo "=== 发送前：UART 计数 ==="
cat /proc/tty/driver/serial 2>/dev/null || sudo cat /proc/tty/driver/serial 2>/dev/null || echo "(读不到)"

echo "=== 向 TX 发 200 字节 ==="
python3 - <<'PY'
import serial, time
s = serial.Serial('/dev/serial0', 115200, timeout=0.3)
s.write(b'A' * 200)
s.flush()
time.sleep(0.5)
s.close()
print('sent 200 bytes on TX')
PY

echo "=== 发送后：UART 计数 ==="
cat /proc/tty/driver/serial 2>/dev/null || sudo cat /proc/tty/driver/serial 2>/dev/null || echo "(读不到)"

echo "=== stty 状态 ==="
stty -F /dev/serial0 -a 2>&1 | head -3

echo "=== GPIO14/15 电平 ==="
raspi-gpio get 14,15

echo "=== 内核是否记录到 break/帧错误 ==="
dmesg 2>/dev/null | grep -iE 'ttyS0|break|framing|parity|uart' | tail -10
