#!/bin/bash
# 把「固定抓取点」这一轮的改动装到树莓派上。
set -u
STAGE=/home/pi/_stage
ROOT=/home/pi/电控
echo "=== 装文件 ==="
for pair in \
    "run_chain.py:$ROOT/deploy/run_chain.py" \
    "pixel_to_device.py:$ROOT/src/electrical_control/rpi/pixel_to_device.py" \
    "sorting_config.ini:/home/pi/sorting_config.ini"
do
    src="$STAGE/${pair%%:*}"
    dst="${pair#*:}"
    if [ -f "$src" ]; then
        cp "$src" "$dst" && echo "OK   $dst  ($(wc -c < "$dst") B)"
    else
        echo "MISS $src"; exit 1
    fi
done
echo
echo "=== 清 __pycache__（旧字节码会让文件换了行为没换）==="
find /home/pi/电控/src /home/pi/电控/deploy -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
echo done
echo
echo "=== 读回配置，确认 [PickPoint] 生效 ==="
cd /home/pi/电控 || exit 1
PYTHONPATH=src:/home/pi/电控/deploy python3 - <<'PY'
import sys
sys.path.insert(0, "src"); sys.path.insert(0, "deploy")
import run_chain
print("config path :", run_chain.DEFAULT_CONFIG_PATH)
print("PickPoint   :", run_chain.load_fixed_pick_point(run_chain.DEFAULT_CONFIG_PATH))
print("DropPoints  :", run_chain.load_drop_points(run_chain.DEFAULT_CONFIG_PATH))
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter
c = PixelToDeviceConverter()
print("标定已加载? :", c.is_calibrated, " <- False 是正常的（用固定抓取点模式）")
PY
