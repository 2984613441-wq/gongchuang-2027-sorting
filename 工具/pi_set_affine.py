#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性写入 6 个仿射参数，并备份 + 用生产加载器回读自检。

为什么不用 pi_set_calib.py 跑 6 次：那样会留 6 份备份，且中途失败会留下
半新半旧的矩阵（a12 是新的、a21 还是旧的），比不写更危险。这里整表原子替换。

用法: python3 pi_set_affine.py <a11> <a12> <tx> <a21> <a22> <ty>
"""
import shutil
import sys
import time

CAL = "/home/pi/电控/calibration_config.ini"
NAMES = ("a11", "a12", "tx", "a21", "a22", "ty")

if len(sys.argv) != 7:
    print(__doc__)
    sys.exit(1)
vals = [float(x) for x in sys.argv[1:7]]

bak = CAL + time.strftime(".bak-affine-%Y%m%d-%H%M%S")
shutil.copy2(CAL, bak)

with open(CAL, encoding="utf-8") as fh:
    lines = fh.readlines()

hit = set()
for i, ln in enumerate(lines):
    body = ln.split("#", 1)[0].strip()
    for n, v in zip(NAMES, vals):
        if body.startswith(n) and body[len(n):].lstrip().startswith("="):
            comment = ln.split("#", 1)[1].rstrip("\n") if "#" in ln else ""
            lines[i] = "%s = %.6f%s\n" % (n, v, ("   #" + comment) if comment else "")
            hit.add(n)

missing = set(NAMES) - hit
if missing:
    print("配置文件里找不到这些键，未做任何写入:", sorted(missing))
    sys.exit(1)

# 无 BOM + LF：有 BOM 时 configparser 会把第一节名读成 '\ufeff[CameraCalibration]'
with open(CAL, "w", encoding="utf-8", newline="\n") as fh:
    fh.writelines(lines)

sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter  # noqa: E402

conv = PixelToDeviceConverter(CAL)          # 构造即跑 validate_affine，不合法会抛
m = conv.affine_matrix
print("写入完成，备份:", bak)
print("加载器回读矩阵:")
for row in m[:2]:
    print("   [%9.6f %9.6f %9.3f]" % (row[0], row[1], row[2]))
