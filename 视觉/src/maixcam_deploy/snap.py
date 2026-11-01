"""MaixCAM 单帧抓图（给分析用）。

用法：python3 /root/snap.py [输出路径] [宽] [高]
默认：/root/snap.jpg 1280 720

注意：
  · 相机被 launcher_daemon 独占，调用前必须 kill 掉（外层脚本负责）
  · 开灯后再拍，否则颜色/亮度都不对
  · 相机刚启动时 AE/AWB 还在收敛，前几帧偏色 ⇒ 预热 1.5 秒
"""
from __future__ import annotations

import os
import sys
import time

from maix import app, camera, display, image

out = sys.argv[1] if len(sys.argv) > 1 else "/root/snap.jpg"
W = int(sys.argv[2]) if len(sys.argv) > 2 else 1280
H = int(sys.argv[3]) if len(sys.argv) > 3 else 720
NO_DISP = os.environ.get("NO_DISP", "1") == "1"
WARMUP = float(os.environ.get("WARMUP_S", "1.5"))

print("[1/3] camera %dx%d" % (W, H))
cam = camera.Camera(W, H, image.Format.FMT_RGB888)

disp = None
if not NO_DISP:
    disp = display.Display()
    print("[2/3] display on")
else:
    print("[2/3] display off")

# 预热：等 AE/AWB 收敛
t0 = time.time()
n = 0
while time.time() - t0 < WARMUP:
    cam.read()
    n += 1
print("预热 %.1fs / %d 帧" % (WARMUP, n))

# 连拍 3 帧取最后一张（再稳一点）
img = None
for i in range(3):
    img = cam.read()
    time.sleep(0.05)

if disp is not None:
    disp.show(img)

img.save(out)
print("[3/3] saved: %s" % out)
try:
    print("     size: %d bytes" % os.path.getsize(out))
except OSError:
    pass
print("     resolution: %dx%d" % (img.width(), img.height()))
