#!/bin/sh
# 树莓派 UART 全面诊断 + 自发自收回环测试（只读，除回环测试外不向板子写字节）
echo "===== 1. 树莓派型号 ====="
cat /proc/device-tree/model; echo

echo "===== 2. device-tree 串口别名 ====="
echo -n "serial0 -> "; cat /proc/device-tree/aliases/serial0; echo
echo -n "serial1 -> "; cat /proc/device-tree/aliases/serial1; echo

echo "===== 3. /dev 下的串口 ====="
ls -l /dev/serial0 /dev/serial1 /dev/ttyS0 /dev/ttyAMA0

echo "===== 4. /boot/config.txt 全文 ====="
cat /boot/config.txt

echo "===== 5. cmdline ====="
cat /boot/cmdline.txt; echo

echo "===== 6. GPIO 工具可用性 ====="
for t in raspi-gpio pinctrl gpioinfo raspi-config; do
    p=$(command -v "$t" 2>/dev/null)
    if [ -n "$p" ]; then echo "$t -> $p"; else echo "$t -> (缺)"; fi
done

echo "===== 7. GPIO14/15 当前功能 ====="
if command -v raspi-gpio >/dev/null 2>&1; then
    raspi-gpio get 14 15
elif command -v pinctrl >/dev/null 2>&1; then
    pinctrl get 14 15
else
    echo "(无 raspi-gpio/pinctrl，改读 debugfs)"
    head -40 /sys/kernel/debug/gpio 2>/dev/null || echo "(debugfs 读不到)"
fi

echo "===== 8. dmesg 里的 uart 记录 ====="
dmesg 2>/dev/null | grep -iE 'ttyS0|ttyAMA|uart|serial' | head -25

echo "===== 9. 自发自收回环测试（GPIO14 与 GPIO15 短接时才回显）====="
python3 - <<'PYEOF'
import serial, time
try:
    s = serial.Serial('/dev/serial0', 115200, timeout=1.0)
except Exception as e:
    print('OPEN FAILED: %r' % e); raise SystemExit
s.reset_input_buffer(); s.reset_output_buffer()
probe = b'LOOPBACK-TEST-12345\r\n'
s.write(probe); s.flush()
time.sleep(1.0)
got = s.read(200)
print('sent     = %r' % probe)
print('received = %r' % got)
if probe in got or b'LOOPBACK' in got:
    print('判定: 回环成功 -> 树莓派 TX/RX 与引脚都正常，问题在板子侧或跳线')
else:
    print('判定: 无回环 -> 8脚/10脚未短接（这不能证明故障），或树莓派 UART 未接到排针')
s.close()
PYEOF
