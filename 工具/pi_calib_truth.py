#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Pi 上【真正在跑】的标定加载器问清楚：光轴基准、帧尺寸、件高表、工作区。

不猜配置文件，直接 import run_chain 用的那个类（pixel_to_device.PixelToDeviceConverter），
再用已知像素回放，看它到底算出什么。

用法： PYTHONPATH=/home/pi/电控/src python3 pi_calib_truth.py
"""
import sys

CAL = "/home/pi/电控/calibration_config.ini"
sys.path.insert(0, "/home/pi/电控/src")

print("=== 原始文件 ===")
with open(CAL, encoding="utf-8") as fh:
    for i, ln in enumerate(fh, 1):
        s = ln.rstrip()
        if s and not s.lstrip().startswith("#"):
            print("%4d| %s" % (i, s))

print()
print("=== 用真实加载器解析 ===")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter  # noqa: E402

c = PixelToDeviceConverter(CAL)
print("is_calibrated      =", c.is_calibrated)
print("camera_height      =", c.camera_height)
print("frame_width        =", getattr(c, "frame_width", "<无此属性>"))
print("frame_height       =", c.frame_height)
print("object_heights     =", c.object_heights)
print("lib keys           =", sorted(c.object_heights))
print("workspace x        =", getattr(c, "x_limits", None) or (getattr(c, "x_min", "?"), getattr(c, "x_max", "?")))
print("workspace y        =", getattr(c, "y_limits", None) or (getattr(c, "y_min", "?"), getattr(c, "y_max", "?")))
print("optical_axis_point =", c._optical_axis_point())
print("affine             =", getattr(c, "affine", getattr(c, "matrix", "<无此属性>")))

print()
print("=== 已知像素回放（看有没有被丢）===")
for name, (px, py) in (("A=(132,175)", (132, 175)), ("B=(148,128)", (148, 128))):
    for bid in (1, 2, 3, 4, 5, 6):
        print("  %-12s box_id=%d -> %s" % (name, bid, c.pixel_to_device(px, py, bid)))
