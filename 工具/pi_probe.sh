#!/bin/bash
# 树莓派现状探针（2026-09-18）— 由 DSH 通过 ssh 管道执行，不落地
echo "=== 1. /opt/ec-chain 结构 ==="
find /opt/ec-chain -maxdepth 3 -type d 2>/dev/null | head -20
echo ""
echo "--- src 下有什么 ---"
ls -la /opt/ec-chain/src 2>/dev/null
echo ""
echo "--- deploy 下有什么 ---"
ls -la /opt/ec-chain/deploy 2>/dev/null
echo ""
echo "=== 2. 主链能不能 import ==="
PYTHONPATH=/opt/ec-chain/src python3 -c "import electrical_control; print('  import OK')" 2>&1 | head -8
echo ""
echo "=== 3. slots=True 残留（Python3.9 致命项）==="
grep -rn "slots=True" /opt/ec-chain/src 2>/dev/null | head -5
echo "  命中数: $(grep -rn 'slots=True' /opt/ec-chain/src 2>/dev/null | wc -l)"
echo ""
echo "=== 4. 关键模块逐个 import ==="
for m in electrical_control.rpi electrical_control.protocol electrical_control.scheduler electrical_control.state_machine; do
  r=$(PYTHONPATH=/opt/ec-chain/src python3 -c "import $m" 2>&1 | tail -1)
  if [ -z "$r" ]; then echo "  OK   $m"; else echo "  FAIL $m -> $r"; fi
done
echo ""
echo "=== 5. Python 依赖 ==="
python3 -c "import PIL; print('  Pillow', PIL.__version__)" 2>&1 | head -2
python3 -c "import numpy; print('  numpy', numpy.__version__)" 2>&1 | head -2
python3 -c "import serial; print('  pyserial OK')" 2>&1 | head -2
echo ""
echo "=== 6. 串口设备 ==="
ls -la /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || echo "  (无 USB 串口接入)"
echo ""
echo "=== 7. 中文字体 ==="
fc-list 2>/dev/null | grep -ci -E "wqy|zenhei" | sed 's/^/  wqy/zenhei 字体数: /'
ls /usr/share/fonts/truetype/wqy/ 2>/dev/null || echo "  (无 wqy 目录)"
echo ""
echo "=== 8. 屏幕 ==="
cat /sys/class/graphics/fb0/bits_per_pixel 2>/dev/null | sed 's/^/  bpp: /'
cat /sys/class/graphics/fb0/virtual_size 2>/dev/null | sed 's/^/  size: /'
cat /sys/class/graphics/fb0/stride 2>/dev/null | sed 's/^/  stride: /'
ls -la /dev/fb0 2>/dev/null
echo ""
echo "=== 9. names.json ==="
cat /opt/ec-chain/names.json 2>/dev/null
echo ""
echo "=== 10. 家目录相关文件 ==="
ls -la /home/pi/ | grep -Ei "ec-|frames|images|chain"
