#!/bin/sh
# 板子上电后彻底静默——先查是"板子没起来"还是"串口被占/坏了"。
echo "=== 占用 /dev/serial0 的进程 ==="
fuser -v /dev/serial0 2>&1 || echo "(fuser 无输出/不可用)"
echo "=== 相关进程 ==="
pgrep -af 'run_chai[n]' || echo "(无 run_chain)"
pgrep -af 'python3' || echo "(无 python3)"
echo "=== 设备节点 ==="
ls -l /dev/serial0 /dev/ttyS0 2>&1
echo "=== 串口参数 ==="
stty -F /dev/serial0 -a 2>&1 | head -3
echo "=== 被动监听 8 秒（板子正常应发约 8 条 1Hz STATUS）==="
python3 - <<'PY'
import time
import serial

p = serial.Serial("/dev/serial0", 115200, timeout=0.5)
buf = bytearray()
end = time.time() + 8.0
while time.time() < end:
    n = p.in_waiting
    chunk = p.read(n if n else 1)
    if chunk:
        buf.extend(chunk)
p.close()
print("收到 %d 字节" % len(buf))
if buf:
    print(buf[:800].decode("ascii", "replace"))
PY
