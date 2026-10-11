#!/bin/bash
# 部署视差修正 + 粗标，并在树莓派上验证
set -u
cp /home/pi/_stage/pixel_to_device.py /home/pi/电控/src/electrical_control/rpi/pixel_to_device.py || exit 1
find /home/pi/电控 -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
echo "已部署 pixel_to_device.py ($(wc -c < /home/pi/电控/src/electrical_control/rpi/pixel_to_device.py) B)"
echo "calibration_config.ini ($(wc -c < /home/pi/电控/calibration_config.ini) B)"
echo "--- 树莓派侧验证 ---"
cd /home/pi/电控 || exit 1
PYTHONPATH=src python3 - <<'PY'
import sys
sys.path.insert(0, "src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter
c = PixelToDeviceConverter()
print("已标定          =", c.is_calibrated)
print("camera_height   =", c.camera_height)
print("物体高度类数    =", len(c.object_heights), c.object_heights)
print("工作区          = X%s Y%s" % (c.x_limits, c.y_limits))
print("光轴落点(nadir) =", tuple(round(v, 1) for v in c._optical_axis_point()))
for uv, want in (((144.5, 232), "(0,0)"), ((178, 155), "(37,-83)"), ((232, 232), "(950,0)")):
    print("像素 %-14s -> %-14s 期望 %s" % (str(uv), str(c.pixel_to_device(uv[0], uv[1], 1)), want))
PY
