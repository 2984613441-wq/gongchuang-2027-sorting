#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""写入 [ToolOffset] 节（工具/夹爪偏移补偿）。

为什么需要它：整链发出的运动目标 = 「像素→装置坐标」+ tool_offset
（pixel_to_device.py:456-458）。夹爪中心相对滑台坐标点偏 (+120.5, +43.5) mm
（夹爪在正方向一侧，2026-09-19 五样本实测）。所以要让滑台实际走到
「物块 − (120.5, 43.5)」，配置里的值必须写**负**的。

⚠️ 不要再用 pi_apply_tool_offset.sh / pi_revert_tool_offset.py：
它们改的是 tx 与落点坐标（旧做法），在有正确仿射标定的今天会直接破坏标定。

用法: python3 pi_set_tool_offset.py <x_mm> <y_mm>
      例: python3 pi_set_tool_offset.py -120.5 -43.5
"""
import shutil
import sys
import time

CAL = "/home/pi/电控/calibration_config.ini"

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)
x_mm, y_mm = float(sys.argv[1]), float(sys.argv[2])

bak = CAL + time.strftime(".bak-tooloffset-%Y%m%d-%H%M%S")
shutil.copy2(CAL, bak)

with open(CAL, encoding="utf-8") as fh:
    lines = fh.readlines()

# 定位 / 删除已存在的 [ToolOffset] 节（到下一个 '[' 之前）
start = None
end = len(lines)
for i, ln in enumerate(lines):
    s = ln.strip()
    if s == "[ToolOffset]":
        start = i
        continue
    if start is not None and s.startswith("[") and i > start:
        end = i
        break

block = [
    "[ToolOffset]\n",
    "# 夹爪中心相对滑台坐标点的偏移补偿。整链发的目标 = 像素→装置坐标 + 本节。\n",
    "# 实测：夹爪偏 (+120.5, +43.5)mm（夹爪在正方向一侧），故这里写负值，\n",
    "# 使滑台实际走到「物块 − (120.5, 43.5)」。\n",
    "# 2026-09-19 五样本实测：(115,47)/(128,42)/(118.5,41.5)/(120.5,43.5)/(120.5,43.5)\n",
    "# 依据：工具/pi_bench_goto.py 逐次逼近，每次由用户目视确认夹爪正中物块。\n",
    "x_mm = %.1f\n" % x_mm,
    "y_mm = %.1f\n" % y_mm,
]

if start is None:
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    new = lines + ["\n"] + block
else:
    new = lines[:start] + block + lines[end:]

# 无 BOM + LF：有 BOM 时 configparser 会把首节名读成 '\ufeff[...]'
with open(CAL, "w", encoding="utf-8", newline="\n") as fh:
    fh.writelines(new)

# 回读自检：用生产加载器，并验证"物块坐标 + tool_offset"确实等于滑台目标
sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter  # noqa: E402

conv = PixelToDeviceConverter(CAL)
print("写入完成，备份:", bak)
print("[ToolOffset] 加载器读回 =", conv.tool_offset_mm)
o = conv.tool_offset_mm
print("自检：物块 (50.8,-2.3) + offset = (%.1f, %.1f)"
      % (50.8 + o[0], -2.3 + o[1]))
print("      期望滑台目标            = (-69.7, -45.8)")
