#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改 calibration_config.ini 里的一个数值，保留结构与行内注释。

🔴 必须用【无 BOM 的 utf-8】写回。2026-09-19 出过一次事故：
   pi_apply_tool_offset.sh 用 utf-8-sig 写，结果配置首行变成 '\ufeff# ====...'，
   configparser 直接报 "File contains no section headers"，
   标定静默失效（is_calibrated=False），整条链路退回固定抓取点。

用法： python3 pi_set_calib.py <键名> <新值> [备注]
"""
import configparser
import shutil
import sys
import time

CAL = "/home/pi/电控/calibration_config.ini"
key, new_value = sys.argv[1], sys.argv[2]
note = sys.argv[3] if len(sys.argv) > 3 else ""

with open(CAL, encoding="utf-8") as fh:
    lines = fh.readlines()

hit = 0
out = []
for ln in lines:
    body = ln.split("#", 1)[0]
    stripped = body.strip()
    if stripped.startswith(key + " =") or stripped.startswith(key + "="):
        old = stripped.split("=", 1)[1].strip()
        tail = ""
        if "#" in ln:
            tail = "   # " + ln.split("#", 1)[1].strip()
        if note:
            tail = "   # %s %s" % (time.strftime("%Y-%m-%d"), note)
        out.append("%s = %s%s\n" % (key, new_value, tail))
        print("  %s: %s -> %s" % (key, old, new_value))
        hit += 1
    else:
        out.append(ln)

if hit != 1:
    sys.exit("拒绝：在 %s 里匹配到 %d 处 `%s =`，必须恰好 1 处" % (CAL, hit, key))

backup = "%s.bak-%s" % (CAL, time.strftime("%H%M%S"))
shutil.copy2(CAL, backup)
# 🔴 无 BOM
with open(CAL, "w", encoding="utf-8", newline="\n") as fh:
    fh.writelines(out)
print("  备份:", backup)

# 自检：真加载器能否读出来
sys.path.insert(0, "/home/pi/电控/src")
from electrical_control.rpi.pixel_to_device import PixelToDeviceConverter  # noqa: E402

c = PixelToDeviceConverter(CAL)
print("  自检 is_calibrated =", c.is_calibrated)

raw = configparser.ConfigParser(inline_comment_prefixes=("#",))
raw.read(CAL, encoding="utf-8")
sec = "CameraCalibration"
print("  自检值 %s = %s" % (key, raw.get(sec, key)))
